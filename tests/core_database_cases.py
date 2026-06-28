from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from strata.config import AppConfig, ModelProfile, build_model_profiles, resolve_default_model_profile, resolve_reasoning_settings
from strata.api import _valid_layer2_status, create_app
from strata.assistant_index import AssistantIndexService
from strata.assistant_service import AssistantService
from strata.api_models import Layer2FeatureCreateRequest, Layer2FeatureEvidenceRequest
from strata.db import Database
from strata.embeddings import EmbeddingService
from strata.export import export_layer2_markdown, export_layer3_manifest
from strata.generation import LAYER2_EXHAUSTION_FAMILIES, LAYER2_LENSES, LAYER2_SURVEY_BUILDER_FAMILIES, GenerationService
from strata.llm import LLMError, LlamaCppClient
from strata.layer2_research import Layer2CompetitorSeed, Layer2ResearchMixin
from strata.layer3_service import validate_product_level_content
from strata.models import (
    CapabilityDesignPayload,
    CapabilityDesignResponse,
    CapabilityPressureTest,
    CapabilityPressureTestResponse,
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
    def test_schema_migrations_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            self.assertEqual(apply_migrations(db), [1])
            self.assertEqual(apply_migrations(db), [])
            self.assertEqual(migration_status(db)["current_version"], 1)

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

    def test_diagnostics_export_uses_unified_platform_job_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "api.db"
            exports_dir = Path(tmpdir) / "exports"
            config = AppConfig(database_backend="sqlite", db_path=db_path, exports_dir=exports_dir, embeddings_enabled=False)
            with patch("strata.api.AppConfig", return_value=config), TestClient(create_app()) as client:
                created = client.post("/api/projects", json={"name": "Queued", "idea": "Durable diagnostics"})
                self.assertEqual(created.status_code, 200)
                project_id = created.json()["id"]

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
                self.assertEqual(payload["manifest"]["bundle_version"], 1)
                self.assertIn("dependency_health", payload["manifest"]["included_sections"])
                self.assertIn("database", payload["dependency_health"])
                self.assertIn("model_server", payload["dependency_health"])

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
                self.assertEqual(draft_response.status_code, 400)

                snapshot = client.get(f"/api/projects/{project_id}").json()
                settings = snapshot["project_model_settings"]
                settings["competitive_intelligence_enabled"] = False
                self.assertEqual(client.patch(f"/api/projects/{project_id}/settings/models", json=settings).status_code, 200)
                self.assertEqual(client.post(f"/api/projects/{project_id}/brief/publish").status_code, 200)

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


