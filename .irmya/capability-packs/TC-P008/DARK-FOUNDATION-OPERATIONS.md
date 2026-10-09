# TC-P008 — Dark Foundation Operations (noncommercial)

Status: RUNBOOK / PREPARED, NOT LIVE CUSTOMER OPERATIONS
Gate: HG-TRENDCITE-PRODUCTION-FOUNDATION-PROVISIONING-001

## Scope and separation

The **dark foundation** is an existing Cloudflare Worker object intentionally unreachable from public routes and disconnected from runtime dependencies. A passing foundation check is NOT production/customer/commercial readiness. The older `scripts/check_production_readiness.py` tests future live-runtime prerequisites and is expected to report blockers. `scripts/check_dark_foundation_readiness.py` covers only local static invariants.

## Monitoring and evidence collection (read-only)

1. Verify canonical repository main and CI before assessing deployments.
2. Run `python scripts/check_dark_foundation_readiness.py` from repo root. Every check must pass; `commercial_ready` must remain false.
3. In the Cloudflare account `a4c8274fca447382525edd54ee20fd74`, inspect `trendcite-prod-runtime` deployments: latest version, target/routing configuration and uploaded bindings. No route, workers.dev, cron, queue or Hyperdrive should be present.
4. Inspect `trendcite-prod-queue` and `trendcite-prod-dlq`: both must retain zero producers/consumers.
5. Review deployment events and request metrics. Expected customer traffic is zero; any traffic, exceptions or unexpected triggers must be investigated as potential drift. Do not assert zero traffic merely because Wrangler reported no targets.
6. Record timestamp, account ID, version ID, Git SHA, target/binding inventory, queue counts and supporting evidence in `.irmya/evidence/`. Do not store passwords, tokens or raw private logs.
7. Verify project/environment by stable IDs. Never infer scope from the display name alone.

Cloudflare metrics are not automatically monitored by this document. No new paid telemetry, alarms or credentials are authorized. Proposed alert conditions: unexpected requests >0, new route or workers.dev endpoint, any scheduled trigger, any queue consumer/producer, changed binding or production flag, failed deployment or unapproved new version. They remain a monitoring design until alert wiring is separately evidenced.

## Recovery (safe rollback)

Incident: unintended route, trigger, dependency binding, or unapproved Worker code.

1. Stop further deploys/changes; preserve timestamp, request/deployment evidence and current versions. Escalate immediately if external/customer impact or credentials are implicated.
2. Do not test the exposed endpoint with real customer data. Do not turn on billing, runtime or integrations to diagnose.
3. Select the last VERIFIED minimal dark Worker version and configuration by Git SHA and Cloudflare deployment history. Avoid blind rollback to an older possibly active build.
4. For safe in-scope recovery, redeploy the known minimal dark config only after reviewing target configuration and confirming the response will have no routes, triggers, queues, Hyperdrive or secrets. If exposure involves an external-impact boundary, obtain the required Human Gate before taking an externally consequential action.
5. Verify all invariants again (Worker target state, bindings, both queue counts and metrics). Archive before/after evidence and classification of root cause.
6. Never delete production resources or rotate/reveal credentials automatically. If a secret was compromised, stop and request credential authority.

Recovery objective: return to **DEPLOYED_DARK**, not restore public production service.

## Activation blockers — intentionally separate

The following are not failures of dark readiness: production Hyperdrive not created; Queue/DLQ intentionally unbound; canonical full-runtime placeholders; customer entitlements, delivery, auth, public routing, production VectURL, IRCL and Dodo commercial flows not activated. Each requires its own readiness evidence and, where applicable, explicit production/credential/billing/commercial authority.

Dodo TEST and LIVE are frozen. Do not create/edit provider brands, products, checkout, keys or configurations. No direct TrendCite-to-Dodo integration; future collection must flow through IRCL.

## Exit criteria

Static foundation checker PASS, Cloudflare remote binding/target and queue verification PASS, CI PASS, evidence persisted. This closes only the dark foundation operational workstream; TC-P008 and all live-commercial gates remain open.
