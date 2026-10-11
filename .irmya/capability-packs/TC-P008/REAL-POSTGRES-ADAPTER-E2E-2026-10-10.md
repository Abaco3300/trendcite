# TC-P008 — Real local PostgreSQL adapter and durable Queue ledger E2E

Status: **PASS — LOCAL/ISOLATED**, not Cloudflare E2E and not production activation.

## Scope and evidence

Run `python scripts/tc_p008_real_store_postgres_probe.py` (opt-in, local Docker `postgres:17` + installed `psycopg`). This starts a disposable PostgreSQL container with a random port published **only to 127.0.0.1**, populates synthetic data using canonical SQL files `0001_cloud_foundation.sql`, `0004_scheduled_radar_orchestration.sql` and `0005_queue_delivery_idempotency.sql`, creates an isolated synthetic runtime role, and removes the container in a `finally` block. There is no project credential transport or Cloudflare connection.

The probe calls the actual `PostgresExecutionStore.get_or_create_run` via an isolated psycopg-to-asyncpg-protocol adapter, **not a simulated database**. PostgreSQL enforced concurrent constraints over 24 requests with independent DB connections: one run per tenant+idempotency key; replay after lost acknowledgment returns the same run; another tenant has a distinct run and cannot read the first tenant's run via the workspace-scoped method.

It also calls actual `PostgresRuntimeStore.record_queue_once` against the canonical durable Queue ledger with 24 concurrent claims, tests a second replay of the same delivery ID, and checks an independent second tenant. Only one claim for the first tenant/logical ID commits.

A deliberate exception within the real transaction ensures that a synthetic insert is rolled back and a subsequent connection sees no row. The real `PostgresRuntimeStore` scheduling methods were then tested with canonical migration `0004_scheduled_radar_orchestration.sql`: 12 simultaneous lease claims yielded exactly one owner; premature reclamation was denied; expiry permitted one recovery owner; stale-owner settlement was denied; the recovery owner settled successfully; subsequent claims were rejected at the retry/terminal-state boundary.

## Defect discovered and fixed

The `cloud_radar_run` table declares independently unique primary keys and tenant/idempotency keys. The schedule-tick insert has not yet been validated in this checkpoint, so its existing conflict-target behavior is unchanged. Deterministic duplicate IDs could cause a primary-key conflict before the named `ON CONFLICT (workspace_id, idempotency_key) DO NOTHING` clause applied. `cloud_queue_delivery` similarly has a primary-key identity and a distinct tenant/logical unique index.

We updated applicable inserts to `ON CONFLICT DO NOTHING`, allowing either unique constraint to prevent duplication. The run lookup immediately following an insert remains tenant/key-scoped and fails closed when no matching row exists. A collision on an unrelated key therefore cannot silently produce a successful different run. The Queue ledger returns `false` only after verifying a tenant/logical duplicate; a primary-key collision with a different logical job raises `RuntimeError` rather than silently dropping work. These semantics are validated locally against actual PostgreSQL constraints.

## Remaining limitations

The probe uses a local psycopg adapter that translates positional placeholders into psycopg placeholders; deployed Cloudflare runtime uses an asyncpg/Hyperdrive interface. No real Cloudflare Queue ACK/redelivery, full Cloudflare scheduler lease E2E, RLS tenant context or process termination during a provider commit is certified here. Local synthetic runtime role grants are **not production authorization evidence**. The source inventory and production-dark state remain unchanged. Dodo TEST and LIVE remain frozen.

## Verified local output

`concurrent_attempts=24, one_run_per_tenant_key=true, replay_idempotent=true, tenant_isolation=true, queue_ledger_concurrent_attempts=24, queue_ledger_exactly_one_claim=true, queue_replay_safe=true, schedule_competing_claims=12, schedule_only_one_owner=true, expired_lease_reclaimed=true, stale_owner_settlement_rejected=true, claim_exhaustion_enforced=true, cloudflare_queue_e2e=NOT_VERIFIED, production_ready=false`.

Next safe operations: real adapter schedule-tick/lease tests and a nonprod Queue consumer ACK/retry E2E with synthetic payloads, followed by independent remote state verification. Binding production Queue/Hyperdrive or commercial activation remains a separate Human Gate.
