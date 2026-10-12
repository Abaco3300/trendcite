# TC-P008 — Production Hyperdrive: recovery after unexpected reboot of LAPTOP-JOSEMILE

Date: 2026-10-12 (America/Bogota)
Authorization: HG-TRENDCITE-P008-PROD-HYPERDRIVE-SECURE-CREDENTIAL-PATH-001
No password, verifier or connection string was retrieved, displayed, transmitted or stored by the executor.

## 1. Supabase read-only state (project yntcafxmjgfjrdinwdmo)

- trendcite_prod_hyperdrive_login: LOGIN true; INHERIT false; SUPERUSER/CREATEROLE/CREATEDB/REPLICATION/BYPASSRLS false; CONNECTION LIMIT 5; VALID UNTIL null; member of trendcite_prod_runtime only.
- trendcite_prod_runtime: NOLOGIN; NOINHERIT; no elevated attributes.
- Nonprod roles unchanged (not modified).
- Postgres logs (metadata-only queries, message text not selected except one auth-failure line):
  - 2026-10-11T01:51:52Z UTC: `password authentication failed for user "trendcite_prod_hyperdrive_login"` (one occurrence; consistent with an interrupted/failed Hyperdrive create attempt).
  - No ALTER ROLE / CREATE ROLE statement observed in postgres logs for 2026-10-09T13:00Z → 2026-10-12T13:45Z.
- Conclusion: it cannot be demonstrated that any operator-held password matches the role. Disposition: ROTATE (new random password, SCRAM verifier applied; plaintext never sent to the server).

## 2. Cloudflare read-only state (account a4c8274fca447382525edd54ee20fd74)

- Hyperdrive filter `trendcite`: only trendcite-nonprod-hyperdrive (403038608f454b4b8172d9609f6a7383). trendcite-prod-hyperdrive = NOT_CREATED.
- Create form (public DB) offers SSL modes require / verify-ca / verify-full; verify-full requires a CA uploaded to the account (none uploaded yet). Caching and connection limit are editable after creation.
- Worker trendcite-prod-runtime: bindings = none; vars = TRENDCITE_PRODUCTION_ACTIVATION=foundation-only; cron = none; queue consumers = none; workers.dev = off; preview URLs = off; custom domains/routes = none.
- Queues: trendcite-prod-queue (007435e8e7d64f1fb949368f1031e439) and trendcite-prod-dlq (8892608637364e92a7e06ca3f7153e19) = Inactive.

## 3. SCRAM verifier tooling

- Original scram_verifier.py on the operator PC: not reachable from executor session (PC not linked); not audited. Replaced by a newly written, auditable script.
- New script SHA-256: 3892a1b6b350857585e8bcebcd24258cf2eb9c12910b722d5651bb6c718a01bf
- Audit: stdlib only (base64, getpass, hashlib, hmac, secrets, sys); no network; no file writes; password read via getpass and never printed; output = ALTER ROLE with verifier only; enforces >=32 ASCII alphanumeric chars.
- Functional proof: real PostgreSQL 16 (isolated, throwaway): role created with generated verifier; correct test password → LOGIN_OK; wrong password → `password authentication failed`.
- Residual risk noted: with log_statement=ddl the verifier (not the password) will appear in Supabase postgres logs; acceptable given >=32-char random password (offline brute-force infeasible).

## 4. Current state

HG-TRENDCITE-P008-PROD-HYPERDRIVE-SECURE-CREDENTIAL-PATH-001 = HUMAN_SECURE_ACTION_REQUIRED (operator: CA upload, verifier application, native password entry)
PRODUCTION_HYPERDRIVE = NOT_CREATED
PRODUCTION_WORKER_BINDING = BLOCKED
PRODUCTION_QUEUE_BINDING = BLOCKED
PRODUCTION_CRON = BLOCKED
PUBLIC_ROUTES = BLOCKED
CUSTOMER_RUNTIME = BLOCKED
DODO_TEST / DODO_LIVE = FROZEN
BILLING / CHECKOUT / CHARGES = BLOCKED
NEW_SPEND = NONE
