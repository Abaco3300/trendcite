# TC-P008 — Parallel Cloudflare Queue publish / hosted PostgreSQL idempotency

Date: 2026-10-14 UTC. NONPROD only. No Worker, producer/consumer, schema or production configuration changes.

## Real remote test
- Baseline hosted SQL: zero entries for `logical_id LIKE 'tc-p008-concurrent-20261014-%'`.
- Cloudflare Queue `trendcite-nonprod-queue` ID `752b703ee758448d81be0bc3639abfdf`; initially backlog 0.
- Five concurrent provider API `POST /messages` requests, with payloads in the ledger-only synthetic `tc_p008_transport_probe` kind. All carried workspace `irmya-nonprod-ws` and logical_id `tc-p008-concurrent-20261014-01`, with unique delivery IDs ending in `-0` to `-4`.
- Cloudflare returned HTTP 200 SUCCESS for all five posts.
- Hosted PostgreSQL read-only query returned exactly one row for the logical_id, `delivery_id=tc-p008-concurrent-20261014-01-0`, `first_seen_at=2026-10-14T04:15:01+00:00`.
- Hosted failure audit query returned zero rows matching that logical_id.
- Posttest source Queue and DLQ `GET /metrics` each showed `backlog_count=0`; nonleasing `messages/peek` each returned no messages.

## Evidence classifications
- `FIVE_PARALLEL_PROVIDER_PUBLICATIONS = PASS_NONPROD`.
- `HOSTED_DATABASE_SINGLE_LOGICAL_ROW = PASS_NONPROD`.
- `NO_FAILURE_EVENTS_AND_QUEUE_DRAIN = OBSERVED`.
- `FIVE_CONCURRENT_WORKER_CONSUMERS = NOT_PROVEN`: five simultaneous producer requests do not prove parallel execution by five workers.
- `CROSS_PROCESS_CRASH_OR_SUCCESSFUL_COMMIT_LOST_ACK = NOT_PROVEN`.
- Synthetic fixture retained as auditable nonprod evidence. No customer deliveries, billing, checkout, credentials, external messages or production activation.

Canonical production boundary remains foundation-only/DARK, requiring separate genuine Human Gate before material production Queue activation.
