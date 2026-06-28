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
    CriticResponse,
    Layer2Candidate,
    Layer2CandidateResponse,
    Layer2CoverageAssessmentResponse,
    Layer2CoverageFamilyAssessment,
    Node,
    PillarCandidate,
    PillarAssessment,
    PillarAssessmentResponse,
    PillarResponse,
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


class GenerationHelperTests(unittest.TestCase):
    def test_layer3_coverage_gap_analysis_is_bounded_and_normalized(self) -> None:
        analysis = GenerationService._validate_coverage_gap_analysis({
            "coverage_gap_analysis": {
                "coverage_score": 120,
                "summary": "Missing lifecycle behavior.",
                "gaps": [{
                    "area": "Lifecycle",
                    "severity": "high",
                    "missing": "Archived behavior",
                    "recommendation": "Define the observable archived state.",
                }],
                "complete_areas": ["Purpose"],
                "recommended_next_actions": ["Add lifecycle states"],
            },
        })

        self.assertEqual(analysis["coverage_score"], 100)
        self.assertEqual(analysis["gaps"][0]["area"], "Lifecycle")
        self.assertEqual(analysis["recommended_next_actions"], ["Add lifecycle states"])

    def test_layer3_generation_batches_never_include_empty_passes(self) -> None:
        sections = [
            "product_purpose",
            "feature_archetype",
            "supported_variants",
            "configurable_options",
            "product_behaviors",
            "validation_constraints",
            "lifecycle_states",
            "edge_cases",
        ]

        batches = GenerationService._layer3_generation_batches(sections)

        self.assertTrue(all(batches))
        self.assertEqual({item for batch in batches for item in batch}, set(sections))

    def test_layer3_pressure_sanitizer_keeps_safe_leakage_signal(self) -> None:
        pressure = {
            "ambiguity": [],
            "product_risk": [],
            "overreach": [],
            "missing_decisions": [],
            "downstream_blockers": [],
            "implementation_leakage": ["The card includes an API endpoint contract."],
            "downstream_readiness_score": 80,
            "readiness_rationale": "Otherwise clear.",
        }

        cleaned = GenerationService._sanitize_pressure_test(pressure)

        self.assertEqual(cleaned["implementation_leakage"], ["Implementation-level detail was detected in the card review."])
        self.assertEqual(GenerationService._bounded_layer3_readiness(cleaned, []), 40)

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
                known_competitors=["Acme"],
                constraints="Mobile-first",
                target_users="Field teams",
                goals=["Reduce rework"],
                preferred_directions=["Offline flows"],
                rejected_directions=["Crypto"],
                notes="Keep setup simple.",
                status="published",
            )

            context = service._published_product_idea(project.id)
            self.assertIn("Product idea: Published idea", context)
            self.assertIn("Target users: Field teams", context)
            self.assertIn("Known competitors: Acme", context)
            self.assertIn("Rejected directions: Crypto", context)

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

    def test_layer2_graph_generation_creates_reviewable_feature(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            db.upsert_project_brief(
                project_id=project.id,
                product_idea="A useful product",
                known_competitors=[],
                constraints="",
                status="published",
            )
            pillar = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Cash Flow Intelligence",
                description="Understand money movement.",
                status="kept",
            )
            service = GenerationService(db, llm_client=None)  # type: ignore[arg-type]
            service._project_llm_runtime = lambda *_args, **_kwargs: {"id": "stub", "label": "Stub Model"}  # type: ignore[method-assign]
            service._ensure_profile_loaded = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

            def stub_pass(**kwargs: object):
                if kwargs.get("schema_label") == "layer2_coverage_assessment":
                    return "", Layer2CoverageAssessmentResponse(
                        coverage_summary="Survey builder coverage is saturated for this stub.",
                        family_assessments=[
                            Layer2CoverageFamilyAssessment(
                                family=family,
                                status="covered",
                                evidence_feature_ids=[],
                            )
                            for family, _ in LAYER2_SURVEY_BUILDER_FAMILIES
                        ],
                        saturation_signal="high",
                        novelty_score=10,
                        continue_recommendation=False,
                        reasoning="Stubbed coverage says stop.",
                    )
                return "", Layer2CandidateResponse(
                    features=[
                        Layer2Candidate(
                            canonical_name="Transaction categorization",
                            description="Group incoming and outgoing transactions into meaningful categories.",
                            feature_type="workflow",
                            aliases=["Spend categorization"],
                            specificity_score=90,
                            pillar_fit_score=92,
                            distinctiveness_score=80,
                            implementation_leakage_score=5,
                            strategic_value_score=88,
                        )
                    ]
                )

            service._call_structured_json_pass = stub_pass  # type: ignore[method-assign]

            summary = service.generate_layer2_feature_graph(
                project.id,
                [pillar.id],
                max_rounds=1,
                target_per_lens=1,
            )

            graph = db.layer2_graph_snapshot(project.id)
            expected_first_round_calls = len(LAYER2_LENSES) + len(LAYER2_EXHAUSTION_FAMILIES)
            self.assertEqual(summary["raw_candidate_count"], expected_first_round_calls)
            self.assertEqual(len(graph["features"]), expected_first_round_calls)
            self.assertTrue(graph["review_open"])
            self.assertEqual(graph["features"][0]["canonical_name"], "Transaction categorization")
            self.assertTrue(graph["features"][0]["candidate_source_ids"])
            self.assertEqual(len(graph["coverage"]), 1)
            self.assertEqual(graph["coverage"][0]["content"]["saturation_signal"], "high")

    def test_layer1_generation_honors_optional_total_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            db.upsert_project_brief(
                project_id=project.id,
                product_idea="A useful product",
                known_competitors=[],
                constraints="",
                status="published",
            )
            service = GenerationService(db, llm_client=None)  # type: ignore[arg-type]
            service._ensure_profile_loaded = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            service._call_structured_json_pass = lambda **_kwargs: ("", PillarResponse(pillars=[]))  # type: ignore[method-assign]
            service._normalize_pillars = lambda **_kwargs: PillarResponse(  # type: ignore[method-assign]
                pillars=[
                    PillarCandidate(title="Cash Flow Intelligence", description="Track money.", why_it_matters="Helps users act."),
                    PillarCandidate(title="Forecasting", description="Predict money.", why_it_matters="Helps users plan."),
                ]
            )
            service._assess_pillars = lambda **_kwargs: PillarAssessmentResponse(  # type: ignore[method-assign]
                assessments=[
                    PillarAssessment(
                        title="Cash Flow Intelligence",
                        canonical_title="Cash Flow Intelligence",
                        cluster_id="cash-flow",
                        is_true_pillar=True,
                        distinctiveness_score=90,
                        strategic_value_score=90,
                        pillar_quality_score=90,
                        rationale="Strong pillar.",
                    ),
                    PillarAssessment(
                        title="Forecasting",
                        canonical_title="Forecasting",
                        cluster_id="forecasting",
                        is_true_pillar=True,
                        distinctiveness_score=90,
                        strategic_value_score=90,
                        pillar_quality_score=90,
                        rationale="Strong pillar.",
                    ),
                ]
            )
            service._run_critic = lambda **_kwargs: CriticResponse(  # type: ignore[method-assign]
                coverage_summary="Stopped at cap.",
                saturation_signal="medium",
                novelty_score=80,
                continue_recommendation=True,
                reasoning="Cap ended the run.",
            )

            summary = service.generate_pillars_until_exhausted(
                project.id,
                model_profiles=[ModelProfile(alias="stub", display_name="Stub", path=None)],
                total_cap=1,
            )

            self.assertEqual(summary.stop_reason, "total_cap_reached")
            self.assertEqual(len(summary.created_nodes), 1)
            self.assertEqual(len(db.list_nodes(project.id, parent_id=None, layer=1, node_type="pillar")), 1)

    def test_layer2_graph_generation_honors_optional_total_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            db.upsert_project_brief(
                project_id=project.id,
                product_idea="A useful product",
                known_competitors=[],
                constraints="",
                status="published",
            )
            pillar = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Cash Flow Intelligence",
                description="Understand money movement.",
                status="kept",
            )
            service = GenerationService(db, llm_client=None)  # type: ignore[arg-type]
            service._project_llm_runtime = lambda *_args, **_kwargs: {"id": "stub", "label": "Stub Model"}  # type: ignore[method-assign]
            service._ensure_profile_loaded = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

            def stub_pass(**kwargs: object):
                if kwargs.get("schema_label") == "layer2_coverage_assessment":
                    return "", Layer2CoverageAssessmentResponse(
                        coverage_summary="Survey builder coverage is saturated for this stub.",
                        family_assessments=[
                            Layer2CoverageFamilyAssessment(
                                family=family,
                                status="covered",
                                evidence_feature_ids=[],
                            )
                            for family, _ in LAYER2_SURVEY_BUILDER_FAMILIES
                        ],
                        saturation_signal="high",
                        novelty_score=10,
                        continue_recommendation=False,
                        reasoning="Stubbed coverage says stop.",
                    )
                return "", Layer2CandidateResponse(
                    features=[
                        Layer2Candidate(
                            canonical_name="Transaction categorization",
                            description="Group incoming and outgoing transactions into meaningful categories.",
                            feature_type="workflow",
                            aliases=["Spend categorization"],
                            specificity_score=90,
                            pillar_fit_score=92,
                            distinctiveness_score=80,
                            implementation_leakage_score=5,
                            strategic_value_score=88,
                        )
                    ]
                )

            service._call_structured_json_pass = stub_pass  # type: ignore[method-assign]

            summary = service.generate_layer2_feature_graph(
                project.id,
                [pillar.id],
                max_rounds=1,
                target_per_lens=1,
                total_cap=2,
            )

            graph = db.layer2_graph_snapshot(project.id)
            self.assertEqual(summary["stop_reason"], "total_cap_reached")
            self.assertEqual(len(summary["created_feature_ids"]), 2)
            self.assertEqual(len(graph["features"]), 2)

    def test_layer2_scope_gate_routes_drift_to_review(self) -> None:
        candidate = Layer2Candidate(
            canonical_name="Executive dashboard",
            description="Shows aggregate survey analytics for leaders.",
            scope_classification="adjacent_owned_elsewhere",
            pillar_fit_score=35,
        )

        status = GenerationService._layer2_candidate_status(candidate, negative_match=False)

        self.assertEqual(status, "needs_review")

    def test_layer3_generation_persists_product_level_capability_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "specforge.db")
            project = db.create_project("Test", "A useful product")
            db.upsert_project_brief(
                project_id=project.id,
                product_idea="A useful product",
                known_competitors=[],
                constraints="",
                status="published",
            )
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
                canonical_name="Branching logic rules",
                description="Conditional routing inside surveys.",
                feature_type="workflow",
                granularity_class="rule",
                owner_pillar_id=pillar.id,
                candidate_source_ids=[],
                status="approved",
            )
            sibling = db.create_layer2_feature(
                project_id=project.id,
                canonical_name="Response capture",
                description="Collect submitted answers.",
                feature_type="capability",
                granularity_class="feature",
                owner_pillar_id=pillar.id,
                candidate_source_ids=[],
                status="approved",
            )
            service = GenerationService(db, llm_client=None)  # type: ignore[arg-type]
            service._project_llm_runtime = lambda *_args, **_kwargs: {"id": "stub", "label": "Stub"}  # type: ignore[method-assign]
            service._ensure_profile_loaded = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            def stub_pass(**kwargs):
                if kwargs["schema_label"] == "capability_pressure_test":
                    return "", CapabilityPressureTestResponse(
                        pressure_test=CapabilityPressureTest(
                            downstream_readiness_score=82,
                            readiness_rationale="Clear behavior with one product decision remaining.",
                        )
                    )
                complete = CapabilityDesignResponse(
                    card=CapabilityDesignPayload(
                        product_purpose="Route respondents through relevant question paths.",
                        feature_archetype="workflow",
                        supported_variants=[{"name": "Single condition", "description": "One condition controls the route."}],
                        configurable_options=[{"name": "Fallback path", "description": "Choose the route used when no condition matches.", "required": False}],
                        product_behaviors=[{"trigger": "A response is submitted", "behavior": "Evaluate configured branch conditions", "outcome": "Continue on the matching path"}],
                        validation_constraints=[{"concept": "Complete condition", "description": "A branch must identify a valid destination."}],
                        lifecycle_states=[{"state": "draft", "meaning": "Rules remain editable", "transitions": ["active"]}],
                        dependencies=["Question response capture"],
                        edge_cases=["Multiple conditions match at the same time."],
                        product_risks=["Ambiguous rule ordering can create surprising routes."],
                        relationships=[{
                            "target_feature_id": sibling.id,
                            "relationship_type": "depends_on",
                            "rationale": "Branch evaluation consumes captured responses.",
                        }],
                        open_decisions=[{"question": "How should multiple matches be resolved?", "options": ["First match", "Explicit priority"]}],
                    )
                )
                sections = kwargs["validator"].__defaults__[0] if kwargs["validator"].__defaults__ else []
                payload = complete.card.model_dump(mode="json")
                return "", {section: payload[section] for section in sections}

            service._call_structured_json_pass = stub_pass  # type: ignore[method-assign]

            created = service.generate_capability_cards(project.id, [feature.id])
            snapshot = db.layer3_snapshot(project.id)

            self.assertEqual(len(created), 1)
            self.assertEqual(created[0].parent_pillar_id, pillar.id)
            self.assertEqual(created[0].feature_id, feature.id)
            self.assertEqual(created[0].review_state, "draft")
            self.assertEqual(created[0].downstream_readiness_score, 79)
            self.assertEqual(len(snapshot["cards"][0]["open_decisions"]), 1)
            self.assertEqual(snapshot["cards"][0]["relationships"][0]["target_feature_id"], sibling.id)
            self.assertNotIn("user_stories", snapshot["cards"][0])

    def test_layer3_review_decisions_and_export_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "strata.db")
            project = db.create_project("Test", "A useful product")
            brief = db.upsert_project_brief(
                project_id=project.id,
                product_idea="A useful product",
                known_competitors=[],
                constraints="",
                status="published",
            )
            pillar = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Reporting",
                description="Understand product outcomes.",
                status="kept",
            )
            feature = db.create_layer2_feature(
                project_id=project.id,
                canonical_name="Scheduled reports",
                description="Deliver recurring reports to selected audiences.",
                feature_type="reporting",
                granularity_class="feature",
                owner_pillar_id=pillar.id,
                candidate_source_ids=["candidate-1"],
                status="approved",
            )
            card = db.upsert_layer3_card(
                project_id=project.id,
                feature_id=feature.id,
                parent_pillar_id=pillar.id,
                parent_pillar_title=pillar.title,
                feature_name=feature.canonical_name,
                feature_description=feature.description,
                product_purpose="Keep stakeholders informed on a predictable cadence.",
                feature_archetype="reporting",
                supported_variants=[],
                configurable_options=[],
                product_behaviors=[],
                validation_constraints=[],
                lifecycle_states=[],
                dependencies=[],
                overlaps_conflicts=[],
                edge_cases=[],
                product_risks=[],
                pressure_test={"implementation_leakage": []},
                downstream_readiness_score=90,
                readiness_rationale="Clear and bounded.",
                review_state="draft",
                provenance={"source_layer2_feature_id": feature.id},
            )
            decisions = db.replace_layer3_decisions(
                project_id=project.id,
                card_id=card.id,
                decisions=[{"question": "Who may receive reports?", "options": ["Admins", "Configured audiences"]}],
            )
            db.update_layer3_decision(decisions[0].id, status="resolved", resolution="Configured audiences")
            db.update_layer3_card(card.id, review_state="approved")
            db.record_layer3_review_action(
                project_id=project.id,
                card_id=card.id,
                action_type="approve",
                payload={"note": "Reviewed"},
            )
            graph = db.layer2_graph_snapshot(project.id)
            layer3 = db.layer3_snapshot(project.id)
            review_count = db._fetchone(
                "SELECT COUNT(*) AS count FROM layer3_review_actions WHERE card_id = ?",
                (card.id,),
            )

            output = export_layer3_manifest(
                project,
                brief.model_dump(mode="json"),
                graph,
                layer3,
                Path(tmpdir),
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(payload["approved_card_count"], 1)
            self.assertEqual(int(review_count["count"]), 1)
            self.assertEqual(payload["capability_design_cards"][0]["lineage"]["layer2"]["feature_id"], feature.id)
            self.assertEqual(payload["capability_design_cards"][0]["card"]["open_decisions"][0]["status"], "resolved")

    def test_layer3_pressure_test_refreshes_stale_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "pressure.db")
            project = db.create_project("Pressure", "A product")
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
                canonical_name="Text input",
                description="Collect text.",
                feature_type="question_type",
                granularity_class="feature",
                owner_pillar_id=pillar.id,
                candidate_source_ids=[],
                status="approved",
            )
            card = db.upsert_layer3_card(
                project_id=project.id,
                feature_id=feature.id,
                parent_pillar_id=pillar.id,
                parent_pillar_title=pillar.title,
                feature_name=feature.canonical_name,
                feature_description=feature.description,
                product_purpose="Collect qualitative feedback.",
                feature_archetype="question_type",
                supported_variants=[],
                configurable_options=[],
                product_behaviors=[],
                validation_constraints=[],
                lifecycle_states=[],
                dependencies=[],
                overlaps_conflicts=[],
                edge_cases=[],
                product_risks=[],
                pressure_test={"stale": True, "implementation_leakage": []},
                downstream_readiness_score=0,
                readiness_rationale="Stale.",
                review_state="needs_review",
                provenance={},
            )
            service = GenerationService(db, llm_client=None)  # type: ignore[arg-type]
            service._project_llm_runtime = lambda *_args, **_kwargs: {"id": "stub"}  # type: ignore[method-assign]
            service._ensure_profile_loaded = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            service._call_structured_json_pass = lambda **_kwargs: (  # type: ignore[method-assign]
                "",
                CapabilityPressureTestResponse(
                    pressure_test=CapabilityPressureTest(
                        downstream_readiness_score=88,
                        readiness_rationale="Product behavior is clear.",
                    )
                ),
            )

            updated = service.pressure_test_capability_card(project.id, card.id)

            self.assertEqual(updated.downstream_readiness_score, 88)
            self.assertNotIn("stale", updated.pressure_test)
            self.assertEqual(updated.review_state, "needs_review")


