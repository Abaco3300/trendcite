# TC-P008 — Hosted physical broker redelivery after durable commit (2026-10-14)

## Real environment and bounded setup

- Cloudflare account: `a4c8274fca447382525edd54ee20fd74`, existing Worker `trendcite-nonprod-runtime`, existing nonprod source Queue and DLQ.
- Commit of deployed handler: merged PR #80, `91121f4d8b5448f6e751f5f34079c8488c737f1f`; canonical wheel/vendor proof PASS; dry-run PASS.
- A PostgreSQL-only migration `deploy/postgres/0010_tc_p008_probe_attempt_audit.sql` was applied in the private `trendcite` schema. The source SQL was corrected to fully qualify the schema and grant INSERT/SELECT only to `trendcite_nonprod_runtime`. Both `anon` and `authenticated` lack SELECT.
- Temporary explicit nonprod config: `TRENDCITE_TC_P008_FAULT_INJECTION=nonprod-enabled` and `TRENDCITE_TC_P008_ATTEMPT_AUDIT=nonprod-enabled`.
- Worker nonprod deployed version with switches enabled: `2279b2de-5b38-4272-bfd8-f880cb9960f5`.
- Published exactly one synthetic Queue message, accepted HTTP 200. Workspace `irmya-nonprod-ws`, logical ID `tc-p008-postcommit-20261014-auditprobe-03`, kind `tc_p008_postcommit_retry_probe`.

## Direct hosted PostgreSQL evidence

The new durable `trendcite.cloud_queue_probe_attempt` table independently records:

| Physical Queue message ID | Broker attempt | Recorded outcome | Observed at (UTC) |
| --- | ---: | --- | --- |
| `be69bf35b71401f84cc49ab3246eab1d` | 1 | `received` | 2026-10-14 15:04:05.266622 |
| `be69bf35b71401f84cc49ab3246eab1d` | 2 | `duplicate_ack` | 2026-10-14 15:04:06.760609 |

Final independent SQL aggregation for the logical ID:
- `trendcite.cloud_queue_delivery`: exactly **1** durable logical record;
- `trendcite.cloud_queue_failure_event`: exactly **1** first-attempt synthetic failure;
- `trendcite.cloud_queue_probe_attempt`: exactly **2** physical attempt records.

This directly proves that a real Cloudflare broker redelivered the same physical Queue message after a synthetic postcommit application failure, and the consumer ACKed the duplicate without a second logical insertion. It does **not** prove an actual Worker crash or transport-level lost ACK.

## Restoration and safety

After the probe, both temporary nonprod feature flags were removed from Wrangler configuration and redeployed. A Cloudflare settings GET confirmed both flags **absent**, source Queue backlog **0**, DLQ backlog **0**, and production Worker activation **foundation-only**. No production bindings, product commerce, customer email, DNS, or secrets were modified.

The synthetic ledger/failure/attempt rows remain as audit evidence; migration table remains nonprod-only. `PRODUCTION_ACTIVATION=BLOCKED`. Independent consumer concurrency and real process crash/lost ACK remain NOT_VERIFIED. Do not treat a simulated application failure as transport-level ACK loss.
