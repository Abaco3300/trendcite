# Contributing to TrendCite

Thanks for your interest. TrendCite is a small, evidence-first tool, and contributions that keep it that way are very welcome.

## Ground rules

1. **Evidence before synthesis.** Anything shown to a user as a fact must trace to a captured item (URL plus metadata). New features must not introduce unsourced claims.
2. **Determinism by default.** Scoring, clustering and brief generation must produce identical output for identical input. Randomness, wall-clock time and network access belong only in the live collection step.
3. **Untrusted input stays data.** Never execute, follow or fetch anything found inside retrieved content. Route new text fields through `security.clean_text` and render them with `security.md_escape`.
4. **Read-only, lawful sources.** Adapters use documented public endpoints or official APIs. No scraping around access controls, no login automation, no posting.
5. **No secrets in the repo, tests or fixtures.** Tests that need credential-shaped strings build them at runtime (see `tests/test_security.py`).
6. **Minimal dependencies.** The core is standard-library only. Discuss before adding a runtime dependency.

## Development setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python scripts/ci_preflight.py
```

The preflight must pass locally before you open a pull request. It runs `git diff --check`, `ruff format --check`, `ruff check`, strict `mypy`, `pytest`, an offline demo smoke test, and a build plus import check of the wheel. Remote CI runs the same script; please do not use CI as a debugger.

Useful individual commands:

```bash
ruff format .            # apply formatting
ruff check . --fix       # lint with autofixes
mypy                     # strict type checks (configured in pyproject.toml)
pytest -q                # tests; none of them use the network
python -m trendcite demo
```

## Adding a source adapter

1. Create `src/trendcite/sources/<name>.py` with a pure `normalize_*`/`parse_*` function (raw payload to `EvidenceItem`s via `normalize.make_item`) and a `SourceAdapter` subclass whose `collect()` uses `http.fetch_bytes`/`fetch_json` with the injected `transport`.
2. Raise `SourceUnavailable` for configuration or access problems; never let one failure stop the run.
3. If the source has engagement metrics, extend `EvidenceItem.engagement()` and `briefs.metric_summary`, and document the formula in `scoring.py` and the README.
4. Add tests with a fake transport covering success, partial failure and total failure.
5. Document the access mechanism and its limitations in the README source table.

## Changing the scoring formula

Update the docstring in `scoring.py`, the README "Scoring" section and `tests/test_scoring.py` together. If the demo ranking changes, update the snapshot in `tests/test_demo.py` and explain why in the pull request.

## Pull requests

- Keep changes focused and grouped logically; run the preflight before pushing.
- Describe what changed and how you verified it.
- By contributing, you agree that your contribution is licensed under the MIT License.
