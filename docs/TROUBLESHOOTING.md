# Troubleshooting

## The UI opens but generation is unavailable

Open Analytics and check Model server health. Confirm `LLAMA_BASE_URL` is
reachable from the Strata process or container and the configured model name is
accepted by the endpoint.

## Docker cannot reach a model running on the host

Use `LLAMA_BASE_URL=http://host.docker.internal:8080`. On Linux, the supplied
Compose file maps `host.docker.internal` through `host-gateway`.

## PostgreSQL or pgvector fails during startup

Use the supplied `pgvector/pgvector:pg16` Compose service or install the vector
extension into the native PostgreSQL server. Check the database URL and ensure
the configured user owns the Strata database.

## The first embedding operation is slow

Sentence-transformers downloads and loads the configured model lazily. Docker
Compose persists the Hugging Face cache in a named volume.

## A research job was interrupted

Queued and running research jobs are recovered on the next process startup.
The project can also disable competitive intelligence entirely from settings.

## Sharing diagnostics

Use the Analytics diagnostics export, then inspect the JSON before sharing it.
Prompt bodies, raw responses, research content, model settings, and project data
may be private. Telemetry retention controls affect future model calls.

## Restoring from backup

Run `python -m strata.backup verify --backup <path>` before restore to confirm
that the dump and metadata sidecar are present. After restoring into Docker or a
native PostgreSQL install, run `python -m strata.backup verify-live` and confirm
that migrations are current, project rows are readable, pgvector is available,
telemetry/research/assistant tables are readable, and the exports directory is
accessible.

## Removing private project data

Project data is kept by default. Use
`python -m strata.lifecycle_admin cleanup-project-data <project-id>` with
explicit retention windows, or configure project data ownership settings through
the API before running cleanup. Use `purge-project --dry-run` first when a whole
project must be removed, then rerun with the `PURGE-<first-8-project-id-chars>`
confirmation token for irreversible deletion.
