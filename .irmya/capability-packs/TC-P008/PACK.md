# TC-P008 — Production Readiness / Foundation Provisioning

Status: PYTHON_RUNTIME_DEPLOYED_DARK / REMOTE_VERIFIED / CUSTOMER_AND_ASYNC_ACTIVATION_BLOCKED

Latest 2026-10-13 checkpoint: PR #64 merged (`2b0a9a0e85e9f287806c8feb9fbb6c975ff03512`), post-merge main CI SUCCESS (run `38442366336`); read-only Cloudflare verified Python Worker version `0b9b3c85-463d-4259-b778-998178abffba`, DARK activation binding, Hyperdrive, no subdomain/previews/cron, prod Queue/DLQ 0 producers and 0 consumers. Portfolio-wide Dodo freeze lifted under Global Governance v1.15.0, while TrendCite-specific commercial readiness/authority remains closed. Historical Dodo freeze and unbound Hyperdrive notes below are superseded; no customer E2E or production activation is claimed.

## Real nonprod Queue integration checkpoint (2026-10-13)

Real Cloudflare Queue API accepted two identical synthetic record-only messages; actual hosted PostgreSQL ledger contains one row, no matching failure events, provider backlog observed zero. This validates nonprod delivery and ledger deduplication, **not** real broker retry, lost ACK or DLQ poison recovery. DLQ `http_pull` was disabled, so no poison message was sent. Production Queue/cron/customer and commercial activation remain blocked. Details: `NONPROD-REAL-QUEUE-DELIVERY-2026-10-13.md`. PR #66 merged, post-merge main CI SUCCESS.

## Authorized gate

HG-TRENDCITE-PRODUCTION-FOUNDATION-PROVISIONING-001 = APPROVED

This gate authorizes isolated production foundation only. It does not authorize public
traffic, customer production access, production delivery, billing, checkout, customer
charges, Dodo actions, commercialization or production VectURL activation.

## Provisioned

- PostgreSQL role trendcite_prod_runtime = CREATED / NOLOGIN / NOINHERIT.
- PostgreSQL login trendcite_prod_hyperdrive_login = CREATED / LOGIN / NOINHERIT.
- login membership = trendcite_prod_runtime only.
- schema trendcite privilege = USAGE / no CREATE.
- current 33 TrendCite tables = SELECT/INSERT/UPDATE/DELETE.
- default future table CRUD grants = configured.
- Cloudflare Queue trendcite-prod-queue = CREATED.
- Queue ID = 007435e8e7d64f1fb949368f1031e439.
- Queue producers = 0.
- Queue consumers = 0.
- Cloudflare DLQ trendcite-prod-dlq = CREATED.
- DLQ ID = 8892608637364e92a7e06ca3f7153e19.
- DLQ producers = 0.
- DLQ consumers = 0.
- dark Worker config = deploy/cloudflare/wrangler.prod.foundation.jsonc.
- workers_dev = false.
- no public routes.
- no cron.
- no Queue binding.
- no Hyperdrive binding.
- production activation flag = foundation-only.
- runtime dark guard = implemented for HTTP / Queue / scheduled handlers.

## October 10 verified technical and remote checkpoint

- GitHub PR #51 MERGED / main CI PASS.
- Local canonical PostgreSQL adapters for runs, durable Queue idempotency and schedule leases: PASS with concurrent synthetic tenants and transaction rollback.
- The Cloudflare dark Worker has been read-only verified in the account: one activation-flag-only binding, subdomain disabled, cron 0, custom domains 0, routes 0 across eight account zones.
- Prod Queue and DLQ producers=0/consumers=0; production Hyperdrive not created.
- See REMOTE-DARK-ATTESTATION-2026-10-10.md and the historical JSON snapshot.
- These results do NOT authorize public runtime or billing. The next privileged credential step is governed separately under HUMAN-GATE-SECURE-CREDENTIAL-PATH.md.

## Foundation Hyperdrive checkpoint (2026-10-12)

Production Hyperdrive `trendcite-prod-hyperdrive` has been CREATED_UNBOUND using operator-controlled protected credential entry. Cloudflare read-only API verified config ID `dae4dcf39acb4b6482bdebbd77fe94d1`, PostgreSQL restricted login identity, TLS `verify-full` + Supabase CA, disabled cache and origin connection limit 5. Worker remains DARK with no Hyperdrive/Queue binding, cron, workers.dev, or Queue/DLQ producers/consumers. See `PROD-HYPERDRIVE-CREATION-VERIFICATION-2026-10-12.md`.

Credential transport limitation resolved by operator-native entry; no password, verifier or connection string passed through connected tools. Real Worker-to-Postgres SQL / Queue E2E and production customer activation remain NOT_VERIFIED / BLOCKED; no security boundary bypassed.

## October 12 real read-only Hyperdrive SQL diagnostic

User-approved temporary Wrangler remote-development diagnostic PASS: `SELECT 1 AS probe_ok` returned HTTP 200 / `{ "ok": true }` through production Hyperdrive. The diagnostic process and files were removed; Cloudflare reports no persistent diagnostic Worker, and the dark Worker and Queues are unchanged. Evidence: `REAL-PROD-HYPERDRIVE-SQL-E2E-2026-10-12.md`. This does not authorize or verify production application/customer/Queue runtime.

## October 13 permanent DARK binding

Explicit HG-F approval for one permanent Hyperdrive binding in foundation-only mode executed: Cloudflare Worker `trendcite-prod-runtime` version `0293abca-2382-4f6c-891a-643caf5fe758`, binding `TRENDCITE_PROD_DB` to `dae4dcf39acb4b6482bdebbd77fe94d1`. Cloudflare read-only API confirmed only that binding plus the original `foundation-only` flag; no cron, workers.dev, Queue producers/consumers. No targets deployed. Production customer/Queue/cron/commercial activation remains blocked. Evidence `PROD-HYPERDRIVE-DARK-BINDING-2026-10-13.md`.

## Historical decision contract for production runtime

`PRODUCTION-RUNTIME-EXPANSION-DECISION-2026-10-13.md` records the pre-authorization decision boundary, safeguards and rollback acceptance criteria. The subsequent explicit HG-A/HG-H authorization and DARK deployment are documented below. The historical decision document is not by itself an approval for future activation.

## October 13 authorized persistent runtime in DARK mode

Explicit operator HG-A/HG-H authorization exercised: Python runtime `src/main.py` deployed under `wrangler.prod.runtime.dark.jsonc`, Cloudflare version `0b9b3c85-463d-4259-b778-998178abffba`. `foundation-only` role guard and read-only Cloudflare metadata verify no routes, no cron, no workers.dev or Queue producers/consumers. No customer/application runtime E2E claimed. Prior DARK version retained for rollback. See `PRODUCTION-RUNTIME-DARK-DEPLOY-2026-10-13.md`.

## Boundaries preserved

PUBLIC_PRODUCTION_TRAFFIC = NO
CUSTOMER_PRODUCTION_ACCESS = NO
PRODUCTION_DELIVERY = NO
BILLING = NO
CHECKOUT = NO
CUSTOMER_CHARGES = NO
DODO_TEST = FROZEN / NO ACTIONS
DODO_LIVE = FROZEN / NO ACTIONS
PRODUCTION_VECTURL = NO
COMMERCIALIZATION = NO
