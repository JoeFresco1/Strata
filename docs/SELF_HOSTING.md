# Self-hosting Strata

Strata is a single-user, local-first application. It is intended for a personal
machine, workstation, home server, or trusted private network. It does not
provide user accounts or tenant isolation.

The public license is GNU AGPL v3.0.

## Docker Compose

Requirements:

- Docker Engine with Compose
- An OpenAI-compatible model endpoint

Copy `.env.example` to `.env`, then set `LLAMA_BASE_URL` and
`STRATA_MODEL_NAME`. If the model runs on the Docker host, the default
`http://host.docker.internal:8080` value works with the included Compose file.
Set `STRATA_MODEL_API_KEY` when the endpoint requires a bearer token.

```bash
docker compose up --build -d
```

Open <http://127.0.0.1:8000>. PostgreSQL, exports, and the embedding-model cache
are stored in named Docker volumes.

```bash
docker compose logs -f strata
docker compose down
docker compose down -v  # permanently removes Strata's Docker data
```

## Native Windows

Install Python 3.12+, Node.js 22+, PostgreSQL 16+ with pgvector, and optionally
llama.cpp. Copy `.env.example` to `.env`, then run:

```powershell
.\start_strata.ps1
```

The script installs dependencies, builds the frontend, and starts the combined
application at <http://127.0.0.1:8000>. Existing `start_specforge.ps1` remains a
Windows development launcher that manages the separate Vite and llama.cpp
processes.

## Native Linux or macOS

Install Python 3.12+, Node.js 22+, PostgreSQL with pgvector, and a model runtime.
Copy `.env.example` to `.env`, then run:

```bash
chmod +x start_strata.sh
./start_strata.sh
```

## Models

Strata uses OpenAI-compatible `/v1/chat/completions` and `/v1/models` endpoints.
Local llama.cpp and LM Studio endpoints work without API fees. Remote providers
may charge for usage; configure their compatible gateway outside Strata and keep
credentials in environment variables or that gateway.

## Database upgrades

Schema upgrades run automatically during startup. Operators can inspect or
apply them explicitly:

```bash
python -m strata.migrations status
python -m strata.migrations upgrade
```

Back up the PostgreSQL volume or database before upgrading between releases.

## Backup and restore

PostgreSQL is Strata's production source of truth. Artifact exports are useful
for sharing generated outputs, but they are not a complete backup.

For Docker Compose, use the scripted backup wrapper. It creates a timestamped
PostgreSQL custom-format dump under `backups/` plus a JSON metadata sidecar:

```bash
scripts/backup_docker.sh
```

On Windows:

```powershell
.\scripts\backup_docker.ps1
```

Inspect the backup metadata before relying on it:

```bash
python -m strata.backup verify --backup backups/strata-YYYYMMDDTHHMMSSZ.backup
```

Restore into a fresh or stopped Docker installation with an explicit
confirmation token based on the backup filename:

```bash
docker compose up -d postgres
scripts/restore_docker.sh backups/strata-YYYYMMDDTHHMMSSZ.backup RESTORE-strata-YYYYMMDDTHHMMSSZ.backup
docker compose run --rm strata python -m strata.migrations status
docker compose run --rm strata python -m strata.backup verify-live
```

On Windows:

```powershell
.\scripts\restore_docker.ps1 -Backup backups\strata-YYYYMMDDTHHMMSSZ.backup -Confirm RESTORE-strata-YYYYMMDDTHHMMSSZ.backup
```

For a native PostgreSQL install, use the configured database URL or equivalent
connection flags:

```bash
pg_dump "$STRATA_DATABASE_URL" -Fc -f strata.backup
dropdb "$STRATA_DATABASE_URL" --if-exists
createdb "$STRATA_DATABASE_URL"
pg_restore "$STRATA_DATABASE_URL" --clean --if-exists -d strata.backup
python -m strata.migrations status
```

After restore, start Strata and open Analytics for a real project. Confirm that
Database health is healthy, recent jobs are visible, and project data appears as
expected before deleting the old backup.

## Data ownership and deletion

Project data is retained until explicit deletion by default. Per-project data
ownership settings can define optional retention windows for telemetry rows,
telemetry bodies, research content, assistant history, and export artifacts.
Blank retention values mean uncapped retention.

Operators can inspect the current ownership summary through the API:

```bash
curl http://127.0.0.1:8000/api/projects/<project-id>/data-ownership
```

Apply configured or explicit cleanup from the admin CLI:

```bash
python -m strata.lifecycle_admin cleanup-project-data <project-id> --telemetry-body-days 30 --research-days 90
```

Preview irreversible project purge before deleting anything:

```bash
python -m strata.lifecycle_admin purge-project <project-id> --dry-run --delete-artifacts
```

Then run the destructive purge only with the required confirmation token:

```bash
python -m strata.lifecycle_admin purge-project <project-id> --confirm PURGE-<first-8-project-id-chars> --delete-artifacts
```

## Network safety

The default bind address is `127.0.0.1`. Do not expose Strata, PostgreSQL, or a
local model server directly to the public internet. For trusted-network access,
use a reverse proxy with authentication and TLS, and set
`STRATA_ALLOWED_ORIGINS` explicitly.
