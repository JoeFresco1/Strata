from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable

from strata.config import AppConfig
from strata.db import Database, utc_now
from strata.dependency_db import canonical_content_hash, feature_revision_token, pillar_revision_token
from strata.storage import build_database


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Database], None]


def _baseline(_: Database) -> None:
    """Mark the existing idempotent schema as the v0.1 baseline."""


def _layer3_immutable_revisions(db: Database) -> None:
    """Backfill legacy Layer 3 projections into immutable revision heads."""
    db.migrate_layer3_revisions()


def _layer3_revision_integrity(db: Database) -> None:
    """Enforce Layer 3 revision ownership and state invariants after the v2 backfill."""
    if not db.is_postgres:
        columns = {str(row[1]) for row in db._fetchall("PRAGMA table_info(layer3_expansion_revision_states)")}
        if "logical_expansion_id" not in columns:
            db._execute("ALTER TABLE layer3_expansion_revision_states ADD COLUMN logical_expansion_id TEXT")
        db._execute(
            """
            UPDATE layer3_expansion_revision_states
            SET logical_expansion_id = (
                SELECT logical_expansion_id
                FROM layer3_expansion_revisions
                WHERE layer3_expansion_revisions.id = layer3_expansion_revision_states.revision_id
            )
            WHERE logical_expansion_id IS NULL
            """
        )
        return
    with db.connect() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE layer3_expansion_revision_states ADD COLUMN IF NOT EXISTS logical_expansion_id TEXT")
            cursor.execute(
                """
                UPDATE layer3_expansion_revision_states states
                SET logical_expansion_id = revisions.logical_expansion_id
                FROM layer3_expansion_revisions revisions
                WHERE revisions.id = states.revision_id
                  AND states.logical_expansion_id IS NULL
                """
            )
            cursor.execute("ALTER TABLE layer3_expansion_revision_states ALTER COLUMN logical_expansion_id SET NOT NULL")
            cursor.execute(
                """
                ALTER TABLE layer3_expansion_revision_states
                ADD COLUMN IF NOT EXISTS active_slot INTEGER GENERATED ALWAYS AS (
                    CASE WHEN workflow_state = 'active' THEN 1 ELSE NULL END
                ) STORED
                """
            )
            constraints = [
                ("layer3_expansion_heads", "layer3_heads_id_project_unique", "UNIQUE (id, project_id)"),
                ("layer3_expansion_heads", "layer3_heads_feature_fk", "FOREIGN KEY (feature_id) REFERENCES layer2_features(id) ON DELETE CASCADE"),
                ("layer3_expansion_heads", "layer3_heads_next_revision_check", "CHECK (next_revision_number >= 1)"),
                ("layer3_expansion_revisions", "layer3_revisions_logical_id_unique", "UNIQUE (logical_expansion_id, id)"),
                ("layer3_expansion_revisions", "layer3_revisions_head_project_fk", "FOREIGN KEY (logical_expansion_id, project_id) REFERENCES layer3_expansion_heads(id, project_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED"),
                ("layer3_expansion_revisions", "layer3_revisions_number_check", "CHECK (revision_number >= 1)"),
                ("layer3_expansion_revision_states", "layer3_revision_states_head_fk", "FOREIGN KEY (logical_expansion_id) REFERENCES layer3_expansion_heads(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED"),
                ("layer3_expansion_revision_states", "layer3_revision_states_revision_owner_fk", "FOREIGN KEY (logical_expansion_id, revision_id) REFERENCES layer3_expansion_revisions(logical_expansion_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED"),
                ("layer3_expansion_revision_states", "layer3_revision_states_workflow_check", "CHECK (workflow_state IN ('candidate', 'active', 'superseded', 'rejected', 'applied_partial'))"),
                ("layer3_expansion_revision_states", "layer3_revision_states_review_check", "CHECK (review_state IN ('draft', 'approved', 'rejected', 'needs_review'))"),
                ("layer3_expansion_revision_states", "layer3_revision_states_freshness_check", "CHECK (freshness_state IN ('fresh', 'stale', 'unknown'))"),
                ("layer3_expansion_revision_states", "layer3_revision_states_consistency_check", "CHECK ((workflow_state <> 'candidate' OR review_state = 'needs_review') AND (workflow_state <> 'rejected' OR review_state = 'rejected') AND (workflow_state <> 'applied_partial' OR review_state = 'approved'))"),
                ("layer3_expansion_revision_states", "layer3_revision_states_one_active", "UNIQUE (logical_expansion_id, active_slot) DEFERRABLE INITIALLY DEFERRED"),
                ("layer3_revision_actions", "layer3_revision_actions_head_project_fk", "FOREIGN KEY (logical_expansion_id, project_id) REFERENCES layer3_expansion_heads(id, project_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED"),
                ("layer3_revision_actions", "layer3_revision_actions_revision_owner_fk", "FOREIGN KEY (logical_expansion_id, revision_id) REFERENCES layer3_expansion_revisions(logical_expansion_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED"),
                ("layer3_expansion_heads", "layer3_heads_active_revision_fk", "FOREIGN KEY (id, active_revision_id) REFERENCES layer3_expansion_revisions(logical_expansion_id, id) DEFERRABLE INITIALLY DEFERRED"),
                ("layer3_feature_expansions", "layer3_projection_active_revision_fk", "FOREIGN KEY (id, active_revision_id) REFERENCES layer3_expansion_revisions(logical_expansion_id, id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED"),
            ]
            for table, name, definition in constraints:
                cursor.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,))
                if cursor.fetchone() is None:
                    cursor.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition}")
            cursor.execute(
                """
                CREATE OR REPLACE FUNCTION strata_validate_layer3_active_head() RETURNS trigger AS $$
                DECLARE
                    logical_id TEXT;
                    head_revision_id TEXT;
                    active_count INTEGER;
                    head_is_active BOOLEAN;
                BEGIN
                    IF TG_TABLE_NAME = 'layer3_expansion_heads' THEN
                        logical_id := COALESCE(NEW.id, OLD.id);
                    ELSE
                        logical_id := COALESCE(NEW.logical_expansion_id, OLD.logical_expansion_id);
                    END IF;
                    SELECT active_revision_id INTO head_revision_id
                    FROM layer3_expansion_heads WHERE id = logical_id;
                    IF NOT FOUND THEN
                        RETURN NULL;
                    END IF;
                    SELECT COUNT(*), COALESCE(BOOL_OR(revision_id = head_revision_id), FALSE)
                    INTO active_count, head_is_active
                    FROM layer3_expansion_revision_states
                    WHERE logical_expansion_id = logical_id AND workflow_state = 'active';
                    IF head_revision_id IS NULL AND active_count <> 0 THEN
                        RAISE EXCEPTION 'Layer 3 head % has no active pointer but % active states', logical_id, active_count;
                    END IF;
                    IF head_revision_id IS NOT NULL AND (active_count <> 1 OR NOT head_is_active) THEN
                        RAISE EXCEPTION 'Layer 3 head % must point to its sole active revision', logical_id;
                    END IF;
                    RETURN NULL;
                END;
                $$ LANGUAGE plpgsql
                """
            )
            cursor.execute("SELECT 1 FROM pg_trigger WHERE tgname = 'layer3_heads_active_consistency'")
            if cursor.fetchone() is None:
                cursor.execute(
                    """
                    CREATE CONSTRAINT TRIGGER layer3_heads_active_consistency
                    AFTER INSERT OR UPDATE OR DELETE ON layer3_expansion_heads
                    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                    EXECUTE FUNCTION strata_validate_layer3_active_head()
                    """
                )
            cursor.execute("SELECT 1 FROM pg_trigger WHERE tgname = 'layer3_states_active_consistency'")
            if cursor.fetchone() is None:
                cursor.execute(
                    """
                    CREATE CONSTRAINT TRIGGER layer3_states_active_consistency
                    AFTER INSERT OR UPDATE OR DELETE ON layer3_expansion_revision_states
                    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                    EXECUTE FUNCTION strata_validate_layer3_active_head()
                    """
                )
        finally:
            cursor.close()


