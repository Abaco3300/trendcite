# TrendCite Cloudflare runtime scaffold

This directory is a **non-production** deployment scaffold created under
`HG-TRENDCITE-PRO-V1-CLOUDFLARE-ARCHITECTURE-ADOPTION-001`, extended through
`HG-TRENDCITE-PRO-V1-ASYNC-APPLICATION-SCHEDULER-BUILD-001`,
`HG-TRENDCITE-PRO-V1-ASYNC-EXECUTION-PIPELINE-BUILD-001`, and
`HG-TRENDCITE-PRO-V1-ASYNC-SOURCE-COLLECTOR-BUILD-001`.

It deliberately contains placeholder resource identifiers and must not be deployed
as-is.

## Runtime contract

- Python Workers runtime.
- Hyperdrive binding: `HYPERDRIVE`.
- Queue binding: `TREND_QUEUE`.
- PostgreSQL is reached only through asyncpg/Hyperdrive adapters.
- External sources are reached only through the async Workers Fetch API transport.
- Runtime SQL is schema-qualified to `trendcite`.
- Schema migrations are administrative work and never run from the Worker.
- Scheduled radar ticks use `cloud_schedule_tick` atomic claim, lease expiry and
  owner-guarded settlement; they are not pre-deduped by the generic Queue ledger.

## Scheduled execution flow

```text
Cron
→ plan due radar boundaries
→ persist ticks
→ enqueue
→ Queue tick
→ atomic claim / lease
→ AsyncCloudApplicationRunner
→ AsyncSourceExecutionServiceImpl
→ HN / GitHub / RSS / Reddit async collectors
→ ExecutionBatch
→ AsyncExecutionPipelineImpl
→ PostgreSQL atomic execution bundle
→ tick settlement / retry
```

Source failures degrade individually into `SourceStatus` and do not automatically
sink the whole radar run.

The source layer reuses the existing parsers and normalizers. It does **not** call
the synchronous `pipeline.run_live()`, `urllib` transport, `ThreadPoolExecutor`
or `time.sleep` from the Workers event loop.

X remains interface-only until a future official authenticated API integration is
explicitly configured. There is no scraping fallback.

The execution bundle contains signals/snapshots, relevance, match state and audit,
coverage, usage, alert candidates and the final succeeded `RadarRun`. The bundle is
written transactionally before the schedule tick is settled.

## Runtime packaging

The Worker must never resolve the public PyPI `trendcite` package as its application
code. It must use the exact repository checkpoint being deployed.

Before any Wrangler dry-run or deploy, build the exact repository checkpoint into the
worker wheelhouse:

```text
python scripts/prepare_cloudflare_runtime.py
```

That command:

1. reads the current package version from the root `pyproject.toml`;
2. builds the matching `trendcite-<version>-py3-none-any.whl`;
3. verifies that the wheel contains the required async Cloud runtime modules;
4. rewrites `deploy/cloudflare/pyproject.toml` to the exact wheel name;
5. removes generated vendor/lock/venv caches so Wrangler cannot reuse a mixed or stale
   `python_modules` tree;
6. prints the wheel SHA-256 as packaging evidence.

`deploy/cloudflare/pyproject.toml` redirects the logical `trendcite` dependency to
that wheel through `[tool.uv.sources]`. Pywrangler regenerates and vendors it,
together with `asyncpg`, into `python_modules/`. Generated wheelhouse, lock, venv
and `python_modules` artefacts are gitignored.

Python Worker dry-runs and deploys must use the dependency-aware wrapper, not raw
Wrangler:

```text
uv run pywrangler deploy --config wrangler.nonprod.jsonc --dry-run
uv run pywrangler deploy --config wrangler.nonprod.jsonc
```

`uv` and the `workers-py`/pywrangler tooling are therefore deployment prerequisites.

`wrangler.jsonc` is the canonical scaffold configuration. Its non-production
resource identifiers remain deliberate placeholders and must be replaced only inside
an explicitly authorized runtime-validation or deployment gate.

This scaffold is locally built only. It does not claim deployment or production
readiness.
