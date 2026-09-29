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
database-level verdict for at-least-once Queue delivery.

## Async runtime boundary

`PostgresRuntimeStore` currently owns the concurrency-sensitive slice validated in E0:

- PostgreSQL health check;
- Queue delivery deduplication;
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

The Queue entrypoint is wired to durable PostgreSQL deduplication. The scheduled
entrypoint currently verifies persistence connectivity only; full async planning,
claiming, Signal Engine execution and settlement are the next implementation block.

## Explicitly incomplete

This checkpoint does **not** yet provide:

- a full async PostgreSQL implementation of every existing repository;
- the async application service that mirrors all synchronous CloudApplication use cases;
- full scheduler plan → enqueue → claim → execute → settle orchestration;
- Supabase Auth integration;
- React/Vite frontend;
- Postmark delivery integration;
- Stripe/billing integration;
- any remote database migration;
- any Cloudflare deployment.

These are subsequent build/gate boundaries. No production readiness is implied.

[executed on device: LAPTOP-JOSEMILE (056f59c1-dbac-4f47-875e-044865a705aa)]