def _critic_human_authority(db: Database) -> None:
    """Upgrade a current v3 database with durable critic authority and finding storage."""
    json_type = "JSONB" if db.is_postgres else "TEXT"
    timestamp_type = "TIMESTAMPTZ" if db.is_postgres else "TEXT"
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS artifact_authority_actions (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            artifact_type TEXT NOT NULL CHECK (artifact_type IN ('layer1_pillar', 'layer2_feature', 'layer3_expansion')), artifact_id TEXT NOT NULL, revision_id TEXT NOT NULL DEFAULT '',
            action_type TEXT NOT NULL, actor TEXT NOT NULL, origin TEXT NOT NULL,
            payload {json_type} NOT NULL, created_at {timestamp_type} NOT NULL
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS critic_findings (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            artifact_type TEXT NOT NULL CHECK (artifact_type IN ('layer1_pillar', 'layer2_feature', 'layer3_expansion')), artifact_id TEXT NOT NULL, artifact_revision_id TEXT NOT NULL DEFAULT '',
            critic_type TEXT NOT NULL, policy_version TEXT NOT NULL, category TEXT NOT NULL,
            severity TEXT NOT NULL, explanation TEXT NOT NULL, evidence {json_type} NOT NULL,
            recommended_action TEXT NOT NULL, source_fingerprint TEXT NOT NULL,
            model_reference TEXT NOT NULL DEFAULT '', job_reference TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK (status IN ('open', 'accepted', 'dismissed', 'superseded')), created_at {timestamp_type} NOT NULL, updated_at {timestamp_type} NOT NULL,
            resolution_action TEXT NOT NULL DEFAULT '', resolution_note TEXT NOT NULL DEFAULT '',
            resolved_by TEXT NOT NULL DEFAULT '', resolved_at {timestamp_type},
            CHECK ((status = 'open' AND resolved_at IS NULL) OR (status <> 'open' AND resolved_at IS NOT NULL)),
            UNIQUE(project_id, artifact_type, artifact_id, artifact_revision_id, critic_type, policy_version, category, source_fingerprint)
        )
        """
    )
    db._execute("CREATE INDEX IF NOT EXISTS idx_artifact_authority_lookup ON artifact_authority_actions(project_id, artifact_type, artifact_id, created_at)")
    db._execute("CREATE INDEX IF NOT EXISTS idx_critic_findings_project ON critic_findings(project_id, artifact_type, artifact_id, status, created_at)")
    db._execute("CREATE INDEX IF NOT EXISTS idx_critic_findings_dedupe_lookup ON critic_findings(project_id, artifact_type, artifact_id, policy_version, category, source_fingerprint)")
    targets = (
        ("nodes", "cleanup_node_critic_records", "layer1_pillar"),
        ("layer2_features", "cleanup_layer2_critic_records", "layer2_feature"),
        ("layer3_expansion_heads", "cleanup_layer3_critic_records", "layer3_expansion"),
    )
    if db.is_postgres:
        db._execute(
            """
            CREATE OR REPLACE FUNCTION strata_cleanup_critic_records() RETURNS trigger AS $$
            DECLARE target_type TEXT;
            BEGIN
                target_type := TG_ARGV[0];
                DELETE FROM critic_findings WHERE artifact_type = target_type AND artifact_id = OLD.id;
                DELETE FROM artifact_authority_actions WHERE artifact_type = target_type AND artifact_id = OLD.id;
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table, trigger, artifact_type in targets:
            db._execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
            db._execute(f"CREATE TRIGGER {trigger} AFTER DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION strata_cleanup_critic_records('{artifact_type}')")
    else:
        for table, trigger, artifact_type in targets:
            db._execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS {trigger} AFTER DELETE ON {table} BEGIN
                    DELETE FROM critic_findings WHERE artifact_type = '{artifact_type}' AND artifact_id = OLD.id;
                    DELETE FROM artifact_authority_actions WHERE artifact_type = '{artifact_type}' AND artifact_id = OLD.id;
                END
                """
            )


def _canonical_mutation_commands(db: Database) -> None:
    """Add the application-command audit and idempotency ledger to a current v4 database."""
    json_type = "JSONB" if db.is_postgres else "TEXT"
    timestamp_type = "TIMESTAMPTZ" if db.is_postgres else "TEXT"
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS command_executions (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            command_type TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            actor_type TEXT NOT NULL CHECK (actor_type IN ('human', 'system', 'import', 'migration', 'model')),
            origin TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_fingerprint TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('running', 'completed')),
            input_payload {json_type} NOT NULL, result_payload {json_type} NOT NULL,
            stale_effects {json_type} NOT NULL, created_at {timestamp_type} NOT NULL,
            completed_at {timestamp_type}, UNIQUE(project_id, idempotency_key)
        )
        """
    )
    db._execute(
        "CREATE INDEX IF NOT EXISTS idx_command_executions_target ON command_executions(project_id, target_type, target_id, created_at)"
    )


