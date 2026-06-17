from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from specforge.config import AppConfig, ModelProfile, build_model_profiles, resolve_default_model_profile, resolve_reasoning_settings
from specforge.db import Database
from specforge.embeddings import EmbeddingService
from specforge.generation import GenerationService
from specforge.llm import LlamaCppClient
from specforge.models import Node, PillarAssessment, ProjectMemory, SimilarityMatch
from specforge.project_settings import default_project_model_settings, normalize_model_settings
from specforge.prompts import build_pillar_prompt, build_pillar_research_assessment_prompt, build_system_prompt, render_prompt
from specforge.brief import BriefService
from specforge.research import ResearchService
from specforge.research import ExtractedPage
from requests.exceptions import SSLError


class DatabaseTests(unittest.TestCase):
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
            self.assertEqual(stored.assignments["layer2_generation"], "default-chat")
            self.assertEqual(stored.prompt_catalog["system_json_generator"], "You are SpecForge, a local product specification generation engine. You must return valid JSON that matches the requested schema and avoid prose outside the JSON.")


class ProjectSettingsTests(unittest.TestCase):
    def test_normalize_model_settings_filters_invalid_profiles_and_assignments(self) -> None:
        config = AppConfig()
        normalized = normalize_model_settings(
            {
                "llm_profiles": [
                    {"id": "alpha", "label": "Alpha", "base_url": "http://localhost:8080/", "model_name": "alpha-model"},
                    {"id": "alpha", "label": "Duplicate", "base_url": "http://localhost:9999", "model_name": "ignored"},
                    {"id": "missing-model", "label": "Missing Model", "base_url": "http://localhost:8081"},
                ],
                "embedding_profiles": [
                    {"id": "embed-a", "label": "Embed A", "model_name": "embed-model"},
                    {"id": "embed-a", "label": "Duplicate", "model_name": "ignored"},
                    {"id": "embed-bad", "label": "Broken", "model_name": ""},
                ],
                "assignments": {
                    "layer0_plan": "alpha",
                    "layer1_generation": ["alpha", "missing", ""],
                    "research_embeddings": "embed-a",
                    "layer0_research": "missing",
                },
            },
            config,
        )

        self.assertEqual(len(normalized["llm_profiles"]), 1)
        self.assertEqual(normalized["llm_profiles"][0]["base_url"], "http://localhost:8080")
        self.assertEqual(len(normalized["embedding_profiles"]), 1)
        self.assertEqual(normalized["assignments"]["layer0_plan"], "alpha")
        self.assertEqual(normalized["assignments"]["layer1_generation"], ["alpha"])
        self.assertEqual(normalized["assignments"]["research_embeddings"], "embed-a")
        self.assertEqual(normalized["assignments"]["layer0_research"], "default-chat")


class EmbeddingServiceTests(unittest.TestCase):
    def test_set_model_name_updates_runtime_state(self) -> None:
        service = EmbeddingService(AppConfig())
        service._model = object()  # type: ignore[assignment]
        service.set_model_name("custom/model")

        self.assertEqual(service.model_name, "custom/model")
        self.assertIsNone(service._model)


class LLMClientTests(unittest.TestCase):
    def test_setters_update_runtime_endpoint_and_model(self) -> None:
        client = LlamaCppClient(AppConfig())
        client.set_base_url("http://localhost:9000/")
        client.set_model_name("custom-chat-model")

        self.assertEqual(client.base_url, "http://localhost:9000")
        self.assertEqual(client.model_name, "custom-chat-model")

    def test_strip_reasoning_wrappers_extracts_json_after_prefix(self) -> None:
        cleaned = LlamaCppClient._strip_reasoning_wrappers('thought\n{"pillars":[{"title":"A"}]}')

        self.assertEqual(cleaned, '{"pillars":[{"title":"A"}]}')

    def test_strip_reasoning_wrappers_handles_code_fences(self) -> None:
        cleaned = LlamaCppClient._strip_reasoning_wrappers('```json\n{"ok": true}\n```')

        self.assertEqual(cleaned, '{"ok": true}')


