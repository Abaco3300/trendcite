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
| Real broker redelivery after successful durable commit and injected application exception | PR #81: hosted attempt ledger records attempts 1 `received` and 2 `duplicate_ack` with the same physical message ID; one ledger effect | PASS NONPROD — simulated exception, not transport ACK loss |
| Actual transport-level lost ACK or forced Worker termination | Requires actual process termination or transport-level lost ACK directly observed after durable commit; an application exception does not prove this | NOT VERIFIED |
| Real overlapping Queue handler executions (different logical identities) | PR #84: 12 completed physical invocation spans; seven positive interval overlaps | PASS NONPROD |
| Real overlapping Queue handler executions (same logical identity) | PR #85: 12 physical messages with the same logical ID; 12 completed spans, one positive overlap pair, exactly one durable effect | PASS NONPROD |
| Concurrent PostgreSQL backend transaction overlap | Application-level overlapping spans do not establish simultaneous active DB transactions | NOT VERIFIED |
| Cross-process crash and recovery | No actual Worker termination observed | NOT VERIFIED |
| Production Queue, routes, cron, customer activation | Not within foundation-only approval; separate true HG-H required before material activation | BLOCKED |

Evidence files: `NONPROD-REAL-QUEUE-DELIVERY-2026-10-13.md`, `NONPROD-REAL-POISON-DLQ-2026-10-13.md`, `NONPROD-REAL-BROKER-RETRY-2026-10-13.md`.

IRMYA gates: an absence of evidence in ordinary nonprod tests is **not** a Human Gate. New prod Queue consumer integration/activation exceeding the authorized foundation is material HG-H. Do not interpret any nonprod PASS as activation authority.

Security: the private Postgres schema is not established as publicly exposed simply because 33 tables have RLS off; before changing RLS, assess schema grants, data API publication, and workload breakage. No permissions, schema, secrets, provider controls or production systems were changed by this report.
