# TC-P008 — Consolidated Queue acceptance matrix

Updated: 2026-10-17. Authority: hosted evidence under TC-P008; production DARK. Local PostgreSQL backend overlap remains separate evidence; the hosted backend and advisory-lock checks passed on 2026-10-17.

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
| Hosted PostgreSQL concurrent independent backend sessions with overlapping server-clock intervals | 2026-10-17 authorized nonprod HTTP 200, Ray `a4c02f4e0f889aa6-MIA`, PIDs `3280486` / `3289156`, overlapping UTC intervals `15:02:32.570971`–`15:02:34.072556` and `15:02:32.576924`–`15:02:34.078484` | PASS HOSTED — SQL backend overlap only |
| Hosted PostgreSQL concurrent transactions with transaction-scoped advisory-lock contention | Same 2026-10-17 authorized nonprod HTTP 200; `distinct_backends=true`, `concurrent_transaction_lock_contention=true` | PASS HOSTED — advisory lock only; no unique-key write contention |
| Hosted concurrent unique-key write contention | Read-only overlap and advisory-lock probes cannot establish a real unique-key write conflict | NOT VERIFIED |
| Actual platform-enforced Worker termination / crash after durable commit | Synthetic postcommit `RuntimeError` does not kill Worker process | NOT VERIFIED |
| Transport-level lost ACK from Worker to broker | Real redelivery after app exception is not observed loss of transport ACK | NOT VERIFIED |
| Production asynchronous/customer/commercial activation | Production `foundation-only`; distinct HG-H required | BLOCKED |

## Latest hosted certification and independent cleanup read-back

- 2026-10-17 15:02:34 UTC: **one** authorized nonprod HTTP 200 diagnostic; Ray `a4c02f4e0f889aa6-MIA`; confirms distinct server-side backend intervals overlap and independent advisory transaction-lock contention. The response explicitly does **not** attest unique-key write contention, Worker termination or lost broker ACK.
- Three six-minute-expiry diagnostic bindings installed solely for the probe and deleted individually (three CLI cleanup return codes 0). Independent Cloudflare settings GET confirmed **all temporary TC-P008 bindings absent**, Hyperdrive and Queue still bound; production activation `foundation-only`.
- Active nonprod Worker version after secret cleanup: `66f70533-0b1d-4e53-9229-6a843ccf39da` (Cloudflare deployments independent read-back). Diagnostic code deployed from commit `471cb64f093d1e1304212f214c89955c3db3fabf` (PR #105). No new production activation or Queue synthetic load.
- 2026-10-15 historical Cloudflare read-only metrics: nonprod source Queue backlog 0 and DLQ backlog 0; these metrics were **not** remeasured during the 2026-10-17 probe.
- Regression coverage: `tests/test_tc_p008_state_validator_contract.py` checks allowed `BOUND_DARK` state and fails closed on unsafe production-state mutations. The separate canonical preflight and hosted evidence remain distinct.
- Latest 2026-10-17 Cloudflare independent read-back: temporary TC-P008 bindings absent; production `TRENDCITE_PRODUCTION_ACTIVATION=foundation-only`. Current Queue and DLQ depths not remeasured.
- Hosted SQL postcommit probe `tc-p008-postcommit-20261014-auditprobe-03`: one logical row, two physical attempt audit rows.
- Hosted SQL distinct-message concurrency probe `tc-p008-concurrency-20261014-hosted-a-*`: 12 logical rows, 12 finished physical invocation spans.

## Remaining proof gates

See `REMAINING-ACCEPTANCE-GATES-2026-10-17.md` for the distinct direct-evidence criteria, authorization and isolation requirements, and explicit hard stops for unique-key write contention, platform-enforced Worker termination, and transport-level ACK loss. None are certified by the 2026-10-17 advisory-lock attestation.

## Operating boundary

No additional synthetic fault, producer load or active Queue probe is needed to reconfirm established PASS evidence. Any further test must target a *different*, explicitly unverified property (unique-key write contention; actual process crash or true transport ACK loss) and preserve nonprod-only scope, strict bounds, restoration and independent read-back. Worker runtime termination or transport interference must not be simulated and reported as an actual crash/lost ACK. Production, billing, customers and credentials are out of scope.
