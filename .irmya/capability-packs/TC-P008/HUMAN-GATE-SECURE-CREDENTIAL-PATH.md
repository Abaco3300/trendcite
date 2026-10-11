# TC-P008 — Proposed true Human Gate: secure production Hyperdrive credential path

Gate ID: HG-TRENDCITE-P008-PROD-HYPERDRIVE-SECURE-CREDENTIAL-PATH-001
Status: HUMAN_DECISION_REQUIRED / NOT APPROVED

## What the decision would authorize

Authorize an **operator-controlled, provider-native secure credential setup procedure** to create the isolated TrendCite production Hyperdrive under the already approved foundation-only scope, solely if the method is compatible with platform security policies and incurs no new expense without a separate budget gate.

This is not permission to reveal, paste, log, export or transfer a production database password through ChatGPT, connected tools, GitHub, terminal output, email or an insecure cross-provider channel. No plaintext is requested in this gate.

Under any approved path, require database role least-privilege verification, native secret entry into provider-protected input, explicit post-provision verification with redacted outputs, and a fail-closed exit if safe custody or transport cannot be achieved.

## Explicitly excluded

No Worker Hyperdrive binding; no production Queue/DLQ consumer or producer; no cron; no public/customer execution; no VectURL activation; no billing, checkout, charges or Dodo TEST/LIVE action; no deployment of customer runtime. A separate runtime integration/activation gate will be required.

## Why this is a genuine Human Gate

The remaining foundation blocker is credential authority/custody across a Supabase-to-Cloudflare trust boundary. The executor cannot infer permission to handle a production secret from the earlier foundation provisioning approval, and the tooling currently cannot carry a password safely across provider boundaries. This is not a request for routine engineering permission: it determines whether a privileged production credential may be created/entered and by which authorized human-operated method.

Until a human approves the procedure and confirms any necessary manual provider-native action, the authority state is BLOCKED. Even after approval, if a secure path is unavailable or nonzero cost appears, stop that operation and request a separate decision.

## Required response

Explicit approval or rejection of the secure credential path. No secret values are to be provided to this conversation.
