# TC-P002 — Persistent Runtime E2E Hardening

Status: CLOSED / PASS

## Outcome

Prove that the persistent non-production runtime behaves correctly across repeated executions, duplicate delivery, failure/retry and lease-recovery conditions before delivery/auth/frontend work begins.

## Acceptance evidence

- repeated automatic runs remain successful: PASS
- idempotent Radar Run identity: PASS
- schedule tick deduplication: PASS
- generic Queue logical-delivery deduplication: PASS
- retryable failed tick can be claimed while below max attempts: PASS
- attempt budget exhaustion blocks a further claim: PASS
- expired running lease can be reclaimed by a new owner: PASS
- stale owner cannot settle reclaimed work: PASS
- current owner can settle reclaimed work: PASS
- same logical Queue ID may exist independently in another workspace: PASS
- wrong-workspace tick claim: BLOCKED
- no cross-project mutation: PASS
- P0=0
- P1=0

## PostgreSQL evidence

Queue duplicate probe:
- first_inserted = 1
- duplicate_inserted = 0
- durable_rows = 1

Radar Run duplicate probe:
- duplicate_run_inserted = 0
- durable_rows_for_logical_run = 1

Lease probe:
- owner A initial claim = 1
- owner B expired-lease reclaim = 1
- resulting attempt = 2
- stale owner settlement = 0
- valid owner settlement = 1

Retry budget probe:
- third allowed attempt claim = 1
- durable_attempt = 3
- max_attempts = 3
- claim after exhausted budget = 0

Isolation probe:
- same logical queue ID in second workspace = allowed
- wrong-workspace tick claim = 0

## Boundaries respected

No production activation.
No billing.
No customer communication.
No cross-project destructive operation.
No new provider spend.
