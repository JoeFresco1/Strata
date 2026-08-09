from __future__ import annotations

import os
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg import sql

from strata.api_support import _build_services
from strata.command_types import (
    CommandActor, CommandConflictError, CompileSpecificationManifest, CreateFeature, CreatePillar,
    EditFeature, PublishBrief, RenderSpecificationManifest,
)
from strata.config import AppConfig
from strata.dependency_db import feature_revision_token, pillar_revision_token
from strata.migrations import MIGRATIONS, apply_migrations, migration_status


POSTGRES_TARGET_URL = os.getenv("STRATA_POSTGRES_TEST_DATABASE_URL", "")
POSTGRES_ADMIN_URL = os.getenv("STRATA_POSTGRES_TEST_ADMIN_URL", "")


@unittest.skipUnless(POSTGRES_TARGET_URL and POSTGRES_ADMIN_URL, "Set disposable PostgreSQL integration URLs to run")
class SpecificationPostgresTests(unittest.TestCase):
    """Validate migration v7 and compiler invariants on PostgreSQL 18."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.database_name = urlparse(POSTGRES_TARGET_URL).path.lstrip("/")
        if not cls.database_name.startswith("strata_l3_revision_test_"):
            raise RuntimeError("PostgreSQL integration database must use the strata_l3_revision_test_ prefix")
        with psycopg.connect(POSTGRES_ADMIN_URL, autocommit=True) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(cls.database_name)))
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cls.database_name)))
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.config = AppConfig(
            database_backend="postgres", database_url=POSTGRES_TARGET_URL,
            postgres_admin_url=POSTGRES_ADMIN_URL, embeddings_enabled=False,
            db_path=Path(cls.tempdir.name) / "unused.db", exports_dir=Path(cls.tempdir.name) / "exports",
        )
        cls.services = _build_services(cls.config)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()
        with psycopg.connect(POSTGRES_ADMIN_URL, autocommit=True) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(cls.database_name)))

    def setUp(self) -> None:
        self.db = self.services.db
        self.actor = CommandActor.human_ui("postgres-manifest-reviewer")
        self.project = self.db.create_project(f"Manifest {uuid.uuid4().hex[:8]}", "PostgreSQL canonical specification")
        brief = self.services.brief_service.ensure_brief(self.project.id)
        self.services.command_service.handle(PublishBrief(
            project_id=self.project.id, actor=self.actor,
            expected_state_token=self.services.command_service.brief_state_token(brief), request_research=False,
        ))

    def tearDown(self) -> None:
        try:
            self.db.purge_project(self.project.id, confirmation_token=f"PURGE-{self.project.id[:8]}")
        except ValueError:
            pass

    def _seed(self):
        pillar_id = self.services.command_service.handle(CreatePillar(
            project_id=self.project.id, actor=self.actor, title="Postgres pillar", description="Reviewed pillar",
        )).target_id
        pillar = self.db.get_node(pillar_id)
        feature_id = self.services.command_service.handle(CreateFeature(
            project_id=self.project.id, actor=self.actor, canonical_name="Postgres feature",
            description="Reviewed feature", owner_pillar_id=pillar.id, status="approved",
        )).target_id
        feature = self.db.get_layer2_feature(feature_id)
        brief = self.services.brief_service.ensure_brief(self.project.id)
        expansion = self.db.upsert_layer3_expansion(
            project_id=self.project.id, feature_id=feature.id, parent_pillar_id=pillar.id,
            parent_pillar_title=pillar.title, feature_name=feature.canonical_name,
            feature_description=feature.description, feature_intent="Reviewed intent",
            expansion_groups=[], overlap_review=[], open_questions=[], review_state="approved",
            provenance={
                "source_brief_revision": brief.current_published_revision_id,
                "source_pillar_revision": pillar_revision_token(pillar),
                "source_layer2_feature_revision": feature_revision_token(feature),
            },
        )
        self.db.set_artifact_freshness(
            project_id=self.project.id, artifact_type="layer3_revision", artifact_id=expansion.id,
            artifact_revision_id=expansion.active_revision_id, freshness_state="current", lineage_quality="exact",
        )
        for source_type, source_id, revision in (
            ("brief", brief.id, str(brief.current_published_revision_id)),
            ("layer1_pillar", pillar.id, pillar_revision_token(pillar)),
            ("layer2_feature", feature.id, feature_revision_token(feature)),
        ):
            self.db.add_artifact_dependency(
                project_id=self.project.id, dependent_artifact_type="layer3_revision",
                dependent_artifact_id=expansion.id, dependent_revision_id=expansion.active_revision_id,
                source_artifact_type=source_type, source_artifact_id=source_id,
                source_revision_id=revision, lineage_quality="exact",
            )
        return pillar, feature

    def _compile(self, *, request_id: str | None = None):
        return self.services.command_service.handle(CompileSpecificationManifest(
            project_id=self.project.id, actor=self.actor, mode="approved",
            expected_state_token=self.services.command_service.specification_source_state_token(self.project.id),
            idempotency_key=request_id or str(uuid.uuid4()),
        ))

    def test_00_v6_to_v7_migration_is_idempotent(self) -> None:
        with self.db.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS specification_rendered_artifacts, specification_manifest_issues, specification_manifest_memberships, specification_manifests CASCADE")
                cursor.execute("DELETE FROM schema_migrations WHERE version = 7")
        self.assertEqual(apply_migrations(self.db), [7])
        self.assertEqual(apply_migrations(self.db), [])
        self.assertEqual(
            migration_status(self.db)["current_version"],
            max(migration.version for migration in MIGRATIONS),
        )

    def test_jsonb_constraints_ownership_uniqueness_and_immutability(self) -> None:
        self._seed()
        manifest = self._compile().data["manifest"]
        self.assertEqual(self.db._fetchone("SELECT pg_typeof(payload)::text AS kind FROM specification_manifests WHERE id = %s", (manifest["manifest_id"],))["kind"], "jsonb")
        with self.assertRaises(psycopg.errors.RaiseException):
            self.db._execute("UPDATE specification_manifests SET status = 'invalid' WHERE id = %s", (manifest["manifest_id"],))
        membership = self.db._fetchone("SELECT * FROM specification_manifest_memberships WHERE manifest_id = %s ORDER BY layer LIMIT 1", (manifest["manifest_id"],))
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.db._execute(
                "INSERT INTO specification_manifest_memberships (id, manifest_id, project_id, layer, artifact_type, logical_artifact_id, artifact_revision, content_token, inclusion_reason, ordinal, dependency_metadata, authority_metadata, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,NOW())",
                (str(uuid.uuid4()), manifest["manifest_id"], self.project.id, membership["layer"], membership["artifact_type"], membership["logical_artifact_id"], membership["artifact_revision"], membership["content_token"], membership["inclusion_reason"], membership["ordinal"], "{}", "{}"),
            )
        other = self.db.create_project("Other owner", "Ownership")
        try:
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                self.db._execute(
                    "INSERT INTO specification_manifest_issues (id, manifest_id, project_id, ordinal, issue_code, stage, severity, message, artifact_type, artifact_id, artifact_revision, details, created_at) VALUES (%s,%s,%s,999,'TEST','policy','warning','bad owner','','','','{}'::jsonb,NOW())",
                    (str(uuid.uuid4()), manifest["manifest_id"], other.id),
                )
        finally:
            self.db.purge_project(other.id, confirmation_token=f"PURGE-{other.id[:8]}")

    def test_idempotency_and_all_failure_stages_leave_no_partial_rows(self) -> None:
        self._seed()
        request_id = str(uuid.uuid4())
        first = self._compile(request_id=request_id)
        second = self._compile(request_id=request_id)
        self.assertTrue(second.idempotent)
        self.assertEqual(first.target_id, second.target_id)
        baseline = len(self.db.list_specification_manifests(self.project.id))
        for target in ("after_command_started", "after_canonical_write", "after_audit_write"):
            self.services.command_service.failure_injector = lambda step, expected=target: (_ for _ in ()).throw(RuntimeError("injected")) if step == expected else None
            with self.assertRaises(RuntimeError):
                self._compile()
            self.assertEqual(len(self.db.list_specification_manifests(self.project.id)), baseline)
        self.services.command_service.failure_injector = None

    def test_project_lock_prevents_mixed_snapshot_during_concurrent_edit(self) -> None:
        _, feature = self._seed()
        original_description = feature.description
        source_token = self.services.command_service.specification_source_state_token(self.project.id)
        entered = threading.Event()
        release = threading.Event()
        results: dict[str, object] = {}

        def pause(step: str) -> None:
            if step == "after_command_started":
                entered.set()
                release.wait(10)

        self.services.command_service.failure_injector = pause
        other = _build_services(self.config)

        def compile_manifest() -> None:
            results["compile"] = self.services.command_service.handle(CompileSpecificationManifest(
                project_id=self.project.id, actor=self.actor, mode="approved", expected_state_token=source_token,
                idempotency_key=str(uuid.uuid4()),
            ))

        def edit_feature() -> None:
            results["edit"] = other.command_service.handle(EditFeature(
                project_id=self.project.id, actor=self.actor, feature_id=feature.id,
                expected_state_token=other.command_service.feature_state_token(other.db.get_layer2_feature(feature.id)),
                updates={"description": "Concurrent edit"},
            ))

        compile_thread = threading.Thread(target=compile_manifest)
        edit_thread = threading.Thread(target=edit_feature)
        compile_thread.start()
        self.assertTrue(entered.wait(10))
        edit_thread.start()
        release.set()
        compile_thread.join(20)
        edit_thread.join(20)
        self.services.command_service.failure_injector = None
        self.assertFalse(compile_thread.is_alive())
        self.assertFalse(edit_thread.is_alive())
        manifest = results["compile"].data["manifest"]
        self.assertEqual(manifest["layer2"][0]["canonical_payload"]["description"], original_description)
        self.assertEqual(self.db.get_layer2_feature(feature.id).description, "Concurrent edit")

    def test_archive_clone_import_render_and_purge(self) -> None:
        self._seed()
        manifest = self._compile().data["manifest"]
        render = self.services.command_service.handle(RenderSpecificationManifest(
            project_id=self.project.id, actor=self.actor, manifest_id=manifest["manifest_id"],
            expected_state_token=manifest["content_hash"], idempotency_key=str(uuid.uuid4()),
        ))
        clone = self.db.clone_project(self.project.id)
        self.assertEqual(self.db.list_specification_manifests(clone.id), [])
        archive = self.db.export_project_archive(self.project.id, Path(self.tempdir.name) / "archives")
        imported = self.db.import_project_archive(archive)["project"]
        imported_headers = self.db.list_specification_manifests(imported.id)
        self.assertEqual(len(imported_headers), 1)
        self.assertNotEqual(imported_headers[0]["id"], manifest["manifest_id"])
        paths = [Path(value) for value in render.data["rendered"].values()]
        self.db.purge_project(self.project.id, confirmation_token=f"PURGE-{self.project.id[:8]}", delete_artifacts=True, exports_dir=Path(self.config.exports_dir))
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertEqual(self.db._fetchone("SELECT COUNT(*) AS count FROM specification_manifests WHERE project_id = %s", (self.project.id,))["count"], 0)
        for project in (clone, imported):
            self.db.purge_project(project.id, confirmation_token=f"PURGE-{project.id[:8]}")
