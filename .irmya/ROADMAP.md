# TrendCite Pro v1 — IRMYA Roadmap

## Milestones

M1 — Persistent Nonprod Foundation
- Supabase schema and runtime roles
- Hyperdrive
- Queue + DLQ
- Worker
- Cron
- persistent health/runtime validation

M2 — Persistent Runtime E2E
- controlled nonprod workspace/radar/watchlist
- scheduled acquisition
- Queue execution
- durable result persistence
- retries and failure evidence

M3 — Transactional Delivery
- Postmark integration
- alert/digest delivery
- delivery retries and baseline semantics

M4 — Authentication and Tenant Access
- Supabase Auth
- workspace membership authorization
- customer-facing API boundary

M5 — Customer Application
- React/Vite frontend
- workspace/watchlist/radar configuration
- signal/history/alert views

M6 — Entitlements and Metering
- plan capability boundaries
- usage metering
- commercial entitlement enforcement
- no live billing until separately authorized

M7 — Full Automation Readiness
- automated recovery/observability/operations
- no routine manual intervention in customer lifecycle

M8 — Production Readiness
- security/reliability/operational review
- production configuration
- production activation remains a Human Gate


## Shared VectURL capability

- Dormant linked-content client: MERGED / TESTED.
- TrendCite source-native scoring remains unchanged.
- Intended first identity: `trendcite-nonprod`.
- No credential issued and no VectURL traffic activated yet.
- Next authority boundary: `HG-TRENDCITE-VECTURL-NONPROD-INTERNAL-CONSUMER-ONBOARDING-001` for one dedicated nonprod credential plus one synthetic zero-cost smoke.


## VectURL nonprod onboarding

- `HG-TRENDCITE-VECTURL-NONPROD-INTERNAL-CONSUMER-ONBOARDING-001` — PASS / CLOSED;
- dedicated `trendcite-nonprod` credential — ACTIVE;
- one synthetic zero-cost smoke — PASS / CLOSED;
- durable VectURL telemetry — 3 successful 2xx operations / cost 0;
- linked-content enrichment in normal TrendCite nonprod runs — NOT ACTIVATED;
- next authority boundary: `HG-TRENDCITE-VECTURL-NONPROD-RUNTIME-ENRICHMENT-ACTIVATION-001`.


## VectURL nonprod runtime enrichment

- `HG-TRENDCITE-VECTURL-NONPROD-RUNTIME-ENRICHMENT-ACTIVATION-001` — PASS / ACTIVE;
- enrichment happens after scoring only;
- maximum 3 linked URLs per run;
- zero-cost / best-effort contract — ENFORCED;
- fail-open — ENFORCED;
- canonical persistence — `cloud_run_linked_content`;
- hosted runtime validation — PASS: 5 signals / 3 enrichments / cost 0;
- scoring invariants — VERIFIED;
- production activation — NOT AUTHORIZED.
