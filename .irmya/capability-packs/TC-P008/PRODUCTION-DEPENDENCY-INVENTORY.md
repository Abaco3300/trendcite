# TC-P008 — Production dependency inventory and activation boundaries

Status: DOCUMENTED / NO ACTIVATION AUTHORIZED

Canonical identity: legalEntityCode=ISTRIADE_GROUP_LLC; brandCode=TRENDCITE_PRO; projectId=trendcite-pro. These identifiers are not interchangeable.

## State vocabulary

- EXISTS: resource has been provisioned. Does not imply the runtime uses it.
- CONNECTED: a binding, producer, consumer, route, or trigger connects a resource to runtime.
- AUTHORIZED: founder/governance permits that connection or operation.
- ACTIVE: actual permitted operational use verified with evidence.
- BLOCKED: prerequisites or authority are absent.

## Production inventory

| Resource | EXISTS | CONNECTED to Worker | AUTHORIZED for execution | Notes |
| --- | --- | --- | --- | --- |
| trendcite-prod-runtime dark JS Worker | YES | NO public routes | foundation-only | workers_dev=false; 404 fetch; no actual app imports |
| trendcite-prod-queue | YES | NO | NO | id 007435e8e7d64f1fb949368f1031e439; zero producers/consumers last verified |
| trendcite-prod-dlq | YES | NO | NO | id 8892608637364e92a7e06ca3f7153e19; zero producers/consumers last verified |
| trendcite-prod-hyperdrive | NO | NO | NO | Credential transfer to Cloudflare remains unresolved |
| PostgreSQL role trendcite_prod_runtime | YES | NO | schema-only provisioning | NOLOGIN/NOINHERIT; do not equate role grants with operational authorization |
| PostgreSQL login trendcite_prod_hyperdrive_login | YES | NO | credential setup needs explicit authority | LOGIN/NOINHERIT; no plaintext in repository |
| Production secrets and delivery | NOT VERIFIED | NO | NO | Never disclose, invent or provision values |
| Public route, cron and customer runtime | NO | NO | NO | Human Gate required |
| IRCL production commerce | routing architecture only | NO | NO | Dodo TEST and LIVE frozen |

Cloudflare account: a4c8274fca447382525edd54ee20fd74. Database project ref: yntcafxmjgfjrdinwdmo; schema trendcite. All remote assertions above are dated previous evidence; refresh before using operationally.

## Future connection contracts — preparation only

1. Hyperdrive: independently validate least-privilege role, production-origin TLS, password custody and transport under an authorized secure boundary; verify connection cap/cache policy and revocation. Do NOT move, expose or generate passwords as part of this pack.
2. Queue/DLQ: verify max attempts, idempotency, dead-letter retention, poison-message behavior and consumer scope using synthetic nonprod cases. Require an explicit gate before binding to real production runtime.
3. Public runtime and delivery: require observability, tenant isolation, authentication negative/positive E2E, safe rollback, delivery control, cost guard and production activation gate. Dark foundation must never be repurposed implicitly by adding a binding.
4. Commerce: route TrendCite Pro → IRCL → provider only; Dodo providerBrandId remains null, providerReviewStatus=PENDING, liveCommercialStatus=BLOCKED. No provider mutation, charge, checkout or credential creation.

## Acceptance matrix

- Dark foundation: code/static guard PASS, remote no-target/no-bindings evidence, production Queue/DLQ zero producers/consumers, no production secrets; may be considered DARK_READY only.
- Production integration ready: all dependencies reviewed, explicit credential/binding gate obtained, nonprod E2E demonstrated; currently BLOCKED.
- Public customer ready: separate production-traffic gate, tenant-safe end-to-end validation and incident procedures; currently BLOCKED.
- Commercial ready: IRCL/Dodo provider review and commercial authorization; currently BLOCKED and Dodo frozen.

The source inventory must never substitute for remote inspection, customer activation approval, or commercial readiness.
