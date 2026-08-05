from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from fastapi.testclient import TestClient
from pydantic import ValidationError

from strata.config import AppConfig, ModelProfile, build_model_profiles, resolve_default_model_profile, resolve_reasoning_settings
from strata.api import _valid_layer2_status, create_app
from strata.assistant_index import AssistantIndexService
from strata.assistant_service import AssistantService
from strata.api_models import Layer2FeatureCreateRequest, Layer2FeatureEvidenceRequest
from strata.db import Database
from strata.command_types import state_token
from strata.diagnostics import Redactor, diagnostics_content_hash
from strata.embeddings import EmbeddingService
from strata.export import export_layer2_markdown, export_layer3_feature_expansions
from strata.generation import LAYER2_EXHAUSTION_FAMILIES, LAYER2_LENSES, LAYER2_SURVEY_BUILDER_FAMILIES, GenerationService
from strata.llm import LLMError, LlamaCppClient
from strata.overlap_critic import OverlapCriticRunner, OverlapItem, split_oversized_clusters, top_k_for_context
from strata.layer2_research import Layer2CompetitorSeed, Layer2ResearchMixin
from strata.layer3_service import validate_product_level_content
from strata.models import (
    FeatureExpansionGroup,
    FeatureExpansionOption,
    FeatureExpansionResponse,
    Layer2Candidate,
    Layer2CandidateResponse,
    Layer2CoverageAssessmentResponse,
    Layer2CoverageFamilyAssessment,
    Node,
    PillarAssessment,
    ProjectMemory,
    SimilarityMatch,
)
from strata.migrations import apply_migrations, migration_status
from strata.project_settings import default_project_model_settings, normalize_model_settings
from strata.project_settings import assignment_domain, default_routing_policy
from strata.prompts import (
    build_pillar_prompt,
    build_pillar_research_assessment_prompt,
    build_system_prompt,
    load_prompt_catalog,
    render_prompt,
)
from strata.brief import BriefService
from strata.research import ResearchService
from strata.research import ExtractedPage
from requests.exceptions import SSLError


