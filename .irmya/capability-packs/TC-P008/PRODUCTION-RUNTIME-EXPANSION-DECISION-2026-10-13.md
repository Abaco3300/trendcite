# TC-P008 — Production runtime expansion: IRMYA decision boundary

Date: 2026-10-13. Decision status: NOT AUTHORIZED. This is planning evidence, not an invented gate ID.

## Baseline already authorized

- `trendcite-prod-runtime` deployed with `foundation-dark.js`, `foundation-only` flag and one Hyperdrive binding `TRENDCITE_PROD_DB`.
- No customer routes or `workers.dev`, Queue producers/consumers, cron or commercial execution.
- Existing Hyperdrive read-only diagnostic `SELECT 1` passed in a separate temporary environment; this does not validate an application runtime.
- Dark-source and deployment-state regression tests are integrated on main.

## Candidate future action, deliberately NOT executed

Replace the minimal DARK Worker with TrendCite runtime modules, keeping HTTP inaccessible, cron absent, Queue detached and delivery inactive. This is a material scope and production-risk expansion relative to the current foundation-only contract, triggering assessment under real IRMYA categories HG-A and HG-H, not an ordinary deploy.

## Mandatory acceptance contract if separately authorized

1. Record the exact application entrypoint, build artifact checksum, deploy version and rollback version; pin a rollback procedure before deployment.
2. Prove fail-closed HTTP, scheduled and Queue behavior in local/CI tests and again by provider metadata read-back.
3. Preserve `workers.dev=false`, zero routes, zero custom domains, zero cron and zero Queue producers and consumers throughout.
4. Retain only the authorized Hyperdrive binding with `verify-full`, disabled cache and maximum five origin connections.
5. No customer credentials, production tenant mutations, real delivery, VectURL production, billing, Dodo or public traffic; no new chargeable service.
6. Fail closed and revert to the last verified DARK version if any invariant drifts.
7. Require separate permission before activating runtime execution or any customer/commercial surface.

## Current disposition

No runtime deployment authorized or carried out by this document. Next consequential decision is whether to expand the production deploy envelope while all live surfaces remain disabled. Do not treat this planning note itself as approval.
