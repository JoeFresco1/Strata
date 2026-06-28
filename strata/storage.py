from __future__ import annotations

from pathlib import Path

from strata.config import AppConfig, resolve_database_target, using_postgres
from strata.db import Database


def build_database(config: AppConfig, *, run_migrations: bool = True) -> Database:
    """Build the active database and seed Postgres from the legacy SQLite file when needed."""
    database = Database(
        resolve_database_target(config),
        postgres_admin_url=config.postgres_admin_url,
    )
    if run_migrations:
        from strata.migrations import apply_migrations
        apply_migrations(database)
    _seed_postgres_from_legacy_sqlite(config, database)
    return database


def _seed_postgres_from_legacy_sqlite(config: AppConfig, database: Database) -> None:
    """Copy the old SQLite dataset into Postgres once when the new target is still empty."""
    if not using_postgres(config):
        return
    if not database.is_postgres:
        return
    if database.list_projects():
        return
    legacy_path = Path(config.db_path)
    if not legacy_path.exists():
        return
    database.import_sqlite_file(legacy_path)
