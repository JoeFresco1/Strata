# Releasing Strata

1. Confirm the platform-completion gate is satisfied, then update
   `CHANGELOG.md`, `pyproject.toml`, and `strata/__init__.py`.
2. Run backend tests, frontend tests/build, prompt validation, migration status,
   and the source-size audit.
3. Build and smoke-test the Docker image on a machine with a current Docker
   Engine and Compose plugin.
4. Run `python scripts/package_release.py --version X.Y.Z`.
5. Tag the commit as `vX.Y.Z` and push the tag.
6. GitHub Actions creates the downloadable self-hosted archive and release notes.

Do not publish a release containing `.env`, databases, logs, diagnostics,
exports, model files, or private project data.

Public packages must contain `LICENSE`, `NOTICE`, and
`CONTRIBUTOR_LICENSE_AGREEMENT.md`. Describe Strata consistently as AGPL-3.0
open source software.
