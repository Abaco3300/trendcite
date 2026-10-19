"""Offline cancellation matrix, no database or network."""

import itertools

import pytest

from trendcite.cloud.tc_p008_backend_cancel import cancel_and_verify_backends


@pytest.mark.parametrize("outcomes", list(itertools.product((False, True), repeat=3)))
def test_independent_absence_is_mandatory(outcomes):
    cancelled = []
    values = iter(outcomes[:2])

    def cancel(pid):
        cancelled.append(pid)
        return next(values)

    result_or_error = None
    try:
        result_or_error = cancel_and_verify_backends(
            (101, 202), cancel=cancel, verify_absent=lambda _: outcomes[2]
        )
    except RuntimeError as exc:
        result_or_error = str(exc)
    assert cancelled == [101, 202]
    if outcomes[2]:
        assert result_or_error == "TERMINATION_OBSERVED_NOT_HOSTED_ATTESTED"
    else:
        assert "NOT_VERIFIED" in result_or_error


def test_cancel_exception_does_not_skip_second_backend():
    calls = []

    def cancel(pid):
        calls.append(pid)
        if pid == 101:
            raise TimeoutError("injected")
        return True

    with pytest.raises(RuntimeError, match="NOT_VERIFIED"):
        cancel_and_verify_backends((101, 202), cancel=cancel, verify_absent=lambda _: False)
    assert calls == [101, 202]


@pytest.mark.parametrize("pids", [(1, 1), (0, 2), (True, 2), (-3, 2)])
def test_invalid_identity_denied(pids):
    with pytest.raises(RuntimeError, match="invalid backend"):
        cancel_and_verify_backends(pids, cancel=lambda _: True, verify_absent=lambda _: True)
