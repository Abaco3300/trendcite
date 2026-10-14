# TC-P008 — Hosted nonprod postcommit synthetic retry, 2026-10-14

## Scope and safeguards

Deployed the already-merged PR #78 handler to the existing Cloudflare nonprod Worker using the documented Python wheel/vendor preparation and pywrangler pipeline. Wheel SHA-256: `f62978ea1298b419aa5c6755b91d60b9d16e0780b6eb581d4b368c53d0b8f317`; packaging source proof PASS; dry-run PASS. Initial deployed nonprod Worker version: `b1d116c6-3b14-44fc-a22d-7a32e67f8385`, fault switch absent.

Temporarily enabled `TRENDCITE_TC_P008_FAULT_INJECTION=nonprod-enabled` strictly in the nonprod Wrangler config, deployed nonprod Worker version `d2c9db5d-b542-4d47-937a-6ae8777425b1`, and posted a single synthetic message to the nonprod provider Queue (HTTP 200). Workspace: `irmya-nonprod-ws`. Logical identity: `tc-p008-postcommit-20261014-liveprobe-01`; delivery ID suffix `-delivery`; kind `tc_p008_postcommit_retry_probe`.

## Actual provider and hosted database observations

PostgreSQL `trendcite.cloud_queue_delivery` returned exactly one row matching the logical identity after the probe and on final read. Failure audit `trendcite.cloud_queue_failure_event` recorded one `RuntimeError`, attempt `1`, physical Queue message ID `f9f6c8a82ebf052b1dd6ed16e685746e`. Both nonprod source Queue and DLQ metrics returned backlog `0` at final check.

After the test, the temporary flag line was removed from the local Wrangler config and the original flag-off config was redeployed. Cloudflare GET settings showed **fault flag absent**. Production GET settings independently confirmed `TRENDCITE_PRODUCTION_ACTIVATION=foundation-only`.

## Exact evidence classification

- `REAL_NONPROD_POSTCOMMIT_EXCEPTION_AFTER_DURABLE_INSERT=PASS`: fault originated in hosted nonprod consumer, after the SQL insert.
- `SINGLE_DURABLE_LOGICAL_RECORD=PASS`: final hosted PostgreSQL row count was exactly one.
- `PROVIDER_FAILURE_AUDIT_ATTEMPT_1=PASS`: hosted failure-event row verified.
- `NONPROD_FLAG_RESTORED=PASS`; `SOURCE_AND_DLQ_BACKLOG_ZERO=PASS`; `PRODUCTION_DARK=PASS`.
- `BROKER_REDELIVERY_ATTEMPT_2_DIRECT_ATTESTATION=NOT_VERIFIED`: no second delivery-attempt log was captured; empty queue plus single record is consistent with successful replay, but is not conclusive proof.
- `REAL_PROCESS_TERMINATION_OR_LOST_ACK=NOT_VERIFIED`: injected application exception and explicit retry are not a killed Worker process or lost transport-level ACK.
- `INDEPENDENT_CONSUMER_PARALLEL_EXECUTION=NOT_VERIFIED`.

All payloads were synthetic; no real customer, billing, external email, prod Queue, or production changes. Retained the synthetic ledger row and failure audit as evidence.
