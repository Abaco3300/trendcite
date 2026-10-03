[Reading 58 lines from start (total: 58 lines, 0 remaining)]

[Reading 54 lines from start (total: 54 lines, 0 remaining)]

# TC-P003 — Transactional Delivery / Postmark

Status: BUILD_READY / LIVE_VALIDATION_PENDING

## Outcome

Add a production-shaped but non-production-gated transactional delivery layer for immediate alerts and daily digests, preserving provider isolation, append-only attempt evidence, retry semantics, tenant isolation and delivered-baseline semantics.

## Architecture

- provider-neutral DeliveryEnvelope / DeliveryResult boundary remains canonical;
- Postmark adapter is async and Cloudflare-compatible;
- Postmark token, sender and recipient are environment bindings, never domain data;
- Postmark metadata includes TrendCite delivery-attempt identity for correlation;
- PostgreSQL delivery store owns alert/digest/attempt/baseline persistence;
- failed sends never advance alert baseline;
- successful sends advance baseline;
- hard max-attempt budget prevents extra provider calls;
- Radar execution and email delivery are separated by Queue work;
- email failure must not turn a succeeded Radar Run into a failed Radar Run;
- Worker delivery stays inactive unless TRENDCITE_DELIVERY_PROVIDER is explicitly set;
- only supported activation mode in this Pack is postmark-nonprod.

## Build evidence

- async Postmark adapter tests: PASS
- async delivery-service tests: PASS
- PostgreSQL delivery-store contract tests: added
- Cloudflare packaging includes new runtime modules: PASS
- fail-closed Worker configuration test: PASS
- ruff: PASS
- mypy: PASS
- full local preflight before final reconciliation: PASS
- package version remains 0.1.1

## Provider semantics

Postmark does not provide a client idempotency key for /email. TrendCite therefore preserves its own deterministic delivery-attempt identity and sends it as provider metadata for correlation. Exactly-once provider delivery is not claimed.

## Remaining live validation

- GitHub checkpoint;
- deploy delivery-capable Worker with delivery still disabled;
- verify /health + scheduled Radar path unchanged;
- provider test-mode request with no real recipient delivery;
- validate persisted delivery attempt behavior;
- validate one controlled real nonprod recipient only if explicitly authorized.

## Human-gate boundaries

Real external email delivery requires an explicitly authorized recipient.
Production delivery activation requires a separate Human Gate.
Any new paid provider spend requires a separate Human Gate.

[executed on device: LAPTOP-JOSEMILE (23bf38cb-a252-4cba-9357-1c203afc359d)]

[executed on device: LAPTOP-JOSEMILE (23bf38cb-a252-4cba-9357-1c203afc359d)]