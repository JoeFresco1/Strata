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
from strata.export import export_layer2_markdown, export_layer3_feature_expansions
from strata.generation import LAYER2_EXHAUSTION_FAMILIES, LAYER2_LENSES, LAYER2_SURVEY_BUILDER_FAMILIES, GenerationService
from strata.llm import LLMError, LlamaCppClient
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


class ConfigTests(unittest.TestCase):
    def test_model_profile_discovery_ignores_mmproj_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model_dir = root / "models"
            model_dir.mkdir()
            (model_dir / "Qwen3.5-9B-Q6_K.gguf").write_text("", encoding="utf-8")
            (model_dir / "mmproj-Qwen3.5-9B.gguf").write_text("", encoding="utf-8")
            config = AppConfig(model_root=model_dir)

            profiles = build_model_profiles(config)

            discovered = [profile for profile in profiles if profile.path and profile.path.parent == model_dir]
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0].path.name, "Qwen3.5-9B-Q6_K.gguf")

    def test_default_profile_prefers_configured_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model_dir = root / "models"
            model_dir.mkdir()
            preferred = model_dir / "preferred.gguf"
            other = model_dir / "other.gguf"
            preferred.write_text("", encoding="utf-8")
            other.write_text("", encoding="utf-8")
            config = AppConfig(model_root=model_dir, preferred_model_path=str(preferred))

            profiles = build_model_profiles(config)
            default = resolve_default_model_profile(config, profiles)

            self.assertIsNotNone(default)
            self.assertEqual(default.path, preferred)

    def test_reasoning_settings_switch_between_off_and_on_modes(self) -> None:
        config = AppConfig(
            reasoning_mode="off",
            reasoning_format="none",
            reasoning_budget=0,
            reasoning_enabled_format="deepseek",
            reasoning_enabled_budget=-1,
        )

        self.assertEqual(resolve_reasoning_settings(config, False), ("off", "none", 0))
        self.assertEqual(resolve_reasoning_settings(config, True), ("on", "deepseek", -1))

    def test_build_model_profiles_includes_preferred_external_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model_dir = root / "models"
            external_dir = root / "external"
            model_dir.mkdir()
            external_dir.mkdir()
            external = external_dir / "custom.gguf"
            external.write_text("", encoding="utf-8")
            config = AppConfig(model_root=model_dir, preferred_model_path=str(external))

            profiles = build_model_profiles(config)

            self.assertEqual(profiles[0].path, external)
            self.assertIn("Custom", profiles[0].display_name)


