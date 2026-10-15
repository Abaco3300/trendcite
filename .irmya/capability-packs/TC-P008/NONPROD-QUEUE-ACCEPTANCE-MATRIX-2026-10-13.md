# TC-P008 — Consolidated Queue acceptance matrix

Updated: 2026-10-15. Authority: hosted evidence under TC-P008; production DARK. Local PostgreSQL backend overlap is a separate, lower-assurance result.

| Acceptance scenario | Direct source | Classification |
| --- | --- | --- |
| Real nonprod Queue delivery and unique logical persistence | #66 real Queue publishes and hosted SQL | PASS HOSTED |
| Poison DLQ routing and safe targeted cleanup | #68 real Cloudflare DLQ evidence | PASS HOSTED |
| Provider-attempt retry to DLQ | #70 failure events for attempts 1/2/3 | PASS HOSTED |
| Postcommit application failure followed by actual broker redelivery of the **same physical message** | #80–81; `NONPROD-REAL-POSTCOMMIT-REDELIVERY-ATTESTED-2026-10-14.md`; message ID retained, attempt 1 received, attempt 2 duplicate_ack, logical row = 1 | PASS HOSTED |
| Concurrent independent Queue handler processing | #83–84; `NONPROD-REAL-CONSUMER-OVERLAP-2026-10-14.md`; 12 complete server-timed spans, 7 overlapping pairs | PASS HOSTED |
| Overlapping hosted Queue processing on one logical identity | #85; `NONPROD-SAME-LOGICAL-CONSUMER-OVERLAP-2026-10-14.md`; 12 physical messages, 1 overlap pair, 1 logical ledger record, 0 failures | PASS HOSTED |
| Offline overlapping handler invocations | #82; real Python handler extracted under fake shared durable store | PASS ISOLATED, not provider |
| Two independent local PostgreSQL backend sessions with overlapping server-clock intervals | #90 `scripts/tc_p008_local_backend_overlap.py`; isolated Docker PostgreSQL 17, PIDs 109/110, measured UTC intervals overlap | PASS LOCAL ONLY |
| Hosted Supabase PostgreSQL transactional overlap of concurrent backend transactions | Sequential hosted SQL requests did not overlap; #90 local Docker sessions cannot establish hosted overlap | NOT VERIFIED |
| Actual platform-enforced Worker termination / crash after durable commit | Synthetic postcommit `RuntimeError` does not kill Worker process | NOT VERIFIED |
| Transport-level lost ACK from Worker to broker | Real redelivery after app exception is not observed loss of transport ACK | NOT VERIFIED |
| Production asynchronous/customer/commercial activation | Production `foundation-only`; distinct HG-H required | BLOCKED |

## Latest read-only revalidation

- Main `b6d4cd4be4899be196f75c2dcd338330ed71c30b` (PR #90), post-merge GitHub Actions CI run `38776775763` SUCCESS. PR #87 repaired the authorized DARK Hyperdrive validator; PR #88 added fail-closed regression coverage; PR #89 bounded disposable PostgreSQL startup retries; PR #90 added an isolated two-backend overlap attestation. The latter does not satisfy hosted transaction-overlap acceptance.
- 2026-10-15 Cloudflare read-only metrics: nonprod source Queue backlog 0 and DLQ backlog 0; production activation `foundation-only`; no temporary TC-P008 nonprod probe bindings.
- Regression coverage: `tests/test_tc_p008_state_validator_contract.py` checks allowed `BOUND_DARK` state and fails closed on unsafe production-state mutations. The separate canonical preflight and hosted evidence remain distinct.
- Current Cloudflare nonprod probe flags: none; source Queue 0, DLQ 0; production `TRENDCITE_PRODUCTION_ACTIVATION=foundation-only`.
- Hosted SQL postcommit probe `tc-p008-postcommit-20261014-auditprobe-03`: one logical row, two physical attempt audit rows.
- Hosted SQL distinct-message concurrency probe `tc-p008-concurrency-20261014-hosted-a-*`: 12 logical rows, 12 finished physical invocation spans.

## Operating boundary

No additional synthetic fault, producer load or active Queue probe is needed to reconfirm established PASS evidence. Any further test must target a *different*, explicitly unverified property (database backend transaction overlap; actual process crash or true transport ACK loss) and preserve nonprod-only scope, strict bounds, restoration and independent read-back. Worker runtime termination or transport interference must not be simulated and reported as an actual crash/lost ACK. Production, billing, customers and credentials are out of scope.
