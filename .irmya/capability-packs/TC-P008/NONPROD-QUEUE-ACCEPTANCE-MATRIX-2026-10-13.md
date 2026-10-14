# TC-P008 — Consolidated Queue acceptance matrix (2026-10-13)

Scope: actual Cloudflare nonprod, hosted Postgres nonprod, and separately identified isolated tests. Production remains DARK.

| Scenario | Evidence | Outcome |
| --- | --- | --- |
| Real Queue delivery to Postgres | Two HTTP 200 sends with same unique synthetic logical identity; one ledger row; Queue backlog observed zero | PASS NONPROD |
| Real repeated payload idempotency | Same logical identity delivered twice through actual provider, no duplicate ledger row | PASS NONPROD |
| Poison message to DLQ | Malformed tagged nonprod message observed physically in Cloudflare DLQ | PASS NONPROD |
| Targeted DLQ cleanup | Unique marker-matched `peek` plus `purge`; HTTP 200; source and DLQ empty afterward | PASS NONPROD |
| Actual broker retries | Three hosted failure records for same message ID, attempts 1/2/3 `UniqueViolationError`, then message appeared in DLQ | PASS NONPROD |
| Persistence failure must not ACK | Executed actual handler code with simulated store failure | PASS ISOLATED |
| Failure audit failure and mixed batch isolation | Executed actual handler with fake dependencies; retry without ACK; unaffected valid message ACK | PASS ISOLATED |
| Post-commit ACK exception + deduplicated replay | PR #71: actual handler with fake durable ledger, ACK exception requests retry and second delivery yields a single effect | PASS ISOLATED |
| Actual lost ACK after successful durable commit | Requires controlled failure in real broker/Worker after commit, with observable true redelivery | NOT VERIFIED |
| Cross-process crash and concurrent transactional deduplication | No remote concurrent-consumer crash campaign proven in this checkpoint | NOT VERIFIED |
| Production Queue, routes, cron, customer activation | Not within foundation-only approval; separate true HG-H required before material activation | BLOCKED |

Evidence files: `NONPROD-REAL-QUEUE-DELIVERY-2026-10-13.md`, `NONPROD-REAL-POISON-DLQ-2026-10-13.md`, `NONPROD-REAL-BROKER-RETRY-2026-10-13.md`.

IRMYA gates: an absence of evidence in ordinary nonprod tests is **not** a Human Gate. New prod Queue consumer integration/activation exceeding the authorized foundation is material HG-H. Do not interpret any nonprod PASS as activation authority.

Security: the private Postgres schema is not established as publicly exposed simply because 33 tables have RLS off; before changing RLS, assess schema grants, data API publication, and workload breakage. No permissions, schema, secrets, provider controls or production systems were changed by this report.