class ResearchServiceTests(unittest.TestCase):
    def test_interrupted_research_jobs_return_to_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Recovery", "Resume local work")
            job = db.create_research_job(
                project_id=project.id,
                scope="layer0",
                scope_id=None,
                job_type="layer0_competitors",
            )
            db.update_research_job(job.id, status="running")

            self.assertEqual(db.recover_interrupted_research_jobs(), 1)
            self.assertEqual(db.list_queued_research_jobs()[0].id, job.id)

    def test_competitive_intelligence_switch_blocks_all_research_queues(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Private", "No competitor research")
            settings = default_project_model_settings(AppConfig())
            settings["competitive_intelligence_enabled"] = False
            db.upsert_project_model_settings(project_id=project.id, **settings)
            service = ResearchService(db, MagicMock(), MagicMock())

            with self.assertRaisesRegex(ValueError, "disabled"):
                service.enqueue_layer0(project.id)
            with self.assertRaisesRegex(ValueError, "disabled"):
                service.enqueue_layer1(project.id, "pillar-id")
            with self.assertRaisesRegex(ValueError, "disabled"):
                service.enqueue_layer2(project.id)

    @staticmethod
    def _layer2_fixture(tmpdir: str, *, feature_count: int = 2) -> tuple[Database, object, list[object]]:
        """Create a small active/cut feature graph for Layer 2 research tests."""
        db = Database(Path(tmpdir) / "specforge.db")
        db.set_app_setting("provider_readiness", json.dumps({"ready": True, "message": "Ready for tests."}))
        project = db.create_project("Test", "Survey software")
        pillar = db.create_node(
            project_id=project.id,
            parent_id=None,
            layer=1,
            node_type="pillar",
            title="Survey Builder",
            description="Build surveys.",
            status="kept",
        )
        features = [
            db.create_layer2_feature(
                project_id=project.id,
                canonical_name=f"Feature {index}",
                description=f"Capability {index}",
                feature_type="capability",
                owner_pillar_id=pillar.id,
                candidate_source_ids=[],
                status="candidate",
            )
            for index in range(feature_count)
        ]
        db.create_layer2_feature(
            project_id=project.id,
            canonical_name="Cut feature",
            description="Rejected capability",
            feature_type="capability",
            owner_pillar_id=pillar.id,
            candidate_source_ids=[],
            status="cut",
        )
        return db, project, features

    def test_layer2_enqueue_selects_active_features_and_rejects_cut_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, features = self._layer2_fixture(tmpdir)
            service = ResearchService(db, MagicMock(), MagicMock())

            job = service.enqueue_layer2(project.id)

            self.assertEqual(job.details["feature_ids"], [feature.id for feature in features])
            cut = next(feature for feature in db.list_layer2_features(project.id) if feature.status == "cut")
            with self.assertRaises(ValueError):
                service.enqueue_layer2(project.id, feature_ids=[cut.id])

    def test_layer2_job_without_competitors_completes_with_actionable_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, _ = self._layer2_fixture(tmpdir)
            service = ResearchService(db, MagicMock(), MagicMock())
            job = service.enqueue_layer2(project.id)

            service.run_job(job.id)

            completed = db.get_research_job(job.id)
            self.assertEqual(completed.status, "completed")
            self.assertIn("Add known competitors", completed.details["warnings"][0])

    def test_layer2_partial_batch_failure_preserves_success_and_crawls_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, features = self._layer2_fixture(tmpdir, feature_count=13)
            db.upsert_layer2_competitive_settings(
                project_id=project.id,
                known_competitors=["Typeform"],
                research_mode="known_only",
            )
            service = ResearchService(db, MagicMock(), MagicMock())
            page = ExtractedPage(
                competitor_name="Typeform",
                url="https://typeform.com/features",
                domain="typeform.com",
                title="Features",
                status_code=200,
                text="Typeform supports branching logic and reusable survey workflows. " * 8,
            )
            service._crawl_competitors = MagicMock(return_value=[page])
            service._store_pages = MagicMock(return_value=1)
            service._expand_layer2_competitors = MagicMock()
            service._classify_layer2_batch = MagicMock(side_effect=[
                [{
                    "feature_id": features[0].id,
                    "competitor_name": "Typeform",
                    "coverage_status": "has_feature",
                    "confidence": 90,
                    "source_url": page.url,
                    "evidence_snippet": "Typeform supports branching logic",
                    "rationale": "Directly documented.",
                }],
                LLMError("malformed batch"),
            ])
            job = service.enqueue_layer2(project.id)

            service.run_job(job.id)

            completed = db.get_research_job(job.id)
            self.assertEqual(completed.status, "completed")
            self.assertEqual(service._crawl_competitors.call_count, 1)
            service._expand_layer2_competitors.assert_not_called()
            evidence = db.list_layer2_feature_evidence(project.id)
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0].source_url, page.url)
            self.assertEqual(evidence[0].research_job_id, job.id)
            self.assertTrue(any("malformed batch" in warning for warning in completed.details["warnings"]))

    def test_layer2_expand_mode_persists_discovered_competitors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, _ = self._layer2_fixture(tmpdir)
            db.upsert_layer2_competitive_settings(
                project_id=project.id,
                known_competitors=["Typeform"],
                research_mode="expand_from_known",
            )
            service = ResearchService(db, MagicMock(), MagicMock())
            service._published_brief = MagicMock(return_value=MagicMock(project_id=project.id))
            service._suggest_competitors = MagicMock(
                return_value=[Layer2CompetitorSeed(name="Jotform", url="https://jotform.com")]
            )

            expanded = service._expand_layer2_competitors(
                project.id,
                [Layer2CompetitorSeed(name="Typeform")],
            )

            self.assertEqual([seed.name for seed in expanded], ["Typeform", "Jotform"])
            settings = db.get_layer2_competitive_settings(project.id)
            self.assertEqual(settings.known_competitors, ["Typeform", "https://jotform.com"])

    def test_layer2_competitor_batches_cap_each_model_request(self) -> None:
        pages = [
            ExtractedPage(
                competitor_name=f"Competitor {index}",
                url=f"https://example{index}.com",
                domain=f"example{index}.com",
                title="Product",
                status_code=200,
                text="Product feature evidence.",
            )
            for index in range(5)
        ]

        batches = Layer2ResearchMixin._competitor_page_batches(pages)

        self.assertEqual([len(batch) for batch in batches], [4, 1])

    def test_coverage_values_map_required_statuses(self) -> None:
        self.assertEqual(ResearchService._coverage_values(80), ("supported", "common", 80))
        self.assertEqual(ResearchService._coverage_values(40), ("partially_supported", "emerging", 55))
        self.assertEqual(ResearchService._coverage_values(20), ("unclear", "unclear", 45))
        self.assertEqual(ResearchService._coverage_values(0), ("not_evident", "rare", 35))

    @patch("strata.research.requests.packages.urllib3.disable_warnings")
    @patch("strata.research.requests.get")
    def test_research_get_retries_without_tls_verification_on_ssl_error(self, mock_get, mock_disable_warnings) -> None:
        secure_error = SSLError("tls")
        fallback_response = object()
        mock_get.side_effect = [secure_error, fallback_response]

        response = ResearchService._research_get("https://example.com", headers={"User-Agent": "Strata"})

        self.assertIs(response, fallback_response)
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[1].kwargs["verify"], False)
        mock_disable_warnings.assert_called_once()

    def test_homepage_candidates_cover_combined_and_primary_brand_forms(self) -> None:
        candidates = ResearchService._homepage_candidates("Salesforce Customer Success")

        self.assertIn("https://www.salesforcecustomersuccess.com", candidates)
        self.assertIn("https://www.salesforce.com", candidates)

    def test_looks_like_competitor_page_rejects_unrelated_brand(self) -> None:
        unrelated = ExtractedPage(
            competitor_name="Gainsight",
            url="https://www.example.com",
            domain="www.example.com",
            title="Example Domain",
            status_code=200,
            text="Example content about sample placeholders and testing only.",
        )
        related = ExtractedPage(
            competitor_name="Gainsight",
            url="https://www.gainsight.com",
            domain="www.gainsight.com",
            title="Customer Success and Product Experience Software | Gainsight",
            status_code=200,
            text="Gainsight helps customer success teams retain and grow accounts.",
        )

        self.assertFalse(ResearchService._looks_like_competitor_page("Gainsight", unrelated))
        self.assertTrue(ResearchService._looks_like_competitor_page("Gainsight", related))


