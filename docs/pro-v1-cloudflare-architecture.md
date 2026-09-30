# TrendCite Pro v1 — Cloudflare architecture adoption

Status: **BUILT LOCALLY / NOT DEPLOYED**

Human Gate: `HG-TRENDCITE-PRO-V1-CLOUDFLARE-ARCHITECTURE-ADOPTION-001`

## Decision

TrendCite Pro v1 adopts the E0-validated execution path:

```text
React/Vite
    ↓
Cloudflare Python Workers
    ↓
asyncpg through Hyperdrive
    ↓
Supabase / PostgreSQL / schema trendcite
    ↓
Cloudflare Queues + Cron
```

Railway is not selected. The existing Signal Engine and Cloud domain stay in Python.

## Why there are two persistence paths

The OSS/local Cloud application is synchronous and uses SQLite. Cloudflare Python Workers
execute inside an event loop, while E0 validated asyncpg for PostgreSQL. The production
path therefore uses explicit async infrastructure rather than blocking an active event
loop or wrapping asyncpg behind `run_until_complete`.

The existing SQLite UnitOfWork remains the reference implementation for local behavior.
`trendcite.cloud.db.postgres` introduces the first PostgreSQL runtime primitives without
claiming that every repository has already been ported.

## PostgreSQL migration model

The canonical Cloud SQL migrations in `src/trendcite/cloud/db/sql` intentionally use a
portable SQLite/PostgreSQL subset. Administrative PostgreSQL execution must:

1. create schema `trendcite` if needed;
2. set `search_path TO trendcite, pg_catalog`;
3. apply ordered migration files;
4. grant only the runtime permissions required by the Worker role.

The Worker runtime must never create or migrate tables.

Migration `0005_queue_delivery_idempotency.sql` adds
`cloud_queue_delivery`. Its unique constraint on `(workspace_id, logical_id)` is the
database-level verdict for generic at-least-once Queue deliveries that can safely be
suppressed after first receipt.

**Scheduled radar ticks deliberately do not use that ledger as a pre-execution gate.**
Their authority is `cloud_schedule_tick`: atomic claim + lease + owner-guarded
settlement. This matters because a worker can crash after receiving a Queue message but
before executing it; a transport retry must remain eligible to reclaim that tick after
the lease expires.

## Async runtime boundary

`PostgresRuntimeStore` now owns the concurrency-sensitive scheduler slice:

- PostgreSQL health check;
- generic Queue delivery deduplication;
- list enabled radar schedules;
- persist due/skipped ticks with database idempotency;
- advance the schedule planning watermark;
- load tenant-scoped schedules/ticks;
- atomic schedule-tick claim;
- lease-owner-guarded tick settlement.

Every runtime query is schema-qualified to `trendcite`. Runtime role names are validated
before use in `SET LOCAL ROLE`.

`AsyncCloudRuntime` is a transport-neutral dispatcher for scheduled and Queue handlers.
It prevents Cloudflare transport objects from leaking into the domain layer.

## Cloudflare scaffold

`deploy/cloudflare` contains a non-production Worker scaffold and placeholder Wrangler
configuration. It is deliberately not deployable without replacing explicit placeholder
resource identifiers.

The scheduled entrypoint now performs the safe half of the production flow:

```text
Cron → list enabled schedules → plan canonical boundaries
     → persist ticks → enqueue newly-created pending ticks
```

`AsyncScheduledCoordinator` also implements the execution semantics:

```text
Queue tick → tenant-scoped load → atomic claim
           → AsyncCloudApplicationRunner
           → owner-guarded settlement
           → requeue retryable failures
```

`AsyncCloudApplicationRunner` now carries the run-level semantics of the synchronous
`CloudApplication.run_radar()` path into the async plane:

- database-enforced get-or-create of the logical `RadarRun`;
- same run identity across retries;
- no re-execution of already-succeeded runs;
- safe failed-run transition when the execution pipeline raises;
- rejection if a pipeline attempts to return a different logical run.

`PostgresRuntimeStore` implements the async run repository operations
`get_or_create_run`, `get_run` and `update_run`, with tenant-scoped SQL and the
existing `UNIQUE(workspace_id, idempotency_key)` database guarantee.

If a claim is lost while the tick is still unfinished, the coordinator requests a
transport retry rather than ACKing. If settlement loses the lease, it also requests a
transport retry. A failed tick is explicitly re-enqueued only while its attempt budget
remains.

The Cloudflare Queue entrypoint still refuses to consume `scheduled_radar_tick`
messages and calls `retry()` because the concrete `AsyncExecutionPipeline` is not yet
configured. This is intentional fail-closed behavior: planning/enqueue, claim/settle
and run-level retry semantics are built; Signal Engine/result persistence wiring is the
remaining application boundary.

## Explicitly incomplete

This checkpoint does **not** yet provide:

- a full async PostgreSQL implementation of every existing repository;
- async implementations of the remaining interactive CloudApplication use cases;
- a concrete `AsyncExecutionPipeline` that executes the Signal Engine and persists
  signals, snapshots, relevance, matches, coverage, usage and alert candidates;
- Supabase Auth integration;
- React/Vite frontend;
- Postmark delivery integration;
- Stripe/billing integration;
- any remote database migration;
- any Cloudflare deployment.

These are subsequent build/gate boundaries. No production readiness is implied.
