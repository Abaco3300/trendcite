# TrendCite — Current IRMYA State

Updated: 2026-10-07
Status: ACTIVE

## Canonical checkpoint

Repository: Abaco3300/trendcite
Canonical branch: main
Package version: 0.1.1

## Readiness

RUNTIME_CORE_READY = YES
PERSISTENT_NONPROD = YES
HOSTED_PRODUCT = NONPROD_ONLY
CUSTOMER_AUTH = REAL_NONPROD_VALIDATED
CUSTOMER_FRONTEND = REAL_NONPROD_VALIDATED
DELIVERY_INTEGRATION = REAL_NONPROD_VALIDATED / PERSISTENT_DELIVERY_DISABLED
BILLING_ENTITLEMENTS = TC-P006 CLOSED / NONCOMMERCIAL PASS
PRODUCTION_READY = NO
COMMERCIALIZATION_READY = NO

## Persistent nonprod state

Supabase schema: trendcite
Runtime role: trendcite_nonprod_runtime
Hyperdrive login role: trendcite_nonprod_hyperdrive_login
Hyperdrive: trendcite-nonprod-hyperdrive
Hyperdrive ID: 403038608f454b4b8172d9609f6a7383
Queue: trendcite-nonprod-queue
Queue ID: 752b703ee758448d81be0bc3639abfdf
DLQ: trendcite-nonprod-dlq
DLQ ID: a5c3d474d01c45e085b5152575f4408e
Worker: trendcite-nonprod-runtime
Worker version: b30cbdac-b1ef-4a7a-a90c-bd3e71461b80
Worker URL: https://trendcite-nonprod-runtime.istriadegroupllc.workers.dev
Cron: */5 * * * *
Runtime role binding: TRENDCITE_RUNTIME_ROLE=trendcite_nonprod_runtime
Persistent delivery provider binding: DISABLED
Postmark nonprod secret: PROVISIONED / WRITE_ONLY

## Closed Packs

TC-P001 — Persistent Nonprod Foundation = CLOSED / PASS
TC-P002 — Persistent Runtime E2E Hardening = CLOSED / PASS
TC-P003 — Transactional Delivery / Postmark = CLOSED / PASS
TC-P004 — Authentication and Tenant Access = CLOSED / PASS
TC-P005 — Customer Application = CLOSED / PASS
TC-P006 — Entitlements and Metering = CLOSED / PASS

## Active internal Pack

ACTIVE_PACK = TC-P007
PACK_NAME = Full Automation Readiness
PACK_STATUS = OPEN / NONPROD IMPLEMENTATION

## TC-P004 closure evidence

- Supabase Auth project JWKS endpoint: PASS
- signing algorithm: ES256
- publishable key runtime configuration: PASS
- identity validation boundary: Supabase Auth /auth/v1/user
- authorization source: trendcite.cloud_membership
- principal mapping: Supabase user id -> Membership.principal_id
- user_metadata used for authorization: NO
- customer API:
  - GET /api/v1/workspaces
  - GET /api/v1/workspaces/{workspace_id}
- persistent nonprod deploy: PASS
- real Supabase Auth session: PASS
- /health: 200 / {"ok": true}
- /api/v1/workspaces without Authorization: 401
- /api/v1/workspaces with invalid bearer: 401
- authenticated workspace list: 200
- authorized workspace A: 200
- unauthorized workspace B: 404
- workspace list contains A and excludes B: PASS
- cross-workspace existence leakage: BLOCKED
- password persisted by validator: NO
- bearer token persisted by validator: NO
- production activation: NO
- Data API exposed schemas verified via Supabase CLI: public, graphql_public, seo_agent
- trendcite schema exposed through Data API: NO
- direct PostgREST probe using Accept-Profile=trendcite: 406 / PGRST106 Invalid schema
- TrendCite database path remains direct PostgreSQL via Cloudflare Hyperdrive
- P0 = 0
- P1 = 0

## Data API security disposition

HG-TRENDCITE-PRO-V1-DATA-API-EXPOSURE-CLOSURE-001 was approved to remove only the trendcite schema if exposed.

Verification established that trendcite was already absent from the remote Data API exposed-schema list. No remote configuration change was required or performed.

The Supabase Advisor may still report RLS disabled for trendcite tables. In the current architecture those tables are not exposed through PostgREST/Data API; Hyperdrive reaches PostgreSQL directly through the controlled runtime role. RLS remains available as defense-in-depth work if the architecture later exposes these tables through Supabase client/Data API access.

## TC-P005 closure evidence

