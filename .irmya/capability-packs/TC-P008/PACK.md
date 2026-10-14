# TC-P008 — Production Readiness / Foundation Provisioning

Status: PYTHON_RUNTIME_DEPLOYED_DARK / REMOTE_VERIFIED / CUSTOMER_AND_ASYNC_ACTIVATION_BLOCKED

Latest 2026-10-13 checkpoint: PR #64 merged (`2b0a9a0e85e9f287806c8feb9fbb6c975ff03512`), post-merge main CI SUCCESS (run `38442366336`); read-only Cloudflare verified Python Worker version `0b9b3c85-463d-4259-b778-998178abffba`, DARK activation binding, Hyperdrive, no subdomain/previews/cron, prod Queue/DLQ 0 producers and 0 consumers. Portfolio-wide Dodo freeze lifted under Global Governance v1.15.0, while TrendCite-specific commercial readiness/authority remains closed. Historical Dodo freeze and unbound Hyperdrive notes below are superseded; no customer E2E or production activation is claimed.

## Real hosted same-logical-identity contention verified (2026-10-14)

Twelve distinct physical Queue messages submitted under one nonprod synthetic logical ID all completed, with one pair of hosted invocation spans overlapping, one logical durable ledger row and zero failure rows. Temporary trace flag removed; source/DLQ backlogs zero; production foundation-only. This demonstrates hosted handler overlap over one logical identity, not overlapping database transactions or process termination. See `NONPROD-SAME-LOGICAL-CONSUMER-OVERLAP-2026-10-14.md`.

## Real hosted Queue consumer overlap verified (2026-10-14)

Twelve actual Cloudflare nonprod synthetic Queue messages were accepted and completed; 12 server-timestamped durable invocation spans were recorded with 7 pairs overlapping in time, across a consumer that processes each batch sequentially. This proves hosted overlapping handler executions, not competing workers on the same logical ID. Temporary trace switch removed, source/DLQ both empty, production foundation-only. See `NONPROD-REAL-CONSUMER-OVERLAP-2026-10-14.md`.

## Hosted real postcommit redelivery directly attested (2026-10-14)

PR #80 delivered opt-in durable synthetic attempt tracing. One nonprod Cloudflare Queue message was actually processed twice under the same physical broker message ID: attempt 1 `received`, attempt 2 `duplicate_ack` after a synthetic postcommit exception; hosted Postgres holds exactly one logical row, one failure audit and two physical attempt rows. Temporary switches restored OFF, Queue/DLQ backlog 0, prod foundation-only. Real process termination/transport ACK loss and independent consumer concurrency remain NOT_VERIFIED. See `NONPROD-REAL-POSTCOMMIT-REDELIVERY-ATTESTED-2026-10-14.md`.

## Real nonprod Queue integration checkpoint (2026-10-13)

Real Cloudflare Queue API accepted two identical synthetic record-only messages; actual hosted PostgreSQL ledger contains one row, no matching failure events, provider backlog observed zero. This validates nonprod delivery and ledger deduplication, **not** real broker retry, lost ACK or DLQ poison recovery. DLQ `http_pull` was disabled, so no poison message was sent. Production Queue/cron/customer and commercial activation remain blocked. Details: `NONPROD-REAL-QUEUE-DELIVERY-2026-10-13.md`. PR #66 merged, post-merge main CI SUCCESS.

## Real nonprod poison Queue / DLQ checkpoint (2026-10-13)

Actual Cloudflare nonprod Queue consumed one malformed synthetic message; its body appeared in the nonprod DLQ and was safely removed through exact marker-matched `messages/peek` and `messages/purge`, with both queues empty afterward. Real poison-to-DLQ PASS; exact number of broker retries and real lost-ACK redelivery remain NOT_VERIFIED. See `NONPROD-REAL-POISON-DLQ-2026-10-13.md`. PR #68 merged, CI on `main` SUCCESS. Production stays DARK.

## Real nonprod broker retry sequence (2026-10-13)

Actual Cloudflare Queue delivered the same synthetic collision message three times (attempts 1, 2, 3 with `UniqueViolationError`) recorded under a single Queue message ID in hosted PostgreSQL. After the third failed attempt, the message appeared in the real DLQ; it was removed by exact marker and both queues were verified empty. This validates real retry-to-DLQ, not ACK loss after successful durable commit. Details: `NONPROD-REAL-BROKER-RETRY-2026-10-13.md`. Production DARK and commercialization blocks remain unchanged.

## Consolidated acceptance matrix (2026-10-13)

See `NONPROD-QUEUE-ACCEPTANCE-MATRIX-2026-10-13.md`: real Queue delivery/idempotency/retry/DLQ clearance PASS in nonprod; simulated postcommit ACK exception PASS isolated (#71); actual lost ACK after durable commit and crash/concurrent-consumer E2E NOT VERIFIED. Production remains DARK.

## Parallel provider submissions verified (2026-10-14)

Five simultaneous Cloudflare Queue nonprod publications with different delivery IDs and same logical identity were accepted; hosted PostgreSQL persisted one record without related failures, queues drained. Independent multi-consumer concurrency and actual durable-commit lost ACK remain unproven. See `NONPROD-PARALLEL-PUBLISH-IDEMPOTENCY-2026-10-14.md`.

## Hosted PostgreSQL parallel insert evidence (2026-10-14)

Four simultaneously issued hosted nonprod SQL inserts against one workspace/logical identity yielded exactly one committed row, three conflict no-ops. Backend overlap, independent concurrent Workers and actual postcommit lost ACK are not proven. See `NONPROD-PARALLEL-POSTGRES-INSERT-2026-10-14.md`. Production DARK.

## Real hosted nonprod postcommit fault probe (2026-10-14)

Deployed PR #78 nonprod-only fault hook temporarily enabled, published one synthetic Cloudflare Queue message, observed one durable PostgreSQL row and a first-attempt RuntimeError failure audit. Nonprod flag was then removed and redeployed; source/DLQ backlog zero, prod foundation-only. A second broker delivery log, actual Worker process loss and independently concurrent consumers remain NOT_VERIFIED. See `NONPROD-REAL-POSTCOMMIT-RETRY-2026-10-14.md`.

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
