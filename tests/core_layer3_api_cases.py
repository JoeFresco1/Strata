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
from strata.layer3_revision import build_structured_diff
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


class Layer3ApiTests(unittest.TestCase):
    @staticmethod
    def _fixture(tmpdir: str) -> tuple[Database, object, object, object]:
        """Create a reviewed Feature Expansion for Layer 3 API integrity tests."""
        db_path = Path(tmpdir) / "layer3-api.db"
        db = Database(db_path)
        project = db.create_project("Layer 3 API", "A product")
        db.upsert_project_brief(
            project_id=project.id,
            product_idea=project.idea,
            known_competitors=[],
            constraints="",
            status="published",
        )
        pillar = db.create_node(
            project_id=project.id,
            parent_id=None,
            layer=1,
            node_type="pillar",
            title="Authoring",
            description="Create content.",
            status="kept",
        )
        feature = db.create_layer2_feature(
            project_id=project.id,
            canonical_name="Open text",
            description="Collect free-form text.",
            feature_type="question_type",
            granularity_class="feature",
            owner_pillar_id=pillar.id,
            candidate_source_ids=[],
            status="approved",
        )
        expansion = db.upsert_layer3_expansion(
            project_id=project.id,
            feature_id=feature.id,
            parent_pillar_id=pillar.id,
            parent_pillar_title=pillar.title,
            feature_name=feature.canonical_name,
            feature_description=feature.description,
            feature_intent="Collect qualitative responses.",
            expansion_groups=[{
                "id": "response-limits",
                "name": "Response limits",
                "description": "Controls for how much text can be entered.",
                "options": [{
                    "id": "one-line",
                    "name": "One-line response",
                    "description": "Limit the response to a single line.",
                    "selection_state": "undecided",
                    "configuration_kind": "boolean",
                    "default_recommendation": "Include for short-answer prompts.",
                    "rationale": "Keeps brief responses concise.",
                    "dependencies": [],
                    "overlaps_feature_ids": [],
                }],
            }],
            overlap_review=[],
            open_questions=["Should formatted text be allowed?"],
            review_state="approved",
            provenance={"source_layer2_feature_id": feature.id},
        )
        return db, project, feature, expansion

    @staticmethod
    def _client(db_path: Path, exports_dir: Path) -> TestClient:
        """Build an isolated FastAPI app over the seeded SQLite fixture."""
        config = AppConfig(
            database_backend="sqlite",
            db_path=db_path,
            exports_dir=exports_dir,
            embeddings_enabled=False,
            preferred_model_path=None,
        )
        with patch("strata.api.AppConfig", return_value=config):
            return TestClient(create_app())

    def test_editing_approved_expansion_requires_review_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, _, expansion = self._fixture(tmpdir)
            client = self._client(db.db_path, Path(tmpdir) / "exports")

            response = client.patch(
                f"/api/projects/{project.id}/layer3/expansions/{expansion.id}",
                json={"feature_intent": "Collect detailed qualitative responses.", "expected_state_token": expansion.active_revision_id},
            )

            self.assertEqual(response.status_code, 200)
            updated = response.json()["snapshot"]["layer3"]["expansions"][0]
            self.assertEqual(updated["review_state"], "needs_review")

    def test_expansion_option_edit_supports_include_exclude_add_and_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, _, expansion = self._fixture(tmpdir)
            client = self._client(db.db_path, Path(tmpdir) / "exports")
            groups = expansion.model_dump(mode="json")["expansion_groups"]
            groups[0]["options"] = [{
                **groups[0]["options"][0],
                "selection_state": "include",
            }, {
                "id": "email-only",
                "name": "Email only",
                "description": "Only accept email-like responses.",
                "selection_state": "exclude",
                "configuration_kind": "rule",
                "default_recommendation": "Exclude unless collecting contact fields.",
                "rationale": "This may overlap dedicated contact fields.",
                "dependencies": [],
                "overlaps_feature_ids": [],
            }]

            response = client.patch(
                f"/api/projects/{project.id}/layer3/expansions/{expansion.id}",
                json={"expansion_groups": groups, "open_questions": [], "expected_state_token": expansion.active_revision_id},
            )

            self.assertEqual(response.status_code, 200)
            saved_options = response.json()["snapshot"]["layer3"]["expansions"][0]["expansion_groups"][0]["options"]
            self.assertEqual([item["selection_state"] for item in saved_options], ["include", "exclude"])
            self.assertEqual(response.json()["snapshot"]["layer3"]["expansions"][0]["open_questions"], [])

    def test_overlap_edit_rejects_inactive_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, _, expansion = self._fixture(tmpdir)
            inactive = db.create_layer2_feature(
                project_id=project.id,
                canonical_name="Retired feature",
                description="No longer active.",
                feature_type="capability",
                granularity_class="feature",
                owner_pillar_id=expansion.parent_pillar_id,
                candidate_source_ids=[],
                status="cut",
            )
            client = self._client(db.db_path, Path(tmpdir) / "exports")
            groups = expansion.model_dump(mode="json")["expansion_groups"]
            groups[0]["options"][0]["overlaps_feature_ids"] = [inactive.id]

            response = client.patch(
                f"/api/projects/{project.id}/layer3/expansions/{expansion.id}",
                json={"expansion_groups": groups},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(db.get_layer3_expansion(expansion.id).expansion_groups[0].options[0].overlaps_feature_ids, [])

    def test_expansion_approval_and_export_reject_stale_layer2_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, feature, expansion = self._fixture(tmpdir)
            db.update_layer2_feature(feature.id, status="kept")
            client = self._client(db.db_path, Path(tmpdir) / "exports")

            approval = client.post(
                f"/api/projects/{project.id}/layer3/expansions/{expansion.id}/review",
                json={"action": "approve", "expected_state_token": expansion.active_revision_id},
            )
            exported = client.post(f"/api/projects/{project.id}/export/layer3")

            self.assertEqual(approval.status_code, 409)
            self.assertEqual(exported.status_code, 400)

    def test_old_layer3_card_endpoints_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, _, expansion = self._fixture(tmpdir)
            client = self._client(db.db_path, Path(tmpdir) / "exports")

            self.assertIn(client.patch(f"/api/projects/{project.id}/layer3/cards/{expansion.id}", json={}).status_code, {404, 405})
            self.assertIn(client.post(f"/api/projects/{project.id}/layer3/cards/{expansion.id}/pressure-test", json={}).status_code, {404, 405})
            self.assertIn(client.post(f"/api/projects/{project.id}/layer3/cards/{expansion.id}/competitive-analysis", json={}).status_code, {404, 405})
            self.assertIn(client.patch(f"/api/projects/{project.id}/layer3/decisions/{expansion.id}", json={}).status_code, {404, 405})
            self.assertIn(client.get(f"/api/projects/{project.id}/delivery/speckit").status_code, {404, 405})

    def test_empty_expansion_update_does_not_invalidate_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, _, expansion = self._fixture(tmpdir)
            client = self._client(db.db_path, Path(tmpdir) / "exports")

            response = client.patch(
                f"/api/projects/{project.id}/layer3/expansions/{expansion.id}",
                json={},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(db.get_layer3_expansion(expansion.id).review_state, "approved")

    def test_layer3_mutations_enforce_project_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, _, _, expansion = self._fixture(tmpdir)
            other_project = db.create_project("Other", "Another product")
            client = self._client(db.db_path, Path(tmpdir) / "exports")

            response = client.patch(
                f"/api/projects/{other_project.id}/layer3/expansions/{expansion.id}",
                json={"feature_intent": "Cross-project edit."},
            )

            self.assertEqual(response.status_code, 400)
            self.assertEqual(db.get_layer3_expansion(expansion.id).feature_intent, "Collect qualitative responses.")

    def test_candidate_apply_returns_409_for_stale_expected_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, feature, expansion = self._fixture(tmpdir)
            active = db.get_layer3_revision(expansion.active_revision_id)
            candidate = db.create_layer3_candidate(
                project_id=project.id,
                feature_id=feature.id,
                artifact_payload={**active["payload"], "feature_intent": "Generated candidate intent."},
                structured_diff=build_structured_diff(active["payload"], {**active["payload"], "feature_intent": "Generated candidate intent."}),
                field_ownership=active["field_ownership"],
                source_layer2_feature_revision=feature.updated_at.isoformat(),
                source_brief_revision="brief-r1",
                source_pillar_revision="pillar-r1",
                generation_reference="api-conflict-test",
                origin="regeneration",
                actor="system",
            )
            db.revise_active_expansion(expansion.id, {"feature_intent": "Concurrent edit."}, actor="user", origin="test")
            client = self._client(Path(tmpdir) / "layer3-api.db", Path(tmpdir) / "exports")

            response = client.post(
                f"/api/projects/{project.id}/layer3/expansions/{expansion.id}/candidates/{candidate['id']}/apply",
                json={"expected_active_revision_id": expansion.active_revision_id, "request_id": "stale-api-command"},
            )

            self.assertEqual(response.status_code, 409)

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


