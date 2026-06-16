from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from specforge.config import AppConfig, ModelProfile, build_model_profiles, resolve_default_model_profile, resolve_reasoning_settings
from specforge.db import Database
from specforge.embeddings import EmbeddingService
from specforge.generation import GenerationService
from specforge.llm import LlamaCppClient
from specforge.models import PillarAssessment, ProjectMemory, SimilarityMatch
from specforge.project_settings import default_project_model_settings
from specforge.prompts import build_pillar_prompt, build_system_prompt, render_prompt
from specforge.brief import BriefService
from specforge.research import ResearchService


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


if __name__ == "__main__":
    unittest.main()
