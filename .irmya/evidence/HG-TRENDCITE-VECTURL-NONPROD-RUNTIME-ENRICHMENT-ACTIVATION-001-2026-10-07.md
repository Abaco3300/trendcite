# HG-TRENDCITE-VECTURL-NONPROD-RUNTIME-ENRICHMENT-ACTIVATION-001

Date: 2026-10-07

Status: APPROVED / IMPLEMENTED / PRE-DEPLOY VALIDATED

## Authorized boundary

Activate VectURL linked-content enrichment only in TrendCite persistent nonprod normal runtime.

Preserved boundaries:
- production activation = NO;
- customer/commercial activation = NO;
- billing / checkout / IRCL = NO;
- Dodo Payments TEST MODE = FROZEN;
- Dodo Payments LIVE MODE = FROZEN;
- max VectURL cost = 0 micro-USD;
- VectURL output is not EvidenceItem and is not a scoring input.

## Architecture

- VectURL enrichment executes only after build_report has completed canonical scoring.
- Source-native EvidenceItem and Observation data remain authoritative for scoring.
- Supplemental records use LinkedContentEnrichment and RunLinkedContentEvidence.
- Durable persistence is isolated in trendcite.cloud_run_linked_content.
- No linked-content path writes scoring, relevance or match inputs.
- Individual VectURL failures are fail-open for the normal TrendCite run.
- Runtime enablement is fail-closed unless:
  - TRENDCITE_VECTURL_RUNTIME_ENRICHMENT=nonprod-enabled;
  - runtime role is nonprod;
  - canonical VectURL host is exact;
  - consumer identity is trendcite-nonprod;
  - VECTURL_CONSUMER_TOKEN exists server-side.
- per-run enrichment limit = 3 signals.
- VectURL request contract = metadata + text / balanced / best_effort / maxCostMicroUsd=0.

## Hosted schema

Migration:
- 0008_vecturl_linked_content_runtime.sql
- Supabase history: hg_trendcite_nonprod_0008_vecturl_linked_content_runtime
- cloud_run_linked_content initial rows = 0
- runtime role privileges verified
- Data API direct probe with Accept-Profile=trendcite = HTTP 406

RLS advisory remains defense-in-depth only under the current architecture because trendcite is not exposed through the Supabase Data API and database access is direct PostgreSQL via Hyperdrive. No automatic RLS change was performed.

## Validation

- focused VectURL runtime tests = PASS
- baseline vs enriched SignalBrief.to_dict = IDENTICAL
- VectURL provider failure = normal run remains usable
- durable linked-content persistence isolation test = PASS
- full pytest suite = PASS
- Ruff format/check = PASS
- mypy = PASS / 80 source files
- frontend tests/build = PASS
- offline demo = PASS
- wheel build/import = PASS
- canonical local preflight = PASS
- exact wheel SHA-256 = b2c75797d64e60cf6ca64abe6b839cc4e702537e09862bf0565bb8919bfc518f
- packaging source proof = PASS / 22 required modules
- pywrangler nonprod dry-run = PASS / 227 modules

## Remaining automatic actions

- one logical GitHub checkpoint;
- remote CI;
- merge if green;
- deploy exact main to persistent nonprod;
- validate normal runtime linked-content persistence and zero cost;
- confirm scoring/non-mutation evidence;
- close this gate.