class AssistantServiceTests(unittest.TestCase):
    def _database(self, tmpdir: str) -> tuple[Database, str]:
        """Create a project with the model assignments required by the assistant."""
        db = Database(Path(tmpdir) / "assistant.db")
        db.set_app_setting("provider_readiness", json.dumps({"ready": True, "message": "Ready for tests."}))
        project = db.create_project("Assistant test", "Map a complex product")
        settings = default_project_model_settings(AppConfig(embeddings_enabled=False))
        db.upsert_project_model_settings(project_id=project.id, **settings)
        return db, project.id

    def test_message_submission_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project_id = self._database(tmpdir)
            index = AssistantIndexService(db, MagicMock())
            service = AssistantService(db, MagicMock(), index)
            conversation = service.create_conversation(project_id, "Architecture", "layer2")
            payload = {
                "project_id": project_id,
                "conversation_id": conversation.id,
                "content": "Where are the coverage gaps?",
                "request_id": "request-1",
                "active_scope": "layer2",
                "focus": {},
                "reference_conversation_ids": [],
                "execution_intent_override": None,
                "thinking_enabled": False,
                "deep_mode": True,
            }

            first = service.submit_message(**payload)
            second = service.submit_message(**payload)

            self.assertEqual(first["assistant_message"].id, second["assistant_message"].id)
            self.assertEqual(len(db.list_assistant_messages(conversation.id)), 2)

    def test_index_refresh_is_incremental_and_scope_search_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project_id = self._database(tmpdir)
            index = AssistantIndexService(db, MagicMock())

            first = index.refresh_project(project_id)
            second = index.refresh_project(project_id)
            results = index.search(project_id, "overall", "complex product", limit=100)

            self.assertGreaterEqual(first["changed"], 1)
            self.assertEqual(second["changed"], 0)
            self.assertLessEqual(len(results), 24)
            self.assertEqual(results[0]["source_type"], "project")

    def test_planner_output_cannot_escape_tool_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project_id = self._database(tmpdir)
            service = AssistantService(db, MagicMock(), AssistantIndexService(db, MagicMock()))

            tools = service._validated_tools(
                [
                    {"name": "execute_sql", "arguments": {"query": "DROP TABLE projects"}},
                    {"name": "coverage_gaps", "arguments": {}},
                ],
                "What is missing?",
                "layer2",
            )

            self.assertNotIn("execute_sql", [item["name"] for item in tools])
            self.assertIn("project_summary", [item["name"] for item in tools])
            self.assertIn("search_documents", [item["name"] for item in tools])

    def test_workspace_focus_is_injected_into_assistant_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project_id = self._database(tmpdir)
            service = AssistantService(db, MagicMock(), AssistantIndexService(db, MagicMock()))

            tools = service._validated_tools(
                [],
                "What should I do here?",
                "layer2",
                {"entity_type": "feature", "entity_id": "feature-123"},
            )

            self.assertEqual(tools[0]["name"], "filter_entities")
            self.assertEqual(tools[0]["arguments"]["source_id"], "feature-123")
            self.assertEqual(tools[1]["name"], "graph_neighbors")

    def test_startup_recovery_marks_interrupted_turn_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project_id = self._database(tmpdir)
            service = AssistantService(db, MagicMock(), AssistantIndexService(db, MagicMock()))
            conversation = service.create_conversation(project_id, "Recovery", "overall")
            result = service.submit_message(
                project_id=project_id,
                conversation_id=conversation.id,
                content="Review this project",
                request_id="interrupted",
                active_scope="overall",
                focus={},
                reference_conversation_ids=[],
                execution_intent_override="api_first",
                thinking_enabled=False,
                deep_mode=False,
            )

            recovered = db.recover_interrupted_assistant_runs()
            message = db.get_assistant_message(result["assistant_message"].id)
            run = db.get_assistant_run_for_message(message.id)

            self.assertEqual(recovered, 1)
            self.assertEqual(message.status, "failed")
            self.assertEqual(run["status"], "failed")

    def test_submit_message_records_execution_intent_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project_id = self._database(tmpdir)
            service = AssistantService(db, MagicMock(), AssistantIndexService(db, MagicMock()))
            conversation = service.create_conversation(project_id, "Routing", "overall")

            result = service.submit_message(
                project_id=project_id,
                conversation_id=conversation.id,
                content="Use the faster path",
                request_id="intent-override",
                active_scope="overall",
                focus={},
                reference_conversation_ids=[],
                execution_intent_override="api_first",
                thinking_enabled=False,
                deep_mode=False,
            )

            self.assertEqual(result["assistant_message"].execution_intent_override, "api_first")
            self.assertEqual(result["run"]["execution_intent"], "api_first")

    def test_profile_resolution_passes_thinking_flag_to_managed_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "assistant.db")
            project = db.create_project("Assistant test", "Map a complex product")
            settings = default_project_model_settings(AppConfig(embeddings_enabled=False))
            settings["llm_profiles"] = [
                {
                    "id": "local-assistant",
                    "label": "Local Assistant",
                    "base_url": "http://127.0.0.1:8080",
                    "model_name": "local-assistant",
                    "local_path": str(Path(tmpdir) / "model.gguf"),
                    "runtime_kind": "managed_local",
                    "context_window": 32768,
                    "supports_reasoning": True,
                    "supports_parallel": False,
                    "max_parallel_requests": 1,
                    "max_specialists": 2,
                    "max_output_tokens": 1800,
                }
            ]
            settings["assignments"]["assistant_orchestration"] = "local-assistant"
            db.upsert_project_model_settings(project_id=project.id, **settings)
            server_manager = MagicMock()
            service = AssistantService(db, MagicMock(), AssistantIndexService(db, MagicMock()), server_manager)

            profile = service._profile(project.id, "assistant_orchestration", thinking_enabled=True)

            self.assertEqual(profile["model_name"], "local-assistant")
            self.assertEqual(server_manager.ensure_model_loaded.call_args.kwargs["thinking_enabled"], True)

    def test_action_confirmation_becomes_stale_after_entity_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project_id = self._database(tmpdir)
            service = AssistantService(db, MagicMock(), AssistantIndexService(db, MagicMock()))
            conversation = service.create_conversation(project_id, "Decisions", "overall")
            message = db.create_assistant_message(
                conversation_id=conversation.id,
                project_id=project_id,
                role="assistant",
                status="completed",
            )
            expected = service._expected_state(project_id, "update_brief", {"notes": "Remember this"})
            proposal = db.create_assistant_action_proposal(
                project_id=project_id,
                conversation_id=conversation.id,
                message_id=message.id,
                action_type="update_brief",
                label="Update brief",
                payload={"notes": "Remember this"},
                expected_state=expected,
            )
            db.upsert_project_brief(
                project_id=project_id,
                product_idea="Changed idea",
                known_competitors=[],
                constraints="",
            )

            self.assertTrue(service.action_is_stale(proposal))


