#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: scripts/restore_docker.sh <backup-path> RESTORE-<backup-filename>" >&2
  exit 2
fi

BACKUP="$1"
CONFIRM="$2"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
DATABASE="${DATABASE:-strata}"
USER_NAME="${USER_NAME:-strata}"

python -m strata.backup restore-docker \
  --backup "$BACKUP" \
  --confirm "$CONFIRM" \
  --postgres-service "$POSTGRES_SERVICE" \
  --database "$DATABASE" \
  --user "$USER_NAME"
