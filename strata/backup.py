from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from strata.config import AppConfig
from strata.migrations import migration_status
from strata.storage import build_database


SCHEMA_VERSION = 1


def backup_metadata(*, backup_path: Path, compose_project: str, postgres_service: str, database: str, user: str) -> dict[str, Any]:
    return {
        "metadata_version": 1,
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backup_path": str(backup_path),
        "compose_project": compose_project,
        "postgres_service": postgres_service,
        "database": database,
        "user": user,
        "format": "pg_dump custom compressed",
    }


def metadata_path_for(backup_path: Path) -> Path:
    return backup_path.with_suffix(backup_path.suffix + ".metadata.json")


def write_backup_metadata(backup_path: Path, metadata: dict[str, Any]) -> Path:
    metadata_path = metadata_path_for(backup_path)
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=True), encoding="utf-8")
    return metadata_path


def backup_docker(args: argparse.Namespace) -> dict[str, Any]:
    backup_dir = Path(args.output_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"strata-{timestamp}.backup"
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        args.postgres_service,
        "pg_dump",
        "-U",
        args.user,
        "-d",
        args.database,
        "-Fc",
    ]
    with backup_path.open("wb") as handle:
        subprocess.run(command, check=True, stdout=handle)
    metadata = backup_metadata(
        backup_path=backup_path,
        compose_project=args.compose_project,
        postgres_service=args.postgres_service,
        database=args.database,
        user=args.user,
    )
    metadata_path = write_backup_metadata(backup_path, metadata)
    return {"backup_path": str(backup_path), "metadata_path": str(metadata_path)}


def restore_docker(args: argparse.Namespace) -> dict[str, Any]:
    backup_path = Path(args.backup)
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    expected = f"RESTORE-{backup_path.name}"
    if args.confirm != expected:
        raise ValueError(f"Confirmation token must be {expected}.")
    subprocess.run(["docker", "compose", "up", "-d", args.postgres_service], check=True)
    subprocess.run(["docker", "compose", "exec", "-T", args.postgres_service, "dropdb", "-U", args.user, "--if-exists", args.database], check=True)
    subprocess.run(["docker", "compose", "exec", "-T", args.postgres_service, "createdb", "-U", args.user, args.database], check=True)
    with backup_path.open("rb") as handle:
        subprocess.run(
            ["docker", "compose", "exec", "-T", args.postgres_service, "pg_restore", "-U", args.user, "-d", args.database, "--clean", "--if-exists"],
            check=True,
            stdin=handle,
        )
    return {"restored_backup": str(backup_path)}


def verify_backup(args: argparse.Namespace) -> dict[str, Any]:
    backup_path = Path(args.backup)
    metadata_path = metadata_path_for(backup_path)
    checks = {
        "backup_exists": backup_path.exists(),
        "metadata_exists": metadata_path.exists(),
    }
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    checks["metadata_matches_backup"] = bool(metadata) and Path(metadata.get("backup_path", backup_path)).name == backup_path.name
    return {"ok": all(checks.values()), "checks": checks, "metadata": metadata}


def verify_live(_: argparse.Namespace) -> dict[str, Any]:
    config = AppConfig()
    db = build_database(config)
    status = migration_status(db)
    project_count = int((db._fetchone("SELECT COUNT(*) AS count FROM projects") or {"count": 0})["count"])
    sample = db._fetchone("SELECT id, name FROM projects ORDER BY updated_at DESC LIMIT 1")
    table_checks = {
        "model_call_events": _table_readable(db, "model_call_events"),
        "research_sources": _table_readable(db, "research_sources"),
        "research_findings": _table_readable(db, "research_findings"),
        "assistant_conversations": _table_readable(db, "assistant_conversations"),
        "assistant_documents": _table_readable(db, "assistant_documents"),
    }
    pgvector = {"enabled": db.is_postgres, "readable": True}
    if db.is_postgres:
        pgvector["readable"] = _pgvector_readable(db)
    exports_ok = config.exports_dir.exists() and config.exports_dir.is_dir()
    checks = {
        "migrations_current": not status.get("pending"),
        "projects_readable": project_count >= 0,
        "sample_project_readable": sample is not None or project_count == 0,
        "pgvector_readable": pgvector["readable"],
        "exports_dir_accessible": exports_ok,
        **{f"{table}_readable": ok for table, ok in table_checks.items()},
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "migration_status": status,
        "project_count": project_count,
        "sample_project": dict(sample) if sample else None,
        "pgvector": pgvector,
        "exports_dir": str(config.exports_dir),
    }


def _table_readable(db: Any, table: str) -> bool:
    try:
        db._fetchone(f"SELECT COUNT(*) AS count FROM {table}")
        return True
    except Exception:
        return False


def _pgvector_readable(db: Any) -> bool:
    try:
        db._fetchone("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        return True
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Strata backup, restore, and restore-verification tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup = subparsers.add_parser("backup-docker", help="Create a Docker Compose PostgreSQL backup.")
    backup.add_argument("--output-dir", default="backups")
    backup.add_argument("--postgres-service", default="postgres")
    backup.add_argument("--database", default="strata")
    backup.add_argument("--user", default="strata")
    backup.add_argument("--compose-project", default="strata")
    backup.set_defaults(func=backup_docker)

    restore = subparsers.add_parser("restore-docker", help="Restore a Docker Compose PostgreSQL backup.")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--confirm", required=True)
    restore.add_argument("--postgres-service", default="postgres")
    restore.add_argument("--database", default="strata")
    restore.add_argument("--user", default="strata")
    restore.set_defaults(func=restore_docker)

    verify = subparsers.add_parser("verify", help="Inspect a backup file and metadata sidecar.")
    verify.add_argument("--backup", required=True)
    verify.set_defaults(func=verify_backup)

    live = subparsers.add_parser("verify-live", help="Verify the currently configured restored database.")
    live.set_defaults(func=verify_live)

    args = parser.parse_args()
    print(json.dumps(args.func(args), indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
