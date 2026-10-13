# TC-P008 — Real nonprod Cloudflare Queue transport and idempotency proof

Date: 2026-10-13 UTC. Scope: nonprod synthetic fixture only; no customer/email/paid/external delivery.

## Preconditions and containment

- Cloudflare Queue ID `752b703ee758448d81be0bc3639abfdf` belongs to `trendcite-nonprod-queue`; real consumer and producer are `trendcite-nonprod-runtime`.
- PostgreSQL fixture `trendcite.cloud_workspace.workspace_id=irmya-nonprod-ws` existed.
- Existing ledger count for `tc-p008-real-queue-smoke-20261013-01` was zero before send.
- Payload: `{"workspace_id":"irmya-nonprod-ws","logical_id":"tc-p008-real-queue-smoke-20261013-01","delivery_id":"tc-p008-real-queue-smoke-20261013-01","kind":"tc_p008_transport_probe"}`.
- The kind uses the already-existing generic record-only Queue handler; it does not invoke `deliver_alert`, `build_digest`, `deliver_digest`, or `scheduled_radar_tick`.

## Executed evidence

1. Cloudflare API POST Queue message with `content_type=text` and JSON-string body: HTTP 200 SUCCESS.
2. Hosted PostgreSQL `trendcite.cloud_queue_delivery` SELECT returned exactly one matching row, with `workspace_id=irmya-nonprod-ws`, `kind=tc_p008_transport_probe` and `first_seen_at=2026-10-13T23:21:35+00:00`.
3. Cloudflare GET Queue metrics: HTTP 200, `backlog_count=0`, `backlog_bytes=0` (best-effort provider metric).
4. Second API POST with identical payload and identities: HTTP 200 SUCCESS.
5. Hosted PostgreSQL `SELECT count(*)` after second delivery: exactly one ledger row; first_seen_at unchanged. Hosted queue failure events for this logical ID: zero. Cloudflare Queue metrics still `backlog_count=0`.
6. New isolated direct Queue handler tests landed in PR #66: merge `e30dddeef5f3388aacffa4e94f33545266de90f2`; post-merge main GitHub Actions run `38483549165`: SUCCESS.

## Evidence level and restrictions

- `REAL_NONPROD_MESSAGE_DELIVERY_TO_POSTGRES = PASS`.
- `REAL_NONPROD_DUPLICATE_PAYLOAD_LEDGER_DEDUPLICATION = PASS`.
- `QUEUE_BACKLOG_DRAINED = OBSERVED_PROVIDER_BEST_EFFORT`.
- `LOST_ACK_CAUSED_REAL_CLOUDFLARE_REDELIVERY = NOT_VERIFIED`. Sending identical payload twice does not simulate an actual ACK loss.
- `POISON_MESSAGE_DLQ_E2E = NOT_EXECUTED`. The DLQ pull API returned `messages cannot be pulled unless http_pull mode is enabled`. No poison message was sent, since safe targeted removal could not be established.
- `PRODUCTION_QUEUE_E2E = NOT_EXECUTED`. Production Queue/DLQ bindings remain disallowed; no production activation occurred.
- No secrets were read or changed; no customer communications, billing, Dodo or production VectURL access occurred.
- The synthetic ledger row was intentionally retained as an auditable nonprod fixture; no destructive cleanup attempted.

Further work: establish a bounded, disposable nonprod DLQ cleanup path before poison-message tests; separately validate real broker-triggered retry/redelivery under controlled conditions. No false E2E completion or new Human Gate is implied.
