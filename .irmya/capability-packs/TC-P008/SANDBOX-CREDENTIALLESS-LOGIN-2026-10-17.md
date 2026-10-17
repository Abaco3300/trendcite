# TC-P008 — Credentialless expiring hosted probe login

2026-10-17. Status: **ROLE CONFIGURED / LOGIN NOT USABLE / HOSTED CONTENTION NOT VERIFIED**.

Target: dedicated sandbox Supabase project `btjgozzguhuzfdueensf`, never the shared ISTRIADE database.

Provider migration `tc_p008_probe_login_without_credentials` returned success and created `tc_p008_probe_login` with LOGIN and inherited membership in the pre-existing least-privilege `tc_p008_probe_writer`. It has no password; a read-only `pg_authid` inspection independently returned `password_absent=true`. Password authentication cannot proceed. Its `VALID UNTIL` is `2026-10-18 23:59:00+00`. Default limits: `statement_timeout=8s`, `lock_timeout=5s`, `idle_in_transaction_session_timeout=10s`, `default_transaction_isolation=read committed`.

Catalog readback: no superuser, CREATEDB, CREATEROLE or BYPASSRLS privilege; schema USAGE and table INSERT inherited; no schema CREATE. No credentials were generated, copied or stored in git.

**Gate:** This setup is not two independent database sessions or the hosted unique-key proof. Any future password provisioning must use a secure credential channel, new explicit execution gate, independent verification of the effective role, bounded two-session SQL procedure and immediate credential removal. Expiration of a login credential does not replace explicit role teardown. Preserve production DARK and commercialization HOLD. Do not use shared runtime or Queues.
