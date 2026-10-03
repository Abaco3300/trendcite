# TC-P002 — Persistent Runtime E2E Hardening

Status: OPEN

## Outcome

Prove that the persistent non-production runtime behaves correctly across repeated executions, duplicate delivery, failure/retry and lease-recovery conditions before delivery/auth/frontend work begins.

## In scope

- repeated scheduled execution across multiple boundaries;
- idempotent Radar Run identity;
- schedule tick deduplication;
- generic queue delivery deduplication;
- retry behavior;
- max-attempt handling;
- lease expiry and reclaim;
- stale-owner settlement protection;
- controlled nonprod failure injection where safe;
- persistent operational evidence;
- project state updates.

## Acceptance criteria

- repeated automatic runs remain successful;
- duplicate logical work does not create duplicate Radar Runs;
- duplicate schedule boundaries do not create duplicate ticks;
- generic queue duplicate delivery is neutralized;
- retryable failures follow configured retry semantics;
- exhausted attempts settle deterministically;
- expired leases can be reclaimed safely;
- stale owners cannot settle reclaimed work;
- no cross-workspace leakage;
- no cross-project mutation;
- canonical local preflight PASS;
- P0=0;
- P1=0.

## Boundaries

No production activation.
No live billing.
No external customer communication.
No destructive cross-project operations.
No new provider spend.
