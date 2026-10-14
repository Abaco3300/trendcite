# TC-P008 — Real hosted Cloudflare Queue consumer overlap (2026-10-14)

## Scope and authoritative evidence

- Source: merged PR #83, commit `0876ec20bbe9c607d1e0ab69b34348041835c780`.
- Only nonprod Cloudflare Worker `trendcite-nonprod-runtime`, synthetic kind `tc_p008_concurrency_probe` and logical prefix `tc-p008-concurrency-`.
- Private hosted PostgreSQL table `trendcite.cloud_queue_probe_invocation`; migration `deploy/postgres/0011_tc_p008_concurrency_probe.sql` applied only to nonprod schema. No client payload stored.
- Runtime packaging source proof PASS, Wrangler dry run PASS.
- Temporary flag `TRENDCITE_TC_P008_CONCURRENCY_TRACE=nonprod-enabled`; deployed version `858191a7-6dcb-4854-b0a2-64104cc4ba59`.
- Exactly 12 synthetic messages published to existing nonprod Queue, all 12 Cloudflare API HTTP 200, IDs `tc-p008-concurrency-20261014-hosted-a-01` through `-12`.

## Direct hosted SQL result

A SQL overlap self-join over completed server-timestamped spans, with predicate `a.started_at < b.finished_at AND b.started_at < a.finished_at`, produced:

| Metric | Actual observed |
|---|---:|
| Completed physical invocation spans | 12 |
| Pairs with positive time overlap | 7 |
| Durable logical rows | 12 |

Example overlapping spans:
- `tc-p008-concurrency-20261014-hosted-a-05`: 15:51:57.443611–15:52:00.387367 UTC.
- `tc-p008-concurrency-20261014-hosted-a-01`: 15:51:58.480357–15:52:00.896681 UTC.

The production handler processes each Queue batch in a sequential `for message in batch.messages` loop. Therefore two distinct messages with overlapping processing spans constitute evidence of overlapping hosted Queue handler executions (not merely parallel producers or isolated Python event loops).

The 12 unique logical records validate receipt and completion of those 12 different logical messages. They do **not** prove two competing handlers racing on one logical identity, process termination, or actual transport-level ACK loss.

## Restoration

Both the on-host nonprod Wrangler flag and deployed runtime flag were removed. Re-deploy returned version `d63cc7a3-88a9-423e-9cdb-abe25e3c8fd4`. Cloudflare read-back confirmed trace flag ABSENT, nonprod Queue backlog 0, DLQ backlog 0, and production `TRENDCITE_PRODUCTION_ACTIVATION=foundation-only`. No prod deployment, customers, or billing changes.

## Classification

**PASS — hosted multi-invocation processing overlap**.
**NOT VERIFIED — overlapping same logical identity, actual Worker termination and transport ACK loss**.
