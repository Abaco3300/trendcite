# TC-P003 — Transactional Delivery / Postmark

Status: CLOSED / PASS

## Outcome

Add a production-shaped but non-production-gated transactional delivery layer for immediate alerts and daily digests, preserving provider isolation, append-only attempt evidence, retry semantics, tenant isolation and delivered-baseline semantics.

## Closure evidence

- provider-neutral async delivery boundary: PASS
- Postmark adapter and Cloudflare POST transport: PASS
- PostgreSQL delivery store: PASS
- retry and hard max-attempt semantics: PASS
- failed delivery never advances baseline: PASS
- successful delivery advances baseline: PASS
- test-mode provider validation: PASS
- real nonprod provider validation: PASS
- authorized recipient: correo@dominio.com
- verified domain: notify.istriadegroup.com
- final sender: trendcite@notify.istriadegroup.com
- final attempt number: 3
- final status: succeeded
- provider reference: 98895ae8-3c79-409b-9295-4317d10dbcd4
- delivered_at: 2026-10-04T23:36:23Z
- persistent delivery binding disabled after validation: PASS
- synthetic validation data removed: PASS
- production untouched: PASS
- P0=0
- P1=0

## Provider semantics

Postmark does not provide a client idempotency key for /email. TrendCite preserves its own deterministic delivery-attempt identity and sends it as provider metadata for correlation. Exactly-once provider delivery is not claimed.

## Closure

HG-TRENDCITE-PRO-V1-POSTMARK-NONPROD-REAL-DELIVERY-001 was approved and consumed.
TC-P003 is complete.
