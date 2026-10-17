# TC-P008 — Dedicated hosted sandbox schema provisioning

Date: 2026-10-17. Classification: **SANDBOX DDL PASS / HOSTED CONTENTION NOT VERIFIED**.

## Provider evidence

Supabase independent Free project `trendcite-tcp008-sandbox` (`btjgozzguhuzfdueensf`), region `us-east-1`, PostgreSQL 17.11, status `ACTIVE_HEALTHY`. It is distinct from the shared `ISTRIADE PLATFORM` project. Project creation was explicitly confirmed in the conversation at the zero-USD monthly project quote; this is not a blanket guarantee against all usage charges.

Provider migration `tc_p008_sandbox_disposable_unique_key_probe_setup` returned `success: true`. Its DDL created:
- Role `tc_p008_probe_writer` as `NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS`.
- Private schema `tc_p008_isolated`, owned by `postgres`; revoked public access.
- Table `tc_p008_isolated.unique_write_probe(probe_key uuid PRIMARY KEY, probe_run uuid NOT NULL, contender text CHECK contender in holder/contender, created_at timestamptz)`.
- Revoked `PUBLIC, anon, authenticated` table access; granted schema USAGE and table SELECT/INSERT/DELETE to `tc_p008_probe_writer` only.

Independent read-only catalog verification: probe writer has USAGE and INSERT/DELETE, no schema CREATE or elevated role attributes; `anon` and `authenticated` have no schema USAGE, INSERT or DELETE. Independent `SELECT count(*)` returned **0 rows**.

**Not yet performed:** creation of narrowly scoped login credentials, testing effective blocking observation privilege, two independent hosted PostgreSQL backend connections, concurrent insert/commit experiment, targeted cleanup of any test rows, or teardown. Role is NOLOGIN by design and cannot itself open two direct sessions. Do not promote DDL success to hosted unique-key contention PASS.

**Safety boundaries:** no shared ISTRIADE PLATFORM SQL, Queue publish, Worker deployment or production binding changes; production DARK and commercialization HOLD. No provider extras were enabled. Retain the role/schema until the separately controlled experiment and teardown are authorized.
