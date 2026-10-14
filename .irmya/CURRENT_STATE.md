# TrendCite — Current IRMYA State

Updated: 2026-10-13
Status: ACTIVE

## Four parallel hosted PostgreSQL inserts — 2026-10-14

- Four concurrent SQL submission requests with the same nonprod tenant/logical identity and distinct delivery IDs yielded one inserted row and three `ON CONFLICT DO NOTHING` results; a later SELECT confirmed exactly one row. This validates hosted database idempotency under parallel submissions, **not** independent Worker consumer execution or postcommit lost ACK. Evidence: `.irmya/capability-packs/TC-P008/NONPROD-PARALLEL-POSTGRES-INSERT-2026-10-14.md`. Production DARK.

## Five parallel real Cloudflare Queue publications — 2026-10-14

- Five simultaneous synthetic nonprod Queue API sends (unique delivery IDs, one tenant/logical identity) all accepted HTTP 200; real hosted Postgres held exactly one logical row; zero related failure events; Queue and DLQ backlog/peeks both zero. This verifies concurrent **producer submissions**, not independent concurrent consumers or real lost-ACK/crash. Evidence: `.irmya/capability-packs/TC-P008/NONPROD-PARALLEL-PUBLISH-IDEMPOTENCY-2026-10-14.md`. No production activation.

## Consolidated TC-P008 Queue acceptance — 2026-10-13

- PR #71 merged as `00ceef86ec447a22d4183b42dd94474f9ed9e4c2`; adds isolated ACK-exception after fake durable commit plus deduplicated replay. This is **not real broker lost-ACK E2E**.
- Single evidence matrix separates actual Cloudflare nonprod delivery, duplicate idempotency, three retry attempts and DLQ cleanup from isolated tests and still-unverified crash/concurrency/lost-ACK scenarios: `.irmya/capability-packs/TC-P008/NONPROD-QUEUE-ACCEPTANCE-MATRIX-2026-10-13.md`.
- Production Queue remains DARK and material activation requires real HG-H, not an invented operational gate.

## Latest real nonprod broker retries checkpoint — 2026-10-13

- A synthetic PostgreSQL delivery-ID collision in the existing nonprod Cloudflare Queue yielded **three distinct actual failure attempts** (1, 2, 3; max 3; `UniqueViolationError`) persisted in `trendcite.cloud_queue_failure_event` under one real Queue message ID. The exact message then appeared in the real nonprod DLQ. Targeted purge HTTP 200; source Queue and DLQ were both empty afterward (metrics plus peeks). No production modification.
- Real broker retry-to-DLQ PASS; missing-ACK after **successful** durable commit remains NOT_VERIFIED. Exact evidence: `.irmya/capability-packs/TC-P008/NONPROD-REAL-BROKER-RETRY-2026-10-13.md`.

## Latest real nonprod poison/DLQ checkpoint — 2026-10-13

- Controlled malformed nonprod Queue message reached actual Cloudflare `trendcite-nonprod-dlq`, matched unique synthetic marker, then was removed using `messages/peek` + **targeted** `messages/purge` (HTTP 200); source Queue and DLQ postcheck: backlog 0, peek 0. Real poison-to-DLQ and safe targeted removal PASS; precise retry count and actual lost-ACK redelivery NOT_VERIFIED.
- PR #68 merged as `7c065015f8fa780abc91481c226f046a926477d6`, post-merge main CI run `38495796075` SUCCESS. Five isolated Queue handler tests PASS, including audit failure and mixed-batch isolation.
- Evidence: `.irmya/capability-packs/TC-P008/NONPROD-REAL-POISON-DLQ-2026-10-13.md`. No production integration authority or activation added.

## Latest real nonprod Queue checkpoint — 2026-10-13

- PR #66 merged into `main` as `e30dddeef5f3388aacffa4e94f33545266de90f2`; post-merge GitHub Actions run `38483549165` SUCCESS. Isolated actual Python Queue handler ACK/retry/DARK tests PASS; not real broker-induced retry proof.
- One fixed synthetic message sent via Cloudflare nonprod Queue API: HTTP 200; PostgreSQL ledger insert observed in `trendcite.cloud_queue_delivery` at 2026-10-13T23:21:35+00:00. Identical payload sent a second time: HTTP 200; ledger remained exactly one row, failure events zero, Queue backlog returned zero (best-effort metric).
- This is real nonprod delivery and duplicate-payload deduplication; **not** real lost-ACK redelivery or poison-message DLQ proof. DLQ `http_pull` currently disabled; no poison message or cleanup attempted. Production remains DARK.
- Evidence: `.irmya/capability-packs/TC-P008/NONPROD-REAL-QUEUE-DELIVERY-2026-10-13.md`.

