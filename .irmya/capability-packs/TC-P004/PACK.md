# TC-P004 — Authentication and Tenant Access

Status: NONPROD_DEPLOYED / POSITIVE_IDENTITY_HUMAN_GATE

## Outcome

Establish a customer-facing API boundary in persistent nonprod where Supabase Auth establishes identity and TrendCite workspace membership establishes authorization.

## Canonical model

Identity:
- Supabase Auth access token.
- Worker validates the Bearer token against the project Auth service.
- Supabase user id becomes TrendCite principal_id.
- user_metadata is never an authorization source.

Authorization:
- cloud_membership is the canonical workspace access edge.
- workspace reads are always scoped by principal_id.
- missing membership returns not_found, preventing cross-tenant existence disclosure.
- roles remain owner/admin/member/viewer.
- this Pack is read-only; customer mutations are deferred.

## API surface

- GET /health — public operational health.
- GET /api/v1/workspaces — authenticated list of workspaces where the principal has membership.
- GET /api/v1/workspaces/{workspace_id} — authenticated membership-scoped workspace read.

## Nonprod Auth configuration

- Supabase project ref: yntcafxmjgfjrdinwdmo
- Supabase Auth JWKS: available
- signing algorithm observed: ES256
- SUPABASE_URL is a public runtime var.
- SUPABASE_PUBLISHABLE_KEY is a public runtime var.
- no service_role / secret key is used by the customer API.

## Validation evidence

- focused auth/access/packaging tests: 22/22 PASS
- full pytest suite: PASS
- mypy remote CI: PASS
- ruff format/check remote CI: PASS
- build + wheel import remote CI: PASS
- Wrangler dry-run: PASS (213 modules)
- PR #28 merged: PASS
- persistent nonprod Worker version: e96fd573-45dc-42e9-97fa-1572a0f699ee
- /health -> 200: PASS
- missing Authorization -> 401: PASS
- invalid bearer -> 401: PASS
- existing cloud_membership rows: 0
- linked Supabase Auth principals: 0
- positive authenticated E2E: PENDING HUMAN GATE
- production untouched: PASS

## Acceptance criteria remaining

- valid authenticated principal can list only own memberships.
- valid authenticated principal cannot read a workspace without membership.
- no cross-tenant leakage under a real Auth session.

## Human Gate

HG-TRENDCITE-PRO-V1-SUPABASE-AUTH-NONPROD-IDENTITY-001

Authorize exactly one controlled nonprod Supabase Auth identity and linked synthetic workspace/membership for positive E2E validation.

No production Auth configuration, customer account creation, commercial activation or personal credentials in chat are authorized by this gate.
