from __future__ import annotations

from typing import Any


def add_layer1_architecture_application(db: Any) -> None:
    """Add explicit architecture application and downstream lineage storage."""
    json_type = "JSONB" if db.is_postgres else "TEXT"
    timestamp_type = "TIMESTAMPTZ" if db.is_postgres else "TEXT"
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS layer1_architecture_applications (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL REFERENCES layer1_territory_runs(id) ON DELETE RESTRICT,
            architecture_candidate_id TEXT NOT NULL
                REFERENCES layer1_architecture_candidates(id) ON DELETE RESTRICT,
            selection_event_id TEXT NOT NULL
                REFERENCES layer1_architecture_selection_events(id) ON DELETE RESTRICT,
            sequence_number INTEGER NOT NULL,
            state TEXT NOT NULL,
            applied_pillar_ids {json_type} NOT NULL,
            superseded_pillar_ids {json_type} NOT NULL,
            retained_territory_candidate_ids {json_type} NOT NULL,
            architecture_content_hash TEXT NOT NULL,
            actor TEXT NOT NULL,
            command_id TEXT NOT NULL,
            note TEXT NOT NULL,
            created_at {timestamp_type} NOT NULL,
            superseded_at {timestamp_type},
            UNIQUE(project_id, sequence_number)
        )
        """
    )
    db._execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_layer1_architecture_application_active
        ON layer1_architecture_applications(project_id) WHERE state = 'active'
        """
    )
    _add_layer2_lineage_columns(db, json_type)


def _add_layer2_lineage_columns(db: Any, json_type: str) -> None:
    """Extend Layer 2 run provenance without rewriting existing run records."""
    if db.is_postgres:
        db._execute(
            "ALTER TABLE layer2_generation_runs "
            "ADD COLUMN IF NOT EXISTS source_architecture_application_id TEXT"
        )
        db._execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'layer2_generation_runs'::regclass
                      AND contype = 'f'
                      AND POSITION(
                          'source_architecture_application_id'
                          IN pg_get_constraintdef(oid)
                      ) > 0
                ) THEN
                    ALTER TABLE layer2_generation_runs
                    ADD CONSTRAINT fk_layer2_runs_architecture_application
                    FOREIGN KEY (source_architecture_application_id)
                    REFERENCES layer1_architecture_applications(id) ON DELETE SET NULL;
                END IF;
            END $$
            """
        )
        db._execute(
            f"ALTER TABLE layer2_generation_runs "
            f"ADD COLUMN IF NOT EXISTS source_territory_candidate_ids {json_type} NOT NULL DEFAULT '[]'::jsonb"
        )
        return
    columns = {
        str(row["name"])
        for row in db._fetchall("PRAGMA table_info(layer2_generation_runs)")
    }
    if "source_architecture_application_id" not in columns:
        db._execute(
            "ALTER TABLE layer2_generation_runs "
            "ADD COLUMN source_architecture_application_id TEXT"
        )
    if "source_territory_candidate_ids" not in columns:
        db._execute(
            "ALTER TABLE layer2_generation_runs "
            "ADD COLUMN source_territory_candidate_ids TEXT NOT NULL DEFAULT '[]'"
        )