## Latest verified TC-P008 checkpoint — 2026-10-13

- PR #64 merged to `main` as `2b0a9a0e85e9f287806c8feb9fbb6c975ff03512`; post-merge GitHub Actions run `38442366336` SUCCESS.
- Cloudflare read-only API revalidated `trendcite-prod-runtime` deployment version `0b9b3c85-463d-4259-b778-998178abffba` (100%), `workers.dev=false`, previews disabled, cron 0, only Hyperdrive `TRENDCITE_PROD_DB` (`dae4dcf39acb4b6482bdebbd77fe94d1`) plus DARK activation and restricted runtime-role bindings.
- Prod Queue `007435e8e7d64f1fb949368f1031e439` and DLQ `8892608637364e92a7e06ca3f7153e19`: Cloudflare API 200; each has 0 producers and 0 consumers.
- Fresh clean worktree at PR #64 merge commit: local static Python DARK validator PASS (`dark_ready=true`, `production_activated=false`); full canonical local CI preflight PASS after frontend npm dependencies installed; no production E2E claimed.
- Global governance v1.15.0 supersedes historical portfolio Dodo freeze claims: Dodo is operational portfolio-wide; TrendCite-specific commercial activation remains unapproved and readiness unproven.
- Actual TC-P008 external-impact activation boundaries remain closed: no customer routes, Queue processing, cron, paid delivery, VectURL prod or IRCL checkout activation.

The older checkpoint statements below are historical and must not override this latest verified state.

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

## Current TC-P008 checkpoint (2026-10-10)

- Previous TC-P001 through TC-P007 historical evidence below is retained as an audit record; `ACTIVE_PACK` now denotes TC-P008.
- Canonical main: PR #51 merged / commit b5b482ab44c33e58344a436591632f8a34505e7b / PR CI PASS / post-merge main CI PASS.
- Real local PostgreSQL 17 adapter/Queue-ledger: PASS, 24 concurrent run attempts and 24 Queue claims, tenant separation, idempotent replay, unrelated delivery identity collision fail-closed.
- Real local schedule lease/settlement: PASS, 12 competing claims, expired lease reclaim, stale owner denial, terminal attempt limit.
- Postgres schema migrations used for isolated tests: 0001 / 0004 / 0005. No live database migrations.
- Production Worker trendcite-prod-runtime: DEPLOYED_DARK / read-only Cloudflare verification PASS / version b495ea31-8cb5-4c31-a9b9-0e94ca045c7b.
- Prod Worker: no workers.dev, no preview, no cron, no script route across all 8 account zones, no custom domain, no Queue or Hyperdrive bindings.
- Historical Oct 10 snapshot: Prod Queue and DLQ 0 producers / 0 consumers; production Hyperdrive was NOT_CREATED at that time.
- Nonprod runtime latest verified Worker version: 9a9ce619-a80b-414b-bca6-4989279163a5 (some old records below retain historical versions).
- Integration gaps: real Cloudflare Queue ACK/redelivery under new code NOT_VERIFIED; remote production credential transport BLOCKED.
- Dodo TEST/LIVE = FROZEN; production customer runtime, VectURL and commercial activation = BLOCKED.
- Remote dark snapshot evidence: .irmya/evidence/TC-P008-CLOUDFLARE-DARK-SNAPSHOT-2026-10-10.json (historical, not live monitoring).
- Secure credential path research approved; Supabase read-only restricted role verification PASS; Cloudflare ordinary Postgres Hyperdrive requires write-only password; managed integration available only for PlanetScale, not Supabase.
- HG-TRENDCITE-P008-PROD-HYPERDRIVE-SECURE-CREDENTIAL-PATH-001 = PROCEDURE_RESEARCH_COMPLETE / OPERATOR_NATIVE_ENTRY_PENDING; no credentials transmitted or Hyperdrive created.
- Procedure and no-secret human action boundary: .irmya/capability-packs/TC-P008/PROD-HYPERDRIVE-SECURE-PATH-VERIFICATION.md.


