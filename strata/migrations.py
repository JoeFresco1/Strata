from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable

from strata.config import AppConfig
from strata.db import Database, utc_now
from strata.storage import build_database


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Database], None]


def _baseline(_: Database) -> None:
    """Mark the existing idempotent schema as the v0.1 baseline."""


MIGRATIONS = [
    Migration(1, "self_hosted_v0_1_baseline", _baseline),
]


def ensure_migration_table(db: Database) -> None:
    """Create the portable migration ledger used for upgrades and diagnostics."""
    timestamp_type = "TIMESTAMPTZ" if db.is_postgres else "TEXT"
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at {timestamp_type} NOT NULL
        )
        """
    )


def apply_migrations(db: Database) -> list[int]:
    """Apply every pending migration in order and return applied versions."""
    ensure_migration_table(db)
    rows = db._fetchall("SELECT version FROM schema_migrations ORDER BY version")
    applied = {int(row["version"]) for row in rows}
    completed: list[int] = []
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        migration.apply(db)
        db._execute(
            f"INSERT INTO schema_migrations (version, name, applied_at) VALUES ({db.param}, {db.param}, {db.param})",
            (migration.version, migration.name, utc_now()),
        )
        completed.append(migration.version)
    return completed


def migration_status(db: Database) -> dict[str, object]:
    """Return current and available schema versions for health and release checks."""
    ensure_migration_table(db)
    rows = db._fetchall("SELECT version, name, applied_at FROM schema_migrations ORDER BY version")
    return {
        "current_version": max((int(row["version"]) for row in rows), default=0),
        "latest_version": max((item.version for item in MIGRATIONS), default=0),
        "applied": [dict(row) for row in rows],
    }


def main() -> None:
    """Run migration status or upgrades from the command line."""
    parser = argparse.ArgumentParser(description="Manage the Strata database schema.")
    parser.add_argument("command", choices=("upgrade", "status"))
    args = parser.parse_args()
    db = build_database(AppConfig(), run_migrations=False)
    if args.command == "upgrade":
        print({"applied_versions": apply_migrations(db), **migration_status(db)})
    else:
        print(migration_status(db))


if __name__ == "__main__":
    main()
