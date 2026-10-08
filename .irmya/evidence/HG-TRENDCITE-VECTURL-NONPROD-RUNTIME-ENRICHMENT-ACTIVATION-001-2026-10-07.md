# HG-TRENDCITE-VECTURL-NONPROD-RUNTIME-ENRICHMENT-ACTIVATION-001

Date: 2026-10-07
Result: PASS / ACTIVE_NONPROD

## Code
- PR #38: VectURL nonprod runtime enrichment
- merge: `4c65d9ce45eb88b18475cac25f4e6368e61535ca`
- PR #40: canonical schema reconciliation
- canonical main after reconciliation: `52dbca2f599d3ea172390216d5d75ca7a0b0cc9d`

## Hosted schema
Canonical table: `trendcite.cloud_run_linked_content`.

Permissions:
- `trendcite_nonprod_runtime`: SELECT / INSERT / UPDATE / DELETE
- `anon`: none
- `authenticated`: none

The transient 0008 duplicate table was removed by forward-only migration 0009.

## Runtime contract
- nonprod only
- consumer: `trendcite-nonprod`
- post-score enrichment
- max 3 URLs
- best_effort
- maxCostMicroUsd=0
- fail-open
- no EvidenceItem creation
- no scoring feedback path

## Real hosted validation
Run:
`9a653c9597105560b73c3c9a96b97ba3`

Result:
- status = succeeded
- signal_count = 5
- coverage = complete
- source counts: HN 30 / GitHub 30 / RSS 45 / Reddit 50
- linked-content rows = 3
- distinct enriched signals = 3
- total linked-content cost = 0 micro-USD

Persisted bundles:
- `veb_e49eb278b37e93ea2d13199a`
- `veb_5325a372754bb2adfda306b2`
- `veb_495add2a4ce6ff0af61ecd79`

All three persisted rows reported:
- quality overall = 0.9
- completeness = 1
- provenance coverage = 1
- actual cost = 0

## Scoring isolation
Five canonical scoring snapshots were persisted independently in `cloud_signal_evaluation`.
Linked content is stored only in `cloud_run_linked_content`.
The VectURL path operates on the already-scored Report and does not create or mutate EvidenceItem records.

## Cleanup
- validation radar version v4 superseded by v5 restore
- temporary validation route removed
- no validation secret installed
- local validation artifacts removed
- final Worker = `9a9ce619-a80b-414b-bca6-4989279163a5`
- health = 200 / ok true
- only persistent secrets: Postmark + VectURL consumer token

Dodo and IRCL remained frozen and untouched.
