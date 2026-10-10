# TC-P008 — Production integration preflight

Status: PREPARED / STATIC NON-AUTHORITATIVE. No production activation.

## Usage

From repository root: `python -m scripts.check_production_integration_preflight`

The output distinguishes:
- PASS: checks of source-controlled dark foundation invariants only.
- BLOCKED: known missing integration authority or resources.
- NOT_VERIFIED: evidence cannot be established from repository files, requires separate remote inventory or validated scenario tests.

`integration_ready` and `activation_authorized` remain false unconditionally. This report MUST NOT be consumed as a deployment or authorization token. For full commercial readiness use the independent governance gate and provider records; never infer from this report.

## Evidence still required

1. Production Cloudflare read-only audit: deployed Worker version and targets, absence of routes, cron and bindings, Queue/DLQ producers/consumers, including drift from previous observations.
2. Hyperdrive: credential-custody solution inside approved security boundaries; verify least-privilege login, TLS, revocation and cost/connection limits **without exposing password values**.
3. Queue/DLQ: synthetic nonprod idempotency, duplicate redelivery, bounded retries, poison messages, DLQ inspection and recovery; no production bindings while unapproved.
4. Tenant-safe E2E authentication, authorization, webhook replay, observability and controlled rollback.
5. Explicit Human Gate for public production integration/activation; commercial provider review and IRCL routing separately required.

Dodo TEST and LIVE remain frozen. The preflight performs no network requests and changes no infrastructure.
