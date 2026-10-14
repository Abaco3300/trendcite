# TC-P008 — Real nonprod Cloudflare broker retry evidence

Evidence date: 2026-10-13 America/Bogota (2026-10-14 UTC). Synthetic-only nonprod.

## Controlled scenario

- Source Cloudflare Queue: `trendcite-nonprod-queue` (ID `752b703ee758448d81be0bc3639abfdf`).
- Existing Worker consumer `trendcite-nonprod-runtime`: `max_retries=2`, `dead_letter_queue=trendcite-nonprod-dlq`.
- Prior synthetic ledger fixture exists: `delivery_id=tc-p008-real-queue-smoke-20261013-01`, `workspace_id=irmya-nonprod-ws`, `logical_id=tc-p008-real-queue-smoke-20261013-01`.
- A different synthetic `logical_id=tc-p008-real-collision-20261013-01` reused that `delivery_id`, intentionally exercising the guarded conflict in `PostgresRuntimeStore.record_queue_once`.
- New payload carried `kind=tc_p008_collision_probe` and `probe_marker=tc-p008-collision-20261013-01`. It used the generic ledger-only handler and was not a customer, delivery, email or commercial task.
- Before sending, the exact collision logical_id had zero existing failure events; DLQ metrics showed backlog zero and peek returned no messages.

## Actual remote execution and observations

1. Cloudflare Queue API POST with `content_type=text` and synthetic JSON body: HTTP 200 SUCCESS.
2. Supabase read-only SQL query on `trendcite.cloud_queue_failure_event` showed **three distinct persisted attempts** for the same real `queue_message_id=429d7a9670b2fce82c2a4d0aad374628`:
   - attempt 1 / max_attempts 3 / `UniqueViolationError`;
   - attempt 2 / max_attempts 3 / `UniqueViolationError`;
   - attempt 3 / max_attempts 3 / `UniqueViolationError`.
3. Cloudflare DLQ `messages/peek`: HTTP 200; message `20014b9513ccaadc3962727924768754` exactly matched synthetic workspace, logical_id and unique marker.
4. Second peek verified the matching exact identity, then `messages/purge` removed only that one message with its opaque reference: HTTP 200 SUCCESS, no unrelated messages selected.
5. Read-only Cloudflare source Queue and DLQ postchecks: both `backlog_count=0` and `messages/peek` returned zero messages.

## Evidence classification

- `ACTUAL_NONPROD_BROKER_INDUCED_RETRY = PASS`: three distinct attempts persisted for the same real message ID.
- `PRODUCTION_SAFE_IDENTITY_COLLISION = PASS_NONPROD_ONLY`: collision raised an error rather than silently ACKing a different job (the production handler was not executed).
- `REAL_NONPROD_RETRIES_TO_DLQ = PASS`: the exact failed message was observed in the physical dead-letter queue.
- `TARGETED_SYNTHETIC_DLQ_CLEANUP = PASS`: only the tagged message was purged.
- `NONPROD_QUEUES_DRAINED = OBSERVED` via metrics and nonleasing peeks.
- `LOST_ACK_AFTER_SUCCESSFUL_DURABLE_COMMIT = NOT_VERIFIED`: this test deliberately failed transaction persistence, not confirmation after a successful commit.
- `PRODUCTION_QUEUE_E2E = NOT_EXECUTED`; `PRODUCTION_ACTIVATION = NOT_AUTHORIZED`.

Failure-audit rows are retained as synthetic, audit-grade evidence; no destructive SQL cleanup was performed. No modifications to credentials, Worker configuration, queue consumers, cron, RLS, production infrastructure, Dodo, external delivery or customer access occurred.
