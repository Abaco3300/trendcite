# TC-P008 — Secure Hyperdrive path investigation / next true operator boundary

Status: PROVIDER CONSTRAINT VERIFIED / NO SECRET TRANSFER / MANUAL SECURE ACTION REQUIRED
Date: 2026-10-10 local America/Bogota

## Read-only Supabase evidence

Project ref yntcafxmjgfjrdinwdmo, schema trendcite.
- trendcite_prod_hyperdrive_login: LOGIN true; INHERIT false; CREATEDB false; CREATEROLE false; SUPERUSER false; REPLICATION false
- trendcite_prod_runtime: LOGIN false; INHERIT false; CREATEDB false; CREATEROLE false; SUPERUSER false; REPLICATION false
- login is a MEMBER of runtime role
- runtime role: schema USAGE=true; CREATE=false
No password/secret material was inspected, retrieved, generated or printed.

## Read-only Cloudflare evidence

Account a4c8274fca447382525edd54ee20fd74.
- Hyperdrive list: 11 existing configurations; none named trendcite-prod...
- Cloudflare OpenAPI create-Hyperdrive contract requires an origin password supplied in write-only input when using an ordinary PostgreSQL origin
- Available Cloudflare-managed `integration` option is PlanetScale, **not** Supabase; this cannot be used as a no-secret bridge

## Safe operator-native procedure (not executed)

1. Confirm with the operator that no new provider charge or plan change will be incurred. If nonzero new costs are required, stop for a separate budget authorization.
2. From an **authenticated Supabase-native administrative workflow**, create or securely reset the password of the restricted `trendcite_prod_hyperdrive_login` role. Never print/query/export the password through ChatGPT, MCP, the terminal, source control, logs, or an assistant-visible form.
3. In the authenticated **Cloudflare dashboard native Hyperdrive create form**, manually enter the production Supabase Postgres host, port, database, the restricted login username and secret directly in its secure field. Use provider-documented TLS controls; require hostname validation where available. Do not paste the connection string into ChatGPT or an intermediary tool.
4. Keep the new Hyperdrive **UNBOUND** from the Worker; do not enable any production Queue/cron/routes/customer runtime.
5. Operator confirms completion **without a password**. Executor performs only metadata read-back: config name/ID, connection identity without password, Worker still dark, zero Queue bindings/consumers and zero public routes.
6. Preserve the credential rotation/revocation path and separate operator approval for later production Worker binding and activation.

If a native form or secure password entry cannot be used, STOP, leave Hyperdrive NOT_CREATED, do not invent or bypass a credential transport.

## Current boundary

The earlier approval to explore the secure path does NOT itself provide a password or mean provider-native entry has occurred. This is a **true operator-action boundary** that cannot be completed by the execution agent without exposing a production secret through an unapproved cross-provider channel.

HG-TRENDCITE-P008-PROD-HYPERDRIVE-SECURE-CREDENTIAL-PATH-001 = PROCEDURE_RESEARCH_COMPLETE / OPERATOR_NATIVE_ENTRY_PENDING
PRODUCTION_WORKER_BINDING = BLOCKED
PRODUCTION_CUSTOMER_ACCESS = BLOCKED
BILLING_AND_DODO = FROZEN
