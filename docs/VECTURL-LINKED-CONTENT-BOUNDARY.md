# TrendCite ↔ VectURL linked-content boundary

Status: readiness-only / dormant.

## Decision

VectURL must not replace TrendCite source adapters and must not create additional
`EvidenceItem` rows for scoring.

TrendCite source adapters remain authoritative for source-native evidence and
engagement metrics:

- Hacker News points/comments
- GitHub stars/forks
- Reddit score/comments
- RSS/Atom publication metadata
- Dev.to source-native fields

VectURL may later enrich already-captured evidence URLs with bounded linked-content
text and provenance.

## Scoring invariant

VectURL linked content is supplemental context only and must not affect:

- recency
- engagement
- corroboration
- relevance
- diversity
- source count
- publisher count

Any future use in generated writing aids must preserve TrendCite's evidence-first
boundary and label the linked content as supplemental provenance-backed context.

## Credential boundary

No VectURL credential is issued by this readiness work.

Intended nonprod identity if onboarding is later authorized:

`trendcite-nonprod`

The next real authority boundary is:

`HG-TRENDCITE-VECTURL-NONPROD-INTERNAL-CONSUMER-ONBOARDING-001`

That gate would authorize a dedicated nonprod credential and one synthetic zero-cost
smoke only. It would not activate customer-facing production or change scoring.