## TC-P008 current remote checkpoint — 2026-10-12

- HG-TRENDCITE-P008-PROD-HYPERDRIVE-SECURE-CREDENTIAL-PATH-001: OPERATOR_NATIVE_ENTRY_COMPLETED / REMOTE_METADATA_PASS. No password, verifier or connection string retrieved or stored by executor.
- Hyperdrive `trendcite-prod-hyperdrive` ID `dae4dcf39acb4b6482bdebbd77fe94d1`: CREATED_UNBOUND; origin `db.yntcafxmjgfjrdinwdmo.supabase.co:5432`, database `postgres`, username `trendcite_prod_hyperdrive_login`.
- Cloudflare read-only GET: TLS `verify-full` with CA `42488d5e-25c1-42dc-971e-b44cfefca64f`; caching disabled; maximum origin connections 5.
- Dark controls reverified: production Worker binding only `TRENDCITE_PRODUCTION_ACTIVATION` (plain text), Queue/DLQ zero producers and zero consumers, cron zero, workers.dev disabled. Cloudflare read-only checks HTTP 200.
- This is metadata verification, **not** proof of a live Worker-to-Postgres SQL query, a Queue ACK delivery, or customer readiness.
- Production Worker/Queue/cron/routes, customer traffic, billing, Dodo TEST/LIVE, VectURL production remain blocked. Do not confuse isolated infrastructure availability with authorization to activate it.
- Evidence: `.irmya/capability-packs/TC-P008/PROD-HYPERDRIVE-CREATION-VERIFICATION-2026-10-12.md`.

## TC-P008 diagnostic read-only SQL checkpoint — 2026-10-12

- Operator-approved temporary, isolated Wrangler remote-development Worker bound to production Hyperdrive executed `SELECT 1 AS probe_ok` successfully, HTTP 200 / `{ "ok": true }`.
- Diagnostic process stopped and temporary local directory removed; Cloudflare Worker script listing confirms no persistent diagnostic script.
- Production `trendcite-prod-runtime` unchanged (only dark activation flag); Queue/DLQ 0 producers/consumers. No customer access, cron, public routes, Dodo or billing.
- Real Hyperdrive SQL diagnostic PASS is not full production runtime, authentication, tenant-isolation or Queue E2E proof.
- Evidence: `.irmya/capability-packs/TC-P008/REAL-PROD-HYPERDRIVE-SQL-E2E-2026-10-12.md`.

## TC-P008 permanent dark Hyperdrive binding — 2026-10-13

- Explicit operator authorization: HG-F, permanent Hyperdrive binding exclusively DARK/foundation-only, without public routes, customers, Queue, cron, Dodo, billing or new spend.
- Wrangler deployed `trendcite-prod-runtime` version `0293abca-2382-4f6c-891a-643caf5fe758`; binding `TRENDCITE_PROD_DB` maps only to Hyperdrive `dae4dcf39acb4b6482bdebbd77fe94d1`.
- Cloudflare independent GET verified only that Hyperdrive binding and `TRENDCITE_PRODUCTION_ACTIVATION=foundation-only`; cron 0; workers.dev false; Queue and DLQ producers 0 / consumers 0.
- Hyperdrive remains TLS verify-full, cache disabled, maximum origin connections 5. No customer runtime or commercial activation authorized; main Worker retains 404/queue-reject/scheduled-noop source.
- Evidence: `.irmya/capability-packs/TC-P008/PROD-HYPERDRIVE-DARK-BINDING-2026-10-13.md`.

## TC-P008 permanent Python runtime DARK deployment — 2026-10-13

