# TC-P008 — Hosted unique-key contention isolation assessment

Date: 2026-10-17. Classification: **READ-ONLY REVIEW / HOSTED NOT VERIFIED**.

## Independently verified Cloudflare state

- GET nonprod Worker settings HTTP 200; `HYPERDRIVE` points to `403038608f454b4b8172d9609f6a7383`; `TRENDCITE_RUNTIME_ROLE=trendcite_nonprod_runtime`. Existing Queue binding and customer nonprod services are present: **not disposable**.
- GET nonprod Hyperdrive HTTP 200; origin `db.yntcafxmjgfjrdinwdmo.supabase.co:5432/postgres`, login `trendcite_nonprod_hyperdrive_login`, origin limit 5, caching disabled. This is the shared ISTRIADE PLATFORM PostgreSQL project, **not** a dedicated scratch database.
- GET production Worker settings HTTP 200; `TRENDCITE_PRODUCTION_ACTIVATION=foundation-only`, production Hyperdrive binding remains the only database binding.
- Do not transcribe publishable keys, secret contents or connection strings into this assessment.

## Repository inspection

`deploy/postgres/0011_tc_p008_concurrency_probe.sql` defines `trendcite.cloud_queue_probe_invocation` and grants `SELECT, INSERT, UPDATE` to `trendcite_nonprod_runtime`. It is an existing Queue diagnostic ledger tied to workspace history, not a disposable namespace. Its primary key and grants do **not** establish suitable DDL, cleanup, schema ownership or observer privileges for a new unique-write proof.

The design in `UNIQUE-KEY-CONTENTION-DESIGN-2026-10-17.md` explicitly forbids repurposing that ledger and calls for a separately authorized disposable nonprod schema/table.

## Decision

`HOSTED_ISOLATION_GATE = BLOCKED`. Current evidence does not establish a segregated database, a disposable role, safe schema ownership, effective `pg_blocking_pids` observation permission, an exclusive cleanup scope, a bounded cost envelope or independently confirmed rollback/removal capability. **Do not execute any DDL or unique-key load in shared PostgreSQL to manufacture evidence.**

A future hosted run requires (a) a genuinely isolated nonproduction database or equivalently verified independent boundary; (b) read-only permission/ownership review; (c) explicit authorized setup and cost decision if necessary; (d) limited, time-bounded two-session execution; (e) independent readback of winner/loser/blocking and exact cleanup; (f) preservation of DARK production and customer/Queue isolation. No new provider provisioning is authorized by this review.

## Classification and next safe action

- Real PostgreSQL unique-key write contention in disposable **local** PostgreSQL 17: **PASS LOCAL** (PR #110).
- Hosted unique-key write contention: **NOT VERIFIED / BLOCKED ON ISOLATION**.
- Platform-enforced Worker termination after commit: **NOT VERIFIED**.
- Transport-level lost ACK: **NOT VERIFIED**.
- Production activation: **DARK / BLOCKED**.
- Commercialization: **HOLD**.

Next safe action: obtain read-only evidence about disposable nonprod topology and least-privilege role capabilities without touching the shared runtime. If no safe isolated resource exists, retain the hosted gate rather than expand scope or spend.
