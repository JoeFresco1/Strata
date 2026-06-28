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
