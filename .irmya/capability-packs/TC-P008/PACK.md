# TC-P008 — Production Readiness / Foundation Provisioning

Status: FOUNDATION_DEPLOYED_DARK / REMOTE_VERIFIED / INTEGRATION_BLOCKED

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