- authenticated customer API router: IMPLEMENTED
- same-transaction membership authorization: IMPLEMENTED
- viewer write denial: IMPLEMENTED
- cross-tenant reads/writes: 404 / NO EXISTENCE LEAKAGE
- watchlist/radar immutable version writes: IMPLEMENTED
- customer mutations: FAIL-CLOSED unless TRENDCITE_CUSTOMER_MUTATIONS=nonprod-enabled
- React/Vite customer application: IMPLEMENTED
- browser credential/token persistence: NONE
- workspace/watchlist/radar UI: IMPLEMENTED
- runs/signals/history/alerts/digests views: IMPLEMENTED
- frontend tests: 3/3 PASS
- frontend production build: PASS
- Python full pytest suite: PASS
- Ruff format/check: PASS
- mypy strict: PASS
- offline demo: PASS
- wheel build/install/import in isolated venv: PASS
- canonical local preflight: PASS
- PR #30 merged to main: PASS
- PR #31 runtime routing repair merged to main: PASS
- main CI after merge: PASS
- persistent nonprod deploy: PASS
- Worker Version ID: b30cbdac-b1ef-4a7a-a90c-bd3e71461b80
- frontend root /: 200 / TrendCite Pro asset shell served
- /health: 200 / {"ok": true}
- /api/v1/session without bearer: 401 / unauthorized
- /api/v1/session invalid bearer: 401 / unauthorized
- positive TC-P005 E2E: OPERATOR_CONFIRMED_COMPLETED
- positive E2E JSON artifact: NOT RECOVERED FROM LOCAL TEMP PATH; do not treat as machine evidence
- P0 = 0
- P1 = 0
- production activation: NO
- live billing / IRCL live: NO
- persistent outbound delivery: DISABLED
- Dodo Payments TEST MODE: FROZEN / NO ACTIONS
- Dodo Payments LIVE MODE: FROZEN / NO ACTIONS

## TC-P006 validation evidence

- existing idempotent metering ledger reused: trendcite.cloud_usage_event
- canonical entitlement capabilities: IMPLEMENTED
- noncommercial plans: nonprod_limited / nonprod_full
- monthly UTC usage aggregation: IMPLEMENTED
- fail-closed missing entitlement: IMPLEMENTED
- radar_run enforcement occurs before run creation: IMPLEMENTED
- customer entitlement API: IMPLEMENTED
- customer usage API: IMPLEMENTED
- Plan & Usage UI: IMPLEMENTED
- cross-tenant entitlement access: 404 / NO EXISTENCE LEAKAGE
- migration 0006_entitlements_metering: APPLIED HOSTED NONPROD
- Supabase migration history: hg_trendcite_nonprod_0006_entitlements_metering
- hosted plans seeded: commercial=0 only
- all 4 existing synthetic/nonprod workspaces assigned nonprod_full
- enabled scheduled workspace irmya-nonprod-ws has nonprod_full entitlement
- TRENDCITE_ENTITLEMENTS=nonprod-enabled: DEPLOYED NONPROD
- PR #32 merged to main: PASS
- main CI after merge: PASS
- persistent nonprod deploy: PASS
- Worker Version ID: 6178a90b-9e25-4182-b649-e158c5d08979
- positive TC-P006 E2E JSON: PASS
- auth session: 200
- authorized workspace A visible: YES
- unauthorized workspace B visible: NO
- entitlement endpoint: 200
- effective plan: nonprod_full
- usage endpoint: 200
- cross-tenant entitlement access: 404
- token persisted: NO
- password persisted: NO
- billing touched: NO
- production touched: NO
- Dodo touched: NO
- focused TC-P006 tests: PASS
- full pytest suite: PASS
- Ruff format/check: PASS
- mypy: PASS (74 source files)
- frontend tests/build: PASS
- canonical local preflight: PASS
- Cloudflare packaging source proof: PASS / 16 required modules
- pywrangler dry-run: PASS / 219 modules / ASSETS + entitlement binding present
- production activation: NO
- billing/checkout/customer charges: NO
- persistent outbound delivery: DISABLED
- Dodo Payments TEST MODE: FROZEN / NO ACTIONS
- Dodo Payments LIVE MODE: FROZEN / NO ACTIONS

## Current Human Gate

NEXT_REAL_HUMAN_GATE = NONE_CURRENTLY_IDENTIFIED

## Next automatic action

Execute TC-P007 Full Automation Readiness in persistent nonprod: automated recovery, observability, stale-work detection, retry/DLQ operational visibility and no-routine-manual-intervention controls. Keep production activation, billing, checkout, persistent outbound delivery, commercialization, Dodo TEST MODE and Dodo LIVE MODE disabled.
