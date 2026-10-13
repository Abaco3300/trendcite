# TC-P008 — Persistent Python runtime DARK deployment

Date: 2026-10-13. Scope: explicitly authorized HG-A/HG-H production runtime expansion without customer or background execution.

- Source entrypoint: `deploy/cloudflare/src/main.py`, `wrangler.prod.runtime.dark.jsonc`.
- Packaging: TrendCite wheel 0.1.1 SHA-256 `9d310ad85024d17e58ebbe0c0da5c51608f060646c7c287d35b5dff68352fcfa`, vendor source proof PASS, 20 required cloud modules checked.
- Wrangler `--dry-run` PASS with 227 bundled modules, no public routes, Queue, cron or assets configuration.
- Static HTTP/Queue/scheduled DARK handler tests PASS before deployment.
- Real deploy command `wrangler deploy --config wrangler.prod.runtime.dark.jsonc --strict` PASS; Cloudflare version `0b9b3c85-463d-4259-b778-998178abffba` and `No targets deployed`.
- Independent Cloudflare GET PASS: only three bindings `TRENDCITE_PROD_DB` (Hyperdrive), `TRENDCITE_RUNTIME_ROLE=trendcite_prod_runtime`, `TRENDCITE_PRODUCTION_ACTIVATION=foundation-only`.
- Cron 0, workers.dev disabled, prod Queue and DLQ 0 producers / 0 consumers.
- Last verified prior DARK Worker version for rollback: `0293abca-2382-4f6c-891a-643caf5fe758`. Wrangler rollback command is available; do not invoke without a failed security invariant.
- Remaining restrictions: no customer traffic, public routes, Queue/cron execution, delivery, Dodo, VectURL or billing. No live application tenant E2E was performed.
