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

`AsyncExecutionPipelineImpl` now implements the durable result half of scheduled
execution. It consumes an async `ExecutionBatch`, reuses the canonical relevance,
matching and materiality domain services, builds one complete persistence bundle and
hands that bundle to `PostgresExecutionStore` for one PostgreSQL transaction. The
transaction writes global signals/snapshots, tenant relevance/match state and audit
history, run-signal edges, source coverage, usage events, alert candidates and only
then settles the `RadarRun` as succeeded.

`PostgresExecutionStore` is intentionally separate from `PostgresRuntimeStore`:
Scheduler concurrency/leases and Signal Engine result persistence are different
responsibilities even though both share the same Hyperdrive connector and runtime
role.

The Cloudflare execution path now also has a Cloudflare-safe source-acquisition layer:

- `AsyncHTTPTransport` defines the runtime-neutral async HTTP contract;
- `CloudflareFetchTransport` implements that contract with the Workers Fetch API;
- async HN, GitHub, RSS and Reddit collectors reuse the canonical parsers/normalizers;
- X remains an explicit interface-only source until an official authenticated API
  integration is configured;
- `collect_async()` records per-source failure as `SourceStatus` instead of failing
  the whole run;
- `AsyncSourceExecutionServiceImpl` builds the canonical report/Signal Engine output
  and returns `ExecutionBatch` to `AsyncExecutionPipelineImpl`.

The Queue consumer is now wired through the complete code path:

```text
scheduled_radar_tick
→ atomic claim
→ AsyncCloudApplicationRunner
→ async source acquisition
→ ExecutionBatch
→ AsyncExecutionPipelineImpl
→ atomic PostgreSQL result persistence
→ tick settlement / retry
```

The old synchronous `pipeline.run_live()` remains the OSS/local live path and is not
called from the Workers event loop.

### Runtime remediation after non-production validation

The first integrated non-production run exposed two implementation defects that are
now remediated in this checkpoint:

1. The Hyperdrive login is deliberately `NOINHERIT`. Therefore every Cloud data
   read must explicitly assume `trendcite_runtime`. Read paths in both
   `PostgresRuntimeStore` and `PostgresExecutionStore` now use the same transaction
   boundary as writes: open connection → begin transaction → `SET LOCAL ROLE
   trendcite_runtime` → query → close. The direct login no longer needs permanent
   schema/table read grants.
2. `workers.fetch()` returns the Python `workers.Response` wrapper. That wrapper
   exposes body buffering through `bytes()`, not the JavaScript-level
   `arrayBuffer()` method. `CloudflareFetchTransport` now consumes
   `await response.bytes()` and applies the request/body operation under an async
   timeout without JS `AbortController` / `Uint8Array` conversion.

Regression tests enforce both boundaries, including a guard that no Cloud data-read
method can silently open a raw connection outside the runtime-role transaction.

### Cloudflare runtime packaging

The Worker application code must come from the exact repository checkpoint being
validated, not from the public PyPI `trendcite` release. The public 0.1.0 artifact
predates the Cloud package.

Before pywrangler sync/dry-run/deploy, `scripts/prepare_cloudflare_runtime.py` builds
the current repository into
`deploy/cloudflare/wheelhouse/trendcite-0.1.0-py3-none-any.whl` and verifies that the
wheel contains the required async runtime modules. The Worker pyproject redirects
`trendcite` to that local wheel using `[tool.uv.sources]`. Pywrangler then vendors
that wheel and compatible third-party packages into `python_modules/`, which Wrangler
bundles with the Worker.

The wheelhouse, `python_modules`, lockfiles and Worker-local virtual environments are
generated validation/deployment artifacts and are not committed.

## Explicitly incomplete

This checkpoint does **not** yet provide:

- a full async PostgreSQL implementation of every existing repository;
- async implementations of the remaining interactive CloudApplication use cases;
- an authenticated official X collector implementation (the interface remains
  deliberately unavailable rather than scraping or bypassing access controls);
- Supabase Auth integration;
- React/Vite frontend;
- Postmark delivery integration;
- Stripe/billing integration;
- any remote database migration;
- any Cloudflare deployment.

These are subsequent build/gate boundaries. No production readiness is implied.
