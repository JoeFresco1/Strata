from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql

from strata.config import AppConfig
from strata.api_support import _build_services
from strata.command_types import (
    ArchiveProject, CommandActor, CommandConflictError, CreateFeature, CreatePillar,
    EditFeature, KeepFeature, PublishBrief, UnarchiveProject, UpdateBriefDraft,
)
from strata.dependency_db import pillar_revision_token
from strata.db import Database
from strata.export import export_layer3_feature_expansions
from strata.layer3_db import Layer3RevisionConflict
from strata.layer3_revision import build_structured_diff, reconcile_generated_candidate
from strata.migrations import apply_migrations, ensure_migration_table, migration_status


POSTGRES_TARGET_URL = os.getenv("STRATA_POSTGRES_TEST_DATABASE_URL", "")
POSTGRES_ADMIN_URL = os.getenv("STRATA_POSTGRES_TEST_ADMIN_URL", "")


@unittest.skipUnless(POSTGRES_TARGET_URL and POSTGRES_ADMIN_URL, "Set disposable PostgreSQL integration URLs to run")
class Layer3PostgresIntegrationTests(unittest.TestCase):
    """Validate the immutable Layer 3 revision workflow on disposable PostgreSQL."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create an exact disposable target database named by the integration environment."""
        cls.database_name = urlparse(POSTGRES_TARGET_URL).path.lstrip("/")
        if not cls.database_name.startswith("strata_l3_revision_test_"):
            raise RuntimeError("PostgreSQL integration database must use the strata_l3_revision_test_ prefix")
        with psycopg.connect(POSTGRES_ADMIN_URL, autocommit=True) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(cls.database_name)))
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database_name)))
        cls.tempdir = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls) -> None:
        """Drop only the explicitly prefixed disposable database and local artifact directory."""
        cls.tempdir.cleanup()
        with psycopg.connect(POSTGRES_ADMIN_URL, autocommit=True) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(cls.database_name)))

    @staticmethod
    def _feature(db: Database, project_id: str, name: str, *, review_state: str = "approved") -> tuple[object, object]:
        """Create one approved Layer 2 source and its legacy Layer 3 projection."""
        pillar = db.create_node(
            project_id=project_id,
            parent_id=None,
            layer=1,
            node_type="pillar",
            title=f"{name} pillar",
            description=f"Owns {name}.",
            status="kept",
        )
        feature = db.create_layer2_feature(
            project_id=project_id,
            canonical_name=name,
            description=f"{name} capability.",
            feature_type="capability",
            granularity_class="feature",
            owner_pillar_id=pillar.id,
            candidate_source_ids=[],
            status="approved",
        )
        expansion = db.upsert_layer3_expansion(
            project_id=project_id,
            feature_id=feature.id,
            parent_pillar_id=pillar.id,
            parent_pillar_title=pillar.title,
            feature_name=feature.canonical_name,
            feature_description=feature.description,
            feature_intent=f"Define {name} safely.",
            expansion_groups=[{
                "id": f"group-{feature.id}",
                "name": "Configuration",
                "description": "Human-edited group description.",
                "options": [{
                    "id": f"option-{feature.id}",
                    "name": "Enabled",
                    "description": "Human-edited nested content.",
                    "selection_state": "include",
                    "configuration_kind": "boolean",
                    "default_recommendation": "Enabled",
                    "rationale": "Required by the product owner.",
                    "dependencies": [],
                    "overlaps_feature_ids": [],
                }],
            }],
            overlap_review=[],
            open_questions=["Who owns this decision?"],
            review_state=review_state,
            provenance={"source_layer2_feature_id": feature.id},
        )
        return feature, expansion

    @classmethod
    def _seed_pre_v2_projects(cls) -> dict[str, object]:
        """Seed realistic legacy variants, then remove every v2 schema object."""
        db = Database(POSTGRES_TARGET_URL, postgres_admin_url=POSTGRES_ADMIN_URL)
        empty_project = db.create_project("Legacy no Layer 3", "No generated expansion")
        db.upsert_project_brief(
            project_id=empty_project.id,
            product_idea=empty_project.idea,
            known_competitors=[],
            constraints="",
            status="published",
        )
        one_project = db.create_project("Legacy one expansion", "One human-edited expansion")
        one_brief = db.upsert_project_brief(
            project_id=one_project.id,
            product_idea=one_project.idea,
            known_competitors=[],
            constraints="",
            status="published",
        )
        one_feature, one_expansion = cls._feature(db, one_project.id, "Open text")
        db.record_layer3_expansion_action(
            project_id=one_project.id,
            expansion_id=one_expansion.id,
            action_type="edit",
            payload={"fields": ["expansion_groups"]},
        )
        multi_project = db.create_project("Legacy multiple expansions", "Several feature expansions")
        db.upsert_project_brief(
            project_id=multi_project.id,
            product_idea=multi_project.idea,
            known_competitors=[],
            constraints="",
            status="published",
        )
        multi_feature_a, multi_expansion_a = cls._feature(db, multi_project.id, "Branching", review_state="approved")
        multi_feature_b, multi_expansion_b = cls._feature(db, multi_project.id, "Validation", review_state="needs_review")
        projection_before = [
            dict(row)
            for row in db._fetchall(
                """
                SELECT id, project_id, feature_id, feature_intent, expansion_groups,
                       overlap_review, open_questions, review_state, provenance, created_at, updated_at
                FROM layer3_feature_expansions ORDER BY id
                """
            )
        ]
        ensure_migration_table(db)
        db._execute("DELETE FROM schema_migrations")
        db._execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (%s, %s, NOW())",
            (1, "self_hosted_v0_1_baseline"),
        )
        with db.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DROP TABLE layer3_revision_actions,
                               layer3_expansion_revision_states,
                               layer3_expansion_revisions,
                               layer3_expansion_heads CASCADE
                    """
                )
                cursor.execute("ALTER TABLE layer3_feature_expansions DROP COLUMN active_revision_id")
                cursor.execute("ALTER TABLE layer3_feature_expansions DROP COLUMN revision_number")
        return {
            "empty_project": empty_project,
            "one_project": one_project,
            "one_brief": one_brief,
            "one_feature": one_feature,
            "one_expansion": one_expansion,
            "multi_project": multi_project,
            "multi_features": [multi_feature_a, multi_feature_b],
            "multi_expansions": [multi_expansion_a, multi_expansion_b],
            "projection_before": projection_before,
        }

    @staticmethod
    def _candidate(db: Database, feature: object, expansion: object, suffix: str) -> dict[str, object]:
        """Persist a model-shaped candidate through the production reconciliation path."""
        current = db.get_layer3_expansion(expansion.id)
        active = db.get_layer3_revision(current.active_revision_id)
        generated = {
            "feature_intent": f"Generated intent {suffix}.",
            "expansion_groups": [{
                "id": "model-owned-group-id",
                "name": "Configuration",
                "description": f"Generated group {suffix}.",
                "options": [{
                    "id": "model-owned-option-id",
                    "name": "Enabled",
                    "description": f"Generated option {suffix}.",
                    "selection_state": "exclude",
                    "configuration_kind": "boolean",
                    "default_recommendation": "Disabled",
                    "rationale": "Model rationale.",
                    "dependencies": [],
                    "overlaps_feature_ids": [],
                }],
            }],
            "overlap_review": [],
            "open_questions": [f"Question {suffix}?"],
        }
        content, diff, ownership = reconcile_generated_candidate(active["payload"], generated, active["field_ownership"])
        artifact = {**active["payload"], **content}
        return db.create_layer3_candidate(
            project_id=current.project_id,
            feature_id=feature.id,
            artifact_payload=artifact,
            structured_diff=diff,
            field_ownership=ownership,
            source_layer2_feature_revision=feature.updated_at.isoformat(),
            source_brief_revision=db.get_project_brief(current.project_id).updated_at.isoformat(),
            source_pillar_revision=db.get_node(current.parent_pillar_id).created_at.isoformat(),
            generation_reference=f"postgres-{suffix}",
            origin="regeneration",
            actor="integration-test",
        )

    def test_postgresql_revision_validation_matrix(self) -> None:
        """Run migration, lifecycle, integrity, concurrency, and restart checks end to end."""
        fixtures = self._seed_pre_v2_projects()
        db = Database(POSTGRES_TARGET_URL, postgres_admin_url=POSTGRES_ADMIN_URL)
        self.assertEqual(apply_migrations(db), [2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
        self.assertEqual(migration_status(db)["current_version"], 11)

        expected_tables = {
            "layer3_expansion_heads",
            "layer3_expansion_revisions",
            "layer3_expansion_revision_states",
            "layer3_revision_actions",
            "brief_heads",
            "brief_revisions",
            "artifact_dependencies",
            "artifact_freshness_states",
            "artifact_stale_transitions",
        }
        self.assertTrue(expected_tables.issubset(db._table_names()))
        projection_after = [
            dict(row)
            for row in db._fetchall(
                """
                SELECT id, project_id, feature_id, feature_intent, expansion_groups,
                       overlap_review, open_questions, review_state, provenance, created_at, updated_at
                FROM layer3_feature_expansions ORDER BY id
                """
            )
        ]
        self.assertEqual(projection_after, fixtures["projection_before"])
        self.assertEqual(db._fetchone("SELECT COUNT(*) AS count FROM layer3_expansion_heads")["count"], 3)
        self.assertEqual(db._fetchone("SELECT COUNT(*) AS count FROM layer3_expansion_revisions")["count"], 3)
        self.assertEqual(db._fetchone("SELECT COUNT(*) AS count FROM layer3_expansion_revision_states")["count"], 3)
        self.assertEqual(
            db._fetchone("SELECT COUNT(*) AS count FROM layer3_expansion_heads WHERE project_id = %s", (fixtures["empty_project"].id,))["count"],
            0,
        )
        for legacy_expansion in [fixtures["one_expansion"], *fixtures["multi_expansions"]]:
            migrated = db.get_layer3_expansion(legacy_expansion.id)
            self.assertEqual(migrated.revision_number, 1)
            self.assertTrue(migrated.active_revision_id)
            self.assertEqual(db.get_layer3_revision(migrated.active_revision_id)["workflow_state"], "active")
            self.assertEqual(db.get_layer3_revision(migrated.active_revision_id)["review_state"], legacy_expansion.review_state)
        ownership = db.get_layer3_revision(db.get_layer3_expansion(fixtures["one_expansion"].id).active_revision_id)["field_ownership"]
        self.assertIn(f"group:group-{fixtures['one_feature'].id}.__entity__", ownership)

        constraint_rows = db._fetchall(
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid IN (
                'layer3_expansion_heads'::regclass,
                'layer3_expansion_revisions'::regclass,
                'layer3_expansion_revision_states'::regclass,
                'layer3_revision_actions'::regclass,
                'layer3_feature_expansions'::regclass
            )
            """
        )
        constraint_names = {str(row["conname"]) for row in constraint_rows}
        self.assertTrue({
            "layer3_heads_active_revision_fk",
            "layer3_revisions_head_project_fk",
            "layer3_revision_states_revision_owner_fk",
            "layer3_revision_states_one_active",
            "layer3_revision_states_consistency_check",
            "layer3_revision_actions_revision_owner_fk",
            "layer3_projection_active_revision_fk",
        }.issubset(constraint_names))
        index_names = {
            str(row["indexname"])
            for row in db._fetchall(
                """
                SELECT indexname FROM pg_indexes
                WHERE tablename IN ('layer3_expansion_revisions', 'layer3_revision_actions')
                """
            )
        }
        self.assertTrue({"idx_layer3_revisions_logical_number", "idx_layer3_revision_actions_logical"}.issubset(index_names))

        expansion = db.get_layer3_expansion(fixtures["one_expansion"].id)
        feature = db.get_layer2_feature(fixtures["one_feature"].id)
        initial_active_id = expansion.active_revision_id
        candidate_full = self._candidate(db, feature, expansion, "full")
        self.assertEqual(db.get_layer3_expansion(expansion.id).active_revision_id, initial_active_id)
        full_result = db.apply_layer3_candidate(
            project_id=expansion.project_id,
            logical_expansion_id=expansion.id,
            candidate_revision_id=candidate_full["id"],
            expected_active_revision_id=initial_active_id,
            request_id="postgres-full-accept",
        )
        self.assertEqual(full_result["active_revision"]["id"], candidate_full["id"])
        repeated = db.apply_layer3_candidate(
            project_id=expansion.project_id,
            logical_expansion_id=expansion.id,
            candidate_revision_id=candidate_full["id"],
            expected_active_revision_id=initial_active_id,
            request_id="postgres-full-accept",
        )
        self.assertTrue(repeated["idempotent"])

        current = db.get_layer3_expansion(expansion.id)
        groups_before_partial = current.model_dump(mode="json")["expansion_groups"]
        candidate_partial = self._candidate(db, feature, current, "partial")
        partial = db.apply_layer3_candidate(
            project_id=current.project_id,
            logical_expansion_id=current.id,
            candidate_revision_id=candidate_partial["id"],
            expected_active_revision_id=current.active_revision_id,
            request_id="postgres-partial-accept",
            selected_sections=["feature_intent"],
        )
        current = db.get_layer3_expansion(expansion.id)
        self.assertEqual(current.feature_intent, "Generated intent partial.")
        self.assertEqual(current.model_dump(mode="json")["expansion_groups"], groups_before_partial)
        self.assertNotEqual(partial["active_revision"]["id"], candidate_partial["id"])

        candidate_reject = self._candidate(db, feature, current, "reject")
        rejected = db.reject_layer3_candidate(
            project_id=current.project_id,
            candidate_revision_id=candidate_reject["id"],
            request_id="postgres-reject",
        )
        self.assertEqual(rejected["candidate_revision"]["workflow_state"], "rejected")
        self.assertEqual(db.get_layer3_expansion(current.id).active_revision_id, current.active_revision_id)

        restored = db.restore_layer3_revision(
            project_id=current.project_id,
            logical_expansion_id=current.id,
            source_revision_id=initial_active_id,
            expected_active_revision_id=current.active_revision_id,
            request_id="postgres-restore",
        )
        self.assertNotEqual(restored["active_revision"]["id"], initial_active_id)
        self.assertEqual(db.get_layer3_expansion(current.id).feature_intent, expansion.feature_intent)

        for failpoint in ("verify", "accept", "supersede", "projection", "audit"):
            with self.subTest(failpoint=failpoint):
                current = db.get_layer3_expansion(expansion.id)
                candidate = self._candidate(db, feature, current, f"failure-{failpoint}")
                before = current.model_dump(mode="json")
                with self.assertRaises(RuntimeError):
                    db.apply_layer3_candidate(
                        project_id=current.project_id,
                        logical_expansion_id=current.id,
                        candidate_revision_id=candidate["id"],
                        expected_active_revision_id=current.active_revision_id,
                        request_id=f"postgres-failure-{failpoint}",
                        fail_after_step=failpoint,
                    )
                self.assertEqual(db.get_layer3_expansion(current.id).model_dump(mode="json"), before)
                self.assertEqual(db.get_layer3_revision(candidate["id"])["workflow_state"], "candidate")

        concurrent_base = db.get_layer3_expansion(expansion.id)
        concurrent_a = self._candidate(db, feature, concurrent_base, "concurrent-a")
        concurrent_b = self._candidate(db, feature, concurrent_base, "concurrent-b")
        barrier = threading.Barrier(2)
        outcomes: list[tuple[str, str]] = []

        def accept(candidate_id: str, request_id: str) -> None:
            client_db = Database(POSTGRES_TARGET_URL, postgres_admin_url=POSTGRES_ADMIN_URL)
            barrier.wait()
            try:
                client_db.apply_layer3_candidate(
                    project_id=concurrent_base.project_id,
                    logical_expansion_id=concurrent_base.id,
                    candidate_revision_id=candidate_id,
                    expected_active_revision_id=concurrent_base.active_revision_id,
                    request_id=request_id,
                )
                outcomes.append(("success", candidate_id))
            except Layer3RevisionConflict:
                outcomes.append(("conflict", candidate_id))

        threads = [
            threading.Thread(target=accept, args=(concurrent_a["id"], "postgres-concurrent-a")),
            threading.Thread(target=accept, args=(concurrent_b["id"], "postgres-concurrent-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(sorted(item[0] for item in outcomes), ["conflict", "success"])
        winner_id = next(item[1] for item in outcomes if item[0] == "success")
        self.assertEqual(db.get_layer3_expansion(expansion.id).active_revision_id, winner_id)
        self.assertEqual(
            db._fetchone(
                """
                SELECT COUNT(*) AS count
                FROM layer3_expansion_revision_states
                WHERE logical_expansion_id = %s AND workflow_state = 'active'
                """,
                (expansion.id,),
            )["count"],
            1,
        )

        revision_race_base = db.get_layer3_expansion(expansion.id)
        revision_barrier = threading.Barrier(2)
        raced_candidates: list[dict[str, object]] = []

        def create_raced_candidate(suffix: str) -> None:
            client_db = Database(POSTGRES_TARGET_URL, postgres_admin_url=POSTGRES_ADMIN_URL)
            revision_barrier.wait()
            raced_candidates.append(self._candidate(client_db, feature, revision_race_base, suffix))

        candidate_threads = [
            threading.Thread(target=create_raced_candidate, args=("number-race-a",)),
            threading.Thread(target=create_raced_candidate, args=("number-race-b",)),
        ]
        for thread in candidate_threads:
            thread.start()
        for thread in candidate_threads:
            thread.join(timeout=30)
        raced_numbers = sorted(int(item["revision_number"]) for item in raced_candidates)
        self.assertEqual(len(raced_numbers), 2)
        self.assertEqual(raced_numbers[1], raced_numbers[0] + 1)

        stale_base = db.get_layer3_expansion(expansion.id)
        stale_candidate = self._candidate(db, feature, stale_base, "stale-http")
        db.revise_active_expansion(expansion.id, {"feature_intent": "Concurrent HTTP edit."}, actor="user", origin="integration")
        from strata.api import create_app

        config = AppConfig(
            database_backend="postgres",
            database_url=POSTGRES_TARGET_URL,
            postgres_admin_url=POSTGRES_ADMIN_URL,
            exports_dir=Path(self.tempdir.name) / "api-exports",
            embeddings_enabled=False,
            preferred_model_path=None,
        )
        with patch("strata.api.AppConfig", return_value=config):
            api_client = TestClient(create_app())
        response = api_client.post(
            f"/api/projects/{stale_base.project_id}/layer3/expansions/{stale_base.id}/candidates/{stale_candidate['id']}/apply",
            json={"expected_active_revision_id": stale_base.active_revision_id, "request_id": "postgres-http-stale"},
        )
        self.assertEqual(response.status_code, 409)

        restarted = Database(POSTGRES_TARGET_URL, postgres_admin_url=POSTGRES_ADMIN_URL)
        restarted_expansion = restarted.get_layer3_expansion(expansion.id)
        self.assertEqual(restarted_expansion.active_revision_id, db.get_layer3_expansion(expansion.id).active_revision_id)
        self.assertTrue(restarted.list_layer3_revisions(expansion.id))

        pending = self._candidate(restarted, feature, restarted_expansion, "lifecycle-pending")
        restarted.set_active_layer3_review_state(expansion.id, "approved", actor="integration")
        export_path = export_layer3_feature_expansions(
            restarted.get_project(expansion.project_id),
            restarted.get_project_brief(expansion.project_id).model_dump(mode="json"),
            restarted.layer2_graph_snapshot(expansion.project_id),
            restarted.layer3_snapshot(expansion.project_id),
            Path(self.tempdir.name) / "layer3-export",
        )
        self.assertTrue(export_path.exists())
        self.assertEqual(json.loads(export_path.read_text(encoding="utf-8"))["approved_expansion_count"], 1)

        restarted.archive_project(expansion.project_id)
        self.assertEqual(restarted.get_project(expansion.project_id).lifecycle_state, "archived")
        restarted.unarchive_project(expansion.project_id)
        clone = restarted.clone_project(expansion.project_id, name="Layer 3 revision clone")
        clone_snapshot = restarted.layer3_snapshot(clone.id)
        self.assertTrue(clone_snapshot["expansions"])
        self.assertTrue(clone_snapshot["revision_history"])
        archive_path = restarted.export_project_archive(expansion.project_id, Path(self.tempdir.name) / "archives")
        imported = restarted.import_project_archive(archive_path)["project"]
        imported_snapshot = restarted.layer3_snapshot(imported.id)
        self.assertEqual(len(imported_snapshot["revision_history"]), len(restarted.layer3_snapshot(expansion.project_id)["revision_history"]))
        self.assertTrue(any(item["id"] != pending["id"] and item["workflow_state"] == "candidate" for item in imported_snapshot["revision_history"]))

        with self.assertRaises(psycopg.errors.CheckViolation):
            with psycopg.connect(POSTGRES_TARGET_URL) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE layer3_expansion_revision_states SET review_state = 'approved' WHERE revision_id = %s",
                        (pending["id"],),
                    )
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with psycopg.connect(POSTGRES_TARGET_URL) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO layer3_expansion_revisions (
                            id, logical_expansion_id, project_id, revision_number,
                            source_layer2_feature_revision, source_brief_revision, source_pillar_revision,
                            generation_reference, origin, actor, payload, structured_diff, field_ownership, created_at
                        )
                        SELECT %s, logical_expansion_id, project_id, revision_number,
                               source_layer2_feature_revision, source_brief_revision, source_pillar_revision,
                               generation_reference, origin, actor, payload, structured_diff, field_ownership, NOW()
                        FROM layer3_expansion_revisions WHERE id = %s
                        """,
                        (str(uuid.uuid4()), pending["id"]),
                    )

        for project_id in (clone.id, imported.id):
            restarted.purge_project(project_id, confirmation_token=f"PURGE-{project_id[:8]}")
            self.assertEqual(
                restarted._fetchone("SELECT COUNT(*) AS count FROM layer3_expansion_revisions WHERE project_id = %s", (project_id,))["count"],
                0,
            )
            self.assertEqual(
                restarted._fetchone("SELECT COUNT(*) AS count FROM layer3_expansion_heads WHERE project_id = %s", (project_id,))["count"],
                0,
            )
            self.assertEqual(
                restarted._fetchone("SELECT COUNT(*) AS count FROM layer3_revision_actions WHERE project_id = %s", (project_id,))["count"],
                0,
            )

        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with psycopg.connect(POSTGRES_TARGET_URL) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO layer3_expansion_revisions (
                            id, logical_expansion_id, project_id, revision_number,
                            source_layer2_feature_revision, source_brief_revision, source_pillar_revision,
                            generation_reference, origin, actor, payload, structured_diff, field_ownership, created_at
                        ) VALUES (%s, %s, %s, 999, '', '', '', '', 'test', 'test', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, NOW())
                        """,
                        (str(uuid.uuid4()), str(uuid.uuid4()), expansion.project_id),
                    )

    def test_zz_postgresql_critic_authority_validation_matrix(self) -> None:
        """Validate the v3 upgrade, dedupe, lifecycle, concurrency, rollback, and orphan contract."""
        db = Database(POSTGRES_TARGET_URL, postgres_admin_url=POSTGRES_ADMIN_URL)
        with db.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS critic_findings, artifact_authority_actions CASCADE")
                cursor.execute("DELETE FROM schema_migrations WHERE version = 4")
        self.assertEqual(apply_migrations(db), [4])
        self.assertEqual(migration_status(db)["current_version"], 11)

        project = db.create_project("Critic authority PG", "Protect decisions")
        pillar = db.create_node(
            project_id=project.id, parent_id=None, layer=1, node_type="pillar",
            title="Authority", description="Human-owned", status="kept",
        )
        db.record_human_artifact_action(
            project_id=project.id, artifact_type="layer1_pillar", artifact_id=pillar.id,
            action_type="keep", actor="user", origin="postgres-test",
        )
        finding_kwargs = dict(
            project_id=project.id, artifact_type="layer1_pillar", artifact_id=pillar.id,
            critic_type="coverage", category="gap", severity="medium", explanation="Possible gap",
            evidence={"references": [pillar.id]}, recommended_action="Review",
            source_payload={"pillar": pillar.id, "revision": 1}, model_reference="call-1", job_reference="job-1",
        )
        failures: list[Exception] = []
        ids: list[str] = []

        def persist_identical() -> None:
            """Submit the same finding on an independent PostgreSQL connection."""
            try:
                ids.append(db.create_critic_finding(**finding_kwargs)["id"])
            except Exception as exc:  # noqa: BLE001 - the assertion reports every concurrency failure.
                failures.append(exc)

        threads = [threading.Thread(target=persist_identical) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], failures)
        self.assertEqual(1, len(set(ids)))
        self.assertEqual(1, db._fetchone("SELECT COUNT(*) AS count FROM critic_findings WHERE project_id = %s", (project.id,))["count"])

        other = db.create_project("Other critic project", "Ownership")
        with self.assertRaises(ValueError):
            db.create_critic_finding(**{**finding_kwargs, "project_id": other.id, "source_payload": {"revision": 2}})
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with psycopg.connect(POSTGRES_TARGET_URL) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO critic_findings (id, project_id, artifact_type, artifact_id, artifact_revision_id, critic_type, policy_version, category, severity, explanation, evidence, recommended_action, source_fingerprint, model_reference, job_reference, status, created_at, updated_at, resolution_action, resolution_note, resolved_by) VALUES (%s, %s, 'layer1_pillar', %s, '', 'test', 'v1', 'test', 'low', 'x', '{}'::jsonb, 'review', 'hash', '', '', 'open', NOW(), NOW(), '', '', '')",
                        (str(uuid.uuid4()), str(uuid.uuid4()), pillar.id),
                    )

        finding = db.list_critic_findings(project.id)[0]
        with psycopg.connect(POSTGRES_TARGET_URL, autocommit=True) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE OR REPLACE FUNCTION fail_critic_authority_insert() RETURNS trigger AS $$
                    BEGIN RAISE EXCEPTION 'injected authority failure'; END;
                    $$ LANGUAGE plpgsql
                    """
                )
                cursor.execute("CREATE TRIGGER injected_critic_failure BEFORE INSERT ON artifact_authority_actions FOR EACH ROW EXECUTE FUNCTION fail_critic_authority_insert()")
        with self.assertRaises(psycopg.errors.RaiseException):
            db.resolve_critic_finding(finding["id"], action="accepted", note="test rollback", resolved_by="user")
        with psycopg.connect(POSTGRES_TARGET_URL, autocommit=True) as conn:
            with conn.cursor() as cursor:
                cursor.execute("DROP TRIGGER injected_critic_failure ON artifact_authority_actions")
                cursor.execute("DROP FUNCTION fail_critic_authority_insert()")
        self.assertEqual("open", db.list_critic_findings(project.id)[0]["status"])
        resolved = db.resolve_critic_finding(finding["id"], action="accepted", note="confirmed", resolved_by="user")
        self.assertEqual("accepted", resolved["status"])
        self.assertTrue(db.has_human_artifact_action(project.id, "layer1_pillar", pillar.id))

        clone = db.clone_project(project.id, name="Critic authority clone")
        clone_findings = db.list_critic_findings(clone.id)
        self.assertEqual(1, len(clone_findings))
        self.assertNotEqual(pillar.id, clone_findings[0]["artifact_id"])
        archive = db.export_project_archive(project.id, Path(self.tempdir.name) / "critic-archives")
        imported = db.import_project_archive(archive)["project"]
        self.assertEqual(1, len(db.list_critic_findings(imported.id)))
        db.archive_project(project.id)
        self.assertEqual(1, len(db.list_critic_findings(project.id)))
        db.unarchive_project(project.id)

        orphan_project = db.create_project("Orphan cleanup", "Delete an artifact")
        orphan_pillar = db.create_node(
            project_id=orphan_project.id, parent_id=None, layer=1, node_type="pillar",
            title="Disposable", description="Delete me", status="kept",
        )
        db.create_critic_finding(**{**finding_kwargs, "project_id": orphan_project.id, "artifact_id": orphan_pillar.id, "source_payload": {"orphan": 1}})
        db._execute("DELETE FROM nodes WHERE id = %s", (orphan_pillar.id,))
        self.assertEqual([], db.list_critic_findings(orphan_project.id))

        for target in (clone, imported, orphan_project, project, other):
            db.purge_project(target.id, confirmation_token=f"PURGE-{target.id[:8]}")
            self.assertEqual(0, db._fetchone("SELECT COUNT(*) AS count FROM critic_findings WHERE project_id = %s", (target.id,))["count"])

    def test_zzz_postgresql_v4_to_v5_command_migration(self) -> None:
        """Upgrade a live v4-shaped database to the command ledger without rebuilding it."""
        db = Database(POSTGRES_TARGET_URL, postgres_admin_url=POSTGRES_ADMIN_URL)
        with db.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS command_executions CASCADE")
                cursor.execute("DELETE FROM schema_migrations WHERE version = 5")
        self.assertEqual(apply_migrations(db), [5])
        self.assertEqual(migration_status(db)["current_version"], 11)
        self.assertIn("command_executions", db._table_names())

    def test_zzzz_postgresql_command_concurrency_rollback_idempotency_and_lifecycle(self) -> None:
        """Prove the command contract on real PostgreSQL connections and row locks."""
        services = _build_services(AppConfig(
            database_backend="postgres", database_url=POSTGRES_TARGET_URL,
            postgres_admin_url=POSTGRES_ADMIN_URL, embeddings_enabled=False,
            db_path=Path(self.tempdir.name) / "no-legacy.db",
        ))
        actor = CommandActor.human_ui("postgres-reviewer")
        project = services.db.create_project("Command PG", "Concurrency")
        services.brief_service.ensure_brief(project.id)
        services.brief_service.publish(project.id)
        pillar_result = services.command_service.handle(CreatePillar(project_id=project.id, actor=actor, title="PG pillar"))
        feature_result = services.command_service.handle(CreateFeature(
            project_id=project.id, actor=actor, canonical_name="PG feature",
            description="Concurrent feature", owner_pillar_id=pillar_result.target_id,
        ))
        feature = services.db.get_layer2_feature(feature_result.target_id)
        token = services.command_service.feature_state_token(feature)
        outcomes: list[str] = []

        def edit(description: str) -> None:
            """Race one edit with the same expected revision on an independent thread connection."""
            try:
                services.command_service.handle(EditFeature(
                    project_id=project.id, actor=actor, expected_state_token=token,
                    feature_id=feature.id, updates={"description": description},
                ))
                outcomes.append("success")
            except CommandConflictError:
                outcomes.append("conflict")

        threads = [threading.Thread(target=edit, args=(value,)) for value in ("first", "second")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["success", "conflict"])

        current = services.db.get_layer2_feature(feature.id)
        current_token = services.command_service.feature_state_token(current)

        def fail(step: str) -> None:
            """Inject failure after the authoritative write but before command commit."""
            if step == "after_canonical_write":
                raise RuntimeError("postgres rollback")

        services.command_service.failure_injector = fail
        with self.assertRaises(RuntimeError):
            services.command_service.handle(KeepFeature(
                project_id=project.id, actor=actor, idempotency_key="pg-rollback",
                expected_state_token=current_token, feature_id=feature.id,
            ))
        services.command_service.failure_injector = None
        self.assertEqual(services.db.get_layer2_feature(feature.id).status, current.status)
        self.assertIsNone(services.db._fetchone("SELECT * FROM command_executions WHERE idempotency_key = %s", ("pg-rollback",)))

        retry = KeepFeature(project_id=project.id, actor=actor, idempotency_key="pg-idempotent", expected_state_token=current_token, feature_id=feature.id)
        first = services.command_service.handle(retry)
        second = services.command_service.handle(retry)
        self.assertFalse(first.idempotent)
        self.assertTrue(second.idempotent)
        latest_project = services.db.get_project(project.id)
        archived = services.command_service.handle(ArchiveProject(project_id=project.id, actor=actor, expected_state_token=services.command_service.project_state_token(latest_project)))
        unarchived = services.command_service.handle(UnarchiveProject(project_id=project.id, actor=actor, expected_state_token=archived.state_token))
        self.assertEqual(unarchived.data["project"]["lifecycle_state"], "active")
        services.db.purge_project(project.id, confirmation_token=f"PURGE-{project.id[:8]}")

    def test_zzzzz_postgresql_v5_to_v6_dependency_revision_matrix(self) -> None:
        """Validate live v5 upgrade, constraints, and publication rollback."""
        db = Database(POSTGRES_TARGET_URL, postgres_admin_url=POSTGRES_ADMIN_URL)
        legacy = db.create_project("Legacy v5 brief", "Backfill immutable publication")
        db.upsert_project_brief(
            project_id=legacy.id, product_idea=legacy.idea, known_competitors=[],
            constraints="", status="published",
        )
        legacy_pillar = db.create_node(
            project_id=legacy.id, parent_id=None, layer=1, node_type="pillar",
            title="Legacy pillar", description="Before v6", status="kept",
        )
        with db.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS artifact_stale_transitions, artifact_dependencies, artifact_freshness_states, brief_revisions, brief_heads CASCADE")
                cursor.execute("DELETE FROM schema_migrations WHERE version = 6")
        self.assertEqual(apply_migrations(db), [6])
        self.assertEqual(migration_status(db)["current_version"], 11)
        head = db.get_brief_head(legacy.id)
        self.assertTrue(head["current_published_revision_id"])
        self.assertEqual(db.lineage_counts(legacy.id), {"exact": 0, "inferred": 1, "unknown": 0})
        published_id = str(head["current_published_revision_id"])
        with self.assertRaises(psycopg.errors.RaiseException):
            with psycopg.connect(POSTGRES_TARGET_URL) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("UPDATE brief_revisions SET payload = '{}'::jsonb WHERE id = %s", (published_id,))
        other = db.create_project("Dependency ownership", "Reject cross project")
        db.upsert_project_brief(project_id=other.id, product_idea=other.idea, known_competitors=[], constraints="", status="published")
        db.ensure_brief_revision_head(other.id)
        with self.assertRaises(psycopg.errors.RaiseException):
            with psycopg.connect(POSTGRES_TARGET_URL) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO artifact_dependencies (id, project_id, dependent_artifact_type, dependent_artifact_id, dependent_revision_id, source_artifact_type, source_artifact_id, source_revision_id, dependency_kind, lineage_quality, created_at) VALUES (%s, %s, 'layer1_pillar', %s, %s, 'brief', %s, %s, 'content', 'exact', NOW())",
                        (str(uuid.uuid4()), other.id, legacy_pillar.id, pillar_revision_token(legacy_pillar), head["id"], published_id),
                    )
        services = _build_services(AppConfig(
            database_backend="postgres", database_url=POSTGRES_TARGET_URL,
            postgres_admin_url=POSTGRES_ADMIN_URL, embeddings_enabled=False,
            db_path=Path(self.tempdir.name) / "no-legacy-v6.db",
        ))
        actor = CommandActor.human_ui("v6-reviewer")
        project = services.db.create_project("Publication rollback", "Atomic v6")
        brief = services.brief_service.ensure_brief(project.id)
        services.command_service.handle(PublishBrief(
            project_id=project.id, actor=actor,
            expected_state_token=services.command_service.brief_state_token(brief), request_research=False,
        ))
        pillar_result = services.command_service.handle(CreatePillar(
            project_id=project.id, actor=actor, title="Atomic pillar",
        ))
        pillar = services.db.get_node(pillar_result.target_id)
        current = services.brief_service.ensure_brief(project.id)
        services.command_service.handle(UpdateBriefDraft(
            project_id=project.id, actor=actor,
            expected_state_token=services.command_service.brief_state_token(current),
            updates={"problem": "Changed"},
        ))
        before = services.brief_service.ensure_brief(project.id)
        old_published = before.current_published_revision_id
        services.command_service.failure_injector = lambda step: (_ for _ in ()).throw(RuntimeError("injected")) if step == "after_canonical_write" else None
        with self.assertRaises(RuntimeError):
            services.command_service.handle(PublishBrief(
                project_id=project.id, actor=actor,
                expected_state_token=services.command_service.brief_state_token(before), request_research=False,
            ))
        services.command_service.failure_injector = None
        self.assertEqual(services.brief_service.ensure_brief(project.id).current_published_revision_id, old_published)
        self.assertEqual(services.db.freshness_for_artifact(project.id, "layer1_pillar", pillar.id, pillar_revision_token(pillar))["freshness_state"], "current")
        for target in (project, other, legacy):
            services.db.purge_project(target.id, confirmation_token=f"PURGE-{target.id[:8]}")