def _immutable_briefs_and_dependencies(db: Database) -> None:
    """Upgrade v5 with immutable brief publications and narrow dependency freshness state."""
    json_type = "JSONB" if db.is_postgres else "TEXT"
    timestamp_type = "TIMESTAMPTZ" if db.is_postgres else "TEXT"
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS brief_heads (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
            current_draft_revision_id TEXT, current_published_revision_id TEXT,
            revision_counter INTEGER NOT NULL DEFAULT 0 CHECK (revision_counter >= 0),
            created_at {timestamp_type} NOT NULL, updated_at {timestamp_type} NOT NULL
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS brief_revisions (
            id TEXT PRIMARY KEY, brief_head_id TEXT NOT NULL REFERENCES brief_heads(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL CHECK (revision_number >= 1), payload {json_type} NOT NULL,
            content_hash TEXT NOT NULL, origin TEXT NOT NULL, actor TEXT NOT NULL,
            creation_command_id TEXT NOT NULL DEFAULT '', lineage_quality TEXT NOT NULL
                CHECK (lineage_quality IN ('exact', 'inferred', 'unknown')),
            created_at {timestamp_type} NOT NULL, published_at {timestamp_type}, superseded_at {timestamp_type},
            UNIQUE (brief_head_id, revision_number), UNIQUE (brief_head_id, id), UNIQUE (project_id, id)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS artifact_dependencies (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            dependent_artifact_type TEXT NOT NULL, dependent_artifact_id TEXT NOT NULL,
            dependent_revision_id TEXT NOT NULL, source_artifact_type TEXT NOT NULL,
            source_artifact_id TEXT NOT NULL, source_revision_id TEXT NOT NULL,
            dependency_kind TEXT NOT NULL CHECK (dependency_kind IN ('content', 'scope', 'research', 'coverage', 'export')),
            lineage_quality TEXT NOT NULL CHECK (lineage_quality IN ('exact', 'inferred', 'unknown')),
            created_at {timestamp_type} NOT NULL,
            UNIQUE (project_id, dependent_artifact_type, dependent_artifact_id, dependent_revision_id,
                    source_artifact_type, source_artifact_id, source_revision_id, dependency_kind)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS artifact_freshness_states (
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            artifact_type TEXT NOT NULL, artifact_id TEXT NOT NULL, artifact_revision_id TEXT NOT NULL,
            freshness_state TEXT NOT NULL CHECK (freshness_state IN ('current', 'stale', 'superseded', 'unknown')),
            lineage_quality TEXT NOT NULL CHECK (lineage_quality IN ('exact', 'inferred', 'unknown')),
            stale_reason_count INTEGER NOT NULL DEFAULT 0 CHECK (stale_reason_count >= 0),
            updated_at {timestamp_type} NOT NULL,
            PRIMARY KEY (project_id, artifact_type, artifact_id, artifact_revision_id)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS artifact_stale_transitions (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            artifact_type TEXT NOT NULL, artifact_id TEXT NOT NULL, artifact_revision_id TEXT NOT NULL,
            prior_freshness_state TEXT NOT NULL, source_artifact_type TEXT NOT NULL,
            source_artifact_id TEXT NOT NULL, previous_source_revision_id TEXT NOT NULL,
            replacement_source_revision_id TEXT NOT NULL, triggering_command_id TEXT NOT NULL,
            actor TEXT NOT NULL, origin TEXT NOT NULL, reason_code TEXT NOT NULL,
            created_at {timestamp_type} NOT NULL,
            UNIQUE (project_id, artifact_type, artifact_id, artifact_revision_id, source_artifact_type,
                    source_artifact_id, previous_source_revision_id, replacement_source_revision_id, reason_code)
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_dependencies_source ON artifact_dependencies(project_id, source_artifact_type, source_artifact_id, source_revision_id)",
        "CREATE INDEX IF NOT EXISTS idx_dependencies_dependent ON artifact_dependencies(project_id, dependent_artifact_type, dependent_artifact_id, dependent_revision_id)",
        "CREATE INDEX IF NOT EXISTS idx_freshness_project_state ON artifact_freshness_states(project_id, freshness_state, artifact_type)",
        "CREATE INDEX IF NOT EXISTS idx_stale_history_artifact ON artifact_stale_transitions(project_id, artifact_type, artifact_id, artifact_revision_id, created_at)",
    ):
        db._execute(statement)
    if db.is_postgres:
        for table, name, definition in (
            ("brief_heads", "brief_heads_draft_owner_fk", "FOREIGN KEY (id, current_draft_revision_id) REFERENCES brief_revisions(brief_head_id, id) DEFERRABLE INITIALLY DEFERRED"),
            ("brief_heads", "brief_heads_published_owner_fk", "FOREIGN KEY (id, current_published_revision_id) REFERENCES brief_revisions(brief_head_id, id) DEFERRABLE INITIALLY DEFERRED"),
        ):
            row = db._fetchone("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,))
            if row is None:
                db._execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {definition}")
        db._execute(
            """
            CREATE OR REPLACE FUNCTION strata_protect_published_brief_content() RETURNS trigger AS $$
            BEGIN
                IF OLD.published_at IS NOT NULL AND
                   (NEW.payload IS DISTINCT FROM OLD.payload OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR
                    NEW.revision_number IS DISTINCT FROM OLD.revision_number OR NEW.brief_head_id IS DISTINCT FROM OLD.brief_head_id OR
                    NEW.project_id IS DISTINCT FROM OLD.project_id) THEN
                    RAISE EXCEPTION 'Published brief revision content is immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        db._execute("DROP TRIGGER IF EXISTS protect_published_brief_content ON brief_revisions")
        db._execute("CREATE TRIGGER protect_published_brief_content BEFORE UPDATE ON brief_revisions FOR EACH ROW EXECUTE FUNCTION strata_protect_published_brief_content()")
        db._execute(
            """
            CREATE OR REPLACE FUNCTION strata_validate_artifact_dependency() RETURNS trigger AS $$
            DECLARE source_valid BOOLEAN := FALSE; dependent_valid BOOLEAN := FALSE;
            BEGIN
                IF NEW.source_artifact_type = 'brief' THEN
                    SELECT EXISTS(SELECT 1 FROM brief_revisions WHERE project_id=NEW.project_id AND brief_head_id=NEW.source_artifact_id AND id=NEW.source_revision_id) INTO source_valid;
                ELSIF NEW.source_artifact_type = 'layer1_pillar' THEN
                    SELECT EXISTS(SELECT 1 FROM nodes WHERE project_id=NEW.project_id AND id=NEW.source_artifact_id) INTO source_valid;
                ELSIF NEW.source_artifact_type = 'layer2_feature' THEN
                    SELECT EXISTS(SELECT 1 FROM layer2_features WHERE project_id=NEW.project_id AND id=NEW.source_artifact_id) INTO source_valid;
                ELSIF NEW.source_artifact_type = 'layer3_revision' THEN
                    SELECT EXISTS(SELECT 1 FROM layer3_expansion_revisions WHERE project_id=NEW.project_id AND logical_expansion_id=NEW.source_artifact_id AND id=NEW.source_revision_id) INTO source_valid;
                ELSE
                    SELECT EXISTS(SELECT 1 FROM artifact_freshness_states WHERE project_id=NEW.project_id AND artifact_type=NEW.source_artifact_type AND artifact_id=NEW.source_artifact_id AND artifact_revision_id=NEW.source_revision_id) INTO source_valid;
                END IF;
                IF NEW.dependent_artifact_type = 'brief' THEN
                    SELECT EXISTS(SELECT 1 FROM brief_revisions WHERE project_id=NEW.project_id AND brief_head_id=NEW.dependent_artifact_id AND id=NEW.dependent_revision_id) INTO dependent_valid;
                ELSIF NEW.dependent_artifact_type = 'layer1_pillar' THEN
                    SELECT EXISTS(SELECT 1 FROM nodes WHERE project_id=NEW.project_id AND id=NEW.dependent_artifact_id) INTO dependent_valid;
                ELSIF NEW.dependent_artifact_type = 'layer2_feature' THEN
                    SELECT EXISTS(SELECT 1 FROM layer2_features WHERE project_id=NEW.project_id AND id=NEW.dependent_artifact_id) INTO dependent_valid;
                ELSIF NEW.dependent_artifact_type = 'layer3_revision' THEN
                    SELECT EXISTS(SELECT 1 FROM layer3_expansion_revisions WHERE project_id=NEW.project_id AND logical_expansion_id=NEW.dependent_artifact_id AND id=NEW.dependent_revision_id) INTO dependent_valid;
                ELSE
                    SELECT EXISTS(SELECT 1 FROM artifact_freshness_states WHERE project_id=NEW.project_id AND artifact_type=NEW.dependent_artifact_type AND artifact_id=NEW.dependent_artifact_id AND artifact_revision_id=NEW.dependent_revision_id) INTO dependent_valid;
                END IF;
                IF NOT source_valid OR NOT dependent_valid THEN
                    RAISE EXCEPTION 'Artifact dependency ownership or revision is invalid';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        db._execute("DROP TRIGGER IF EXISTS validate_artifact_dependency ON artifact_dependencies")
        db._execute("CREATE TRIGGER validate_artifact_dependency BEFORE INSERT OR UPDATE ON artifact_dependencies FOR EACH ROW EXECUTE FUNCTION strata_validate_artifact_dependency()")
        db._execute(
            """
            CREATE OR REPLACE FUNCTION strata_cleanup_artifact_dependencies() RETURNS trigger AS $$
            BEGIN
                DELETE FROM artifact_dependencies
                WHERE (source_artifact_type=TG_ARGV[0] AND source_artifact_id=OLD.id)
                   OR (dependent_artifact_type=TG_ARGV[0] AND dependent_artifact_id=OLD.id);
                DELETE FROM artifact_freshness_states WHERE artifact_type=TG_ARGV[0] AND artifact_id=OLD.id;
                DELETE FROM artifact_stale_transitions WHERE artifact_type=TG_ARGV[0] AND artifact_id=OLD.id;
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table, trigger, artifact_type in (
            ("nodes", "cleanup_node_dependencies", "layer1_pillar"),
            ("layer2_features", "cleanup_feature_dependencies", "layer2_feature"),
            ("layer3_expansion_heads", "cleanup_layer3_dependencies", "layer3_revision"),
            ("brief_heads", "cleanup_brief_dependencies", "brief"),
        ):
            db._execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
            db._execute(f"CREATE TRIGGER {trigger} BEFORE DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION strata_cleanup_artifact_dependencies('{artifact_type}')")
    else:
        db._execute(
            """
            CREATE TRIGGER IF NOT EXISTS protect_published_brief_content
            BEFORE UPDATE OF payload, content_hash, revision_number, brief_head_id, project_id ON brief_revisions
            WHEN OLD.published_at IS NOT NULL
            BEGIN SELECT RAISE(ABORT, 'Published brief revision content is immutable'); END
            """
        )
        for table, trigger, artifact_type in (
            ("nodes", "cleanup_node_dependencies", "layer1_pillar"),
            ("layer2_features", "cleanup_feature_dependencies", "layer2_feature"),
            ("layer3_expansion_heads", "cleanup_layer3_dependencies", "layer3_revision"),
            ("brief_heads", "cleanup_brief_dependencies", "brief"),
        ):
            db._execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE DELETE ON {table} BEGIN
                    DELETE FROM artifact_dependencies WHERE (source_artifact_type='{artifact_type}' AND source_artifact_id=OLD.id) OR (dependent_artifact_type='{artifact_type}' AND dependent_artifact_id=OLD.id);
                    DELETE FROM artifact_freshness_states WHERE artifact_type='{artifact_type}' AND artifact_id=OLD.id;
                    DELETE FROM artifact_stale_transitions WHERE artifact_type='{artifact_type}' AND artifact_id=OLD.id;
                END
                """
            )
    _backfill_revision_dependencies(db)


def _backfill_revision_dependencies(db: Database) -> None:
    """Conservatively label exact, inferred, and unknown lineage for existing projects."""
    for project in db.list_projects(state="all"):
        project_id = str(project["id"] if isinstance(project, dict) else project.id)
        brief = db.get_project_brief(project_id)
        if brief is None:
            continue
        head = db.ensure_brief_revision_head(project_id)
        brief_revision = str(head.get("current_published_revision_id") or head.get("current_draft_revision_id") or "")
        pillars = db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
        pillar_tokens: dict[str, str] = {}
        for pillar in pillars:
            token = pillar_revision_token(pillar)
            pillar_tokens[pillar.id] = token
            db.set_artifact_freshness(project_id=project_id, artifact_type="layer1_pillar", artifact_id=pillar.id, artifact_revision_id=token, freshness_state="current", lineage_quality="inferred")
            if brief_revision:
                db.add_artifact_dependency(project_id=project_id, dependent_artifact_type="layer1_pillar", dependent_artifact_id=pillar.id, dependent_revision_id=token, source_artifact_type="brief", source_artifact_id=str(head["id"]), source_revision_id=brief_revision, lineage_quality="inferred")
        features = db.list_layer2_features(project_id)
        feature_tokens: dict[str, str] = {}
        for feature in features:
            token = feature_revision_token(feature)
            feature_tokens[feature.id] = token
            db.set_artifact_freshness(project_id=project_id, artifact_type="layer2_feature", artifact_id=feature.id, artifact_revision_id=token, freshness_state="current", lineage_quality="inferred")
            if brief_revision:
                db.add_artifact_dependency(project_id=project_id, dependent_artifact_type="layer2_feature", dependent_artifact_id=feature.id, dependent_revision_id=token, source_artifact_type="brief", source_artifact_id=str(head["id"]), source_revision_id=brief_revision, lineage_quality="inferred")
            pillar_token = pillar_tokens.get(feature.owner_pillar_id)
            if pillar_token:
                db.add_artifact_dependency(project_id=project_id, dependent_artifact_type="layer2_feature", dependent_artifact_id=feature.id, dependent_revision_id=token, source_artifact_type="layer1_pillar", source_artifact_id=feature.owner_pillar_id, source_revision_id=pillar_token, lineage_quality="inferred")
        revisions = db._fetchall(f"SELECT * FROM layer3_expansion_revisions WHERE project_id = {db.param}", (project_id,))
        for revision in revisions:
            logical_id = str(revision["logical_expansion_id"])
            revision_id = str(revision["id"])
            state = db._fetchone(f"SELECT freshness_state FROM layer3_expansion_revision_states WHERE revision_id = {db.param}", (revision_id,))
            freshness = "current" if state and str(state["freshness_state"]) == "fresh" else (str(state["freshness_state"]) if state else "unknown")
            freshness = "current" if freshness == "fresh" else freshness
            quality = "inferred" if str(revision["source_brief_revision"] or "") else "unknown"
            db.set_artifact_freshness(project_id=project_id, artifact_type="layer3_revision", artifact_id=logical_id, artifact_revision_id=revision_id, freshness_state=freshness, lineage_quality=quality)
            payload = db._load_json(revision["payload"])
            feature_id = str(payload.get("feature_id") or "")
            pillar_id = str(payload.get("parent_pillar_id") or "")
            if brief_revision:
                db.add_artifact_dependency(project_id=project_id, dependent_artifact_type="layer3_revision", dependent_artifact_id=logical_id, dependent_revision_id=revision_id, source_artifact_type="brief", source_artifact_id=str(head["id"]), source_revision_id=brief_revision, lineage_quality=quality)
            if feature_id and feature_tokens.get(feature_id):
                db.add_artifact_dependency(project_id=project_id, dependent_artifact_type="layer3_revision", dependent_artifact_id=logical_id, dependent_revision_id=revision_id, source_artifact_type="layer2_feature", source_artifact_id=feature_id, source_revision_id=feature_tokens[feature_id], lineage_quality=quality)
            if pillar_id and pillar_tokens.get(pillar_id):
                db.add_artifact_dependency(project_id=project_id, dependent_artifact_type="layer3_revision", dependent_artifact_id=logical_id, dependent_revision_id=revision_id, source_artifact_type="layer1_pillar", source_artifact_id=pillar_id, source_revision_id=pillar_tokens[pillar_id], lineage_quality=quality)
        memories = db._fetchall(f"SELECT * FROM project_memory WHERE project_id = {db.param}", (project_id,))
        for memory in memories:
            scope_id = str(memory["scope_id"] or "")
            if scope_id not in pillar_tokens:
                continue
            memory_type = str(memory["memory_type"])
            artifact_type = "layer2_scope_contract" if memory_type == "scope_contract" else "layer2_coverage_state"
            revision_id = canonical_content_hash(db._load_json(memory["content"]))
            db.set_artifact_freshness(project_id=project_id, artifact_type=artifact_type, artifact_id=str(memory["id"]), artifact_revision_id=revision_id, freshness_state="current", lineage_quality="inferred")
            db.add_artifact_dependency(project_id=project_id, dependent_artifact_type=artifact_type, dependent_artifact_id=str(memory["id"]), dependent_revision_id=revision_id, source_artifact_type="layer1_pillar", source_artifact_id=scope_id, source_revision_id=pillar_tokens[scope_id], dependency_kind="scope" if memory_type == "scope_contract" else "coverage", lineage_quality="inferred")
        coverage_rows = db._fetchall(f"SELECT * FROM layer2_coverage_matrix WHERE project_id = {db.param}", (project_id,))
        for coverage in coverage_rows:
            pillar_id = str(coverage["pillar_id"])
            revision_id = str(coverage["updated_at"])
            db.set_artifact_freshness(project_id=project_id, artifact_type="layer2_coverage_matrix", artifact_id=str(coverage["id"]), artifact_revision_id=revision_id, freshness_state="current", lineage_quality="inferred")
            if pillar_tokens.get(pillar_id):
                db.add_artifact_dependency(project_id=project_id, dependent_artifact_type="layer2_coverage_matrix", dependent_artifact_id=str(coverage["id"]), dependent_revision_id=revision_id, source_artifact_type="layer1_pillar", source_artifact_id=pillar_id, source_revision_id=pillar_tokens[pillar_id], dependency_kind="coverage", lineage_quality="inferred")
            for feature_id in db._load_json(coverage["evidence_feature_ids"]):
                feature_id = str(feature_id)
                if feature_tokens.get(feature_id):
                    db.add_artifact_dependency(project_id=project_id, dependent_artifact_type="layer2_coverage_matrix", dependent_artifact_id=str(coverage["id"]), dependent_revision_id=revision_id, source_artifact_type="layer2_feature", source_artifact_id=feature_id, source_revision_id=feature_tokens[feature_id], dependency_kind="coverage", lineage_quality="inferred")
        findings = db._fetchall(f"SELECT * FROM research_findings WHERE project_id = {db.param}", (project_id,))
        for finding in findings:
            scope_id = str(finding["scope_id"] or "")
            revision_id = str(finding["updated_at"])
            db.set_artifact_freshness(project_id=project_id, artifact_type="research_assessment", artifact_id=str(finding["id"]), artifact_revision_id=revision_id, freshness_state="current", lineage_quality="inferred")
            if brief_revision:
                db.add_artifact_dependency(project_id=project_id, dependent_artifact_type="research_assessment", dependent_artifact_id=str(finding["id"]), dependent_revision_id=revision_id, source_artifact_type="brief", source_artifact_id=str(head["id"]), source_revision_id=brief_revision, dependency_kind="research", lineage_quality="inferred")
            if pillar_tokens.get(scope_id):
                db.add_artifact_dependency(project_id=project_id, dependent_artifact_type="research_assessment", dependent_artifact_id=str(finding["id"]), dependent_revision_id=revision_id, source_artifact_type="layer1_pillar", source_artifact_id=scope_id, source_revision_id=pillar_tokens[scope_id], dependency_kind="research", lineage_quality="inferred")
            if feature_tokens.get(scope_id):
                    db.add_artifact_dependency(project_id=project_id, dependent_artifact_type="research_assessment", dependent_artifact_id=str(finding["id"]), dependent_revision_id=revision_id, source_artifact_type="layer2_feature", source_artifact_id=scope_id, source_revision_id=feature_tokens[scope_id], dependency_kind="research", lineage_quality="inferred")


def _product_discovery_revisions(db: Database) -> None:
    """Add independent immutable revision stores for discovery, research, and projections."""
    json_type = "JSONB" if db.is_postgres else "TEXT"
    timestamp_type = "TIMESTAMPTZ" if db.is_postgres else "TEXT"
    boolean_type = "BOOLEAN" if db.is_postgres else "INTEGER"
    if db.is_postgres:
        db._execute(
            "ALTER TABLE project_model_settings ADD COLUMN IF NOT EXISTS "
            "discovery_settings JSONB NOT NULL DEFAULT '{}'::jsonb"
        )
    else:
        settings_columns = {
            str(row[1]) for row in db._fetchall("PRAGMA table_info(project_model_settings)")
        }
        if "discovery_settings" not in settings_columns:
            db._execute(
                "ALTER TABLE project_model_settings ADD COLUMN "
                "discovery_settings TEXT NOT NULL DEFAULT '{}'"
            )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS product_discovery_heads (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
            current_candidate_revision_id TEXT,
            current_published_revision_id TEXT,
            revision_counter INTEGER NOT NULL DEFAULT 0 CHECK (revision_counter >= 0),
            created_at {timestamp_type} NOT NULL,
            updated_at {timestamp_type} NOT NULL,
            UNIQUE(project_id, id)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS competitor_research_heads (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
            current_candidate_revision_id TEXT,
            current_published_revision_id TEXT,
            revision_counter INTEGER NOT NULL DEFAULT 0 CHECK (revision_counter >= 0),
            created_at {timestamp_type} NOT NULL,
            updated_at {timestamp_type} NOT NULL,
            UNIQUE(project_id, id)
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS competitor_research_revisions (
            id TEXT PRIMARY KEY,
            head_id TEXT NOT NULL REFERENCES competitor_research_heads(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
            source_brief_revision_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('candidate', 'approved', 'published', 'rejected', 'superseded')),
            scope {json_type} NOT NULL,
            profiles {json_type} NOT NULL,
            evidence {json_type} NOT NULL,
            inferred_pillars {json_type} NOT NULL,
            territories {json_type} NOT NULL,
            gaps {json_type} NOT NULL,
            derived_lenses {json_type} NOT NULL,
            human_decisions {json_type} NOT NULL,
            runtime_provenance {json_type} NOT NULL,
            checkpoint_state {json_type} NOT NULL,
            partial_completion {boolean_type} NOT NULL DEFAULT FALSE,
            freshness_state TEXT NOT NULL CHECK (freshness_state IN ('current', 'stale', 'superseded', 'unknown')),
            stale_reason TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL,
            creation_command_id TEXT NOT NULL DEFAULT '',
            created_at {timestamp_type} NOT NULL,
            research_date {timestamp_type},
            last_verified_at {timestamp_type},
            approved_at {timestamp_type},
            published_at {timestamp_type},
            rejected_at {timestamp_type},
            superseded_at {timestamp_type},
            UNIQUE(head_id, revision_number),
            UNIQUE(project_id, id),
            FOREIGN KEY (project_id, source_brief_revision_id)
                REFERENCES brief_revisions(project_id, id) DEFERRABLE INITIALLY DEFERRED
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS product_discovery_revisions (
            id TEXT PRIMARY KEY,
            head_id TEXT NOT NULL REFERENCES product_discovery_heads(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL CHECK (revision_number >= 1),
            source_brief_revision_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('candidate', 'approved', 'published', 'rejected', 'superseded')),
            competitor_research_mode TEXT NOT NULL CHECK (
                competitor_research_mode IN (
                    'no_competitor_research', 'lightweight_competitor_scan', 'deep_competitor_research'
                )
            ),
            competitor_research_revision_id TEXT REFERENCES competitor_research_revisions(id),
            generation_job_id TEXT REFERENCES platform_jobs(id) ON DELETE SET NULL,
            payload {json_type} NOT NULL,
            model_authored_fields {json_type} NOT NULL,
            human_owned_fields {json_type} NOT NULL,
            review_findings {json_type} NOT NULL,
            runtime_provenance {json_type} NOT NULL,
            audit_history {json_type} NOT NULL,
            dependency_metadata {json_type} NOT NULL,
            freshness_state TEXT NOT NULL CHECK (freshness_state IN ('current', 'stale', 'superseded', 'unknown')),
            stale_reason TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL,
            creation_command_id TEXT NOT NULL DEFAULT '',
            created_at {timestamp_type} NOT NULL,
            approved_at {timestamp_type},
            published_at {timestamp_type},
            rejected_at {timestamp_type},
            superseded_at {timestamp_type},
            UNIQUE(head_id, revision_number),
            UNIQUE(project_id, id),
            FOREIGN KEY (project_id, source_brief_revision_id)
                REFERENCES brief_revisions(project_id, id) DEFERRABLE INITIALLY DEFERRED
        )
        """
    )
    db._execute(
        f"""
        CREATE TABLE IF NOT EXISTS discovery_context_projections (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            projection_type TEXT NOT NULL CHECK (projection_type IN ('layer1_discovery', 'competitive')),
            source_discovery_revision_id TEXT NOT NULL REFERENCES product_discovery_revisions(id) ON DELETE CASCADE,
            source_competitor_research_revision_id TEXT REFERENCES competitor_research_revisions(id) ON DELETE SET NULL,
            compiler_version TEXT NOT NULL,
            payload {json_type} NOT NULL,
            included_item_ids {json_type} NOT NULL,
            excluded_item_ids {json_type} NOT NULL,
            inclusion_rationale {json_type} NOT NULL,
            exclusion_rationale {json_type} NOT NULL,
            token_estimate INTEGER NOT NULL CHECK (token_estimate >= 0),
            content_hash TEXT NOT NULL,
            creation_command_id TEXT NOT NULL DEFAULT '',
            created_at {timestamp_type} NOT NULL,
            UNIQUE(project_id, projection_type, content_hash)
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_discovery_revisions_project ON product_discovery_revisions(project_id, revision_number)",
        "CREATE INDEX IF NOT EXISTS idx_discovery_revisions_brief ON product_discovery_revisions(project_id, source_brief_revision_id)",
        "CREATE INDEX IF NOT EXISTS idx_competitor_revisions_project ON competitor_research_revisions(project_id, revision_number)",
        "CREATE INDEX IF NOT EXISTS idx_competitor_revisions_brief ON competitor_research_revisions(project_id, source_brief_revision_id)",
        "CREATE INDEX IF NOT EXISTS idx_discovery_projections_source ON discovery_context_projections(project_id, source_discovery_revision_id)",
    ):
        db._execute(statement)
    if db.is_postgres:
        for table, name, columns, target in (
            (
                "product_discovery_heads",
                "discovery_head_candidate_fk",
                "(id, current_candidate_revision_id)",
                "product_discovery_revisions(head_id, id)",
            ),
            (
                "product_discovery_heads",
                "discovery_head_published_fk",
                "(id, current_published_revision_id)",
                "product_discovery_revisions(head_id, id)",
            ),
            (
                "competitor_research_heads",
                "competitor_head_candidate_fk",
                "(id, current_candidate_revision_id)",
                "competitor_research_revisions(head_id, id)",
            ),
            (
                "competitor_research_heads",
                "competitor_head_published_fk",
                "(id, current_published_revision_id)",
                "competitor_research_revisions(head_id, id)",
            ),
        ):
            if db._fetchone("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,)) is None:
                db._execute(
                    f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY {columns} "
                    f"REFERENCES {target} DEFERRABLE INITIALLY DEFERRED"
                )
        db._execute(
            """
            CREATE OR REPLACE FUNCTION strata_protect_published_discovery_content() RETURNS trigger AS $$
            BEGIN
                IF OLD.state = 'published' AND (
                    NEW.payload IS DISTINCT FROM OLD.payload OR
                    NEW.model_authored_fields IS DISTINCT FROM OLD.model_authored_fields OR
                    NEW.human_owned_fields IS DISTINCT FROM OLD.human_owned_fields OR
                    NEW.review_findings IS DISTINCT FROM OLD.review_findings OR
                    NEW.runtime_provenance IS DISTINCT FROM OLD.runtime_provenance OR
                    NEW.source_brief_revision_id IS DISTINCT FROM OLD.source_brief_revision_id OR
                    NEW.competitor_research_revision_id IS DISTINCT FROM OLD.competitor_research_revision_id OR
                    NEW.content_hash IS DISTINCT FROM OLD.content_hash
                ) THEN
                    RAISE EXCEPTION 'Published Product Discovery content is immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        db._execute(
            """
            CREATE OR REPLACE FUNCTION strata_protect_published_competitor_content() RETURNS trigger AS $$
            BEGIN
                IF OLD.state = 'published' AND (
                    NEW.scope IS DISTINCT FROM OLD.scope OR
                    NEW.profiles IS DISTINCT FROM OLD.profiles OR
                    NEW.evidence IS DISTINCT FROM OLD.evidence OR
                    NEW.inferred_pillars IS DISTINCT FROM OLD.inferred_pillars OR
                    NEW.territories IS DISTINCT FROM OLD.territories OR
                    NEW.gaps IS DISTINCT FROM OLD.gaps OR
                    NEW.derived_lenses IS DISTINCT FROM OLD.derived_lenses OR
                    NEW.human_decisions IS DISTINCT FROM OLD.human_decisions OR
                    NEW.runtime_provenance IS DISTINCT FROM OLD.runtime_provenance OR
                    NEW.source_brief_revision_id IS DISTINCT FROM OLD.source_brief_revision_id OR
                    NEW.content_hash IS DISTINCT FROM OLD.content_hash
                ) THEN
                    RAISE EXCEPTION 'Published competitor research content is immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        db._execute("DROP TRIGGER IF EXISTS protect_published_discovery_content ON product_discovery_revisions")
        db._execute(
            "CREATE TRIGGER protect_published_discovery_content BEFORE UPDATE ON product_discovery_revisions "
            "FOR EACH ROW EXECUTE FUNCTION strata_protect_published_discovery_content()"
        )
        db._execute("DROP TRIGGER IF EXISTS protect_published_competitor_content ON competitor_research_revisions")
        db._execute(
            "CREATE TRIGGER protect_published_competitor_content BEFORE UPDATE ON competitor_research_revisions "
            "FOR EACH ROW EXECUTE FUNCTION strata_protect_published_competitor_content()"
        )
    else:
        db._execute(
            """
            CREATE TRIGGER IF NOT EXISTS protect_published_discovery_content
            BEFORE UPDATE OF payload, model_authored_fields, human_owned_fields, review_findings,
                runtime_provenance, source_brief_revision_id, competitor_research_revision_id, content_hash
            ON product_discovery_revisions
            WHEN OLD.state = 'published'
            BEGIN SELECT RAISE(ABORT, 'Published Product Discovery content is immutable'); END
            """
        )
        db._execute(
            """
            CREATE TRIGGER IF NOT EXISTS protect_published_competitor_content
            BEFORE UPDATE OF scope, profiles, evidence, inferred_pillars, territories, gaps,
                derived_lenses, human_decisions, runtime_provenance, source_brief_revision_id, content_hash
            ON competitor_research_revisions
            WHEN OLD.state = 'published'
            BEGIN SELECT RAISE(ABORT, 'Published competitor research content is immutable'); END
            """
        )


MIGRATIONS = [
    Migration(1, "self_hosted_v0_1_baseline", _baseline),
    Migration(2, "layer3_immutable_candidate_revisions", _layer3_immutable_revisions),
    Migration(3, "layer3_revision_integrity_constraints", _layer3_revision_integrity),
    Migration(4, "critic_human_authority_and_findings", _critic_human_authority),
    Migration(5, "canonical_mutation_command_ledger", _canonical_mutation_commands),
    Migration(6, "immutable_briefs_and_dependency_freshness", _immutable_briefs_and_dependencies),
    Migration(7, "product_discovery_and_competitor_research", _product_discovery_revisions),
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
