# TC-P008 — Supabase least-privilege and topology inventory

Date: 2026-10-17. **READ-ONLY VERIFIED / HOSTED UNIQUE KEY NOT VERIFIED.**

## Independent provider observations

Supabase connector, ISTRIADE account, project `yntcafxmjgfjrdinwdmo`:
- Project `ISTRIADE PLATFORM`: `ACTIVE_HEALTHY`, PostgreSQL 17, region `us-east-1`.
- Supabase branch listing returned only the default `main` entry; **no separately provisioned test branch identified**. An inactive named project elsewhere in the account is not evidence of a suitable disposable environment.
- Read-only catalog queries establish `trendcite_nonprod_runtime` as NOLOGIN, not SUPERUSER, not BYPASSRLS, not CREATEROLE/CREATEDB. It has USAGE but not CREATE on `trendcite` and not CREATE on the database.
- `trendcite_nonprod_hyperdrive_login` is LOGIN, not SUPERUSER, not BYPASSRLS, not CREATEROLE/CREATEDB. It has neither USAGE nor CREATE on `trendcite`, and no database CREATE privilege. Membership in runtime role is present for the inspector; exact runtime SET ROLE behavior is not independently established by these observations.
- Neither nonprod role is a member of `pg_monitor` nor `pg_read_all_stats`. **Do not conflate this with a demonstrated inability to call `pg_blocking_pids()`**; effective SQL observation capabilities remain unverified.
- Catalog query for candidate namespaces found `trendcite` owned by `postgres`; neither `tc_p008_isolated` nor `tc_p008_disposable` was present.
- `trendcite_nonprod_runtime` has INSERT on the existing `trendcite.cloud_queue_probe_invocation` ledger; Hyperdrive login itself does not. **Never reuse that customer/Queue-linked ledger as disposable test storage.**

## Decision

`HOSTED_ISOLATION_GATE = BLOCKED`. No existing independent disposable hosted PostgreSQL boundary or purpose-limited test owner/role was identified. Creating a Supabase branch or a new project is a separate provider provisioning/cost decision and **was not undertaken**. Do not grant broad schema permissions, modify shared production/nonprod roles, create SQL objects or run a contention test in the common platform.

The local PostgreSQL 17 two-session result remains `PASS LOCAL`; hosted same-key unique-write contention, platform-enforced Worker termination and actual lost ACK remain `NOT VERIFIED`.

## Next controlled boundary

Assess, without provisioning, the price and operational isolation of an explicit disposable branch or independent project, including data-copy policy, billing, network access, TTL and guaranteed removal. An actual provider-cost authorization and a clean SQL role / limited observer plan are needed before any hosted setup or execution. Continue to enforce production DARK and commercialization HOLD.
