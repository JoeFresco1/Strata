from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from specforge.config import AppConfig, ModelProfile, build_model_profiles, resolve_default_model_profile, resolve_reasoning_settings
from specforge.db import Database
from specforge.generation import GenerationService
from specforge.models import PillarAssessment, ProjectMemory
from specforge.prompts import build_system_prompt, render_prompt


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


class GenerationHelperTests(unittest.TestCase):
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

        lens_name, _ = GenerationService._layer1_lens_for_round(0, memory)

        self.assertEqual(lens_name, "Analytics and Reporting")

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
            self.assertEqual(profiles[0].alias, "managed-alias")
            self.assertEqual(profiles[0].display_name, "Managed Model")

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
            self.assertEqual(profiles[0].alias, "config-alias")


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


if __name__ == "__main__":
    unittest.main()
