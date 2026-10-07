# TC-P007 — Full Automation Readiness

Status: OPEN / NONPROD IMPLEMENTATION

## Outcome

Make TrendCite Pro capable of routine autonomous nonprod operation without manual intervention by adding deterministic recovery, observability and stale-work controls around the existing scheduler, queue, retries and DLQ.

## Scope

- automated stale-run detection and safe recovery;
- retry-state visibility and deterministic retry exhaustion handling;
- DLQ operational visibility and replay-safe recovery controls;
- scheduler liveness and overdue-work detection;
- health/operations summary endpoints for authorized operators;
- durable audit trail for automated recovery decisions;
- explicit classification of recoverable vs terminal failures;
- tests proving no duplicate run creation, no cross-tenant recovery and no hidden infinite retry loops.

## Authorized

- additive TrendCite-only schema changes if required;
- nonprod Worker/runtime changes;
- synthetic failure/recovery fixtures;
- local tests/preflight, one logical GitHub checkpoint, CI, merge;
- safe persistent nonprod deployment and E2E validation.

## Not authorized

- production activation;
- persistent outbound delivery activation;
- billing, checkout or customer charges;
- IRCL live;
- Dodo Payments TEST MODE actions;
- Dodo Payments LIVE MODE actions;
- Stripe or other PSP work;
- real customer communication;
- destructive migrations or irreversible data operations.

## Dodo freeze

DODO_PAYMENTS_TEST_MODE = FROZEN
DODO_PAYMENTS_LIVE_MODE = FROZEN

No Dodo API calls, dashboard reads/writes, products, prices, checkouts, webhooks, tests, configuration or integration changes are permitted until an explicit new human order.

## Acceptance criteria

1. Stale in-progress work is detected deterministically.
2. Safe recovery does not duplicate already completed work.
3. Retry exhaustion becomes terminal and observable.
4. DLQ state is visible and replay decisions are idempotent.
5. Scheduler liveness and overdue schedules are observable.
6. Automated recovery actions are auditable.
7. Recovery remains workspace/tenant scoped.
8. Operator-facing health/ops summary exists without exposing secrets.
9. Local canonical preflight passes.
10. Remote CI passes at one logical checkpoint.
11. Safe persistent-nonprod deploy and E2E validation pass.
12. Production, billing, outbound delivery activation and all Dodo actions remain disabled.

## Human Gates

No Human Gate for implementation, tests, commits, PR, CI, safe nonprod deploy or synthetic recovery validation.

Stop only for genuine authority boundaries: new spend, contracts/legal/tax, new protected credential authority, real third-party/customer communication, production/external activation, live financial action, destructive/hard-to-reverse action, non-remediable P0, or material scope change.


## Current implementation evidence

- Additive migration 0007 applied to hosted nonprod.
- Scheduler heartbeat, stale-work detection, retry exhaustion terminalization and recovery audit implemented.
- Queue failure visibility uses Cloudflare message attempts and max_attempts=3 for max_retries=2.
- /operations is authenticated and workspace membership-scoped.
- claim_tick cannot reacquire an expired lease once attempt >= max_attempts.
- Recovery rollout is protected by TRENDCITE_AUTOMATION_RECOVERY_AFTER=2026-10-07T21:30:00+00:00.
- Legacy TC-P002 stale fixtures remain visible but are excluded from automatic replay.
- Hosted stale candidates after the watermark: zero before deployment.
- Focused tests: 37/37 PASS.
- Full canonical preflight: PASS.
- mypy: PASS across 77 source files.
- Cloudflare packaging proof: PASS with 19 required modules.
- pywrangler nonprod dry-run: PASS with 223 modules.
- Production, billing, checkout, persistent outbound delivery activation and all Dodo actions remain disabled.
