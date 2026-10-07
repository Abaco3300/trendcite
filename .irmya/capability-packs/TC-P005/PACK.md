# TC-P005 — Customer Application

Status: LOCAL_VALIDATED / REMOTE_CHECKPOINT_PENDING

## Outcome

Deliver a usable persistent-nonprod TrendCite Pro customer application where an authenticated user can enter the product, see only authorized workspaces, configure the core monitoring objects, and inspect TrendCite results without any production, billing or commercial activation.

## Customer surface

Frontend:
- React/Vite application.
- Supabase Auth session handling.
- authenticated workspace selector.
- workspace/watchlist/radar configuration.
- signal and history views.
- alert and digest views.
- explicit loading, empty, unavailable and authorization-denied states.

Backend:
- extend the existing Cloudflare Worker customer API only where the frontend requires it.
- all reads and writes remain membership-scoped by principal_id.
- tenant existence must not leak across workspaces.
- mutations are nonprod-only for this Pack.
- no service_role or Supabase secret key in the customer-facing runtime.

## Canonical security model

Identity:
- Supabase Auth bearer token.
- Worker validates identity through the project Auth service.

Authorization:
- trendcite.cloud_membership is the canonical workspace access edge.
- user_metadata is never an authorization source.
- every workspace-scoped query resolves membership before returning or mutating customer data.
- unauthorized workspace identifiers return 404 rather than disclosing existence.

Database:
- application database access remains PostgreSQL through Cloudflare Hyperdrive.
- trendcite is not exposed through Supabase Data API.
- direct browser-to-table access is not part of this Pack.

## Authorized scope

AUTHORIZED:
- persistent nonprod frontend implementation.
- persistent nonprod Worker/API extensions required by the frontend.
- TrendCite schema additions only when additive, non-destructive, validated and required for the customer application.
- automated tests, local preflight, one logical remote CI checkpoint, safe nonprod deploy and nonprod validation.
- synthetic TrendCite-only nonprod fixtures where required.

NOT AUTHORIZED:
- production activation.
- production Auth changes.
- live billing or payment collection.
- IRCL live activation.
- persistent outbound delivery activation.
- customer broadcast or real customer onboarding.
- changes to dtp, dtp_staging, dtp_prod, doesaiseeme or unrelated schemas.
- service_role exposure.
- destructive migrations or destructive customer-data operations.
- new paid infrastructure without a separate cost Human Gate.
- any Dodo Payments action or modification in TEST MODE or LIVE MODE until a new explicit human order.

## Acceptance criteria

1. Authenticated customer shell loads in persistent nonprod.
2. User can see only workspaces backed by their cloud_membership.
3. User can create/update the minimum supported watchlist and radar configuration inside an authorized workspace.
4. User can inspect signal/history data for an authorized workspace.
5. User can inspect alert/digest state for an authorized workspace.
6. Cross-tenant reads and writes fail without revealing object existence.
7. No bearer token, password or secret is persisted in repository artifacts or application logs.
8. Local CI preflight passes.
9. Remote CI passes at one logical checkpoint.
10. Nonprod deployment and browser/API E2E validation pass.
11. Production, billing, persistent outbound delivery and commercialization remain disabled.

## Local validation evidence

- Customer API + PostgreSQL customer store: IMPLEMENTED.
- Membership and object access remain workspace-scoped.
- Cross-tenant access returns not_found without existence disclosure.
- Viewer writes are denied.
- Customer mutations require the exact nonprod enablement flag.
- React/Vite customer application: IMPLEMENTED.
- Frontend tests: 3/3 PASS.
- Frontend production build: PASS.
- Full Python pytest suite: PASS.
- Ruff format/check: PASS.
- mypy strict: PASS.
- Offline demo: PASS.
- Wheel build/install/import in isolated venv: PASS.
- Canonical local preflight: PASS.
- No production, billing, persistent outbound delivery or Dodo Payments action occurred.

## Human Gates

No Human Gate is required for internal implementation, tests, commits, PRs, CI, safe nonprod deployment or synthetic nonprod validation within the authorized scope.

Stop only for a genuine authority boundary such as:
- new unapproved spend;
- new protected credential authority;
- real third-party/customer communication;
- production/external activation;
- live financial action;
- destructive or hard-to-reverse operation;
- non-remediable P0;
- material change to product objective/scope.
