# TC-P008 — Hosted same-logical-identity contention (2026-10-14)

## Scope
Single bounded nonprod test using the existing opt-in TC-P008 concurrency trace; no production changes or customer messages.
- Source: Cloudflare Queue `trendcite-nonprod-queue`; Worker `trendcite-nonprod-runtime`.
- Unique synthetic logical identity: `tc-p008-concurrency-20261014-same-identity-01`.
- Twelve physical message publications with distinct delivery IDs but the same workspace, logical ID and synthetic kind `tc_p008_concurrency_probe`. All twelve accepted HTTP 200.
- Temporary `TRENDCITE_TC_P008_CONCURRENCY_TRACE=nonprod-enabled`; instrumented Worker version `dafca32d-8406-4a04-96b5-82185be9d2d5`.
- Probe records physical message IDs and server timestamps in `trendcite.cloud_queue_probe_invocation`, without customer payload persistence.

## Direct hosted PostgreSQL evidence

After the messages finished, the same-query SQL aggregate reported:

| Metric | Observed |
|---|---:|
| Physical invocation spans | 12 |
| Completed invocation spans | 12 |
| Overlapping completed span pairs of same logical ID | 1 |
| Durable logical rows in `cloud_queue_delivery` | 1 |
| Related Queue failure audit rows | 0 |

The overlap predicate was `a.started_at < b.finished_at AND b.started_at < a.finished_at` over distinct invocation IDs. This directly demonstrates hosted overlapping processing of a single logical identity while exactly one logical record is committed. The processor sequentially iterates a given Queue batch, so overlapping spans are not sequential iteration inside a single handler.

**PASS** — hosted overlapping same-logical-identity submissions deduplicated durably; **NOT VERIFIED** — backend database transactions overlapped, actual Worker process crash, or transport-level lost ACK.

## Teardown and verification

Removed the temporary trace flag from the local Wrangler configuration and redeployed nonprod Worker version `482a5c28-f346-467a-9c3a-c6f2ce1cc9ff`. Direct Cloudflare settings read confirmed trace flag absent; source Queue backlog 0; DLQ backlog 0. Production Worker remained `TRENDCITE_PRODUCTION_ACTIVATION=foundation-only`. No production deployment or commercial activation.

The synthetic-only SQL data is retained for audit evidence.
