# HG-TRENDCITE-VECTURL-NONPROD-INTERNAL-CONSUMER-ONBOARDING-001

Date: 2026-10-07

`RESULT = PASS / CLOSED`

## VectURL
- consumer: `trendcite-nonprod`
- dedicated secret slot: `VECTURL_CONSUMER_TOKEN_TRENDCITE_NONPROD`
- PR #41 merge: `2aa55026ae3e639a392816b8ab7955081655fbe5`
- auth-code deploy: `be29e48e-4a0e-4764-b393-0252be337afb`
- current version after credential installation: `1beb1221-e78f-4b53-bf89-b7ab346b01d6`

## TrendCite nonprod
- PR #36 merge: `a433eb2d5339f2dcac82b031f39ec8967c1aa980`
- runtime: `trendcite-nonprod-runtime`
- deploy before secret operations: `f2008be7-5673-4d14-b68a-943f8e9f0269`
- final version after smoke-secret deletion: `8c550a88-2de5-4829-97b7-c395cc186fc0`
- permanent secret: `VECTURL_CONSUMER_TOKEN`
- temporary smoke secret: deleted
- health: 200
- smoke route after closure: 404

Packaging:
- exact repository wheel
- SHA-256: `adce12ac4aba3a680c8cd11414c6b0a90935409f73335e2644c4b9508d33a302`
- vendor sync: PASS
- required Cloudflare modules: 19

## Smoke
- URL: `https://example.com/`
- policy: `best_effort`
- max cost: 0 micro-USD
- bundle: `veb_926c307ff529c0e6ee11d1d9`
- status: ready
- fulfilled: text, metadata
- missing: none
- actual cost: 0

Durable metrics:
- ingestion_create 2xx: 1
- ingestion_status 2xx: 1
- content_get 2xx: 1
- total actual cost: 0

## Scope
Normal TrendCite runtime enrichment through VectURL remains disabled.
TrendCite scoring remains unchanged.
No Dodo/IRCL/billing/production/customer activation occurred.