- Explicit HG-A/HG-H authorization exercised: replaced minimal DARK Worker deployment with persistent TrendCite Python runtime, without customer or asynchronous activation.
- New Cloudflare Worker version `0b9b3c85-463d-4259-b778-998178abffba`; `wrangler.prod.runtime.dark.jsonc`, entrypoint `src/main.py`, Python Workers package 227 modules; packaging source proof and Wrangler dry-run PASS.
- Independent Cloudflare read-back: Hyperdrive `TRENDCITE_PROD_DB`, runtime role `trendcite_prod_runtime`, `TRENDCITE_PRODUCTION_ACTIVATION=foundation-only`, workers.dev false, cron 0, Queue/DLQ 0 producers and consumers.
- `No targets deployed`; no customer access, Dodo, billing, VectURL production, Queue processing, cron or delivery enabled. This is deployment confirmation, not production application E2E.
- Rollback candidate: prior verified `foundation-dark.js` Worker version `0293abca-2382-4f6c-891a-643caf5fe758`.
- Evidence: `.irmya/capability-packs/TC-P008/PRODUCTION-RUNTIME-DARK-DEPLOY-2026-10-13.md`.

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
Worker version: 9a9ce619-a80b-414b-bca6-4989279163a5 (remote verified 2026-10-10; older historical references retained below)
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

ACTIVE_PACK = TC-P008
PACK_NAME = Production Readiness / Dark Foundation & Integration
PACK_STATUS = FOUNDATION_DARK_REMOTE_VERIFIED / LOCAL_REAL_POSTGRES_E2E_PASS / CUSTOMER_ACTIVATION_BLOCKED

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

## TC-P007 validation evidence

- durable scheduler heartbeat: IMPLEMENTED
- stale pending / retryable failed / expired lease detection: IMPLEMENTED
- expired final-attempt terminalization: IMPLEMENTED
- recovery audit ledger: IMPLEMENTED
- Queue failure ledger with total-attempt semantics: IMPLEMENTED
- Cloudflare Queue max_retries=2 mapped to max_attempts=3: VERIFIED
- authenticated /operations summary: IMPLEMENTED / MEMBERSHIP-SCOPED
- scheduler liveness and overdue schedule observability: IMPLEMENTED
- claim_tick cannot exceed max_attempts: VERIFIED
- migration 0007_full_automation_readiness: APPLIED HOSTED NONPROD
- Supabase migration history: hg_trendcite_nonprod_0007_full_automation_readiness
- runtime role privileges on new tables: VERIFIED
- legacy stale records identified as TC-P002 synthetic fixtures
- TRENDCITE_AUTOMATION_RECOVERY_AFTER=2026-10-07T21:30:00+00:00
- stale recovery candidates after activation watermark: 0
- legacy pre-watermark fixtures remain observable but are not auto-replayed
- focused TC-P007 tests: PASS (37/37)
- full pytest suite: PASS
- Ruff format/check: PASS
- mypy: PASS (77 source files)
- frontend tests/build: PASS
- canonical local preflight: PASS
- Cloudflare packaging source proof: PASS / 19 required modules
- pywrangler dry-run: PASS / 223 modules
- production activation: NO
- billing/checkout/customer charges: NO
- persistent outbound delivery activation: NO
- Dodo Payments TEST MODE: FROZEN / NO ACTIONS
- Dodo Payments LIVE MODE: FROZEN / NO ACTIONS

## VectURL linked-content readiness — 2026-10-07

`TRENDCITE_VECTURL_LINKED_CONTENT_READINESS = READY_FOR_NONPROD_CREDENTIAL_GATE`
`TRENDCITE_VECTURL_CLIENT_MAIN = 3e7bae30dae3063ce13af9e3074c55048b19d6ca`
`TRENDCITE_VECTURL_INTENDED_CONSUMER_ID = trendcite-nonprod`
`TRENDCITE_VECTURL_CREDENTIAL = NOT_ISSUED`
`TRENDCITE_VECTURL_RUNTIME = DORMANT`
`TRENDCITE_SCORING_IMPACT = NONE_BY_DESIGN`

Architecture:
- existing Hacker News / GitHub / Reddit / RSS / Dev.to adapters remain authoritative for source-native evidence and engagement metrics;
- VectURL linked content is represented as a separate `LinkedContentEvidence` object;
- VectURL output does not become an `EvidenceItem`;
- therefore VectURL cannot change recency, engagement, corroboration, relevance, diversity, source count or publisher count;
- the client is canonical-host pinned, server-side authenticated, zero-cost and best-effort;
- returned text/provenance is bounded before use;
- no credential, hosted runtime change or external VectURL request occurred in this readiness work.

