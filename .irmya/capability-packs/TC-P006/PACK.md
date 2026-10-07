# TC-P006 — Entitlements and Metering

Status: OPEN / NONCOMMERCIAL IMPLEMENTATION

## Outcome

Implement plan capability boundaries and usage metering for TrendCite Pro in persistent nonprod, without any live billing, checkout, payment-provider activation, production activation, or commercial customer charging.

## Scope

Entitlements:
- define canonical plan capability sets;
- enforce feature access server-side;
- expose current effective entitlement state to the authenticated customer application;
- keep authorization distinct from authentication and workspace membership;
- default to fail-closed when entitlement state is missing or invalid.

Metering:
- record usage events for billable-capability candidates without charging;
- provide deterministic aggregation by workspace and accounting period;
- enforce configured noncommercial quotas in nonprod;
- support idempotent usage recording and replay-safe accounting;
- expose usage summary/status for the customer UI and operations;
- preserve an auditable trail of entitlement and usage decisions.

## Canonical boundaries

AUTHORIZED:
- nonprod entitlement models, storage, APIs, UI and tests;
- additive, non-destructive TrendCite schema changes if required and validated;
- usage event capture and aggregation;
- quota enforcement in nonprod;
- synthetic fixtures and test plans;
- local preflight, GitHub checkpoint, remote CI, safe nonprod deploy and validation.

NOT AUTHORIZED:
- real billing;
- checkout creation;
- payment collection;
- refunds/disputes;
- IRCL live activation;
- Dodo Payments TEST MODE actions;
- Dodo Payments LIVE MODE actions;
- Stripe or any alternative PSP;
- commercial activation;
- production activation;
- real customer charging;
- persistent outbound delivery activation;
- destructive migrations.

## Dodo freeze

DODO_PAYMENTS_TEST_MODE = FROZEN
DODO_PAYMENTS_LIVE_MODE = FROZEN

No Dodo API calls, dashboard changes, products, prices, checkouts, webhooks, tests, configuration, integration changes or operational modifications are permitted until a new explicit human order.

## Security and correctness

- Supabase Auth remains identity only.
- trendcite.cloud_membership remains workspace authorization.
- Entitlements must never weaken tenant isolation.
- Effective entitlement resolution must be server-side.
- Client-provided plan/usage values are untrusted.
- Usage writes must be idempotent.
- Quota enforcement must be deterministic and auditable.
- Missing entitlement data must fail closed for gated features.
- Existing nonprod read access must not become cross-tenant.

## Acceptance criteria

1. Canonical entitlement model exists with explicit capability keys.
2. Effective entitlements resolve per workspace/account context.
3. Server-side enforcement exists for at least one gated capability path.
4. Usage events are recorded idempotently.
5. Usage aggregates are deterministic by accounting period.
6. Noncommercial quota enforcement works in nonprod.
7. Customer API exposes entitlement and usage summary safely.
8. Customer UI can display plan/capability/usage state without trusting browser-supplied authority.
9. Cross-tenant entitlement or usage access returns 404/no existence leakage.
10. Local canonical preflight passes.
11. Remote CI passes at one logical checkpoint.
12. Safe persistent-nonprod deploy and E2E validation pass.
13. Production, billing, checkout, persistent outbound delivery and all Dodo actions remain disabled.

## Human Gates

No Human Gate is required for internal design, additive schema work, implementation, tests, commits, PRs, CI, safe nonprod deployment or synthetic validation within this Pack.

Stop only for a genuine authority boundary:
- new unapproved spend;
- contracts/legal/tax obligations;
- new protected credential authority;
- real third-party/customer communication;
- production/external activation;
- live financial action;
- destructive or hard-to-reverse operation;
- non-remediable P0;
- material change to product objective/scope.


## Current implementation evidence

- Existing idempotent usage ledger reused: cloud_usage_event.
- Entitlement plan and workspace assignment schema added by portable migration 0006.
- Hosted nonprod migration applied as hg_trendcite_nonprod_0006_entitlements_metering.
- nonprod_limited and nonprod_full plans seeded with commercial=0.
- All existing synthetic/nonprod workspaces assigned nonprod_full before runtime enforcement activation.
- Effective capability resolution is server-side and fail-closed.
- Monthly UTC usage aggregation and quota decision logic implemented.
- radar_run quota enforcement occurs before run creation and expensive execution.
- Authenticated entitlement and usage endpoints are membership-scoped.
- Plan & Usage customer UI reads server-authoritative state.
- Focused tests, full pytest, Ruff, mypy, frontend tests/build and canonical local preflight: PASS.
- Cloudflare packaging proof and pywrangler dry-run: PASS.
- TRENDCITE_ENTITLEMENTS nonprod flag is ready but not yet deployed from this branch.
- Production, billing, checkout, customer charging, persistent outbound delivery and all Dodo Payments actions remain disabled.
