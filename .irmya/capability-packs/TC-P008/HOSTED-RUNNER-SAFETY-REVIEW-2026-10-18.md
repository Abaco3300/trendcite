# TC-P008 — Hosted runner safety review (2026-10-18)

**PR #121 remains DRAFT; NO HOSTED EXECUTION AUTHORIZED.**

A read-only review of `src/trendcite/cloud/tc_p008_hosted_runner.py` at `8ef638596458bcb7b9132e76d8a658078d6272dd` identifies these release blockers:

1. **Unreachable execution body.** `execute_probe()` raises unconditionally before allocating the probe IDs, including when `approved=True`. This is an intentional safety gate; keep it until all other blockers are closed.
2. **Cleanup not guaranteed after connection failure.** The `finally` branch attempts to open a cleanup connection, but failure to establish it is not independently recovered or attested. A subsequent connection/readback can also fail. Treat any such failure as an incident requiring operator review; do not report cleanup PASS.
3. **Open backend risk.** Worker threads are daemon threads. A timed join does not force the PostgreSQL backend transaction to terminate. An explicit cancellation/rollback/close protocol plus independent readback of `pg_stat_activity` or equivalent evidence is required before claiming sessions closed.
4. **Missing end-to-end recovery tests.** Existing injected failures cover the separate cleanup audit and the disabled execution gate; they do not exercise the unreachable transaction body. Add synthetic integration tests for INSERT failure, observer failure, holder deadline, contender deadline, rollback, cancellation and cleanup connection failure before enabling.
5. **Authority and identity.** The current connection factory is not wired to the previously restricted sandbox target preflight. Any future operational path must validate the exact project/role and TLS identity *before* the first connection, avoid secrets in argv/logs, and require a separate execution authorization.
6. **Classification.** `assess_hosted_probe(..., hosted_run_attested=False)` intentionally cannot mark a hosted proof accepted. Retain independent attestation and do not infer PASS from CI.

Acceptance sequence: offline failure-injection evidence -> static security review -> narrow authorized sandbox credential channel -> two independent live backend sessions -> lock observation -> one durable winner -> targeted delete -> independent zero-row and backend-termination audit -> explicit evidence review.

Production remains DARK; commercialization remains HOLD. No SQL, Queue, Worker, credential or hosted probe action is approved by this review.