Validation:
- PR #33 first CI run: mypy PASS / pytest PASS / Ruff formatting failed only;
- canonical Ruff formatter applied;
- exact-head CI run #81 = PASS;
- PR #33 merged as `3e7bae30dae3063ce13af9e3074c55048b19d6ca`.

## Current Human Gate

NEXT_REAL_HUMAN_GATE = HG-TRENDCITE-VECTURL-NONPROD-INTERNAL-CONSUMER-ONBOARDING-001

## Next automatic action

Create one logical GitHub checkpoint for TC-P007, run remote CI once, merge if green, then deploy only persistent nonprod and validate heartbeat plus the authenticated /operations surface. Keep production activation, billing, checkout, persistent outbound delivery, commercialization, Dodo TEST MODE and Dodo LIVE MODE disabled.


## HG-TRENDCITE-VECTURL-NONPROD-INTERNAL-CONSUMER-ONBOARDING-001 — 2026-10-07

`RESULT = PASS / CLOSED`
`TRENDCITE_VECTURL_CONSUMER_ID = trendcite-nonprod`
`TRENDCITE_VECTURL_CREDENTIAL = ISSUED / SERVER_SIDE_ONLY / NONPROD`
`TRENDCITE_VECTURL_SMOKE = PASS / CLOSED`
`TRENDCITE_VECTURL_RUNTIME_ROUTING = NOT_ACTIVATED`
`TRENDCITE_SCORING_IMPACT = NONE`
`DODO_TEST_AND_LIVE_FREEZE = ACTIVE_USER_ORDER`

Implementation:
- VectURL PR #41 added the dedicated isolated secret slot for `trendcite-nonprod`; merge `2aa55026ae3e639a392816b8ab7955081655fbe5`;
- VectURL production auth code deployed as version `be29e48e-4a0e-4764-b393-0252be337afb`;
- persistent consumer secret installed in VectURL as `VECTURL_CONSUMER_TOKEN_TRENDCITE_NONPROD`;
- VectURL current version after secret installation: `1beb1221-e78f-4b53-bf89-b7ab346b01d6`;
- TrendCite PR #36 added the guarded nonprod smoke and canonical VectURL identity vars; merge `a433eb2d5339f2dcac82b031f39ec8967c1aa980`;
- exact repository wheel packaging proof PASS; wheel SHA-256 `adce12ac4aba3a680c8cd11414c6b0a90935409f73335e2644c4b9508d33a302`;
- TrendCite nonprod runtime deployed as version `f2008be7-5673-4d14-b68a-943f8e9f0269`;
- persistent `VECTURL_CONSUMER_TOKEN` installed as secret_text.

Controlled smoke:
- source = `https://example.com/`;
- consumer = `trendcite-nonprod`;
- required capabilities = metadata + text;
- policy = best_effort;
- max cost = 0 micro-USD;
- result bundle = `veb_926c307ff529c0e6ee11d1d9`;
- status = ready;
- fulfilled = text + metadata;
- missing capabilities = none;
- actual cost = 0 micro-USD.

Durable VectURL telemetry:
- `ingestion_create / 2xx / count 1 / 422 ms / cost 0`;
- `ingestion_status / 2xx / count 1 / 73 ms / cost 0`;
- `content_get / 2xx / count 1 / 37 ms / cost 0`.

Closure:
- temporary `TRENDCITE_VECTURL_SMOKE_TOKEN` deleted;
- local temporary token files/scripts deleted;
- final TrendCite secret list contains `POSTMARK_SERVER_TOKEN` and permanent `VECTURL_CONSUMER_TOKEN` only;
- final TrendCite Worker version after smoke-secret deletion = `8c550a88-2de5-4829-97b7-c395cc186fc0`;
- `GET /health` = HTTP 200 / ok true;
- unauthenticated internal smoke route = HTTP 404.

Boundary preserved:
- VectURL linked-content enrichment is still dormant in normal TrendCite execution;
- VectURL does not create `EvidenceItem` rows and cannot alter scoring;
- no production, customer traffic, commercialization, billing, IRCL, Dodo or customer charge occurred.

`NEXT_REAL_HUMAN_GATE_VECTURL = HG-TRENDCITE-VECTURL-NONPROD-RUNTIME-ENRICHMENT-ACTIVATION-001`


