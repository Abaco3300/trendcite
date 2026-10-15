# TC-P008 — Consolidated Queue acceptance matrix

Updated: 2026-10-14. Authority: hosted evidence under TC-P008; production DARK.

| Acceptance scenario | Direct source | Classification |
| --- | --- | --- |
| Real nonprod Queue delivery and unique logical persistence | #66 real Queue publishes and hosted SQL | PASS HOSTED |
| Poison DLQ routing and safe targeted cleanup | #68 real Cloudflare DLQ evidence | PASS HOSTED |
| Provider-attempt retry to DLQ | #70 failure events for attempts 1/2/3 | PASS HOSTED |
| Postcommit application failure followed by actual broker redelivery of the **same physical message** | #80–81; `NONPROD-REAL-POSTCOMMIT-REDELIVERY-ATTESTED-2026-10-14.md`; message ID retained, attempt 1 received, attempt 2 duplicate_ack, logical row = 1 | PASS HOSTED |
| Concurrent independent Queue handler processing | #83–84; `NONPROD-REAL-CONSUMER-OVERLAP-2026-10-14.md`; 12 complete server-timed spans, 7 overlapping pairs | PASS HOSTED |
| Overlapping hosted Queue processing on one logical identity | #85; `NONPROD-SAME-LOGICAL-CONSUMER-OVERLAP-2026-10-14.md`; 12 physical messages, 1 overlap pair, 1 logical ledger record, 0 failures | PASS HOSTED |
| Offline overlapping handler invocations | #82; real Python handler extracted under fake shared durable store | PASS ISOLATED, not provider |
| SQLite/Postgres transactional overlap of concurrent backend transactions | Available hosted SQL parallel *submissions* do not establish backend overlap | NOT VERIFIED |
| Actual platform-enforced Worker termination / crash after durable commit | Synthetic postcommit `RuntimeError` does not kill Worker process | NOT VERIFIED |
| Transport-level lost ACK from Worker to broker | Real redelivery after app exception is not observed loss of transport ACK | NOT VERIFIED |
| Production asynchronous/customer/commercial activation | Production `foundation-only`; distinct HG-H required | BLOCKED |

## Latest read-only revalidation

- Main `d7a49e3eaa0f9b15aab86792865e3bc6a8cbbfab` (PR #87), post-merge GitHub Actions CI run `38626431951` SUCCESS; authorized DARK Hyperdrive validator repaired. This read-back updates the former `77803e7` snapshot without changing the hosted Queue acceptance classifications.
- 2026-10-15 Cloudflare read-only metrics: nonprod source Queue backlog 0 and DLQ backlog 0; production activation `foundation-only`; no temporary TC-P008 nonprod probe bindings.
- Regression coverage: `tests/test_tc_p008_state_validator_contract.py` checks allowed `BOUND_DARK` state and fails closed on unsafe production-state mutations. The separate canonical preflight and hosted evidence remain distinct.
- Current Cloudflare nonprod probe flags: none; source Queue 0, DLQ 0; production `TRENDCITE_PRODUCTION_ACTIVATION=foundation-only`.
- Hosted SQL postcommit probe `tc-p008-postcommit-20261014-auditprobe-03`: one logical row, two physical attempt audit rows.
- Hosted SQL distinct-message concurrency probe `tc-p008-concurrency-20261014-hosted-a-*`: 12 logical rows, 12 finished physical invocation spans.

## Operating boundary

No additional synthetic fault, producer load or active Queue probe is needed to reconfirm established PASS evidence. Any further test must target a *different*, explicitly unverified property (database backend transaction overlap; actual process crash or true transport ACK loss) and preserve nonprod-only scope, strict bounds, restoration and independent read-back. Worker runtime termination or transport interference must not be simulated and reported as an actual crash/lost ACK. Production, billing, customers and credentials are out of scope.
