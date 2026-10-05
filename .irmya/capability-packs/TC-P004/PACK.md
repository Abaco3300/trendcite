# TC-P004 — Authentication and Tenant Access

Status: BUILD_IN_PROGRESS / POSITIVE_IDENTITY_VALIDATION_PENDING

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

## Acceptance criteria

- missing Authorization -> 401.
- malformed bearer -> 401.
- invalid/expired token -> 401.
- Auth upstream failure -> 503.
- valid authenticated principal can list only own memberships.
- valid authenticated principal cannot read a workspace without membership.
- no cross-tenant leakage.
- packaging includes auth/access modules.
- /health regression remains PASS.
- canonical local preflight PASS or explicit evidence of local-tool execution block with deterministic tests passing.
- P0=0.
- P1=0.

## Human Gate boundary

Creating or authorizing a real Supabase Auth nonprod test identity is a credential/protected-identity authority action and must stop for explicit approval if no already-authorized test identity exists.
