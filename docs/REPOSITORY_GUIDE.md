# Repository guide

This guide explains where to look first when working on Strata. The repository keeps
the runtime code, browser client, operational scripts, tests, and product documentation
separate so a new contributor can find the right layer quickly.

## Start here

1. Read the root [README](../README.md) for the product model and a working local setup.
2. Read [PRODUCT.md](../PRODUCT.md) for the product definition and boundaries.
3. Read [docs/README.md](README.md) for the architecture-document index.
4. Use [docs/SELF_HOSTING.md](SELF_HOSTING.md) for deployment, database, and provider setup.
5. Use [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md) when the local stack does not start.

## Directory map

| Path | Purpose | Start with |
| --- | --- | --- |
| `frontend/` | React and Vite browser application | `frontend/src/main.jsx`, `frontend/src/App.jsx` |
| `frontend/src/workspace/` | Canonical project workspace and Layer 0–3 views | `WorkspacePage.jsx`, `Layer0View.jsx` |
| `strata/` | FastAPI backend, domain services, persistence, jobs, and provider integration | `api.py`, `models.py`, `db.py` |
| `tests/` | Backend regression and integration coverage | `test_core.py` and the focused `core_*_cases.py` files |
| `frontend/tests/` | Browser-client unit tests | `apiClient.test.mjs`, `setupRuntime.test.mjs` |
| `docs/` | Product, architecture, operations, QA, and decision documentation | `docs/README.md` |
| `docs/skills/` | Repository-local contributor/design instructions | `docs/skills/strata-agent-design/SKILL.md` |
| `scripts/` | Backup, restore, release packaging, and native QA helpers | `package_release.py` |
| `data/` | Local project data and database-related runtime storage | Keep local; do not commit secrets or databases |
| `exports/` | Local generated Markdown, JSON, and delivery bundles | Keep local; generated contents are ignored |
| `.github/` | CI, issue templates, pull-request templates, and GitHub workflows | `.github/workflows/` |

## Root-level files

- `README.md`: public orientation, quick start, workflow overview, and architecture summary.
- `PRODUCT.md`: product definition and intended user experience.
- `AGENTS.md`: instructions for agents and contributors working in this repository.
- `pyproject.toml`: Python project metadata and tooling configuration.
- `requirements.txt` / `requirements-dev.txt`: runtime and development dependencies.
- `compose.yml` / `Dockerfile`: containerized runtime.
- `start_strata.*` / `stop_*`: supported local launch and shutdown helpers.
- `run_strata.py` / `serve_api.py`: direct Python entry points for the application.
- `prompts.json`: the versioned prompt catalog used by the application.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, and the code-of-conduct files: project governance and release-facing policy.

`start_specforge.ps1` and `stop_specforge.ps1` are compatibility aliases retained for
older local workflows. New documentation and scripts should use the `start_strata` and
matching Strata names.

## Where a change belongs

- A visible workflow or layout change usually belongs in `frontend/src/` and may need a
  focused frontend test or a `npm run build` check.
- An API, persistence, lifecycle, generation, review, or provider change belongs in
  `strata/` with a focused backend regression case in `tests/`.
- A migration or schema change belongs with the database/migration modules and must be
  documented with upgrade or rollback implications.
- A product or architecture decision belongs in `docs/`, not in a loose root note.
- A release or operational workflow belongs in `scripts/` and should be linked from the
  relevant self-hosting or release guide.

## Local-only folders

The following are expected on a developer machine and are ignored by Git:

`.venv/`, `.runtime/`, `.local/`, `.codex/`, `.tmp-playwright/`, `.pytest_cache/`,
`__pycache__/`, `frontend/node_modules/`, `frontend/dist/`, `dist/`, local `.env`, and
runtime logs. They are not part of the project structure that contributors need to review
or commit.

## Documentation conventions

- Keep durable guidance in a named file under `docs/`.
- Put dated validation and QA evidence in `docs/QA_*.md`.
- Put current open work in `docs/TODO_LOG.md` or an issue; do not create new root-level
  files with spaces in their names.
- Put historical design notes in `docs/notes/` and give them descriptive, stable names.
- Update `docs/README.md` when adding a durable architecture or operations document.
