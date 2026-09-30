# TrendCite Cloudflare runtime scaffold

This directory is a **non-production** deployment scaffold created under
`HG-TRENDCITE-PRO-V1-CLOUDFLARE-ARCHITECTURE-ADOPTION-001`, extended under
`HG-TRENDCITE-PRO-V1-ASYNC-APPLICATION-SCHEDULER-BUILD-001`, and complemented by
`HG-TRENDCITE-PRO-V1-ASYNC-EXECUTION-PIPELINE-BUILD-001`.

It deliberately contains placeholder resource identifiers and must not be deployed
as-is.

## Runtime contract

- Python Workers runtime.
- Hyperdrive binding: `HYPERDRIVE`.
- Queue binding: `TREND_QUEUE`.
- PostgreSQL is reached only through asyncpg/Hyperdrive adapters.
- Runtime SQL is schema-qualified to `trendcite`.
- Schema migrations are administrative work and never run from the Worker.
- Generic Queue delivery deduplication may use
  `trendcite.cloud_queue_delivery UNIQUE(workspace_id, logical_id)`.
- **Scheduled radar ticks do not use that ledger as a pre-execution gate.**
  Their authority is `cloud_schedule_tick` atomic claim, lease expiry and
  owner-guarded settlement.

## Scheduled flow built

```text
Cron
→ plan due radar boundaries
→ persist ticks
→ enqueue
→ Queue tick
→ atomic claim / lease
→ AsyncCloudApplicationRunner
→ AsyncExecutionPipelineImpl
→ PostgreSQL atomic execution bundle
→ tick settlement / retry
```

The execution bundle contains:

- globally canonical signals and signal snapshots;
- relevance evaluations and current watchlist-match state;
- match audit rows and current radar-match state;
- run-signal edges;
- per-source coverage;
- usage events;
- alert candidates, including suppressed candidates;
- the final succeeded `RadarRun`.

`PostgresExecutionStore.persist_execution()` writes that bundle in one transaction and
settles the `RadarRun` only after the result rows have been written.

## Intentional fail-closed boundary

The Cloudflare Queue entrypoint still calls `retry()` for
`kind=scheduled_radar_tick` because TrendCite does not yet have a Cloudflare-safe
**async source collector/executor**.

The current live path in `trendcite.pipeline.run_live()` uses synchronous source
adapters and may perform network I/O. It must not be inserted directly into the Workers
event loop merely to make the scaffold look complete.

The next runtime block is therefore source acquisition / async collector adaptation,
not result persistence.

This scaffold does not claim production readiness.
