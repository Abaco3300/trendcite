"""Offline checks for the operator Test A CLI: no network, no secret leakage."""

import json

import pytest
from scripts import tc_p008_hosted_unique_key_probe as cli

SECRET = "synthetic-operator-secret-value"


class Session:
    def __init__(self, row=None, fail_alter=False):
        self.row = row
        self.fail_alter = fail_alter
        self.statements = []
        self.committed = False
        self.closed = False

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if "ALTER ROLE" in sql and self.fail_alter:
            raise OSError("synthetic network failure")
        return self

    def fetchone(self):
        return self.row

    def rollback(self):
        pass

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


GOOD_ROW = (
    "tc_p008_probe_login",
    "tc_p008_probe_login",
    False,
    True,
    "TLSv1.3",
    "17.11",
    True,
    False,
)


def test_identity_contract_accepts_only_restricted_tls_session():
    session = Session(GOOD_ROW)
    result = cli.verify_session_identity(lambda: session)
    assert result["tls"] is True and result["current_user"] == "tc_p008_probe_login"
    assert session.closed


@pytest.mark.parametrize(
    ("index", "value", "message"),
    [
        (0, "postgres", "restricted sandbox identity"),
        (2, True, "elevated"),
        (2, None, "elevated"),
        (3, False, "TLS not in use"),
        (7, True, "least-privilege"),
    ],
)
def test_identity_contract_fails_closed(index, value, message):
    row = list(GOOD_ROW)
    row[index] = value
    with pytest.raises(RuntimeError, match=message):
        cli.verify_session_identity(lambda: Session(tuple(row)))


def test_revocation_sql_contains_no_secret_and_commits():
    session = Session()
    assert cli.revoke_own_password(lambda: session) == "PASSWORD_NULL_COMMITTED"
    assert session.statements == ["ALTER ROLE CURRENT_USER PASSWORD NULL"]
    assert session.committed and session.closed


def test_confirmation_mismatch_never_prompts(monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("prompted without confirmation")

    monkeypatch.setattr(cli.getpass, "getpass", forbidden)
    code = cli.main(["--transport", "direct", "--sslrootcert", "x", "--confirm", "nope"])
    assert code == 2


def test_password_only_from_getpass_and_never_in_output(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: SECRET)
    seen = {}

    def fake_run(transport, sslrootcert, password):
        seen["password"] = password
        return {
            "probe_status": "COMPLETED_EVIDENCE_PENDING_REVIEW",
            "credential_revocation": "PASSWORD_NULL_COMMITTED",
            "hosted_certification": "NOT_VERIFIED_PENDING_INDEPENDENT_REVIEW",
        }

    monkeypatch.setattr(cli, "run", fake_run)
    out_file = tmp_path / "evidence.json"
    code = cli.main(
        [
            "--transport",
            "session-pooler",
            "--sslrootcert",
            "ca.crt",
            "--confirm",
            cli.CONFIRMATION,
            "--evidence-out",
            str(out_file),
        ]
    )
    assert code == 0
    assert seen["password"] == SECRET
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert SECRET not in out_file.read_text("utf-8")
    assert json.loads(out_file.read_text("utf-8"))["hosted_certification"].startswith(
        "NOT_VERIFIED"
    )


def test_failed_probe_still_attempts_revocation(monkeypatch, tmp_path):
    ca = tmp_path / "ca.crt"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    sessions = []

    def driver(**kwargs):
        assert kwargs["password"] == SECRET
        session = Session(row=None)
        sessions.append(session)
        return session

    monkeypatch.setattr(cli, "load_driver", lambda: driver)
    report = cli.run("direct", str(ca), SECRET)
    assert report["probe_status"] == "FAILED_CLOSED"
    assert report["credential_revocation"] == "PASSWORD_NULL_COMMITTED"
    assert "ALTER ROLE CURRENT_USER PASSWORD NULL" in sessions[-1].statements
    assert SECRET not in json.dumps(report, default=str)


def test_driver_error_message_is_never_serialized(monkeypatch, tmp_path):
    ca = tmp_path / "ca.crt"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")

    class LeakingSession(Session):
        def execute(self, sql, params=None):
            if "SELECT current_user" in sql:
                raise RuntimeError("connection failed with password=" + SECRET)
            return super().execute(sql, params)

    monkeypatch.setattr(cli, "load_driver", lambda: lambda **kwargs: LeakingSession())
    report = cli.run("direct", str(ca), SECRET)
    assert report["probe_status"] == "FAILED_CLOSED"
    assert report["probe_error"] == "PROBE_EXCEPTION_REDACTED"
    assert SECRET not in json.dumps(report)
    assert report["credential_revocation"] == "PASSWORD_NULL_COMMITTED"


def test_preparation_exception_redacted_at_cli_boundary(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: SECRET)

    def crash(*_args):
        raise RuntimeError("driver traceback password=" + SECRET)

    monkeypatch.setattr(cli, "run", crash)
    output = tmp_path / "evidence.json"
    code = cli.main(
        [
            "--transport",
            "direct",
            "--sslrootcert",
            "ca.crt",
            "--evidence-out",
            str(output),
            "--confirm",
            cli.CONFIRMATION,
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "PROBE_PREPARATION_FAILED_REDACTED" in captured.err
    assert SECRET not in captured.out + captured.err
    assert not output.exists()
