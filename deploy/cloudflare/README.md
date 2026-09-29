# TrendCite Cloudflare runtime scaffold

This directory is a **non-production** deployment scaffold created under
`HG-TRENDCITE-PRO-V1-CLOUDFLARE-ARCHITECTURE-ADOPTION-001`.

It deliberately contains placeholders and must not be deployed as-is.

## Runtime contract

- Python Workers runtime.
- Hyperdrive binding: `HYPERDRIVE`.
- Queue binding: `TREND_QUEUE`.
- PostgreSQL is reached only through the asyncpg/Hyperdrive adapter.
- Runtime SQL is schema-qualified to `trendcite`.
- Schema migrations are administrative work and never run from the Worker.
- Queue delivery deduplication is database-enforced by
  `trendcite.cloud_queue_delivery UNIQUE(workspace_id, logical_id)`.

The scheduled entrypoint currently validates persistence connectivity only. Wiring the
full async scheduler/application adapter is intentionally left for a later local
checkpoint; this scaffold does not claim production readiness.

[executed on device: LAPTOP-JOSEMILE (056f59c1-dbac-4f47-875e-044865a705aa)]