#!/usr/bin/env bash
set -euo pipefail

OUTPUT_DIR="${OUTPUT_DIR:-backups}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
DATABASE="${DATABASE:-strata}"
USER_NAME="${USER_NAME:-strata}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-strata}"

python -m strata.backup backup-docker \
  --output-dir "$OUTPUT_DIR" \
  --postgres-service "$POSTGRES_SERVICE" \
  --database "$DATABASE" \
  --user "$USER_NAME" \
  --compose-project "$COMPOSE_PROJECT"
