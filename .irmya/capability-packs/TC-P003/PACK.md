# TC-P003 — Transactional Delivery / Postmark

Status: TEST_MODE_VALIDATED / REAL_RECIPIENT_HUMAN_GATE

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
- PostgreSQL delivery-store contract tests: PASS
- Cloudflare packaging includes required runtime modules: PASS
- fail-closed Worker configuration test: PASS
- ruff: PASS
- mypy: PASS
- canonical local preflight: PASS
- package version: 0.1.1

## Provider semantics

Postmark does not provide a client idempotency key for /email. TrendCite therefore preserves its own deterministic delivery-attempt identity and sends it as provider metadata for correlation. Exactly-once provider delivery is not claimed.

## Packaging remediation

- stale mixed vendor after initial delivery-capable deploy: confirmed
- root cause: worker uv source / lock / vendor retained TrendCite 0.1.0
- root project version drives wheel name: PASS
- worker pyproject rewritten to exact wheel: PASS
- generated python_modules / venv / lock caches invalidated: PASS
- pywrangler sync executed by preparer: PASS
- wheel/vendor byte equality checked: PASS
- pylock current-version/current-wheel assertions: PASS
- regenerated vendor version: 0.1.1
- pywrangler dry-run: PASS (211 modules)
- remediation PR #26: MERGED
- clean persistent nonprod redeploy: PASS
- persistent Worker version: ddb8640c-6a88-4483-9b60-1655cde4522a
- production untouched

## Runtime regression evidence after remediation

- /health: PASS (HTTP 200)
- automatic tick 2026-10-03T22:00:00Z: succeeded
- corresponding Radar Run: succeeded
- coverage_state: complete
- existing Hyperdrive / Queue / Cron bindings preserved
- Postmark delivery provider not enabled on persistent Worker

## Postmark test-mode validation

Executed with POSTMARK_API_TEST and fictitious sender/recipient values, so no real email was delivered.

Results:
- isolated synthetic workspace: PASS
- alert materialization: PASS
- provider request: PASS
- alert delivery_state: delivered
- attempt_count: 1
- cloud_delivery_attempt status: succeeded
- provider reference persisted: PASS
- delivered baseline advanced after success: PASS
- probe Worker deleted: PASS
- synthetic workspace and all dependent rows deleted: PASS
- temporary probe source/config deleted: PASS
- clean persistent Worker redeployed without probe module: PASS

## Human Gate

HG-TRENDCITE-PRO-V1-POSTMARK-NONPROD-REAL-DELIVERY-001

A real external email must not be sent until the human explicitly authorizes:
- exactly one controlled real nonprod delivery;
- the intended recipient;
- use of real nonprod Postmark credential/sender configuration.

Production activation and new paid provider spend remain separate Human Gates.
