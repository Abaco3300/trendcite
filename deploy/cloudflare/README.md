# TrendCite Cloudflare runtime scaffold

This directory is a **non-production** deployment scaffold created under
`HG-TRENDCITE-PRO-V1-CLOUDFLARE-ARCHITECTURE-ADOPTION-001` and extended under
`HG-TRENDCITE-PRO-V1-ASYNC-APPLICATION-SCHEDULER-BUILD-001`.

It deliberately contains placeholder resource identifiers and must not be deployed
as-is.

## Runtime contract

- Python Workers runtime.
- Hyperdrive binding: `HYPERDRIVE`.
- Queue binding: `TREND_QUEUE`.
- PostgreSQL is reached only through the asyncpg/Hyperdrive adapter.
- Runtime SQL is schema-qualified to `trendcite`.
- Schema migrations are administrative work and never run from the Worker.
- Generic Queue delivery deduplication may use
  `trendcite.cloud_queue_delivery UNIQUE(workspace_id, logical_id)`.
- **Scheduled radar ticks do not use that ledger as a pre-execution gate.**
  Their idempotency/recovery authority is `cloud_schedule_tick` atomic claim,
  lease expiry and owner-guarded settlement.

## Scheduled flow now built

The Cron entrypoint performs:

```text
list enabled schedules
→ derive canonical due boundaries
→ persist pending/skipped ticks idempotently
→ advance planning watermark
→ enqueue newly-created pending ticks
```

`trendcite.cloud.async_scheduler.AsyncScheduledCoordinator` implements the worker-side
semantics for:

```text
load tick
→ atomic claim
→ execute async radar runner
→ settle success/failure
→ requeue retryable failures
→ request transport retry after lost claim/lease
```

`AsyncCloudApplicationRunner` now provides run identity/retry semantics, backed by
PostgreSQL run get-or-create/update operations. Its concrete `AsyncExecutionPipeline`
for Signal Engine execution and detailed result persistence is intentionally **not
wired yet**. Until that component exists, the Cloudflare Queue entrypoint calls
`retry()` for `kind=scheduled_radar_tick` rather than consuming the message. This
fail-closed behavior prevents a partially configured deployment from losing scheduled
work.

This scaffold does not claim production readiness.
