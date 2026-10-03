# TC-P001 — Persistent Nonprod Foundation

Status: OPEN / BLOCKED_AT_CREDENTIAL_TRANSPORT

## Outcome

Create and validate the permanent TrendCite non-production runtime foundation.

## In scope

- canonical trendcite schema and migrations;
- nonprod database runtime/login roles;
- Cloudflare Hyperdrive;
- Queue + DLQ;
- persistent Worker;
- Cron;
- health check;
- controlled nonprod E2E;
- project-state registration.

## Acceptance criteria

- 27 canonical tables present.
- NOINHERIT login has no direct TrendCite table privileges.
- runtime role access works via SET LOCAL ROLE.
- Hyperdrive connected.
- Worker deployed with HYPERDRIVE + TREND_QUEUE.
- Queue consumer and DLQ configured.
- Cron registered.
- /health PASS.
- scheduled() automatic fire PASS.
- automatic tick persistence PASS.
- Queue -> Worker execution PASS.
- Radar execution and result persistence PASS.
- unrelated ISTRIADE project resources untouched.
- P0=0, P1=0.

## Current blocker

Persistent database credential must be configured manually because plaintext secret transport through chat/Git is prohibited. The resource decision is already within the authorized nonprod outcome; the required human action is transport, not a new product decision.

## Resume

After credential + Hyperdrive creation confirmation, IRMYA resumes automatically through packaging, deploy, validation, repair, QA, Pack close, and next required Pack unless a genuine Human Gate appears.
