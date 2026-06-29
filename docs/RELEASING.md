# Releasing Strata

1. Confirm the platform-completion audit is still closed, then update
   `CHANGELOG.md`, `pyproject.toml`, and `strata/__init__.py`.
2. Run backend tests, frontend tests/build, prompt validation, migration status,
   and the source-size audit.
3. Confirm Docker packaging through CI or a Docker-capable host. Capture a full
   Docker Compose startup/setup/archive transcript when available; this is
   operator-confidence evidence, not a v0.1 publication blocker by itself.
4. Run `python scripts/package_release.py --version X.Y.Z`.
5. Tag the commit as `vX.Y.Z` and push the tag.
6. GitHub Actions creates the downloadable self-hosted archive and release notes.

Do not publish a release containing `.env`, databases, logs, diagnostics,
exports, model files, or private project data.

Public packages must contain `LICENSE`, `NOTICE`, and the contribution policy.
Describe Strata consistently as AGPL-3.0 open source software.
