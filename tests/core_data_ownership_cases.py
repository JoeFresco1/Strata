from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from strata.backup import backup_metadata, metadata_path_for, verify_backup
from strata.db import Database


class DataOwnershipTests(unittest.TestCase):
    def test_data_ownership_settings_default_to_keep_and_normalize_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Ownership", "Keep by default")

            self.assertEqual(db.get_data_ownership_settings(project.id)["telemetry_retention_days"], None)

            settings = db.upsert_data_ownership_settings(
                project.id,
                {
                    "telemetry_retention_days": 30,
                    "telemetry_body_retention_days": None,
                    "research_retention_days": 45,
                    "assistant_retention_days": 60,
                    "exports_retention_days": 7,
                },
            )

            self.assertEqual(settings["telemetry_retention_days"], 30)
            self.assertIsNone(settings["telemetry_body_retention_days"])
            self.assertEqual(db.get_data_ownership_settings(project.id)["exports_retention_days"], 7)

    def test_project_cleanup_redacts_telemetry_and_removes_old_project_data_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            exports_dir = Path(tmpdir) / "exports"
            exports_dir.mkdir()
            project = db.create_project("Cleanup", "Retention")
            other = db.create_project("Other", "Untouched")
            db.record_model_call({
                "project_id": project.id,
                "layer": "assistant",
                "workflow": "chat",
                "system_prompt": "private",
                "user_prompt": "private",
                "raw_response": "private",
                "parsed_result": {"private": True},
            })
            db.record_model_call({"project_id": other.id, "layer": "assistant", "workflow": "chat", "system_prompt": "other"})
            old = "2000-01-01T00:00:00+00:00"
            db._execute(f"UPDATE model_call_events SET completed_at = {db.param}, started_at = {db.param} WHERE project_id = {db.param}", (old, old, project.id))

            source = db.insert_research_source(
                project_id=project.id,
                scope="layer0",
                scope_id=None,
                competitor_name="Alpha",
                domain="example.com",
                url="https://example.com",
                page_type="home",
                title="Alpha",
                status_code=200,
                content_hash="hash",
            )
            db.insert_research_chunk(
                project_id=project.id,
                scope="layer0",
                scope_id=None,
                source_id=source.id,
                competitor_name="Alpha",
                domain="example.com",
                url="https://example.com",
                title="Alpha",
                chunk_index=0,
                text="Evidence",
                embedding_model="test",
                embedding=[0.1] * 384,
            )
            db.insert_research_finding(
                project_id=project.id,
                scope="layer0",
                scope_id=None,
                finding_type="market",
                title="Finding",
                summary="Summary",
            )
            for table, column in (("research_sources", "fetched_at"), ("research_chunks", "created_at"), ("research_findings", "updated_at")):
                db._execute(f"UPDATE {table} SET {column} = {db.param} WHERE project_id = {db.param}", (old, project.id))

            conversation = db.create_assistant_conversation(project.id, "Old", "overall")
            message = db.create_assistant_message(
                conversation_id=conversation.id,
                project_id=project.id,
                role="user",
                content="Question",
                request_id="req-1",
                active_scope="overall",
                focus={},
            )
            db._execute(f"UPDATE assistant_conversations SET updated_at = {db.param} WHERE id = {db.param}", (old, conversation.id))
            db._execute(f"UPDATE assistant_messages SET updated_at = {db.param} WHERE id = {db.param}", (old, message.id))
            artifact = exports_dir / f"{project.id}-diagnostics.json"
            artifact.write_text("{}", encoding="utf-8")
            os.utime(artifact, (946684800, 946684800))
            other_artifact = exports_dir / f"{other.id}-diagnostics.json"
            other_artifact.write_text("{}", encoding="utf-8")
            os.utime(other_artifact, (946684800, 946684800))

            self.assertEqual(db.cleanup_project_telemetry(project.id, body_retention_days=1)["redacted_rows"], 1)
            self.assertIsNone(db.list_model_calls(project.id, limit=1)[0]["system_prompt"])
            self.assertEqual(db.cleanup_project_research(project.id, retention_days=1)["research_sources"], 1)
            self.assertEqual(db.cleanup_project_assistant_history(project.id, retention_days=1)["assistant_messages"], 1)
            self.assertEqual(len(db.cleanup_project_exports(project.id, exports_dir=exports_dir, retention_days=1)["deleted_artifacts"]), 1)
            self.assertFalse(artifact.exists())
            self.assertTrue(other_artifact.exists())
            self.assertEqual(len(db.list_model_calls(other.id, limit=10)), 1)

    def test_assistant_cleanup_keeps_conversation_with_retained_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Assistant retention", "Keep live turns")
            conversation = db.create_assistant_conversation(project.id, "Mixed age", "overall")
            message = db.create_assistant_message(
                conversation_id=conversation.id,
                project_id=project.id,
                role="user",
                content="Still relevant",
                request_id="retained",
                active_scope="overall",
                focus={},
            )
            old = "2000-01-01T00:00:00+00:00"
            db._execute(f"UPDATE assistant_conversations SET updated_at = {db.param} WHERE id = {db.param}", (old, conversation.id))

            result = db.cleanup_project_assistant_history(project.id, retention_days=1)

            self.assertEqual(result["assistant_messages"], 0)
            self.assertEqual(result["assistant_conversations"], 0)
            self.assertEqual(db.get_assistant_message(message.id).content, "Still relevant")
            self.assertEqual(db.get_assistant_conversation(conversation.id).id, conversation.id)

    def test_project_purge_dry_run_reports_counts_and_confirmation_guards_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            exports_dir = Path(tmpdir) / "exports"
            exports_dir.mkdir()
            project = db.create_project("Purge Me", "Remove all rows")
            db.upsert_project_brief(project_id=project.id, product_idea=project.idea, known_competitors=[], constraints="")
            db.create_platform_job(project_id=project.id, kind="diagnostics", workflow="diagnostics_export", scope="project")
            artifact = exports_dir / f"{project.id}-project-archive.zip"
            artifact.write_text("zip", encoding="utf-8")

            preview = db.purge_project(project.id, dry_run=True, exports_dir=exports_dir)
            self.assertEqual(preview["table_counts"]["project_briefs"], 1)
            self.assertEqual(preview["table_counts"]["platform_jobs"], 1)
            self.assertEqual(preview["matching_artifacts"], [str(artifact)])
            self.assertIsNotNone(db.get_project(project.id))

            with self.assertRaises(ValueError):
                db.purge_project(project.id, confirmation_token="PURGE-wrong")

            result = db.purge_project(
                project.id,
                confirmation_token=f"PURGE-{project.id[:8]}",
                delete_artifacts=True,
                exports_dir=exports_dir,
            )
            self.assertEqual(result["deleted_artifacts"], [str(artifact)])
            self.assertFalse(artifact.exists())
            platform_jobs = db._fetchone(f"SELECT COUNT(*) AS count FROM platform_jobs WHERE project_id = {db.param}", (project.id,))
            self.assertEqual(int(platform_jobs["count"]), 0)
            with self.assertRaises(ValueError):
                db.get_project(project.id)

    def test_backup_metadata_and_verify_backup_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "strata-test.backup"
            backup_path.write_bytes(b"backup")
            metadata = backup_metadata(
                backup_path=backup_path,
                compose_project="strata",
                postgres_service="postgres",
                database="strata",
                user="strata",
            )
            metadata_path_for(backup_path).write_text(json.dumps(metadata), encoding="utf-8")

            result = verify_backup(type("Args", (), {"backup": str(backup_path)})())

            self.assertTrue(result["ok"])
            self.assertTrue(result["checks"]["metadata_matches_backup"])
