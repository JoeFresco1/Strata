# Strata

Strata is an AGPL-licensed, local-first product discovery and feature
architecture platform you can self-host.

It helps a team turn an idea into a reviewable product structure:

- Layer 0 builds one canonical product brief.
- Layer 1 discovers and reviews major product pillars.
- Layer 2 builds a provenance-aware feature graph under approved pillars.
- Layer 3 turns approved features into Capability Design Cards for downstream
  planning without jumping straight into implementation code.

Strata runs as a `FastAPI + React` application with `PostgreSQL + pgvector` and
OpenAI-compatible model endpoints, including local runtimes such as
`llama.cpp`.

Current status: **pre-release**. The platform is substantial and usable, but it
is not being presented as finished. The current public release gate lives in
[`docs/PLATFORM_COMPLETION_AUDIT.md`](docs/PLATFORM_COMPLETION_AUDIT.md).

## Why Strata exists

Most AI product-planning tools either stop at vague brainstorming or jump too
early into implementation artifacts. Strata is built to hold the middle ground:

- one durable source of truth instead of scattered notes and chat threads;
- explicit review checkpoints between idea, pillars, features, and capability
  design;
- grounded research and provenance instead of opaque generation;
- self-hosted operation with local-model support, telemetry, and export paths.

## What it does

Core workflows:

- Create a project from an idea and shape it into one canonical Layer 0 brief.
- Run local-first competitor and market research with cited findings.
- Generate and review Layer 1 pillars with duplicate detection and memory-aware
  broadening.
- Build and maintain a graph-native Layer 2 feature map with review controls,
  relationships, and competitive evidence.
- Generate, edit, pressure-test, approve, and export Layer 3 Capability Design
  Cards.
- Use one project assistant with durable runs, citations, confirmed actions,
  and project-aware retrieval.
- Inspect analytics for token usage, configured remote cost, request health,
  latency, workflow totals, and dependency status.
- Export project artifacts, diagnostics, and delivery handoff bundles.

## Quick start

### Docker Compose

Requirements:

- Docker Engine with Compose
- An OpenAI-compatible model endpoint

Clone the repository, copy the environment file, and start the stack:

```bash
git clone <your-repo-url> strata
cd strata
cp .env.example .env
docker compose up --build -d
```

Then open <http://127.0.0.1:8000>.

Set `LLAMA_BASE_URL` and `STRATA_MODEL_NAME` in `.env`. If your model runs on
the Docker host, the default `http://host.docker.internal:8080` value works
with the included Compose file.

### Native launchers

Windows:

```powershell
.\start_strata.ps1
```

Linux or macOS:

```bash
chmod +x start_strata.sh
./start_strata.sh
```

For deeper operator guidance, see
[`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md) and
[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

## Runtime model support

Strata talks to OpenAI-compatible `/v1/models` and `/v1/chat/completions`
endpoints. That lets you use:

- local `llama.cpp` servers;
- hosted providers that expose OpenAI-compatible APIs;
- mixed setups where some workflows stay local and others use remote models.

Project settings support separate assignments for generation, research,
assistant work, and embeddings.

## Workflow at a glance

### Layer 0

Create and refine a brief in conversational Plan mode or direct Form mode.
Publishing the brief promotes it to the canonical project source of truth and
unlocks downstream work.

### Layer 1

Discover and review product pillars. Strata tracks overlap, supports
multi-pass broadening, and separates user-confirmed, persisted-system, and
critic-inferred memory signals.

### Layer 2

Generate and review a graph of features under approved pillars. Strata stores
relationships, supporting evidence, competitive coverage, and review state in
durable project data.

### Layer 3

Turn approved Layer 2 features into Capability Design Cards with decisions,
risks, relationships, readiness, pressure testing, and coverage-gap checks.

## Operating model

Strata is designed first for:

- a single user;
- a trusted internal team;
- a private workstation or home-lab deployment.

It is not a multi-tenant SaaS application. It does not currently provide user
accounts or tenant isolation, so it should stay behind localhost or a trusted
private network unless you add your own access controls.

## Repository guide

Top-level paths:

- [`strata/`](strata) for backend application code
- [`frontend/`](frontend) for the React frontend
- [`docs/`](docs) for release, architecture, self-hosting, and troubleshooting
- [`tests/`](tests) for regression coverage
- [`prompts.json`](prompts.json) for editable system prompts and templates
- [`compose.yml`](compose.yml) for containerized self-hosting
- [`start_strata.ps1`](start_strata.ps1) and [`start_strata.sh`](start_strata.sh)
  for native combined startup
- [`start_specforge.ps1`](start_specforge.ps1) for the legacy Windows
  development launcher

## Development

Basic local setup:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cd frontend
npm install
cd ..
```

Useful validation commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_core.py -q
.\.venv\Scripts\python.exe -m compileall strata
cd frontend
npm run test:cache
npm run build
```

Contribution guidance lives in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Documentation

- [`docs/SELF_HOSTING.md`](docs/SELF_HOSTING.md): Docker and native deployment
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md): runtime and setup issues
- [`docs/PRODUCTION_ARCHITECTURE.md`](docs/PRODUCTION_ARCHITECTURE.md): runtime
  boundaries and production structure
- [`docs/layer architecture.md`](<docs/layer architecture.md>): layer-by-layer
  behavior and memory model
- [`docs/PLATFORM_COMPLETION_AUDIT.md`](docs/PLATFORM_COMPLETION_AUDIT.md):
  current release blockers
- [`AGENTS.md`](AGENTS.md): repo operating rules

## License

Strata is licensed under the
[GNU Affero General Public License v3.0](LICENSE).

If you run a modified version for users over a network, AGPL requires you to
make the corresponding source available to those users under the same license.

