# PyPI publishing runbook

TrendCite is prepared for tokenless PyPI publishing through GitHub Actions and PyPI Trusted Publishing. **Nothing in this document authorizes a publication.** PyPI publication is a separate release action and must be explicitly approved before the workflow is dispatched.

## Current state

- Distribution name: `trendcite`
- Canonical repository: `Abaco3300/trendcite`
- Workflow: `.github/workflows/publish-pypi.yml`
- GitHub environment expected by the workflow: `pypi`
- PyPI authentication: OIDC Trusted Publishing; no long-lived PyPI token is required or expected
- PyPI project lookup on 2026-09-22: `trendcite` returned 404 (no public project at that name at the time of the check)
- A pending Trusted Publisher does **not** reserve the project name. Re-check availability immediately before first publication.

The workflow is manual (`workflow_dispatch`) only. It does not run on pushes, pull requests, tags, or GitHub Release events.

## One-time setup before the first publication

### 1. Configure the GitHub environment

In `Abaco3300/trendcite` open **Settings ? Environments** and create or review the environment named exactly:

```text
pypi
```

Use deployment protection appropriate for the repository. Add this environment variable only when the PyPI side is fully configured and publication is intentionally armed:

```text
PYPI_TRUSTED_PUBLISHING_READY=true
```

If the variable is absent or has any other value, the privileged publish job fails closed before requesting publication.

Do not add a `PYPI_TOKEN`, password, username, or other long-lived PyPI credential to GitHub Secrets.

### 2. Configure PyPI Trusted Publishing

On PyPI, configure a GitHub Actions Trusted Publisher for these exact values:

```text
PyPI project name: trendcite
GitHub owner: Abaco3300
GitHub repository: trendcite
Workflow filename: publish-pypi.yml
Environment: pypi
```

If `trendcite` does not yet exist on PyPI, use PyPI's pending-publisher flow. A pending publisher becomes effective when the first matching upload creates the project, but it does not reserve the name beforehand.

### 3. Verify the release target

Before publishing, the target must already be an existing Git tag and a published GitHub Release. The package version in `pyproject.toml` at that tag must exactly match the tag after removing the leading `v`.

Examples:

```text
v0.1.0  ?  version = "0.1.0"
v0.2.0  ?  version = "0.2.0"
```

Never publish from a moving branch such as `main`.

## Local package validation

Install the release tooling in a development environment:

```bash
pip install -e ".[release]"
```

Then run:

```bash
python scripts/package_preflight.py
```

For a release candidate, pin the expected version explicitly:

```bash
python scripts/package_preflight.py --expected-version 0.2.0
```

The package preflight:

1. builds one wheel and one sdist;
2. runs `twine check` on both;
3. verifies package metadata and required bundled data;
4. installs the wheel into a new isolated virtual environment;
5. imports TrendCite and runs the deterministic demo;
6. prints SHA-256 hashes for the two distributions;
7. never uploads anything.

## Publishing procedure

Only after an explicit publication authorization:

1. Confirm the GitHub Release is already published and its tag resolves to the intended release commit.
2. Confirm `PYPI_TRUSTED_PUBLISHING_READY=true` exists in the `pypi` GitHub environment.
3. Open **Actions ? Publish to PyPI ? Run workflow**.
4. Enter the exact existing release tag, for example `v0.2.0`.
5. Run the workflow once.

The workflow then:

- checks out the exact tag;
- verifies tag SHA equals the checked-out commit;
- verifies package version equals the tag version;
- verifies the matching GitHub Release exists and is not a draft;
- builds wheel + sdist in an unprivileged job;
- runs `twine check` and an isolated wheel smoke test;
- transfers only the validated distributions to the publish job;
- uses GitHub OIDC to obtain short-lived PyPI credentials;
- publishes provenance attestations through the official PyPA publish action.

The build job has no OIDC permission. Only the final publish job has `id-token: write`.

## Post-publication verification

After a successful upload, verify independently in a clean environment:

```bash
python -m venv verify-pypi
# Windows: verify-pypi\Scripts\activate
# macOS/Linux: source verify-pypi/bin/activate
pip install "trendcite==<version>"
trendcite --version
python -m trendcite demo
```

Also verify on PyPI that:

- project name and version are correct;
- source/repository URLs point to `Abaco3300/trendcite`;
- wheel and sdist are both present;
- Trusted Publishing/provenance is shown as expected;
- no unintended version or duplicate file was uploaded.

## Failure rules

Stop rather than bypass when any of these occurs:

- PyPI project name is no longer available for the first upload;
- Trusted Publisher claims do not match owner/repository/workflow/environment exactly;
- package version differs from the tag;
- GitHub Release is missing or still a draft;
- `twine check` fails;
- isolated wheel smoke test fails;
- the `pypi` environment readiness flag is absent;
- OIDC/Trusted Publishing fails.

Do not fall back to creating or storing a long-lived PyPI API token merely to bypass a Trusted Publishing failure.