class AssistantIndexTests(unittest.TestCase):
    def test_assistant_index_uses_shared_embedding_assignment_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "assistant-index.db")
            project = db.create_project("Assistant test", "Map a complex product")
            settings = default_project_model_settings(AppConfig(embeddings_enabled=False))
            settings["embedding_profiles"] = [
                {"id": "default-embedding", "label": "Default", "model_name": "default-model"},
                {"id": "assistant-embed", "label": "Assistant", "model_name": "assistant-model"},
            ]
            settings["assignments"]["assistant_embeddings"] = "assistant-embed"
            db.upsert_project_model_settings(project_id=project.id, **settings)
            index = AssistantIndexService(db, MagicMock(model_name="fallback-model"))

            model_name = index._embedding_model(project.id)

            self.assertEqual(model_name, "assistant-model")


class PromptTests(unittest.TestCase):
    def test_render_prompt_replaces_placeholders_from_external_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "prompts.json"
            prompt_file.write_text('{"demo":"Hello {{name}}"}', encoding="utf-8")

            rendered = render_prompt("demo", {"name": "Strata"}, prompts_path=prompt_file)

            self.assertEqual(rendered, "Hello Strata")

    def test_build_system_prompt_reads_external_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "prompts.json"
            prompt_file.write_text('{"system_json_generator":"System prompt text"}', encoding="utf-8")

            rendered = build_system_prompt(prompts_path=prompt_file)

            self.assertEqual(rendered, "System prompt text")

    def test_build_system_prompt_uses_prompt_catalog_override(self) -> None:
        rendered = build_system_prompt(prompt_catalog={"system_json_generator": "Override prompt"})

        self.assertEqual(rendered, "Override prompt")

    def test_default_prompt_catalog_exposes_layer2_sub_agent_prompts(self) -> None:
        catalog = load_prompt_catalog()

        expected_keys = {
            "layer2_dynamic_coverage_family_discovery",
            "layer2_scope_coverage_critic",
            "layer2_granularity_critic",
            "layer2_overlap_dedupe_critic",
            "layer2_shared_concern_critic",
            "layer2_ambiguity_critic",
            "layer2_negative_cache_critic",
        }

        self.assertTrue(expected_keys.issubset(catalog))
        for key in expected_keys:
            self.assertIn("Return valid JSON only", catalog[key])

    def test_prompt_catalog_cache_refreshes_after_file_change(self) -> None:
        """Prompt edits on disk should be visible without clearing caches or restarting the API."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "prompts.json"
            prompt_file.write_text(json.dumps({"demo": "First {{name}}"}), encoding="utf-8")
            first = render_prompt("demo", {"name": "Strata"}, prompts_path=prompt_file)

            prompt_file.write_text(json.dumps({"demo": "Second version {{name}}"}), encoding="utf-8")
            second = render_prompt("demo", {"name": "Strata"}, prompts_path=prompt_file)

            self.assertEqual(first, "First Strata")
            self.assertEqual(second, "Second version Strata")

    def test_build_pillar_prompt_separates_memory_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "prompts.json"
            prompt_file.write_text(
                json.dumps(
                    {
                        "layer1_pillar_generation": (
                            "Rejected: {{user_rejected_ideas}}\n"
                            "Approved: {{user_approved_directions}}\n"
                            "Persisted: {{persisted_pillars}}\n"
                            "Families: {{persisted_families}}\n"
                            "Critic Summary: {{critic_coverage_summary}}\n"
                            "Critic Gaps: {{critic_uncovered_areas}}\n"
                            "Critic Lens: {{critic_recommended_lens}}"
                        )
                    }
                ),
                encoding="utf-8",
            )

            rendered = build_pillar_prompt(
                "Idea",
                ["No crypto"],
                ["Budgeting"],
                [{"title": "Budget Analysis", "description": "desc", "tags": ["budget"], "fingerprint": "concept"}],
                ["Budget Analysis"],
                "Coverage summary",
                ["Reporting gaps"],
                "Analytics and Reporting",
                "Core Outcomes",
                "Explore outcomes",
                "Explorer",
                "Role guidance",
                prompts_path=prompt_file,
            )

            self.assertIn("Rejected: - No crypto", rendered)
            self.assertIn("Approved: - Budgeting", rendered)
            self.assertIn("Persisted: - Budget Analysis", rendered)
            self.assertIn("Critic Summary: Coverage summary", rendered)
            self.assertIn("Critic Lens: Analytics and Reporting", rendered)

    def test_build_pillar_research_assessment_prompt_formats_inputs(self) -> None:
        rendered = build_pillar_research_assessment_prompt(
            product_idea="Idea",
            pillar_title="Billing",
            pillar_description="Handle subscriptions and invoices",
            competitor_matrix=[{"competitor_name": "Acme", "coverage_status": "supported"}],
            evidence=[{"url": "https://example.com", "competitor_name": "Acme", "snippet": "Hello"}],
            prompt_catalog={
                "layer1_pillar_research_assessment": (
                    "Idea={{product_idea}}\n"
                    "Pillar={{pillar_title}}\n"
                    "Matrix={{competitor_matrix}}\n"
                    "Evidence={{evidence}}"
                )
            },
        )

        self.assertIn("Pillar=Billing", rendered)
        self.assertIn("Acme", rendered)


