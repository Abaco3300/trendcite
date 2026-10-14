# TC-P008 — Real nonprod Cloudflare poison message to DLQ and targeted cleanup

Evidence date: 2026-10-13 local Colombia / 2026-10-14 UTC. Scope: synthetic nonprod only.

## Preconditions

- Source Queue: `trendcite-nonprod-queue`, ID `752b703ee758448d81be0bc3639abfdf`; the existing `trendcite-nonprod-runtime` is its consumer.
- Dead Letter Queue: `trendcite-nonprod-dlq`, ID `a5c3d474d01c45e085b5152575f4408e`.
- Read-only baseline Cloudflare GET metrics: DLQ `backlog_count=0`.
- Read-only `POST /messages/peek` with `batch_size=5`: HTTP 200, no messages.
- Existing consumer contract: `max_retries=2`, `dead_letter_queue=trendcite-nonprod-dlq`.
- Controlled input: `{"workspace_id":"irmya-nonprod-ws","kind":"tc_p008_poison_probe","probe_marker":"tc-p008-dlq-20261013-01"}`. This deliberately lacks `logical_id` and cannot access delivery, billing, customer or email flows.
- No worker configuration, routes, cron, permissions, consumers, schema, RLS or production resources modified.

## Executed actions and observed results

1. Cloudflare `POST /queues/752b703ee758448d81be0bc3639abfdf/messages` with `content_type=text` and the JSON-string body: HTTP 200 / SUCCESS.
2. Cloudflare `POST /queues/a5c3d474d01c45e085b5152575f4408e/messages/peek`: HTTP 200; one message with ID `912dd6222ddca08c0e35e491b7c7ce6e`. Its exact body matched the synthetic marker, workspace and missing `logical_id`.
3. Queried the DLQ again; selected only the one message whose decoded body contained the exact marker and workspace; targeted `POST /messages/purge` using the opaque ref returned by peek: HTTP 200 SUCCESS. There were no other messages to affect.
4. Read-only postchecks for both source Queue and DLQ: `GET /metrics` returned backlog 0 / bytes 0 and `POST /messages/peek` returned no messages for either; all calls HTTP 200 SUCCESS.
5. PR #68, tests covering no-ACK upon persistence/audit failure and nonblocking mixed batches: merged `7c065015f8fa780abc91481c226f046a926477d6`; post-merge main Actions run `38495796075` SUCCESS.

## Evidence classification

- `REAL_NONPROD_POISON_MESSAGE_ROUTED_TO_DLQ = PASS`: physical Cloudflare Queue-to-DLQ result was observed.
- `SYNTHETIC_DLQ_TARGETED_PURGE = PASS`: exact-identity message was removed.
- `NONPROD_QUEUE_AND_DLQ_DRAINED = OBSERVED` (provider best-effort metrics plus empty peeks).
- `BROKER_RETRY_COUNT_PER_MESSAGE = NOT_VERIFIED`: DLQ peek returned `attempts=0` after transfer; no per-attempt logs were inspected and the number of broker retries is not asserted.
- `BROKER_INDUCED_LOST_ACK_REDELIVERY = NOT_VERIFIED`: a prior manually duplicated delivery does not simulate lost acknowledgment.
- `PRODUCTION_QUEUE_E2E = NOT_EXECUTED` and `PRODUCTION_ACTIVATION = NOT_AUTHORIZED`.

The obsolete assumption that a disabled `http_pull` consumer prevents inspection/cleanup is corrected: provider `messages/peek` plus exact `messages/purge` worked in nonprod. No sweeping/purge-all operation was used. Repeat scenarios must first verify baseline DLQ emptiness, ensure payload marker isolation, and require successful read-after-purge postchecks.