## HG-TRENDCITE-VECTURL-NONPROD-RUNTIME-ENRICHMENT-ACTIVATION-001 — 2026-10-07

`RESULT = PASS / ACTIVE_NONPROD`
`TRENDCITE_VECTURL_ENRICHMENT = nonprod-enabled`
`TRENDCITE_VECTURL_CONSUMER = trendcite-nonprod`
`MAX_ENRICHMENTS_PER_RUN = 3`
`VECTURL_MAX_COST_MICRO_USD = 0`
`SCORING_IMPACT = NONE_BY_ARCHITECTURE_AND_VALIDATION`
`PRODUCTION_ACTIVATION = NO`
`DODO_TEST_AND_LIVE_FREEZE = ACTIVE_USER_ORDER`

Implementation:
- PR #38 implemented post-score VectURL linked-content enrichment and merged as `4c65d9ce45eb88b18475cac25f4e6368e61535ca`;
- PR #40 reconciled the linked-content persistence schema forward-only; canonical main after reconciliation = `52dbca2f599d3ea172390216d5d75ca7a0b0cc9d`;
- canonical persistence table = `trendcite.cloud_run_linked_content`;
- transient duplicate `cloud_linked_content_evidence` removed by migration 0009;
- runtime role `trendcite_nonprod_runtime` has SELECT/INSERT/UPDATE/DELETE on the canonical table;
- anon/authenticated have no grants;
- hosted migration history records the 0008 and 0009 VectURL migrations/reconciliation.

Runtime semantics:
- TrendCite source-native adapters execute first;
- Signal Engine scoring completes before VectURL enrichment;
- VectURL can enrich at most 3 unique linked URLs per radar run;
- enrichment uses `best_effort` + `maxCostMicroUsd=0`;
- VectURL failures are fail-open and cannot fail the radar run;
- linked content persists separately from `EvidenceItem`, signal snapshots and score components.

Hosted validation:
- temporary multi-source radar version: `irmya-nonprod-radar-v4-vecturl-runtime-validation`;
- sources: hackernews + github + rss + reddit;
- local live precheck: 115 items / 5 briefs;
- hosted validation run: `9a653c9597105560b73c3c9a96b97ba3`;
- run status: succeeded;
- signal_count: 5;
- coverage: complete;
- source coverage: GitHub 30 / Hacker News 30 / Reddit 50 / RSS 45;
- canonical score snapshots persisted for all 5 signals with normal score/component fields;
- linked-content rows: 3 for 3 distinct signals;
- linked-content aggregate cost: 0 micro-USD;
- VectURL bundle quality on all 3 persisted rows: overall 0.9 / completeness 1 / provenance coverage 1.

Scoring-invariance evidence:
- score data remained in `cloud_signal_evaluation` / `cloud_run_signal`;
- VectURL data persisted only in `cloud_run_linked_content`;
- the enrichment path receives an already-built/scored Report and never creates `EvidenceItem`;
- test suite explicitly compares score totals/components/evidence IDs before and after enrichment;
- hosted run persisted scoring and linked-content independently.

Validation runtime lifecycle:
- temporary validation route deployed only to nonprod;
- one controlled invocation executed through the real `AsyncCloudApplicationRunner`;
- temporary route removed by redeploying canonical main;
- no temporary validation secret was installed;
- final Worker version: `9a9ce619-a80b-414b-bca6-4989279163a5`;
- final secret list: `POSTMARK_SERVER_TOKEN`, `VECTURL_CONSUMER_TOKEN` only;
- health: HTTP 200 / ok true;
- canonical repository contains no validation-route code.

Synthetic radar restoration:
- validation version v4 was append-only;
- canonical behavior restored with `irmya-nonprod-radar-v5-restore-after-vecturl-validation`;
- restored sources = hackernews;
- restored niche = ai + agents.

Boundary:
- enrichment is active only in TrendCite nonprod;
- no customer production traffic, commercialization, billing, IRCL, Dodo or customer charge occurred.

`NEXT_REAL_HUMAN_GATE_VECTURL = TRENDCITE_PRODUCTION_VECTURL_ENRICHMENT_ACTIVATION_IF_EVER_DESIRED`