class BriefServiceTests(unittest.TestCase):
    def test_plan_turn_updates_same_canonical_brief(self) -> None:
        class StubClient:
            def generate_json(self, **_: object):
                class Response:
                    parsed_json = {"updates": {"known_competitors": ["Acme"], "goals": ["Faster review"]}}
                return Response()

            def generate_text(self, **_: object) -> str:
                return "Captured. What constraints matter?"

        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            service = BriefService(db, StubClient())  # type: ignore[arg-type]

            reply, brief = service.append_plan_turn(project.id, "Competitor is Acme.")

            self.assertIn("Captured", reply)
            self.assertEqual(brief.known_competitors, ["Acme"])
            self.assertEqual(brief.goals, ["Faster review"])
            self.assertEqual(len(db.list_brief_conversation(project.id)), 2)


class GenerationHelperTests(unittest.TestCase):
    def test_layer1_requires_published_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            service = GenerationService(db, llm_client=None)  # type: ignore[arg-type]

            with self.assertRaises(ValueError):
                service._published_product_idea(project.id)

            db.upsert_project_brief(
                project_id=project.id,
                product_idea="Published idea",
                known_competitors=[],
                constraints="",
                status="published",
            )

            self.assertEqual(service._published_product_idea(project.id), "Published idea")

    def test_assessment_matching_tolerates_small_renames(self) -> None:
        assessment = PillarAssessment(
            title="Household Cashflow Intelligence",
            canonical_title="Household Cash Flow Intelligence",
            cluster_id="cash-flow",
            is_true_pillar=True,
            distinctiveness_score=88,
            strategic_value_score=91,
            pillar_quality_score=90,
            rationale="Same concept with a cleaner canonical title.",
        )

        matched = GenerationService._assessment_for_pillar(
            "Household Cash Flow Intelligence",
            [assessment],
        )

        self.assertIs(matched, assessment)

    def test_pillar_quality_gate_rejects_narrow_low_quality_items(self) -> None:
        weak_assessment = PillarAssessment(
            title="CSV Import Screen",
            canonical_title="CSV Import Screen",
            cluster_id="csv-import-screen",
            is_true_pillar=True,
            distinctiveness_score=38,
            strategic_value_score=42,
            pillar_quality_score=48,
            too_narrow=True,
            rationale="Too narrow for a major pillar.",
        )

        self.assertFalse(GenerationService._passes_pillar_quality_gate(weak_assessment))

    def test_existing_pillar_family_keys_include_canonical_titles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            node = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Household Cash Flow",
                description="Cash flow planning and budget pressure management.",
                json_payload={
                    "canonical_title": "Cash Flow Intelligence",
                    "pillar_assessment": {
                        "title": "Household Cash Flow",
                        "canonical_title": "Cash Flow Intelligence",
                        "cluster_id": "cash-flow",
                        "is_true_pillar": True,
                        "distinctiveness_score": 88,
                        "strategic_value_score": 90,
                        "pillar_quality_score": 89,
                        "too_narrow": False,
                        "too_implementation_specific": False,
                        "too_broad_generic": False,
                        "merge_into": None,
                        "rename_to": None,
                        "sharpen_to": None,
                        "rationale": "Canonical family"
                    }
                },
            )
            service = GenerationService(db, llm_client=None)  # type: ignore[arg-type]

            keys = service._existing_pillar_family_keys([node])

            self.assertIn("cashflowintelligence", keys)

    def test_pillar_quality_gate_rejects_too_broad_generic_items(self) -> None:
        weak_assessment = PillarAssessment(
            title="Core Platform",
            canonical_title="Core Platform",
            cluster_id="core-platform",
            is_true_pillar=True,
            distinctiveness_score=61,
            strategic_value_score=70,
            pillar_quality_score=58,
            too_broad_generic=True,
            rationale="Too vague to be a useful Layer 1 pillar."
        )

        self.assertFalse(GenerationService._passes_pillar_quality_gate(weak_assessment))

    def test_validate_pillar_assessment_scales_1_to_10_scores(self) -> None:
        response = GenerationService._validate_pillar_assessment(
            {
                "assessments": [
                    {
                        "title": "Predictive Health",
                        "canonical_title": "Predictive Health",
                        "cluster_id": "predictive-health",
                        "is_true_pillar": True,
                        "distinctiveness_score": 8,
                        "strategic_value_score": 9,
                        "pillar_quality_score": 8,
                        "too_narrow": False,
                        "too_implementation_specific": False,
                        "too_broad_generic": False,
                        "merge_into": None,
                        "rename_to": None,
                        "sharpen_to": None,
                        "rationale": "Strong pillar.",
                    }
                ]
            }
        )

        self.assertEqual(response.assessments[0].distinctiveness_score, 80)
        self.assertEqual(response.assessments[0].strategic_value_score, 90)
        self.assertEqual(response.assessments[0].pillar_quality_score, 80)

    def test_representative_pillar_memory_collapses_same_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            node_one = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Cash Flow Intelligence",
                description="Track budget pressure.",
                json_payload={"canonical_title": "Cash Flow Intelligence", "tags": ["cashflow"]},
            )
            node_two = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Household Cash Flow",
                description="Similar family.",
                json_payload={"canonical_title": "Cash Flow Intelligence", "tags": ["budgeting"]},
            )
            service = GenerationService(db, llm_client=None)  # type: ignore[arg-type]

            packet = service._representative_pillar_memory([node_one, node_two])

            self.assertEqual(len(packet), 1)
            self.assertEqual(packet[0]["title"], "Cash Flow Intelligence")

    def test_representative_pillar_memory_collapses_same_overlap_cluster(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            service = GenerationService(db, llm_client=None)  # type: ignore[arg-type]
            cluster_payload = {
                "overlap_cluster": {
                    "cluster_id": "semantic-financial-ops",
                    "representative_node_id": "n1",
                    "representative_title": "Financial Operations Intelligence",
                    "member_count": 2,
                    "member_node_ids": ["n1", "n2"],
                    "member_titles": ["Financial Operations Intelligence", "Budget Workflow Intelligence"],
                    "average_score": 0.84,
                }
            }
            node_one = Node(
                id="n1",
                project_id="p1",
                layer=1,
                node_type="pillar",
                title="Financial Operations Intelligence",
                description="Track budgets and approvals.",
                json_payload=cluster_payload,
                created_at=datetime.now(),
            )
            node_two = Node(
                id="n2",
                project_id="p1",
                layer=1,
                node_type="pillar",
                title="Budget Workflow Intelligence",
                description="Related overlap cluster.",
                json_payload=cluster_payload,
                created_at=datetime.now(),
            )

            packet = service._representative_pillar_memory([node_one, node_two])

            self.assertEqual(len(packet), 1)
            self.assertEqual(packet[0]["title"], "Financial Operations Intelligence")

    def test_connected_similarity_clusters_group_linked_neighbors(self) -> None:
        nodes = [
            Node(id="n1", project_id="p1", layer=1, node_type="pillar", title="A", created_at=datetime.now()),
            Node(id="n2", project_id="p1", layer=1, node_type="pillar", title="B", created_at=datetime.now()),
            Node(id="n3", project_id="p1", layer=1, node_type="pillar", title="C", created_at=datetime.now()),
        ]
        adjacency = {"n1": {"n2"}, "n2": {"n1", "n3"}, "n3": {"n2"}}
        edge_scores = {("n1", "n2"): 0.82, ("n2", "n3"): 0.88}

        clusters = GenerationService._connected_similarity_clusters(nodes, adjacency, edge_scores)

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].representative_node_id, "n2")
        self.assertEqual(clusters[0].member_node_ids, ["n1", "n2", "n3"])

    def test_layer1_lens_prefers_critic_recommendation(self) -> None:
        lens_name, _ = GenerationService._layer1_lens_for_round(0, model_role="Explorer")
        self.assertEqual(lens_name, "Core Outcomes")

    def test_layer1_lens_gives_challengers_partial_independence(self) -> None:
        lens_name, _ = GenerationService._layer1_lens_for_round(0, model_role="Challenger")
        self.assertEqual(lens_name, "Analytics and Reporting")

    def test_critic_advisory_lens_is_separate_from_selected_lens(self) -> None:
        memory = ProjectMemory(
            id="x",
            project_id="p",
            scope="layer1",
            scope_id=None,
            memory_type="coverage",
            content={"recommended_next_lens": "Analytics and Reporting"},
            created_at=__import__("datetime").datetime.now(),
            updated_at=__import__("datetime").datetime.now(),
        )

        self.assertEqual(GenerationService._critic_advisory_lens(memory), "Analytics and Reporting")

    def test_semantic_similarity_payload_keeps_top_score_and_matches(self) -> None:
        payload = GenerationService._semantic_similarity_payload(
            [
                SimilarityMatch(
                    node_id="n1",
                    title="Budget Intelligence",
                    description="Budget overlap",
                    layer=1,
                    node_type="pillar",
                    score=0.91,
                ),
                SimilarityMatch(
                    node_id="n2",
                    title="Cash Flow Planning",
                    description="Cash flow overlap",
                    layer=1,
                    node_type="pillar",
                    score=0.84,
                ),
            ]
        )

        self.assertEqual(payload["top_score"], 0.91)
        self.assertEqual(len(payload["matches"]), 2)

    def test_semantic_overlap_block_uses_embedding_threshold(self) -> None:
        class StubEmbeddings:
            config = AppConfig(pillar_similarity_block_threshold=0.9)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = GenerationService(
                Database(Path(tmpdir) / "specforge.db"),
                llm_client=None,  # type: ignore[arg-type]
                embedding_service=StubEmbeddings(),  # type: ignore[arg-type]
            )

            self.assertTrue(
                service._should_block_on_semantic_overlap(
                    [SimilarityMatch(node_id="n1", title="Budget", description=None, layer=1, node_type="pillar", score=0.93)]
                )
            )
            self.assertFalse(
                service._should_block_on_semantic_overlap(
                    [SimilarityMatch(node_id="n1", title="Budget", description=None, layer=1, node_type="pillar", score=0.82)]
                )
            )

    def test_overlap_relationship_type_distinguishes_near_duplicates(self) -> None:
        self.assertEqual(GenerationService._overlap_relationship_type(0.93, 0.9), "near_duplicate")
        self.assertEqual(GenerationService._overlap_relationship_type(0.84, 0.9), "cluster_neighbor")

    def test_resolve_layer1_profiles_prefers_managed_current_model(self) -> None:
        class StubServerManager:
            def get_loaded_model_alias(self) -> str | None:
                return "managed-alias"

            def get_managed_profile(self, alias: str) -> ModelProfile:
                return ModelProfile(alias=alias, display_name="Managed Model", path=Path("C:/models/test.gguf"))

        class StubClient:
            model_name = "config-alias"

        with tempfile.TemporaryDirectory() as tmpdir:
            service = GenerationService(
                Database(Path(tmpdir) / "specforge.db"),
                StubClient(),
                server_manager=StubServerManager(),
            )  # type: ignore[arg-type]

            profiles = service._resolve_layer1_profiles(None)

            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0]["id"], "managed-alias")
            self.assertEqual(profiles[0]["label"], "Managed Model")

    def test_resolve_layer1_profiles_falls_back_to_client_model_name(self) -> None:
        class StubClient:
            model_name = "config-alias"

        with tempfile.TemporaryDirectory() as tmpdir:
            service = GenerationService(
                Database(Path(tmpdir) / "specforge.db"),
                StubClient(),
            )  # type: ignore[arg-type]

            profiles = service._resolve_layer1_profiles(None)

            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0]["id"], "config-alias")


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

            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0].path.name, "Qwen3.5-9B-Q6_K.gguf")

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
    def test_coverage_values_map_required_statuses(self) -> None:
        self.assertEqual(ResearchService._coverage_values(80), ("supported", "common", 80))
        self.assertEqual(ResearchService._coverage_values(40), ("partially_supported", "emerging", 55))
        self.assertEqual(ResearchService._coverage_values(20), ("unclear", "unclear", 45))
        self.assertEqual(ResearchService._coverage_values(0), ("not_evident", "rare", 35))

    @patch("specforge.research.requests.packages.urllib3.disable_warnings")
    @patch("specforge.research.requests.get")
    def test_research_get_retries_without_tls_verification_on_ssl_error(self, mock_get, mock_disable_warnings) -> None:
        secure_error = SSLError("tls")
        fallback_response = object()
        mock_get.side_effect = [secure_error, fallback_response]

        response = ResearchService._research_get("https://example.com", headers={"User-Agent": "SpecForge"})

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


class PromptTests(unittest.TestCase):
    def test_render_prompt_replaces_placeholders_from_external_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "prompts.json"
            prompt_file.write_text('{"demo":"Hello {{name}}"}', encoding="utf-8")

            rendered = render_prompt("demo", {"name": "SpecForge"}, prompts_path=prompt_file)

            self.assertEqual(rendered, "Hello SpecForge")

    def test_build_system_prompt_reads_external_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "prompts.json"
            prompt_file.write_text('{"system_json_generator":"System prompt text"}', encoding="utf-8")

            rendered = build_system_prompt(prompts_path=prompt_file)

            self.assertEqual(rendered, "System prompt text")

    def test_build_system_prompt_uses_prompt_catalog_override(self) -> None:
        rendered = build_system_prompt(prompt_catalog={"system_json_generator": "Override prompt"})

        self.assertEqual(rendered, "Override prompt")

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


if __name__ == "__main__":
    unittest.main()