class DatabaseTests(unittest.TestCase):
    def test_overlap_top_k_scales_with_context_window(self) -> None:
        self.assertLess(top_k_for_context(4096), top_k_for_context(32768))

    def test_overlap_cluster_split_caps_groups_at_eight(self) -> None:
        member_ids = [f"item-{index}" for index in range(11)]
        edge_scores = {
            tuple(sorted((left, right))): 0.9
            for left in member_ids
            for right in member_ids
            if left < right
        }
        groups = split_oversized_clusters(member_ids, edge_scores, max_size=8)
        self.assertTrue(groups)
        self.assertTrue(all(len(group) <= 8 for group in groups))

    def test_overlap_shortlist_excludes_cut_and_merged_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Overlap", "Find duplicates")
            active = db.create_node(project_id=project.id, parent_id=None, layer=1, node_type="pillar", title="Survey Builder", description="Create surveys", status="kept")
            near = db.create_node(project_id=project.id, parent_id=None, layer=1, node_type="pillar", title="Survey Creation", description="Build surveys", status="generated")
            db.create_node(project_id=project.id, parent_id=None, layer=1, node_type="pillar", title="Deleted Builder", description="Create surveys", status="cut")
            db.create_node(project_id=project.id, parent_id=None, layer=1, node_type="pillar", title="Merged Builder", description="Create surveys", status="merged")
            service = type("Services", (), {"db": db})()
            runner = OverlapCriticRunner(service)

            items = runner._active_items(project.id, "layer1")
            self.assertEqual({item.id for item in items}, {active.id, near.id})
            shortlist = runner._lexical_shortlist(items, top_k=4, sim_threshold=0.2)
            self.assertEqual(shortlist[active.id][0].item.id, near.id)

    def test_overlap_snapshot_uses_latest_completed_and_hides_stale_verdicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Overlap", "Find duplicates")
            left = db.create_node(project_id=project.id, parent_id=None, layer=1, node_type="pillar", title="Survey Builder", description="Create surveys", status="kept")
            right = db.create_node(project_id=project.id, parent_id=None, layer=1, node_type="pillar", title="Survey Creation", description="Build surveys", status="generated")
            first_job = db.create_platform_job(project_id=project.id, kind="critic", workflow="layer1_overlap_critic", scope="layer1")
            db.update_platform_job(first_job.id, status="completed", completed_at="2026-01-01T00:00:00+00:00")
            second_job = db.create_platform_job(project_id=project.id, kind="critic", workflow="layer1_overlap_critic", scope="layer1", dedupe_key="second")
            db.update_platform_job(second_job.id, status="completed", completed_at="2026-01-02T00:00:00+00:00")
            hashes = db.current_overlap_item_hashes(project.id, "layer1")
            db.insert_overlap_verdict(
                project_id=project.id,
                job_id=first_job.id,
                layer="layer1",
                target_id=left.id,
                neighbor_id=right.id,
                relation="merge",
                confidence=0.9,
                rationale="Old job",
                critic_source="overlap_critic",
                target_hash=hashes[left.id],
                neighbor_hash=hashes[right.id],
            )
            db.insert_overlap_verdict(
                project_id=project.id,
                job_id=second_job.id,
                layer="layer1",
                target_id=left.id,
                neighbor_id=right.id,
                relation="merge",
                confidence=0.9,
                rationale="Latest job",
                critic_source="overlap_critic",
                target_hash=hashes[left.id],
                neighbor_hash=hashes[right.id],
            )
            snapshot = db.overlap_snapshot(project.id)
            self.assertEqual(snapshot["layer1"]["latest_completed_job_id"], second_job.id)
            self.assertEqual(snapshot["layer1"]["verdicts"][0]["rationale"], "Latest job")

            db.update_node(right.id, title="Completely different")
            self.assertEqual(db.overlap_snapshot(project.id)["layer1"]["verdicts"], [])

    def test_overlap_resolution_state_tracks_active_and_stale_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Overlap", "Find duplicates")
            left = db.create_node(project_id=project.id, parent_id=None, layer=1, node_type="pillar", title="Survey Builder", description="Create surveys", status="kept")
            right = db.create_node(project_id=project.id, parent_id=None, layer=1, node_type="pillar", title="Survey Creation", description="Build surveys", status="generated")
            first_job = db.create_platform_job(project_id=project.id, kind="critic", workflow="layer1_overlap_critic", scope="layer1")
            db.update_platform_job(first_job.id, status="completed", completed_at="2026-01-01T00:00:00+00:00")
            hashes = db.current_overlap_item_hashes(project.id, "layer1")
            verdict = db.insert_overlap_verdict(
                project_id=project.id,
                job_id=first_job.id,
                layer="layer1",
                target_id=left.id,
                neighbor_id=right.id,
                relation="merge",
                confidence=0.9,
                rationale="Same builder",
                critic_source="overlap_critic",
                target_hash=hashes[left.id],
                neighbor_hash=hashes[right.id],
            )
            db.create_overlap_verdict_resolution(
                project_id=project.id,
                verdict_id=verdict.id,
                layer="layer1",
                target_id=left.id,
                neighbor_id=right.id,
                action="keep_separate",
                target_hash=hashes[left.id],
                neighbor_hash=hashes[right.id],
            )
            snapshot = db.overlap_snapshot(project.id)["layer1"]
            self.assertEqual(snapshot["verdicts"][0]["resolution_state"], "resolved")
            self.assertEqual(snapshot["summary"]["resolved"], 1)

            db.update_node(right.id, description="Build surveys and score responses")
            second_job = db.create_platform_job(project_id=project.id, kind="critic", workflow="layer1_overlap_critic", scope="layer1", dedupe_key="fresh")
            db.update_platform_job(second_job.id, status="completed", completed_at="2026-01-02T00:00:00+00:00")
            fresh_hashes = db.current_overlap_item_hashes(project.id, "layer1")
            db.insert_overlap_verdict(
                project_id=project.id,
                job_id=second_job.id,
                layer="layer1",
                target_id=left.id,
                neighbor_id=right.id,
                relation="link",
                confidence=0.7,
                rationale="Still related",
                critic_source="overlap_critic",
                target_hash=fresh_hashes[left.id],
                neighbor_hash=fresh_hashes[right.id],
            )
            fresh_snapshot = db.overlap_snapshot(project.id)["layer1"]
            self.assertEqual(fresh_snapshot["verdicts"][0]["resolution_state"], "stale_resolution")
            self.assertEqual(fresh_snapshot["summary"]["stale_resolution"], 1)

    def test_overlap_runner_skips_pairs_with_active_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Overlap", "Find duplicates")
            left = db.create_node(project_id=project.id, parent_id=None, layer=1, node_type="pillar", title="Survey Builder", description="Create surveys", status="kept")
            right = db.create_node(project_id=project.id, parent_id=None, layer=1, node_type="pillar", title="Survey Creation", description="Build surveys", status="generated")
            job = db.create_platform_job(project_id=project.id, kind="critic", workflow="layer1_overlap_critic", scope="layer1")
            hashes = db.current_overlap_item_hashes(project.id, "layer1")
            verdict = db.insert_overlap_verdict(
                project_id=project.id,
                job_id=job.id,
                layer="layer1",
                target_id=left.id,
                neighbor_id=right.id,
                relation="merge",
                confidence=0.9,
                rationale="Same builder",
                critic_source="overlap_critic",
                target_hash=hashes[left.id],
                neighbor_hash=hashes[right.id],
            )
            db.create_overlap_verdict_resolution(
                project_id=project.id,
                verdict_id=verdict.id,
                layer="layer1",
                target_id=left.id,
                neighbor_id=right.id,
                action="dismiss",
                target_hash=hashes[left.id],
                neighbor_hash=hashes[right.id],
            )
            runner = OverlapCriticRunner(type("Services", (), {"db": db})())
            target = OverlapItem(id=left.id, title=left.title, description=left.description or "", status=left.status)
            neighbor = OverlapItem(id=right.id, title=right.title, description=right.description or "", status=right.status)

            filtered = runner._filter_resolved_neighbors(
                project.id,
                "layer1",
                target,
                [type("NeighborStub", (), {"item": neighbor, "score": 0.9})()],
                db._stable_overlap_hash(target.text),
            )

            self.assertEqual(filtered, [])

    def test_overlap_review_routing_is_visible_not_blended_special_case(self) -> None:
        self.assertEqual(assignment_domain("layer1_overlap_critic"), "review")
        self.assertEqual(assignment_domain("layer2_overlap_critic"), "review")
        self.assertIn("review", default_routing_policy("blended"))

    def test_overlap_api_enqueue_dedupes_active_jobs_and_returns_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "specforge.db"
            config = AppConfig(database_backend="sqlite", db_path=db_path, embeddings_enabled=False)
            with (
                patch("strata.api.AppConfig", return_value=config),
                patch("strata.jobs.PlatformJobService.run_job", return_value=None),
                TestClient(create_app()) as client,
            ):
                created = client.post("/api/projects", json={"name": "Overlap", "idea": "Find duplicates"})
                project_id = created.json()["id"]
                db = Database(db_path)
                db.set_app_setting("setup_completed", "true")
                db.set_app_setting("provider_readiness", json.dumps({"ready": True, "message": "Ready for tests."}))

                first = client.post(f"/api/projects/{project_id}/overlap/layer1")
                second = client.post(f"/api/projects/{project_id}/overlap/layer1")

                self.assertEqual(first.status_code, 200)
                self.assertEqual(second.status_code, 200)
                self.assertEqual(first.json()["job"]["id"], second.json()["job"]["id"])
                self.assertIn("snapshot", first.json())
                self.assertIn("overlap", first.json()["snapshot"])

    def test_overlap_api_resolution_records_layer2_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "specforge.db"
            config = AppConfig(database_backend="sqlite", db_path=db_path, embeddings_enabled=False)
            with (
                patch("strata.api.AppConfig", return_value=config),
                TestClient(create_app()) as client,
            ):
                created = client.post("/api/projects", json={"name": "Overlap", "idea": "Find duplicates"})
                project_id = created.json()["id"]
                db = Database(db_path)
                db.set_app_setting("setup_completed", "true")
                db.set_app_setting("provider_readiness", json.dumps({"ready": True, "message": "Ready for tests."}))
                pillar = db.create_node(project_id=project_id, parent_id=None, layer=1, node_type="pillar", title="Survey", description="Survey workflows", status="kept")
                first = db.create_layer2_feature(
                    project_id=project_id,
                    canonical_name="Survey Builder",
                    description="Create surveys",
                    feature_type="workflow",
                    owner_pillar_id=pillar.id,
                    candidate_source_ids=[],
                    status="kept",
                )
                second = db.create_layer2_feature(
                    project_id=project_id,
                    canonical_name="Survey Designer",
                    description="Design surveys",
                    feature_type="workflow",
                    owner_pillar_id=pillar.id,
                    candidate_source_ids=[],
                    status="kept",
                )
                job = db.create_platform_job(project_id=project_id, kind="critic", workflow="layer2_overlap_critic", scope="layer2")
                db.update_platform_job(job.id, status="completed", completed_at="2026-01-01T00:00:00+00:00")
                hashes = db.current_overlap_item_hashes(project_id, "layer2")
                verdict = db.insert_overlap_verdict(
                    project_id=project_id,
                    job_id=job.id,
                    layer="layer2",
                    target_id=first.id,
                    neighbor_id=second.id,
                    relation="link",
                    confidence=0.8,
                    rationale="Related creation workflows",
                    critic_source="overlap_critic",
                    target_hash=hashes[first.id],
                    neighbor_hash=hashes[second.id],
                )

                response = client.post(
                    f"/api/projects/{project_id}/overlap/layer2/verdicts/{verdict.id}/resolve",
                    json={"action": "link", "expected_state_token": state_token({"target": hashes[first.id], "neighbor": hashes[second.id], "verdict": verdict.id})},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["resolution"]["action"], "link")
                relationships = Database(db_path).list_layer2_relationships(project_id)
                self.assertTrue(any(relationship.relationship_type == "overlaps_with" for relationship in relationships))

    def test_schema_migrations_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            self.assertEqual(apply_migrations(db), [1, 2, 3, 4, 5, 6, 7, 8])
            self.assertEqual(apply_migrations(db), [])
            self.assertEqual(migration_status(db)["current_version"], 8)

    def test_telemetry_aggregates_usage_and_honors_body_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Telemetry", "Track model activity")
            db.record_model_call({
                "project_id": project.id,
                "layer": "layer2",
                "workflow": "feature_generation",
                "provider_kind": "remote",
                "model_name": "test-model",
                "status": "completed",
                "latency_ms": 1250,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "estimated_cost_usd": 0.01,
                "system_prompt": "system",
                "user_prompt": "user",
                "raw_response": '{"ok":true}',
                "parsed_result": {"ok": True},
            })

            summary = db.telemetry_summary(project.id)
            self.assertEqual(summary["totals"]["total_tokens"], 150)
            self.assertEqual(summary["totals"]["remote_calls"], 1)
            self.assertEqual(summary["by_layer"][0]["name"], "layer2")

            db.upsert_telemetry_settings(project.id, {
                "enabled": True,
                "capture_prompt_bodies": False,
                "capture_response_bodies": False,
                "capture_parsed_results": False,
            })
            db.record_model_call({
                "project_id": project.id,
                "layer": "assistant",
                "workflow": "assistant_synthesis",
                "status": "failed",
                "error_type": "timeout",
                "system_prompt": "private",
                "user_prompt": "private",
                "raw_response": "private",
                "parsed_result": {"private": True},
            })
            latest = db.list_model_calls(project.id, limit=1)[0]
            self.assertIsNone(latest["system_prompt"])
            self.assertIsNone(latest["raw_response"])
            self.assertEqual(latest["parsed_result"], {})
            self.assertEqual(db.telemetry_summary(project.id)["totals"]["timeouts"], 1)

    def test_platform_jobs_dedupe_cancel_retry_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Jobs", "Durable work")
            job = db.create_platform_job(
                project_id=project.id,
                kind="generation",
                workflow="layer1_generation",
                scope="layer1",
                request_payload={"max_rounds": 1},
                dedupe_key="layer1-once",
            )
            duplicate = db.create_platform_job(
                project_id=project.id,
                kind="generation",
                workflow="layer1_generation",
                scope="layer1",
                dedupe_key="layer1-once",
            )
            self.assertEqual(duplicate.id, job.id)

            running = db.update_platform_job(job.id, status="running", started_at=datetime.now().isoformat())
            self.assertEqual(running.status, "running")
            self.assertEqual(db.recover_interrupted_platform_jobs(), 1)
            interrupted = db.get_platform_job(job.id)
            self.assertEqual(interrupted.status, "interrupted")
            self.assertIn("restart", interrupted.error_message or "")

            retried = db.retry_platform_job(job.id)
            self.assertEqual(retried.status, "queued")
            self.assertEqual(retried.attempt, 2)
            cancelled = db.request_platform_job_cancel(job.id)
            self.assertEqual(cancelled.status, "cancelled")
            self.assertTrue(cancelled.cancel_requested)

            summary = db.platform_job_summary(project.id)
            self.assertEqual(summary["cancelled"], 1)
            self.assertEqual(summary["recent"][0]["id"], job.id)

    def test_project_archive_import_roundtrip_warns_and_remaps_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Archive Source", "Portable archive test")
            db.upsert_project_brief(
                project_id=project.id,
                product_idea=project.idea,
                known_competitors=["Qualtrics"],
                constraints="",
                status="published",
            )
            settings = default_project_model_settings(
                AppConfig(database_backend="sqlite", db_path=Path(tmpdir) / "specforge.db", embeddings_enabled=False),
            )
            settings["llm_profiles"][0]["local_path"] = str(Path(tmpdir) / "missing-model.gguf")
            db.upsert_project_model_settings(project_id=project.id, **settings)
            job = db.create_platform_job(
                project_id=project.id,
                kind="diagnostics",
                workflow="diagnostics_export",
                scope="project",
            )
            db.update_platform_job(job.id, status="completed", result_payload={"json_path": "diagnostics.json"})

            archive_path = db.export_project_archive(project.id, Path(tmpdir) / "exports")
            result = db.import_project_archive(archive_path)

            self.assertNotEqual(result["project"].id, project.id)
            self.assertTrue(result["lifecycle_warnings"])
            imported_settings = db.get_project_model_settings(result["project"].id)
            self.assertIsNotNone(imported_settings)
            self.assertEqual(imported_settings.llm_profiles[0].local_path, "")
            imported_jobs = db.list_platform_jobs(result["project"].id)
            self.assertEqual(len(imported_jobs), 1)
            self.assertEqual(imported_jobs[0].workflow, "diagnostics_export")

    def test_archived_project_blocks_metadata_writes_until_unarchived(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "api.db"
            config = AppConfig(database_backend="sqlite", db_path=db_path, embeddings_enabled=False)
            with patch("strata.api.AppConfig", return_value=config), TestClient(create_app()) as client:
                created = client.post("/api/projects", json={"name": "Archive Guard", "idea": "Lifecycle test"})
                self.assertEqual(created.status_code, 200)
                project_id = created.json()["id"]

                snapshot = client.get(f"/api/projects/{project_id}").json()
                archived = client.post(f"/api/projects/{project_id}/archive", params={"expected_state_token": snapshot["project"]["state_token"]})
                self.assertEqual(archived.status_code, 200)
                self.assertEqual(archived.json()["lifecycle_state"], "archived")

                blocked = client.patch(
                    f"/api/projects/{project_id}",
                    json={"name": "Archive Guard", "idea": "Lifecycle test"},
                )
                self.assertEqual(blocked.status_code, 409)

                archived_token = client.get("/api/projects?state=archived").json()[0]["state_token"]
                unarchived = client.post(f"/api/projects/{project_id}/unarchive", params={"expected_state_token": archived_token})
                self.assertEqual(unarchived.status_code, 200)
                allowed = client.patch(
                    f"/api/projects/{project_id}",
                    json={"name": "Archive Guard Restored", "idea": "Lifecycle test", "expected_state_token": unarchived.json()["state_token"]},
                )
                self.assertEqual(allowed.status_code, 200)
                self.assertEqual(allowed.json()["name"], "Archive Guard Restored")

    def test_diagnostics_export_uses_unified_platform_job_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "api.db"
            exports_dir = Path(tmpdir) / "exports"
            runtime_logs = Path(tmpdir) / ".runtime" / "logs"
            runtime_logs.mkdir(parents=True)
            (runtime_logs / "strata-api.log").write_text(
                "Bearer abcdefghijklmnopqrstuvwxyz123456\n"
                "database=postgresql://user:secret@localhost:5432/db\n"
                "path=C:\\Users\\Fresc\\secret.txt email=test@example.com\n",
                encoding="utf-8",
            )
            config = AppConfig(database_backend="sqlite", db_path=db_path, exports_dir=exports_dir, embeddings_enabled=False)
            with patch("strata.api.AppConfig", return_value=config), patch("strata.diagnostics.ROOT_DIR", Path(tmpdir)), TestClient(create_app()) as client:
                created = client.post("/api/projects", json={"name": "Queued", "idea": "Durable diagnostics"})
                self.assertEqual(created.status_code, 200)
                project_id = created.json()["id"]
                db = Database(db_path)
                db.set_app_setting("provider_readiness", json.dumps({"ready": True, "message": "Ready for tests."}))

                queued = client.post(f"/api/projects/{project_id}/diagnostics/export")
                self.assertEqual(queued.status_code, 200)
                job_id = queued.json()["job"]["id"]

                jobs = client.get(f"/api/projects/{project_id}/jobs").json()["jobs"]
                matching = next(job for job in jobs if job["id"] == job_id)
                self.assertEqual(matching["workflow"], "diagnostics_export")
                self.assertEqual(matching["status"], "completed")
                output_path = Path(matching["result_payload"]["json_path"])
                self.assertTrue(output_path.exists())
                payload = json.loads(output_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["manifest"]["bundle_version"], 2)
                self.assertEqual(payload["manifest"]["bundle_schema_id"], "strata.diagnostics.bundle.v2")
                self.assertRegex(payload["manifest"]["content_hash"], r"^[a-f0-9]{64}$")
                self.assertIn("dependency_health", payload["manifest"]["included_sections"])

    @patch("strata.provider_onboarding.requests.post")
    @patch("strata.provider_onboarding.requests.get")
    def test_setup_complete_persists_server_side_token_without_returning_it(self, mock_get: MagicMock, mock_post: MagicMock) -> None:
        mock_get.return_value = MagicMock(ok=True, json=MagicMock(return_value={"data": [{"id": "local-model"}]}))
        mock_post.return_value = MagicMock(ok=True, status_code=200, json=MagicMock(return_value={"choices": [{"message": {"content": "OK"}}]}))
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "setup.db"
            config = AppConfig(database_backend="sqlite", db_path=db_path, embeddings_enabled=False)
            with patch("strata.api.AppConfig", return_value=config), TestClient(create_app()) as client:
                response = client.post("/api/setup/complete", json={
                    "llama_base_url": "http://127.0.0.1:8080",
                    "model_name": "local-model",
                    "embeddings_enabled": False,
                    "embeddings_model_name": "sentence-transformers/all-MiniLM-L6-v2",
                    "bearer_token": "super-secret-token",
                    "context_window": 4096,
                    "max_output_tokens": 512,
                    "runtime_preset": "llama_cpp",
                })

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertNotIn("bearer_token", payload)
                self.assertNotIn("super-secret-token", json.dumps(payload))
                self.assertTrue(payload["has_bearer_token"])
                self.assertTrue(payload["provider_readiness"]["ready"])
                db = Database(db_path)
                self.assertEqual(db.get_app_setting("model_api_key"), "super-secret-token")
                status = client.get("/api/setup/status").json()
                self.assertTrue(status["defaults"]["has_bearer_token"])
                self.assertNotIn("super-secret-token", json.dumps(status))
                config_payload = client.get("/api/config").json()
                self.assertTrue(config_payload["has_bearer_token"])
                self.assertNotIn("super-secret-token", json.dumps(config_payload))

    @patch("strata.provider_onboarding.requests.get")
    def test_setup_complete_allows_offline_provider_but_marks_not_ready(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = requests.ConnectionError("offline")
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "setup-offline.db"
            config = AppConfig(database_backend="sqlite", db_path=db_path, embeddings_enabled=False)
            with patch("strata.api.AppConfig", return_value=config), TestClient(create_app()) as client:
                response = client.post("/api/setup/complete", json={
                    "llama_base_url": "http://127.0.0.1:8080",
                    "model_name": "local-model",
                    "embeddings_enabled": False,
                    "embeddings_model_name": "sentence-transformers/all-MiniLM-L6-v2",
                    "context_window": 4096,
                    "max_output_tokens": 512,
                    "runtime_preset": "llama_cpp",
                })

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["completed"])
                self.assertFalse(payload["model_ok"])
                self.assertIn("Could not reach", payload["provider_readiness"]["message"])
                status = client.get("/api/setup/status").json()
                self.assertTrue(status["completed"])
                self.assertFalse(status["provider_readiness"]["ready"])

    def test_diagnostics_export_is_blocked_when_setup_completed_but_provider_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "blocked.db"
            config = AppConfig(database_backend="sqlite", db_path=db_path, embeddings_enabled=False)
            db = Database(db_path)
            db.set_app_setting("setup_completed", "true")
            db.set_app_setting("provider_readiness", json.dumps({
                "ready": False,
                "reachable": True,
                "auth_ok": True,
                "model_listed": False,
                "capability_ok": False,
                "message": "Model-backed workflows are blocked until validation passes.",
                "error_code": "model_missing",
            }))
            with patch("strata.api.AppConfig", return_value=config), TestClient(create_app()) as client:
                created = client.post("/api/projects", json={"name": "Blocked", "idea": "Diagnostics gate"})
                self.assertEqual(created.status_code, 200)
                project_id = created.json()["id"]

                blocked = client.post(f"/api/projects/{project_id}/diagnostics/export", json={})

                self.assertEqual(blocked.status_code, 400)
                self.assertIn("blocked", blocked.json()["detail"])

    def test_existing_project_without_setup_flag_still_blocks_unverified_provider_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "upgraded.db"
            config = AppConfig(database_backend="sqlite", db_path=db_path, embeddings_enabled=False)
            db = Database(db_path)
            project = db.create_project("Upgraded", "Existing install")
            with patch("strata.api.AppConfig", return_value=config), TestClient(create_app()) as client:
                blocked = client.post(f"/api/projects/{project.id}/diagnostics/export", json={})

                self.assertEqual(blocked.status_code, 400)
                self.assertIn("blocked", blocked.json()["detail"])

    def test_diagnostics_preview_does_not_write_export_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "api.db"
            exports_dir = Path(tmpdir) / "exports"
            config = AppConfig(database_backend="sqlite", db_path=db_path, exports_dir=exports_dir, embeddings_enabled=False)
            with patch("strata.api.AppConfig", return_value=config), patch("strata.diagnostics.ROOT_DIR", Path(tmpdir)), TestClient(create_app()) as client:
                created = client.post("/api/projects", json={"name": "Preview", "idea": "Redaction preview"})
                self.assertEqual(created.status_code, 200)
                project_id = created.json()["id"]

                preview = client.get(
                    f"/api/projects/{project_id}/diagnostics/preview",
                    params={"include_logs": "false", "include_recent_errors": "true", "include_traces": "false"},
                )
                self.assertEqual(preview.status_code, 200)
                payload = preview.json()
                self.assertEqual(payload["manifest"]["bundle_version"], 2)
                self.assertIn("recent_errors", payload["manifest"]["included_sections"])
                self.assertNotIn("logs", payload["manifest"]["included_sections"])
                self.assertFalse((exports_dir / f"{project_id}-diagnostics.json").exists())

    def test_diagnostics_redaction_and_hash_are_deterministic(self) -> None:
        redactor = Redactor()
        value = redactor.redact(
            "api_key=sk-test-secret Bearer abcdefghijklmnopqrstuvwxyz123456 "
            "postgresql://user:pass@localhost/db C:\\Users\\Fresc\\file.txt person@example.com"
        )
        self.assertIn("[REDACTED:api_key]", value)
        self.assertIn("[REDACTED:bearer_token]", value)
        self.assertIn("[REDACTED:database_url]", value)
        self.assertIn("[REDACTED:windows_path]", value)
        self.assertIn("[REDACTED:email]", value)

        first = {
            "manifest": {"generated_at": "2026-01-01T00:00:00Z", "content_hash": ""},
            "exported_at": "2026-01-01T00:00:00Z",
            "logs": {"files": [{"lines": ["same"]}]},
        }
        second = {
            "manifest": {"generated_at": "2026-01-02T00:00:00Z", "content_hash": "old"},
            "exported_at": "2026-01-02T00:00:00Z",
            "logs": {"files": [{"lines": ["same"]}]},
        }
        changed = {
            "manifest": {"generated_at": "2026-01-02T00:00:00Z", "content_hash": ""},
            "exported_at": "2026-01-02T00:00:00Z",
            "logs": {"files": [{"lines": ["different"]}]},
        }
        self.assertEqual(diagnostics_content_hash(first), diagnostics_content_hash(second))
        self.assertNotEqual(diagnostics_content_hash(first), diagnostics_content_hash(changed))

    def test_project_lifecycle_routes_filter_edit_archive_and_guard_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "api.db"
            config = AppConfig(database_backend="sqlite", db_path=db_path, embeddings_enabled=False)
            with patch("strata.api.AppConfig", return_value=config), TestClient(create_app()) as client:
                created = client.post("/api/projects", json={"name": "Lifecycle", "idea": "Original summary"})
                self.assertEqual(created.status_code, 200)
                project_id = created.json()["id"]

                initial = client.get(f"/api/projects/{project_id}").json()
                edited = client.patch(f"/api/projects/{project_id}", json={"name": "Lifecycle Edited", "idea": "Library summary", "expected_state_token": initial["project"]["state_token"]})
                self.assertEqual(edited.status_code, 200)
                self.assertEqual(edited.json()["name"], "Lifecycle Edited")

                self.assertEqual(len(client.get("/api/projects?state=active").json()), 1)
                active_snapshot = client.get(f"/api/projects/{project_id}").json()
                archived = client.post(f"/api/projects/{project_id}/archive", params={"expected_state_token": active_snapshot["project"]["state_token"]})
                self.assertEqual(archived.status_code, 200)
                self.assertEqual(archived.json()["lifecycle_state"], "archived")
                self.assertEqual(client.get("/api/projects?state=active").json(), [])
                self.assertEqual(client.get("/api/projects?state=archived").json()[0]["id"], project_id)

                snapshot = client.get(f"/api/projects/{project_id}")
                self.assertEqual(snapshot.status_code, 200)
                blocked = client.patch(f"/api/projects/{project_id}/brief", json={
                    "product_idea": "Changed",
                    "known_competitors": [],
                    "constraints": "",
                })
                self.assertEqual(blocked.status_code, 409)
                self.assertIn("Archived projects are read-only", blocked.json()["detail"])

                clone = client.post(f"/api/projects/{project_id}/clone", json={})
                self.assertEqual(clone.status_code, 200)
                self.assertEqual(clone.json()["source_project_id"], project_id)

                archived_token = client.get("/api/projects?state=archived").json()[0]["state_token"]
                unarchived = client.post(f"/api/projects/{project_id}/unarchive", params={"expected_state_token": archived_token})
                self.assertEqual(unarchived.status_code, 200)
                self.assertEqual(unarchived.json()["lifecycle_state"], "active")

    def test_project_clone_archive_import_and_purge_preserve_expected_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Clone Source", "Original library summary")
            db.upsert_project_brief(
                project_id=project.id,
                product_idea="Published product",
                known_competitors=["Acme"],
                constraints="Local",
                status="published",
            )
            pillar = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Pillar",
                description="Pillar description",
                status="kept",
            )
            db.upsert_project_workspace_state(
                project_id=project.id,
                view_mode="table",
                selected_entity_type="pillar",
                selected_entity_id=pillar.id,
                table_scope="project",
                map_state={"zoom": 2},
                table_state={"q": "pillar"},
            )
            db.record_model_call({"project_id": project.id, "layer": "layer1", "workflow": "test", "status": "completed"})

            clone = db.clone_project(project.id)
            self.assertNotEqual(clone.id, project.id)
            self.assertEqual(clone.source_project_id, project.id)
            self.assertEqual(db.get_project_brief(clone.id).product_idea, "Published product")
            self.assertEqual(len(db.list_nodes(clone.id)), 1)
            self.assertIsNone(db.get_project_workspace_state(clone.id))
            self.assertEqual(db.telemetry_summary(clone.id)["totals"]["calls"], 0)

            archive_path = db.export_project_archive(project.id, Path(tmpdir) / "exports")
            self.assertTrue(archive_path.exists())
            imported = db.import_project_archive(archive_path)
            imported_project = imported["project"]
            self.assertNotEqual(imported_project.id, project.id)
            self.assertEqual(db.get_project_brief(imported_project.id).product_idea, "Published product")
            self.assertEqual(len(db.list_nodes(imported_project.id)), 1)
            self.assertEqual(db.telemetry_summary(imported_project.id)["totals"]["calls"], 1)

            with self.assertRaises(ValueError):
                db.purge_project(project.id, confirmation_token="wrong")
            result = db.purge_project(project.id, confirmation_token=f"PURGE-{project.id[:8]}")
            self.assertEqual(result["purged_project_id"], project.id)
            with self.assertRaises(ValueError):
                db.get_project(project.id)

    def test_manual_layer1_pillar_route_requires_published_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "api.db"
            config = AppConfig(database_backend="sqlite", db_path=db_path, embeddings_enabled=False)
            with patch("strata.api.AppConfig", return_value=config), TestClient(create_app()) as client:
                created = client.post("/api/projects", json={"name": "Manual", "idea": "Known product map"})
                self.assertEqual(created.status_code, 200)
                project_id = created.json()["id"]

                draft_response = client.post(
                    f"/api/projects/{project_id}/layer1/pillars",
                    json={"title": "Workflow Intelligence", "description": "High-level known area"},
                )
                self.assertEqual(draft_response.status_code, 422)

                snapshot = client.get(f"/api/projects/{project_id}").json()
                settings = snapshot["project_model_settings"]
                settings["competitive_intelligence_enabled"] = False
                self.assertEqual(client.patch(f"/api/projects/{project_id}/settings/models", json=settings).status_code, 200)
                publish_snapshot = client.get(f"/api/projects/{project_id}").json()
                self.assertEqual(client.post(f"/api/projects/{project_id}/brief/publish", params={"expected_state_token": publish_snapshot["brief"]["state_token"]}).status_code, 200)

                response = client.post(
                    f"/api/projects/{project_id}/layer1/pillars",
                    json={
                        "title": "Workflow Intelligence",
                        "description": "Manual pillar",
                        "status": "prioritized",
                        "priority": 7,
                    },
                )
                self.assertEqual(response.status_code, 200)
                pillars = [node for node in response.json()["snapshot"]["nodes"] if node["node_type"] == "pillar"]
                self.assertEqual(len(pillars), 1)
                self.assertEqual(pillars[0]["title"], "Workflow Intelligence")
                self.assertEqual(pillars[0]["status"], "prioritized")
                self.assertEqual(pillars[0]["json_payload"]["source"], "manual")

    def test_layer0_proposal_apply_uses_revision_token_and_surfaces_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "api.db"
            config = AppConfig(database_backend="sqlite", db_path=db_path, embeddings_enabled=False)
            with patch("strata.api.AppConfig", return_value=config), TestClient(create_app()) as client:
                project_id = client.post(
                    "/api/projects", json={"name": "Proposal", "idea": "A planning tool"},
                ).json()["id"]
                initial = client.get(f"/api/projects/{project_id}").json()
                initial_token = initial["brief"]["state_token"]
                db = Database(db_path)
                applied_turn = db.append_brief_conversation_turn(
                    project_id=project_id,
                    role="assistant",
                    content="I can make the problem more specific.",
                    request_id="proposal-apply",
                    extracted_updates={
                        "stream_status": "completed",
                        "proposal": {
                            "id": "proposal-1",
                            "status": "pending",
                            "base_state_token": initial_token,
                            "updates": {"problem": "Planning converges before alternatives are explored."},
                            "fields": [{
                                "field": "problem", "current_value": "",
                                "proposed_value": "Planning converges before alternatives are explored.",
                                "operation": "new", "reason": "Captured from the user message.",
                            }],
                            "applied_fields": [],
                        },
                    },
                )

                applied = client.post(
                    f"/api/projects/{project_id}/brief/proposals/{applied_turn.id}/decision",
                    json={"decision": "apply", "expected_state_token": initial_token, "request_id": "apply-1"},
                )
                self.assertEqual(applied.status_code, 200)
                self.assertEqual(applied.json()["brief"]["problem"], "Planning converges before alternatives are explored.")
                self.assertEqual(db.get_brief_conversation_turn(applied_turn.id).extracted_updates["proposal"]["status"], "applied")

                current_token = applied.json()["brief"]["state_token"]
                partial_turn = db.append_brief_conversation_turn(
                    project_id=project_id,
                    role="assistant",
                    content="Two more possible fields.",
                    request_id="proposal-partial",
                    extracted_updates={
                        "proposal": {
                            "id": "proposal-partial", "status": "pending", "base_state_token": current_token,
                            "updates": {"target_users": "Product teams", "constraints": "Local first"},
                            "fields": [
                                {"field": "target_users", "current_value": "", "proposed_value": "Product teams", "operation": "new", "reason": "Captured."},
                                {"field": "constraints", "current_value": "", "proposed_value": "Local first", "operation": "new", "reason": "Captured."},
                            ],
                            "applied_fields": [],
                        },
                    },
                )
                partial = client.post(
                    f"/api/projects/{project_id}/brief/proposals/{partial_turn.id}/decision",
                    json={
                        "decision": "apply", "selected_fields": ["constraints"],
                        "expected_state_token": current_token, "request_id": "apply-partial",
                    },
                )
                self.assertEqual(partial.status_code, 200)
                self.assertEqual(partial.json()["brief"]["constraints"], "Local first")
                self.assertEqual(partial.json()["brief"]["target_users"], "")
                self.assertEqual(db.get_brief_conversation_turn(partial_turn.id).extracted_updates["proposal"]["status"], "partially_applied")

                stale_turn = db.append_brief_conversation_turn(
                    project_id=project_id,
                    role="assistant",
                    content="A stale suggestion.",
                    request_id="proposal-stale",
                    extracted_updates={
                        "proposal": {
                            "id": "proposal-2", "status": "pending", "base_state_token": initial_token,
                            "updates": {"target_users": "Product teams"},
                            "fields": [{
                                "field": "target_users", "current_value": "", "proposed_value": "Product teams",
                                "operation": "new", "reason": "Captured from the user message.",
                            }],
                            "applied_fields": [],
                        },
                    },
                )
                conflict = client.post(
                    f"/api/projects/{project_id}/brief/proposals/{stale_turn.id}/decision",
                    json={"decision": "apply", "expected_state_token": initial_token, "request_id": "apply-stale"},
                )

                self.assertEqual(conflict.status_code, 409)
                self.assertEqual(db.get_brief_conversation_turn(stale_turn.id).extracted_updates["proposal"]["status"], "stale")

    def test_layer3_boundary_rejects_implementation_specs(self) -> None:
        forbidden_examples = [
            "Create backend API endpoints and database tables.",
            "Add GraphQL requests and HTTP status codes.",
            "Write integration test cases and acceptance criteria.",
        ]
        for example in forbidden_examples:
            with self.subTest(example=example), self.assertRaises(ValueError):
                validate_product_level_content({"notes": example})

    def test_layer2_status_normalization_maps_review_actions_to_feature_statuses(self) -> None:
        self.assertEqual(_valid_layer2_status("approve_for_layer3"), "approved")
        self.assertEqual(_valid_layer2_status("keep"), "kept")

    def test_layer2_manual_feature_request_rejects_blank_required_fields(self) -> None:
        with self.assertRaises(ValidationError):
            Layer2FeatureCreateRequest(
                canonical_name=" ",
                description="Useful feature",
                owner_pillar_id="pillar_1",
            )

    def test_layer2_feature_evidence_request_rejects_blank_competitor(self) -> None:
        with self.assertRaises(ValidationError):
            Layer2FeatureEvidenceRequest(
                feature_id="feat_1",
                competitor_name=" ",
            )

    def test_update_node_preserves_priority_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            node = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Original",
                description="Original description",
                priority=4,
            )

            updated = db.update_node(node.id, title="Renamed")

            self.assertEqual(updated.title, "Renamed")
            self.assertEqual(updated.priority, 4)

    def test_update_node_can_clear_priority_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            node = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Original",
                description="Original description",
                priority=4,
            )

            updated = db.update_node(node.id, priority=None)

            self.assertIsNone(updated.priority)

    def test_project_brief_and_conversation_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            brief = db.upsert_project_brief(
                project_id=project.id,
                product_idea="A useful product",
                problem="Manual workflows are scattered and unclear.",
                known_competitors=["Alpha"],
                constraints="Local only",
                target_users="Operators",
                goals=["Reduce manual work"],
                preferred_directions=[],
                rejected_directions=["Paid APIs"],
                notes="Draft",
            )
            turn = db.append_brief_conversation_turn(
                project_id=project.id,
                role="assistant",
                content="Captured.",
                extracted_updates={"known_competitors": ["Alpha"]},
            )

            self.assertEqual(brief.status, "draft")
            self.assertEqual(db.get_project_brief(project.id).problem, "Manual workflows are scattered and unclear.")
            self.assertEqual(db.get_project_brief(project.id).known_competitors, ["Alpha"])
            self.assertEqual(db.list_brief_conversation(project.id)[0].id, turn.id)

    def test_app_setting_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            db.set_app_setting("embeddings_model_name", "custom/model")

            self.assertEqual(db.get_app_setting("embeddings_model_name"), "custom/model")

    def test_project_list_includes_workspace_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            db.upsert_project_brief(
                project_id=project.id,
                product_idea="A useful product",
                known_competitors=[],
                constraints="",
            )
            db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Pillar",
                description="desc",
            )

            projects = db.list_projects()

            self.assertEqual(projects[0]["brief_status"], "draft")
            self.assertEqual(projects[0]["node_count"], 1)
            self.assertEqual(projects[0]["pillar_count"], 1)

    def test_project_model_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            payload = default_project_model_settings(AppConfig())
            payload["assignments"]["layer2_generation"] = "default-chat"

            stored = db.upsert_project_model_settings(project_id=project.id, **payload)

            self.assertEqual(stored.project_id, project.id)
            self.assertEqual(stored.llm_profiles[0].id, "default-chat")
            self.assertEqual(stored.embedding_profiles[0].id, "default-embedding")
            self.assertEqual(stored.execution_intent, "local_first")
            self.assertEqual(stored.routing_policy["assistant"], "local")
            self.assertEqual(stored.concurrency_policy["managed_local_parallelism"], 1)
            self.assertEqual(stored.assignments["layer2_generation"], "default-chat")
            self.assertIn("structured product-architecture engine", stored.prompt_catalog["system_json_generator"])
            self.assertIn("return only valid JSON", stored.prompt_catalog["system_json_generator"])

    def test_project_workspace_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Workspace", "A living product map")

            stored = db.upsert_project_workspace_state(
                project_id=project.id,
                view_mode="table",
                selected_entity_type="pillar",
                selected_entity_id="pillar-123",
                table_scope="focused",
                map_state={"zoom": 1.2, "collapsed_ids": ["pillar-456"]},
                table_state={"sort": "hierarchy"},
            )

            loaded = db.get_project_workspace_state(project.id)
            self.assertEqual(stored.view_mode, "table")
            self.assertEqual(loaded.selected_entity_id, "pillar-123")
            self.assertEqual(loaded.map_state["zoom"], 1.2)
            self.assertEqual(loaded.table_state["sort"], "hierarchy")

    def test_layer2_graph_records_provenance_review_and_negative_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            pillar = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Cash Flow Intelligence",
                description="Understand household cash movement.",
                status="kept",
            )
            db.upsert_layer1_pillar(pillar)
            run = db.create_layer2_generation_run(
                project_id=project.id,
                source_pillar_ids=[pillar.id],
                lenses=["core_workflows"],
                source_model="local",
            )
            raw = db.insert_layer2_raw_candidate(
                project_id=project.id,
                generation_run_id=run.id,
                source_pillar_id=pillar.id,
                source_lens="core_workflows",
                source_model="local",
                generation_round=1,
                raw_text="Transaction categorization",
                payload={"canonical_name": "Transaction categorization"},
            )
            feature = db.create_layer2_feature(
                project_id=project.id,
                canonical_name="Transaction categorization",
                description="Group transactions into useful household categories.",
                feature_type="workflow",
                owner_pillar_id=pillar.id,
                candidate_source_ids=[raw.id],
                aliases=["Spend categorization"],
            )
            db.insert_layer2_affinity(
                project_id=project.id,
                feature_id=feature.id,
                pillar_id=pillar.id,
                affinity_score=0.93,
                recommended_owner_pillar_id=pillar.id,
            )
            db.record_layer2_review_action(
                project_id=project.id,
                feature_id=feature.id,
                action_type="cut",
                payload={"reason": "Out of scope"},
            )
            db.create_layer2_negative_cache_entry(
                project_id=project.id,
                rejected_name=feature.canonical_name,
                semantic_cluster="transaction categorization",
                rejected_aliases=feature.aliases,
                rejected_from_pillar_id=pillar.id,
            )

            graph = db.layer2_graph_snapshot(project.id)

            self.assertEqual(graph["features"][0]["candidate_source_ids"], [raw.id])
            self.assertEqual(graph["affinity"][0]["recommended_owner_pillar_id"], pillar.id)
            self.assertEqual(graph["review_actions"][0]["action_type"], "cut")
            self.assertEqual(graph["negative_cache"][0]["rejected_at_layer"], 2)

    def test_layer2_relationship_remove_action_deletes_edge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            pillar = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Cash Flow Intelligence",
                description="Understand household cash movement.",
                status="kept",
            )
            left = db.create_layer2_feature(
                project_id=project.id,
                canonical_name="Transaction categorization",
                description="Group transactions.",
                feature_type="workflow",
                owner_pillar_id=pillar.id,
                candidate_source_ids=[],
            )
            right = db.create_layer2_feature(
                project_id=project.id,
                canonical_name="Budget variance alerts",
                description="Warn when budget drift appears.",
                feature_type="notification",
                owner_pillar_id=pillar.id,
                candidate_source_ids=[],
            )
            db.insert_layer2_relationship(
                project_id=project.id,
                source_feature_id=left.id,
                target_feature_id=right.id,
                relationship_type="related_to",
                strength=0.75,
            )
            removed = db.delete_layer2_relationship(
                project_id=project.id,
                source_feature_id=left.id,
                target_feature_id=right.id,
                relationship_type="related_to",
            )

            self.assertEqual(removed, 1)
            self.assertEqual(db.list_layer2_relationships(project.id), [])

    def test_layer2_workbench_snapshot_includes_evidence_settings_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            pillar = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Survey Builder",
                description="Build and distribute structured surveys.",
                status="kept",
            )
            db.upsert_layer1_pillar(pillar)
            feature = db.create_layer2_feature(
                project_id=project.id,
                canonical_name="Question branching logic",
                description="Route respondents through different paths based on prior answers.",
                feature_type="workflow",
                owner_pillar_id=pillar.id,
                candidate_source_ids=[],
                status="approved",
                metadata={"coverage_family": "Logic"},
            )
            db.upsert_layer2_competitive_settings(
                project_id=project.id,
                known_competitors=["Typeform", "SurveyMonkey"],
                research_mode="known_only",
            )
            db.create_layer2_feature_evidence(
                project_id=project.id,
                feature_id=feature.id,
                competitor_name="Typeform",
                coverage_status="has_feature",
                confidence=90,
                source_url="https://example.com",
                evidence_snippet="Branching logic is documented.",
            )

            graph = db.layer2_graph_snapshot(project.id)
            row = graph["workbench"]["rows"][0]

            self.assertEqual(graph["competitive_settings"]["known_competitors"], ["Typeform", "SurveyMonkey"])
            self.assertEqual(graph["feature_evidence"][0]["competitor_name"], "Typeform")
            self.assertTrue(row["layer3_ready"])
            self.assertEqual(row["research_status"], "manual_evidence")
            self.assertEqual(row["competitor_coverage_score"], 100)
            self.assertEqual(row["coverage_family"], "Logic")

    def test_layer2_competitive_settings_inherit_brief_competitors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            db.upsert_project_brief(
                project_id=project.id,
                product_idea=project.idea,
                known_competitors=["Typeform", "SurveyMonkey"],
                constraints="",
            )
            db.upsert_layer2_competitive_settings(
                project_id=project.id,
                known_competitors=["Jotform", "typeform"],
                research_mode="known_only",
            )

            settings = db.get_layer2_competitive_settings(project.id)

            self.assertEqual(settings.known_competitors, ["Typeform", "SurveyMonkey", "Jotform"])

    def test_layer2_workbench_uses_latest_evidence_for_matrix_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            pillar = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Survey Builder",
                description="Build surveys.",
                status="kept",
            )
            feature = db.create_layer2_feature(
                project_id=project.id,
                canonical_name="Branching",
                description="Route respondents.",
                feature_type="workflow",
                owner_pillar_id=pillar.id,
                candidate_source_ids=[],
            )
            db.create_layer2_feature_evidence(
                project_id=project.id,
                feature_id=feature.id,
                competitor_name="Typeform",
                coverage_status="not_found",
            )
            db.create_layer2_feature_evidence(
                project_id=project.id,
                feature_id=feature.id,
                competitor_name="Typeform",
                coverage_status="has_feature",
                source_type="discovered",
                research_job_id="job-2",
            )

            row = db.layer2_workbench_snapshot(project.id)["rows"][0]

            self.assertEqual(row["evidence_count"], 2)
            self.assertEqual(row["competitor_coverage_score"], 100)
            self.assertEqual(row["research_status"], "researched")

    def test_layer2_markdown_export_writes_workbench_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            pillar = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Survey Builder",
                description="Build surveys.",
                status="kept",
            )
            db.upsert_layer1_pillar(pillar)
            feature = db.create_layer2_feature(
                project_id=project.id,
                canonical_name="Question type library",
                description="Offer structured question formats for survey authors.",
                feature_type="feature",
                owner_pillar_id=pillar.id,
                candidate_source_ids=[],
            )
            db.create_layer2_feature_evidence(
                project_id=project.id,
                feature_id=feature.id,
                competitor_name="Typeform",
                coverage_status="partial",
                confidence=70,
            )

            output_path = export_layer2_markdown(project, db.layer2_graph_snapshot(project.id), Path(tmpdir))
            markdown = output_path.read_text(encoding="utf-8")

            self.assertIn("# Test Layer 2", markdown)
            self.assertIn("Question type library", markdown)
            self.assertIn("## Competitive Evidence", markdown)
            self.assertIn("Typeform", markdown)


