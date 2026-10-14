# TC-P008 — Parallel hosted PostgreSQL insert identity race (2026-10-14)

Environment: TrendCite nonprod PostgreSQL schema `trendcite`; existing synthetic workspace `irmya-nonprod-ws`. Production unchanged.

Four SQL operations were issued concurrently through four Supabase SQL tool invocations, each with a distinct `delivery_id` suffix a/b/c/d, but the same `logical_id=tc-p008-sql-race-20261014-01`. Each executed `INSERT INTO trendcite.cloud_queue_delivery (delivery_id,workspace_id,logical_id,kind,first_seen_at) VALUES (...,'irmya-nonprod-ws','tc-p008-sql-race-20261014-01','tc_p008_sql_race_probe',now()) ON CONFLICT DO NOTHING RETURNING delivery_id`.

Baseline SELECT: zero matching logical records. Four operations completed without error: a returned one inserted delivery ID; b/c/d each returned empty. Subsequent hosted SELECT confirmed exactly one row, winner `tc-p008-sql-race-20261014-01-a`. This establishes actual hosted PostgreSQL unique-constraint idempotency with concurrently submitted SQL requests, but does **not** attest four simultaneous database backend transaction overlaps, independent Worker consumers, process termination, or ACK loss after successful commit.

Retained one synthetic database fixture as audit evidence. No customers, external email, charges, production Queue binding or activation. Production Worker binding was separately read as `foundation-only`.

Classification: `PARALLEL_SQL_SUBMISSION=PASS_NONPROD`, `SINGLE_PERSISTED_LOGICAL_ROW=PASS_NONPROD`, `INDEPENDENT_WORKER_CONCURRENT_EXECUTION=NOT_VERIFIED`, `POSTCOMMIT_REAL_ACK_LOSS=NOT_VERIFIED`.
