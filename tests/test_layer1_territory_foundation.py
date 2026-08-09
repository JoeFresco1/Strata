from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from strata.db import Database
from strata.generation import GenerationService
from strata.command_service import CommandService
from strata.command_types import (
    ActorType,
    ApplyLayer1ArchitectureCandidate,
    ClassifyTerritoryCandidate,
    CommandActor,
    CommandOrigin,
    HumanAuthorityRequiredError,
    PublishProductDiscoveryRevision,
    StartLayer1TerritoryExpansion,
    StaleSourceError,
)
from strata.api_layer1 import register_layer1_routes
from strata.layer1_territory_models import (
    ArchitectureKind,
    ArchitectureState,
    AttemptStatus,
    CandidateDispositionSource,
    ClosedTerritoryScope,
    ModelRuntimeProvenance,
    PolicyHumanState,
    TerritoryDestination,
    TerritoryRunStage,
    TerritoryRunStatus,
)
from strata.layer1_territory_policy import (
    DivergencePolicy,
    global_completion,
    next_temperature,
)
from strata.discovery_service import DiscoveryService
from strata.layer1_territory_prompts import build_territory_divergence_prompt
from strata.migrations import apply_migrations
from strata.llm import LLMError, LLMResponse
from strata.models import FeatureExpansionResponse


def empty_discovery() -> dict[str, object]:
    """Return a valid minimal Product Discovery payload."""
    return {
        "archetypes": [],
        "lenses": [{
            "id": "lens-authority",
            "title": "Actors, Authority, and Decision Rights",
            "description": "Explore who can decide, delegate, and override.",
            "source": "human_added",
            "downstream_state": "required",
            "recommendation": "required",
            "relevance_score": 0.95,
            "applicable_actor_ids": ["actor-admin"],
        }],
        "actors": [{
            "id": "actor-admin",
            "title": "Platform administrator",
            "description": "Operates delegated enterprise authority.",
            "source": "human_added",
            "downstream_state": "required",
            "relevant_lens_ids": ["lens-authority"],
        }],
        "lifecycle_stages": [],
        "enterprise_obligations": [],
        "domains": [],
        "cross_domain_opportunities": [],
        "coverage_risks": [],
        "open_questions": [],
        "summary": {},
    }


class Layer1TerritoryFoundationTests(unittest.TestCase):
    """Protect exact lineage, frozen calls, and the lossless candidate ledger."""

    def setUp(self) -> None:
        """Create a project with exact published brief and discovery lineage."""
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "territory.db")
        apply_migrations(self.db)
        self.project = self.db.create_project("Territory", "Explore broadly")
        self.db.upsert_project_brief(
            project_id=self.project.id,
            product_idea="A decision-support platform",
            problem="Teams converge prematurely",
            target_users="Product leaders",
            known_competitors=[],
            constraints="Local first",
            status="published",
        )
        brief_head = self.db.ensure_brief_revision_head(self.project.id)
        self.brief_revision_id = str(brief_head["current_published_revision_id"])
        discovery = self.db.create_discovery_revision(
            project_id=self.project.id,
            source_brief_revision_id=self.brief_revision_id,
            competitor_research_mode="no_competitor_research",
            payload=empty_discovery(),
            command_id="create-discovery",
        )
        self.discovery = self.db.transition_discovery_revision(
            revision_id=discovery.id,
            target_state="approved",
            command_id="approve-discovery",
            actor="user",
            origin="test",
        )
        self.discovery = self.db.transition_discovery_revision(
            revision_id=discovery.id,
            target_state="published",
            command_id="publish-discovery",
            actor="user",
            origin="test",
        )
        self.run = self.db.create_layer1_territory_run(
            project_id=self.project.id,
            source_brief_revision_id=self.brief_revision_id,
            source_discovery_revision_id=self.discovery.id,
            config={"candidates_per_lens": 18},
            budget={"max_model_calls": 30},
        )
        self.runtime = ModelRuntimeProvenance(
            prompt_key="layer1_territory_divergence",
            prompt_version="1",
            effective_temperature=0.65,
            exact_model_identifier="fixture-model",
        )

    def tearDown(self) -> None:
        """Remove the disposable database directory."""
        self.tmp.cleanup()

    def create_lens(
        self,
        *,
        source_lens_id: str = "lens-required",
        required: bool = True,
        risk: int = 5,
        relevance: float = 0.9,
        missing: int = 4,
        human: int = 3,
        order: int = 0,
    ) -> object:
        """Persist one canonical lens work item."""
        return self.db.create_layer1_lens_work_item(
            run_id=self.run.id,
            source_lens_id=source_lens_id,
            source_discovery_item_ids=["actor-admin", "risk-convergence"],
            title=source_lens_id,
            instruction="Explore authority and operating rights.",
            required=required,
            discovery_order=order,
            risk_priority=risk,
            relevance_score=relevance,
            missing_coverage_priority=missing,
            human_priority=human,
            max_attempts=4,
        )

    def create_attempt(self, lens: object, *, number: int = 1) -> object:
        """Create one frozen, context-independent divergence attempt."""
        return self.db.create_layer1_lens_attempt(
            lens_execution_id=lens.id,
            attempt_number=number,
            attempt_kind="divergence",
            settings={"temperature": 0.65, "candidate_target": 18},
            source_projection={"brief": {"problem": "Premature convergence"}},
            closed_territory_revision_ids=[],
            anti_generic_pattern_revision_ids=[],
            prompt_key="layer1_territory_divergence",
            prompt_version="1",
            prompt_projection_hash="fixture-hash",
            runtime_provenance=self.runtime,
        )

    def create_candidate(
        self,
        attempt: object,
        *,
        ordinal: int = 0,
        attributable: bool = True,
    ) -> object:
        """Persist one raw territory candidate directly from an attempt."""
        return self.db.persist_layer1_raw_candidate(
            lens_attempt_id=attempt.id,
            raw_ordinal=ordinal,
            payload={
                "title": f"Candidate {ordinal}",
                "description": "A concrete product territory.",
                "source_discovery_item_ids": ["actor-admin"] if attributable else [],
                "lens_specific_mechanism": "Delegated authority" if attributable else "",
                "proposed_destination": "standalone_pillar_candidate",
            },
            runtime_provenance=self.runtime,
        )

    def test_run_rejects_non_current_or_unpublished_lineage(self) -> None:
        """Layer 1 cannot detach itself from exact published upstream revisions."""
        with self.assertRaisesRegex(ValueError, "current published"):
            self.db.create_layer1_territory_run(
                project_id=self.project.id,
                source_brief_revision_id="wrong",
                source_discovery_revision_id=self.discovery.id,
                config={},
                budget={},
            )

    def test_layer1_http_schedules_jobs_and_round_trips_lens_token(self) -> None:
        """The review API schedules durable jobs and supplies required lens concurrency."""
        lens = self.create_lens()
        generation = GenerationService(self.db, SimpleNamespace())

        class FakeJobService:
            """Capture enqueued and background-executed jobs without invoking a model."""

            def __init__(self) -> None:
                self.enqueued: list[str] = []
                self.executed: list[str] = []

            def enqueue(self, **_kwargs: object) -> object:
                job_id = f"job-{len(self.enqueued) + 1}"
                self.enqueued.append(job_id)
                return SimpleNamespace(
                    id=job_id,
                    model_dump=lambda **_options: {"id": job_id, "status": "queued"},
                )

            def run_job(self, job_id: str) -> None:
                self.executed.append(job_id)

        jobs = FakeJobService()
        services = SimpleNamespace(
            db=self.db,
            generation_service=generation,
            job_service=jobs,
            brief_service=SimpleNamespace(
                ensure_brief=lambda project_id: self.db.get_project_brief(project_id)
            ),
        )
        services.command_service = CommandService(services)
        app = FastAPI()
        register_layer1_routes(app, services)

        with TestClient(app) as client:
            detail = client.get(
                f"/api/projects/{self.project.id}/layer1/exploration-runs/{self.run.id}"
            )
            self.assertEqual(detail.status_code, 200)
            lens_payload = next(
                item for item in detail.json()["lenses"] if item["id"] == lens.id
            )
            self.assertTrue(lens_payload["state_token"])
            response = client.post(
                f"/api/projects/{self.project.id}/layer1/exploration-runs/{self.run.id}/lenses/{lens.id}",
                json={
                    "action": "run",
                    "expected_state_token": lens_payload["state_token"],
                    "request_id": "http-lens-run",
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(jobs.enqueued, ["job-1"])
        self.assertEqual(jobs.executed, ["job-1"])

    def test_lens_order_uses_required_risk_relevance_missing_and_human_priority(self) -> None:
        """The application, rather than the model, owns deterministic lens order."""
        self.create_lens(source_lens_id="optional", required=False, risk=99)
        self.create_lens(source_lens_id="human", risk=5, relevance=0.9, missing=4, human=9)
        self.create_lens(source_lens_id="risk", risk=9, relevance=0.1, missing=0, human=0)
        ordered = self.db.list_layer1_lens_work_items(self.run.id)
        self.assertEqual([item.source_lens_id for item in ordered], ["risk", "human", "optional"])

    def test_attempt_settings_remain_frozen_across_checkpoints(self) -> None:
        """Runtime checkpoints cannot rewrite queued inference settings."""
        attempt = self.create_attempt(self.create_lens())
        self.db.checkpoint_layer1_lens_attempt(
            attempt.id,
            status=AttemptStatus.COMPLETED,
            raw_response='{"candidates":[]}',
            parsed_candidate_count=0,
        )
        completed = self.db.get_layer1_lens_attempt(attempt.id)
        self.assertEqual(completed.settings, attempt.settings)
        self.assertEqual(completed.source_projection, attempt.source_projection)
        self.assertEqual(completed.runtime_provenance, attempt.runtime_provenance)

    def test_malformed_response_is_preserved_on_failed_attempt(self) -> None:
        """A parse failure retains the exact raw model output on its checkpoint."""
        attempt = self.create_attempt(self.create_lens())
        service = GenerationService(self.db, SimpleNamespace())
        raw = '{"candidates": [{"title": "truncated"}'

        service._record_territory_attempt_failure(
            attempt,
            LLMError("Malformed JSON", raw_content=raw, error_type="parse_error"),
        )

        stored = self.db.get_layer1_lens_attempt(attempt.id)
        self.assertEqual(stored.status, AttemptStatus.SCHEMA_FAILED)
        self.assertEqual(stored.raw_response, raw)
        self.assertEqual(stored.error_type, "parse_error")

    def test_global_completion_preserves_adversarial_checkpoint_metrics(self) -> None:
        """Coverage recomputation cannot erase a completed adversarial pass."""
        self.db.update_layer1_territory_run(
            self.run.id,
            status=TerritoryRunStatus.RUNNING,
            stage=TerritoryRunStage.ADVERSARIAL,
            metrics={"adversarial_complete": True, "adversarial_role": "operator"},
            incomplete_reason="",
        )
        service = GenerationService(self.db, SimpleNamespace())

        service._finish_territory_divergence(
            self.run.id,
            model_calls=3,
            hard_budget_exhausted=False,
        )

        stored = self.db.get_layer1_territory_run(self.run.id)
        self.assertTrue(stored.metrics["adversarial_complete"])
        self.assertEqual(stored.metrics["adversarial_role"], "operator")

    def test_raw_candidate_is_immutable_and_missing_attribution_is_flagged(self) -> None:
        """Raw model output remains recoverable and attribution gaps stay visible."""
        candidate = self.create_candidate(
            self.create_attempt(self.create_lens()),
            attributable=False,
        )
        self.assertTrue(candidate.weakly_attributable)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db._execute(
                f"UPDATE layer1_territory_candidates SET title = {self.db.param} "
                f"WHERE id = {self.db.param}",
                ("Mutated", candidate.id),
            )

    def test_normalization_preserves_every_raw_candidate_and_marks_omissions(self) -> None:
        """A malformed or partial normalization response never loses candidates."""
        attempt = self.create_attempt(self.create_lens())
        first = self.create_candidate(attempt, ordinal=0)
        second = self.create_candidate(attempt, ordinal=1)
        rows = self.db.complete_layer1_normalization_batch(
            run_id=self.run.id,
            normalization_attempt_id="normalize-1",
            normalized_by_candidate_id={
                first.id: {
                    "normalized_title": "Authority delegation",
                    "normalized_description": "Controlled delegation.",
                    "destination_recommendation": "standalone_pillar_candidate",
                }
            },
        )
        self.assertEqual({row.candidate_id for row in rows}, {first.id, second.id})
        omitted = next(row for row in rows if row.candidate_id == second.id)
        self.assertTrue(omitted.normalization_dropped)
        self.assertTrue(omitted.human_review_eligible)
        self.assertEqual(len(self.db.list_layer1_raw_candidates(self.run.id)), 2)

    def test_human_disposition_supersedes_model_without_deleting_history(self) -> None:
        """Human routing becomes current while the prior model decision remains auditable."""
        candidate = self.create_candidate(self.create_attempt(self.create_lens()))
        model = self.db.append_layer1_candidate_disposition(
            candidate_id=candidate.id,
            destination=TerritoryDestination.REJECTED_GENERIC_REPETITION,
            source=CandidateDispositionSource.MODEL,
            reason="Generic",
            actor="model",
            command_id="model-classify",
        )
        human = self.db.append_layer1_candidate_disposition(
            candidate_id=candidate.id,
            destination=TerritoryDestination.STRATEGIC_OPPORTUNITY,
            source=CandidateDispositionSource.HUMAN,
            reason="Domain-specific opportunity",
            actor="user",
            command_id="human-reclassify",
        )
        self.assertEqual(human.supersedes_disposition_id, model.id)
        self.assertEqual(
            self.db.get_current_layer1_candidate_disposition(candidate.id).destination,
            TerritoryDestination.STRATEGIC_OPPORTUNITY,
        )

    def test_closed_territory_can_be_reopened_and_pattern_revisions_are_auditable(self) -> None:
        """Human policy revisions change effective prompts without erasing history."""
        closed = self.db.append_closed_territory_revision(
            project_id=self.project.id,
            logical_id=None,
            run_id=None,
            title="Generic evidence collection",
            description="Do not repeat generic evidence collection.",
            semantic_examples=["collect evidence"],
            source_family_ids=[],
            source="human",
            scope=ClosedTerritoryScope.PROJECT,
            active=True,
            human_state=PolicyHumanState.APPROVED,
            reason="Already covered",
            actor="user",
            command_id="close",
        )
        self.assertEqual(len(self.db.list_active_closed_territories(self.project.id)), 1)
        self.db.append_closed_territory_revision(
            project_id=self.project.id,
            logical_id=closed.logical_id,
            run_id=None,
            title=closed.title,
            description=closed.description,
            semantic_examples=closed.semantic_examples,
            source_family_ids=[],
            source="human",
            scope=ClosedTerritoryScope.PROJECT,
            active=False,
            human_state=PolicyHumanState.APPROVED,
            reason="Reopened",
            actor="user",
            command_id="reopen",
        )
        self.assertEqual(self.db.list_active_closed_territories(self.project.id), [])

        pattern = self.db.append_anti_generic_pattern_revision(
            project_id=self.project.id,
            logical_id=None,
            title="Generic SaaS lifecycle",
            description="Evidence, model, action, governance, learning.",
            semantic_examples=["feedback loop"],
            source_run_ids=[self.run.id],
            confidence=0.8,
            scope="project",
            active=True,
            human_state=PolicyHumanState.APPROVED,
            actor="user",
            command_id="pattern-1",
        )
        revised = self.db.append_anti_generic_pattern_revision(
            project_id=self.project.id,
            logical_id=pattern.logical_id,
            title=pattern.title,
            description=pattern.description,
            semantic_examples=pattern.semantic_examples,
            source_run_ids=[self.run.id],
            confidence=0.9,
            scope="project",
            active=True,
            human_state=PolicyHumanState.APPROVED,
            actor="user",
            command_id="pattern-2",
        )
        self.assertEqual(revised.revision_number, 2)

    def test_candidate_integrity_metrics_are_reproducible(self) -> None:
        """Candidate counts derive from durable rows rather than transient output."""
        attempt = self.create_attempt(self.create_lens())
        first = self.create_candidate(attempt, ordinal=0)
        self.create_candidate(attempt, ordinal=1)
        self.db.complete_layer1_normalization_batch(
            run_id=self.run.id,
            normalization_attempt_id="normalize-metrics",
            normalized_by_candidate_id={},
        )
        self.db.append_layer1_candidate_disposition(
            candidate_id=first.id,
            destination=TerritoryDestination.LAYER_2_FEATURE_FAMILY,
            source=CandidateDispositionSource.DETERMINISTIC,
            reason="Subordinate territory",
            actor="system",
            command_id="classify",
        )
        first_metrics = self.db.layer1_candidate_integrity_metrics(self.run.id)
        second_metrics = self.db.layer1_candidate_integrity_metrics(self.run.id)
        self.assertEqual(first_metrics, second_metrics)
        self.assertEqual(first_metrics["raw_candidates"], 2)
        self.assertEqual(first_metrics["normalization_drops"], 2)
        self.assertEqual(first_metrics["classified_candidates"], 2)
        self.assertEqual(first_metrics["undispositioned_candidates"], 0)

    def test_prompt_is_lens_local_and_includes_effective_exclusions(self) -> None:
        """Independent prompts include compact policy state but no prior transcripts."""
        lens = self.create_lens()
        closed = self.db.append_closed_territory_revision(
            project_id=self.project.id,
            logical_id=None,
            run_id=self.run.id,
            title="Evidence acquisition",
            description="Already represented.",
            semantic_examples=["collect signals"],
            source_family_ids=[],
            source="experiment",
            scope=ClosedTerritoryScope.RUN,
            active=True,
            human_state=PolicyHumanState.APPROVED,
            reason="Control",
            actor="user",
            command_id="close-prompt",
        )
        pattern = self.db.append_anti_generic_pattern_revision(
            project_id=self.project.id,
            logical_id=None,
            title="Generic feedback loop",
            description="A relabeled learn-and-improve cycle.",
            semantic_examples=["continuous learning"],
            source_run_ids=[self.run.id],
            confidence=0.9,
            scope="project",
            active=True,
            human_state=PolicyHumanState.APPROVED,
            actor="user",
            command_id="generic-prompt",
        )
        prompt = build_territory_divergence_prompt(
            brief_projection={"problem": "Premature convergence"},
            discovery_revision_id=self.discovery.id,
            lens=lens.model_dump(mode="json"),
            relevant_discovery_items=[{"id": "actor-admin", "title": "Administrator"}],
            required_source_ids={"actor_ids": ["actor-admin"]},
            closed_territories=[closed],
            anti_generic_patterns=[pattern],
            target_count=18,
            minimum_count=12,
        )
        self.assertIn(closed.id, prompt)
        self.assertIn(pattern.id, prompt)
        self.assertIn("Do not use or infer conversational history", prompt)
        self.assertNotIn("prior model response", prompt)

    def test_closed_territory_violation_is_rejected_without_candidate_deletion(self) -> None:
        """Explicit generic repetition is classified while its raw record survives."""
        lens = self.create_lens()
        attempt = self.create_attempt(lens)
        closed = self.db.append_closed_territory_revision(
            project_id=self.project.id,
            logical_id=None,
            run_id=self.run.id,
            title="Evidence acquisition",
            description="Already represented.",
            semantic_examples=["collect organizational evidence"],
            source_family_ids=[],
            source="human",
            scope=ClosedTerritoryScope.RUN,
            active=True,
            human_state=PolicyHumanState.APPROVED,
            reason="Covered",
            actor="user",
            command_id="close-violation",
        )
        service = GenerationService(self.db, SimpleNamespace())
        service._persist_territory_attempt_candidates(
            attempt_id=attempt.id,
            candidates=[{
                "title": "Evidence Acquisition",
                "description": "Collect organizational evidence.",
                "source_discovery_item_ids": ["actor-admin"],
                "lens_specific_mechanism": "Evidence collection",
                "non_generic_rationale": "",
                "proposed_destination": "standalone_pillar_candidate",
            }],
            runtime_provenance=self.runtime,
        )
        candidate = self.db.list_layer1_raw_candidates(self.run.id)[0]
        assessment = self.db.list_layer1_territory_assessments(candidate.id)[0]
        self.assertIn(closed.id, assessment.closed_territory_violation_ids)
        self.assertEqual(
            self.db.get_current_layer1_candidate_disposition(candidate.id).destination,
            TerritoryDestination.REJECTED_GENERIC_REPETITION,
        )
        self.assertEqual(len(self.db.list_layer1_raw_candidates(self.run.id)), 1)
        retry = self.create_attempt(lens, number=2)
        service._persist_territory_attempt_candidates(
            attempt_id=retry.id,
            candidates=[{
                "title": "Tenant-specific evidence configuration",
                "description": "Administrators configure evidence rules per tenant.",
                "source_discovery_item_ids": ["actor-admin"],
                "lens_specific_mechanism": "Tenant-scoped administrator configuration",
                "non_generic_rationale": "Adds tenant authority and configurable operating behavior.",
                "proposed_destination": "enterprise_platform_obligation",
            }],
            runtime_provenance=self.runtime,
        )
        extension = self.db.list_layer1_raw_candidates(self.run.id)[1]
        extension_assessment = self.db.list_layer1_territory_assessments(extension.id)[0]
        self.assertEqual(extension_assessment.closed_territory_violation_ids, [])
        self.assertEqual(
            self.db.get_current_layer1_candidate_disposition(extension.id).destination,
            TerritoryDestination.ENTERPRISE_PLATFORM_OBLIGATION,
        )

    def test_temperature_changes_only_for_configured_unresolved_conditions(self) -> None:
        """Low count alone does not raise temperature when the lens is well covered."""
        lens = self.create_lens()
        covered = self.db.persist_layer1_lens_coverage(
            lens_execution_id=lens.id,
            attempt_number=1,
            payload={
                "addressed_discovery_item_ids": ["actor-admin"],
                "unresolved_discovery_item_ids": [],
                "lens_adherence_score": 90,
                "useful_novelty_score": 75,
                "generic_repetition_rate": 0.1,
                "duplicate_rate": 0,
                "weak_attribution_rate": 0,
                "recommendation": "mark_saturated",
            },
        )
        self.assertEqual(
            next_temperature(
                policy=DivergencePolicy(),
                attempt_number=1,
                assessment=covered,
                budget_remaining=True,
            ),
            0.65,
        )
        unresolved = covered.model_copy(
            update={
                "unresolved_discovery_item_ids": ["risk-convergence"],
                "useful_novelty_score": 20,
            }
        )
        self.assertEqual(
            next_temperature(
                policy=DivergencePolicy(),
                attempt_number=1,
                assessment=unresolved,
                budget_remaining=True,
            ),
            0.8,
        )

    def test_frozen_policy_rehydrates_the_workflow_output_limit(self) -> None:
        """The persisted per-workflow output cap must not revert to the default."""
        policy = GenerationService._territory_policy(
            DivergencePolicy(divergence_max_output_tokens=5200).as_dict()
        )
        self.assertEqual(policy.divergence_max_output_tokens, 5200)

    def test_model_routing_cannot_silently_close_territory(self) -> None:
        """Only a human disposition may promote accepted output into exclusions."""
        lens = self.create_lens()
        attempt = self.create_attempt(lens)
        service = GenerationService(self.db, SimpleNamespace())
        service._persist_territory_attempt_candidates(
            attempt_id=attempt.id,
            candidates=[{
                "title": "Authority operating model",
                "description": "Define accountable product authority.",
                "source_discovery_item_ids": ["actor-admin"],
                "lens_specific_mechanism": "Role-bound operating authority",
                "non_generic_rationale": "Introduces role-bound approval and override rights.",
                "proposed_destination": "standalone_pillar_candidate",
            }],
            runtime_provenance=self.runtime,
        )
        candidate = self.db.list_layer1_raw_candidates(self.run.id)[0]
        self.assertEqual(
            self.db.list_active_closed_territories(self.project.id, run_id=self.run.id),
            [],
        )
        self.db.append_layer1_candidate_disposition(
            candidate_id=candidate.id,
            destination=TerritoryDestination.STANDALONE_PILLAR_CANDIDATE,
            source=CandidateDispositionSource.HUMAN,
            reason="Human accepted this semantic family.",
            actor="reviewer",
            command_id="human-close-source",
        )
        service._refresh_deterministic_closed_territory(self.run.id)
        closed = self.db.list_active_closed_territories(
            self.project.id,
            run_id=self.run.id,
        )
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0].source, "accepted_semantic_family")

    def test_global_completion_cannot_skip_required_lenses_or_hide_budget_exhaustion(self) -> None:
        """A local critic and hard budget cannot produce false global saturation."""
        from strata.layer1_territory_models import LensTerminalState

        pending = global_completion(
            required_lens_states=[LensTerminalState.PENDING, LensTerminalState.SATURATED],
            unresolved_high_severity_item_ids=[],
            required_actor_gaps=[],
            enterprise_obligation_gaps=[],
            undispositioned_candidate_count=0,
            adversarial_complete_or_skipped=True,
            hard_budget_exhausted=False,
        )
        self.assertFalse(pending.ready_for_synthesis)
        exhausted = global_completion(
            required_lens_states=[LensTerminalState.BUDGET_EXHAUSTED],
            unresolved_high_severity_item_ids=[],
            required_actor_gaps=[],
            enterprise_obligation_gaps=[],
            undispositioned_candidate_count=0,
            adversarial_complete_or_skipped=True,
            hard_budget_exhausted=True,
        )
        self.assertTrue(exhausted.incomplete)
        self.assertTrue(any("budget" in reason.lower() for reason in exhausted.reasons))

    def test_architectures_coexist_and_selection_does_not_mutate_content(self) -> None:
        """Multiple mapped views remain immutable while review state is append-only."""
        candidate = self.create_candidate(self.create_attempt(self.create_lens()))
        coverage = self.db.persist_layer1_coverage_state(
            run_id=self.run.id,
            discovery_coverage={},
            territory_diversity={},
            lens_adherence={},
            candidate_integrity={"undispositioned_candidates": 0},
            architecture_breadth={},
            runtime_cost={},
            unresolved_high_severity_item_ids=[],
            ready_for_synthesis=True,
            incomplete_reasons=[],
        )
        mapping = {
            "pillar_id": "pillar-1",
            "territory_candidate_ids": [candidate.id],
            "source_discovery_item_ids": ["actor-admin"],
        }
        first = self.db.persist_layer1_architecture_candidate(
            run_id=self.run.id,
            kind=ArchitectureKind.COHERENT_CORE,
            title="Coherent core",
            rationale="Compact responsibility boundaries.",
            pillars=[{"id": "pillar-1", "title": "Authority"}],
            mappings=[mapping],
            significant_non_pillar_territory_ids=[],
            unresolved_risk_ids=[],
            runtime_provenance=self.runtime,
        )
        second = self.db.persist_layer1_architecture_candidate(
            run_id=self.run.id,
            kind=ArchitectureKind.EXPANSIVE_DIFFERENTIATION,
            title="Expansive",
            rationale="Visible differentiation.",
            pillars=[{"id": "pillar-1", "title": "Delegated Authority"}],
            mappings=[mapping],
            significant_non_pillar_territory_ids=[candidate.id],
            unresolved_risk_ids=[],
            runtime_provenance=self.runtime,
        )
        before = [item.content_hash for item in self.db.list_layer1_architecture_candidates(self.run.id)]
        self.db.select_layer1_architecture(
            run_id=self.run.id,
            architecture_candidate_id=second.id,
            state=ArchitectureState.SELECTED,
            actor="user",
            command_id="select",
        )
        after = [item.content_hash for item in self.db.list_layer1_architecture_candidates(self.run.id)]
        self.assertEqual(before, after)
        self.assertEqual({first.id, second.id}, {
            item.id for item in self.db.list_layer1_architecture_candidates(self.run.id)
        })
        result = self.db.persist_layer1_synthesis_result(
            run_id=self.run.id,
            source_coverage_state_id=coverage.id,
            architecture_candidate_ids=[first.id, second.id],
            retained_non_pillar_territory_ids=[candidate.id],
            runtime_provenance=self.runtime,
        )
        self.assertEqual(len(result.architecture_candidate_ids), 2)

    def test_selected_architecture_requires_explicit_atomic_application(self) -> None:
        """Selection alone is inert; apply preserves old pillars and creates exact lineage."""
        candidate = self.create_candidate(self.create_attempt(self.create_lens()))
        architecture = self.db.persist_layer1_architecture_candidate(
            run_id=self.run.id,
            kind=ArchitectureKind.COHERENT_CORE,
            title="Applied core",
            rationale="A reviewed replacement map.",
            pillars=[{
                "id": "authority-core",
                "title": "Authority Core",
                "description": "Governed decision authority.",
            }],
            mappings=[{
                "pillar_id": "authority-core",
                "territory_candidate_ids": [candidate.id],
                "source_discovery_item_ids": ["actor-admin"],
            }],
            significant_non_pillar_territory_ids=[candidate.id],
            unresolved_risk_ids=[],
            runtime_provenance=self.runtime,
        )
        old = self.db.create_node(
            project_id=self.project.id,
            parent_id=None,
            layer=1,
            node_type="pillar",
            title="Original Pillar",
            description="Preserve this historical map entry.",
            status="kept",
        )
        self.db.select_layer1_architecture(
            run_id=self.run.id,
            architecture_candidate_id=architecture.id,
            state=ArchitectureState.SELECTED,
            actor="user",
            command_id="select-before-apply",
        )
        generation = GenerationService(self.db, SimpleNamespace())
        services = SimpleNamespace(
            db=self.db,
            generation_service=generation,
            brief_service=SimpleNamespace(
                ensure_brief=lambda project_id: self.db.get_project_brief(project_id)
            ),
        )
        commands = CommandService(services)
        command = ApplyLayer1ArchitectureCandidate(
            project_id=self.project.id,
            actor=CommandActor.human_ui(),
            idempotency_key="apply-selected-architecture",
            run_id=self.run.id,
            architecture_candidate_id=architecture.id,
            expected_current_pillar_tokens={old.id: commands.pillar_state_token(old)},
            confirm_replace=True,
        )
        result = commands.handle(command)
        replay = commands.handle(command)
        application = self.db.get_active_layer1_architecture_application(self.project.id)
        self.assertTrue(replay.idempotent)
        self.assertIsNotNone(application)
        self.assertEqual(application.architecture_candidate_id, architecture.id)
        self.assertEqual(application.superseded_pillar_ids, [old.id])
        self.assertEqual(self.db.get_node(old.id).status, "cut")
        created = self.db.get_node(result.data["pillars"][0]["id"])
        self.assertEqual(created.status, "kept")
        self.assertEqual(
            created.json_payload["architecture_application_id"],
            application.id,
        )
        dependencies = self.db._fetchall(
            "SELECT source_artifact_type FROM artifact_dependencies WHERE dependent_artifact_id = ?",
            (created.id,),
        )
        self.assertIn(
            "layer1_architecture_application",
            {str(item["source_artifact_type"]) for item in dependencies},
        )
        generation._project_llm_runtime = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
            "id": "stub",
            "label": "Stub Model",
        }
        generation._ensure_profile_loaded = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
        generation._run_layer2_lens_passes = lambda **_kwargs: None  # type: ignore[method-assign]
        generation._layer2_graph_summary = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
            "created_feature_ids": [],
            "raw_candidate_count": 0,
        }
        generation.generate_layer2_feature_graph(self.project.id, [created.id])
        layer2_row = self.db._fetchone(
            "SELECT id FROM layer2_generation_runs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
            (self.project.id,),
        )
        layer2_run = self.db.get_layer2_generation_run(str(layer2_row["id"]))
        self.assertEqual(layer2_run.source_architecture_application_id, application.id)
        self.assertEqual(layer2_run.source_territory_candidate_ids, [candidate.id])
        raw_feature = self.db.insert_layer2_raw_candidate(
            project_id=self.project.id,
            generation_run_id=layer2_run.id,
            source_pillar_id=created.id,
            source_lens="workflow",
            source_model="Stub Model",
            generation_round=1,
            raw_text="Governed routing",
            payload={"canonical_name": "Governed routing"},
        )
        feature = self.db.create_layer2_feature(
            project_id=self.project.id,
            canonical_name="Governed routing",
            description="Route decisions through bounded authority.",
            feature_type="workflow",
            owner_pillar_id=created.id,
            candidate_source_ids=[raw_feature.id],
            status="approved",
        )
        generation._prompt_catalog = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
        generation._call_structured_json_pass = lambda **_kwargs: (  # type: ignore[method-assign]
            SimpleNamespace(model_name="stub-model"),
            FeatureExpansionResponse(expansion={
                "feature_intent": "Route decisions through bounded authority.",
                "expansion_groups": [{
                    "name": "Authority modes",
                    "options": [{
                        "name": "Delegated route",
                        "description": "Use a reviewed delegated decision path.",
                    }],
                }],
            }),
        )
        expansion = generation.generate_feature_expansions(
            self.project.id,
            [feature.id],
        )[0]
        provenance = expansion["payload"]["provenance"]
        self.assertEqual(
            provenance["source_layer1_architecture_application_id"],
            application.id,
        )
        self.assertEqual(
            provenance["source_layer1_territory_candidate_ids"],
            [candidate.id],
        )
        layer3_dependencies = self.db._fetchall(
            "SELECT source_artifact_type FROM artifact_dependencies WHERE dependent_revision_id = ?",
            (expansion["id"],),
        )
        self.assertIn(
            "layer1_architecture_application",
            {str(item["source_artifact_type"]) for item in layer3_dependencies},
        )
        evaluated = self.db.evaluate_artifact_freshness(
            project_id=self.project.id,
            artifact_type="layer3_revision",
            artifact_id=str(expansion["logical_expansion_id"]),
            artifact_revision_id=str(expansion["id"]),
        )
        self.assertEqual(evaluated["freshness_state"], "current")
        replacement = self.db.create_discovery_revision(
            project_id=self.project.id,
            source_brief_revision_id=self.brief_revision_id,
            competitor_research_mode="no_competitor_research",
            payload=empty_discovery(),
            command_id="replacement-discovery",
        )
        replacement = self.db.transition_discovery_revision(
            revision_id=replacement.id,
            target_state="approved",
            command_id="approve-replacement-discovery",
            actor="user",
            origin="test",
        )
        services.discovery_service = DiscoveryService(services)
        publish = commands.handle(PublishProductDiscoveryRevision(
            project_id=self.project.id,
            actor=CommandActor.human_ui(),
            idempotency_key="publish-replacement-discovery",
            revision_id=replacement.id,
            expected_state_token=commands.discovery_state_token(replacement),
        ))
        self.assertEqual(publish.stale_effect.effect, "marked")
        freshness = self.db.freshness_for_artifact(
            self.project.id,
            "layer1_architecture_application",
            application.id,
            application.architecture_content_hash,
        )
        self.assertEqual(freshness["freshness_state"], "stale")
        with self.assertRaisesRegex(ValueError, "architecture is stale"):
            generation.generate_layer2_feature_graph(self.project.id, [created.id])
        with self.assertRaises(StaleSourceError):
            commands.handle(ApplyLayer1ArchitectureCandidate(
                project_id=self.project.id,
                actor=CommandActor.human_ui(),
                idempotency_key="reject-stale-architecture-apply",
                run_id=self.run.id,
                architecture_candidate_id=architecture.id,
                expected_current_pillar_tokens={
                    created.id: commands.pillar_state_token(self.db.get_node(created.id))
                },
                confirm_replace=True,
            ))
        archive = self.db.project_archive_payload(
            self.project.id,
            include_full_history=True,
        )
        self.assertEqual(len(archive["tables"]["layer1_architecture_applications"]), 1)
        imported = self.db.import_project_archive_payload(
            archive,
            name_override="Imported applied architecture",
        )["project"]
        imported_application = self.db.get_active_layer1_architecture_application(
            imported.id
        )
        self.assertIsNotNone(imported_application)
        self.assertNotEqual(imported_application.id, application.id)
        self.assertEqual(
            imported_application.architecture_content_hash,
            application.architecture_content_hash,
        )
        self.db._execute(
            "UPDATE layer1_architecture_applications SET state = 'superseded' WHERE id = ?",
            (application.id,),
        )
        with self.assertRaisesRegex(ValueError, "superseded Layer 1 architecture"):
            generation.generate_feature_expansions(self.project.id, [feature.id])

    def test_context_window_populates_territory_preflight_limit(self) -> None:
        """Production profile naming must not silently disable Layer 1 token preflight."""
        provenance = GenerationService._territory_runtime_provenance(
            {"id": "local", "model_name": "model", "context_window": 16384},
            temperature=0.65,
            prompt_key="test",
            prompt_version="1",
        )
        self.assertEqual(provenance.context_limit, 16384)

    def test_bounded_model_context_preserves_inventory_and_destination_breadth(self) -> None:
        """Compaction keeps every exact ID while bounding detailed model context."""
        territory = [
            {
                "candidate_id": f"candidate-{index:03d}",
                "title": f"Territory {index} " + ("x" * 200),
                "description": "Detailed behavior " + ("y" * 800),
                "destination": f"destination-{index % 10}",
                "source_discovery_item_ids": [f"source-{index % 7}"],
                "affected_actor_ids": [f"actor-{index % 4}"],
                "affected_domain_ids": [f"domain-{index % 6}"],
                "affected_enterprise_obligation_ids": [f"obligation-{index % 4}"],
                "affected_coverage_risk_ids": [f"risk-{index % 4}"],
                "lens_specific_mechanism": "Mechanism " + ("z" * 400),
            }
            for index in range(126)
        ]
        context = {
            "brief": {"problem": "p" * 3000},
            "discovery": {
                "lenses": [
                    {
                        "id": f"lens-{index}",
                        "title": f"Lens {index}",
                        "description": "d" * 600,
                        "required_discovery_item_ids": [f"source-{index}"],
                    }
                    for index in range(7)
                ]
            },
            "territory": territory,
            "semantic_clusters": [],
        }

        bounded = GenerationService._bounded_territory_model_context(context)

        included_ids = {
            candidate_id
            for candidate_ids in bounded["territory_inventory"].values()
            for candidate_id in candidate_ids
        }
        self.assertEqual(len(included_ids), 48)
        self.assertLessEqual(included_ids, {item["candidate_id"] for item in territory})
        self.assertEqual(
            sum(item["total"] for item in bounded["territory_population_summary"].values()),
            126,
        )
        self.assertEqual(len(bounded["territory"]), 10)
        self.assertEqual(
            len({item["destination"] for item in bounded["territory"]}),
            10,
        )
        self.assertLess(len(json.dumps(bounded)), 40_000)

    def test_unmapped_accepted_territory_is_retained_by_application(self) -> None:
        """Architecture sampling cannot silently erase accepted territory."""
        payload = {
            "mappings": [{"territory_candidate_ids": ["candidate-a"]}],
            "significant_non_pillar_territory_ids": ["candidate-b"],
        }

        retained = GenerationService._retain_unmapped_territory(
            payload,
            {"candidate-a", "candidate-b", "candidate-c"},
        )

        self.assertEqual(
            retained["significant_non_pillar_territory_ids"],
            ["candidate-b", "candidate-c"],
        )

    def test_executable_engine_persists_raw_before_downstream_work(self) -> None:
        """One real service pass uses independent context and completes from durable rows."""
        class FakeLLM:
            """Return one attributed fixture candidate and retain prompts for inspection."""

            def __init__(self) -> None:
                self.prompts: list[str] = []

            def generate_json(self, **kwargs: object) -> LLMResponse:
                """Return a valid territory envelope without external inference."""
                self.prompts.append(str(kwargs["user_prompt"]))
                payload = {
                    "candidates": [{
                        "candidate_id": "fixture-territory",
                        "source_discovery_item_ids": ["actor-admin"],
                        "title": "Delegated authority workspace",
                        "description": "Operators assign scoped rights with expiry.",
                        "concrete_product_behavior": "Issue and revoke scoped grants.",
                        "user_or_operator_value": "Administrators delegate safely.",
                        "affected_actor_ids": ["actor-admin"],
                        "lens_specific_mechanism": "Time-bounded delegated authority",
                        "non_generic_rationale": "Introduces rights issuance and revocation.",
                        "proposed_destination": "actor_workspace",
                        "standalone_pillar_potential": 0.7,
                        "confidence": 0.8,
                    }]
                }
                return LLMResponse(
                    content='{"candidates":[{"candidate_id":"fixture-territory"}]}',
                    parsed_json=payload,
                    model_name="fixture-model",
                    raw_payload={},
                )

        fake = FakeLLM()
        service = GenerationService(self.db, fake)
        run = service.start_layer1_territory_expansion(
            self.project.id,
            policy=DivergencePolicy(
                target_raw_candidates=18,
                minimum_raw_candidates=12,
                maximum_raw_candidates=30,
                max_attempts_per_lens=1,
                enable_adversarial_pass=False,
            ),
        )
        result = service.run_layer1_territory_expansion(
            run.id,
            runtime_profile={
                "id": "fixture",
                "label": "Fixture",
                "model_name": "fixture-model",
                "base_url": "http://fixture.invalid",
            },
        )
        self.assertEqual(len(fake.prompts), 1)
        self.assertIn("Do not use or infer conversational history", fake.prompts[0])
        self.assertEqual(result.raw_candidate_count, 1)
        self.assertEqual(result.classified_candidate_count, 1)
        self.assertEqual(result.undispositioned_candidate_count, 0)
        attempt = self.db.get_layer1_lens_attempt(
            self.db.list_layer1_raw_candidates(run.id)[0].lens_attempt_id
        )
        self.assertEqual(attempt.status, AttemptStatus.COMPLETED)
        self.assertTrue(attempt.raw_response)

    def test_adversarial_findings_share_ledger_and_synthesis_uses_mapped_territory(self) -> None:
        """Blind spots enter the ledger before two immutable synthesis views are stored."""
        class QueuedLLM:
            """Return divergence, adversarial, then synthesis fixture responses."""

            def __init__(self) -> None:
                self.responses = [
                    {
                        "candidates": [{
                            "candidate_id": "authority-territory",
                            "source_discovery_item_ids": ["actor-admin"],
                            "title": "Delegated authority workspace",
                            "description": "Assign scoped operating rights.",
                            "affected_actor_ids": ["actor-admin"],
                            "lens_specific_mechanism": "Scoped delegation",
                            "non_generic_rationale": "Adds explicit decision rights.",
                            "proposed_destination": "actor_workspace",
                        }]
                    },
                    {
                        "scenarios": [{
                            "scenario": "A departing admin retains emergency access.",
                            "affected_actor_id": "actor-admin",
                            "insufficient_territory_ids": ["authority-territory"],
                            "concrete_failure": "Emergency access outlives employment.",
                            "missing_product_territory": "Privileged-access succession",
                            "distinctness_rationale": "Models continuity and revocation.",
                            "proposed_destination": "governance_mechanism",
                            "severity": "high",
                            "source_discovery_item_ids": ["actor-admin"],
                        }]
                    },
                ]

            def generate_json(self, **_: object) -> LLMResponse:
                """Return the next staged fixture response."""
                payload = self.responses.pop(0)
                return LLMResponse(
                    content=str(payload),
                    parsed_json=payload,
                    model_name="fixture-model",
                    raw_payload={},
                )

        fake = QueuedLLM()
        service = GenerationService(self.db, fake)
        run = service.start_layer1_territory_expansion(
            self.project.id,
            policy=DivergencePolicy(
                max_attempts_per_lens=1,
                enable_adversarial_pass=True,
                architecture_views=(
                    "coherent_core",
                    "expansive_differentiation",
                ),
            ),
        )
        profile = {
            "id": "fixture",
            "label": "Fixture",
            "model_name": "fixture-model",
            "base_url": "http://fixture.invalid",
        }
        divergent = service.run_layer1_territory_expansion(run.id, runtime_profile=profile)
        self.assertTrue(divergent.partial_completion)
        adversarial = service.run_layer1_adversarial_pass(
            run.id,
            role="platform super-administrator",
            runtime_profile=profile,
        )
        self.assertFalse(adversarial.partial_completion)
        scenarios = self.db.list_layer1_adversarial_scenarios(run.id)
        self.assertEqual(len(scenarios), 1)
        self.assertEqual(len(self.db.list_layer1_raw_candidates(run.id)), 2)

        territory_ids = [item.id for item in self.db.list_layer1_raw_candidates(run.id)]
        fake.responses.append({
            "architectures": [
                {
                    "kind": "coherent_core",
                    "title": "Coherent core",
                    "pillars": [{"id": "core-authority", "title": "Authority"}],
                    "mappings": [{
                        "pillar_id": "core-authority",
                        "territory_candidate_ids": territory_ids,
                        "source_discovery_item_ids": ["actor-admin"],
                    }],
                    "significant_non_pillar_territory_ids": [],
                    "unresolved_risk_ids": [],
                },
                {
                    "kind": "expansive_differentiation",
                    "title": "Expansive differentiation",
                    "pillars": [{"id": "succession", "title": "Access Succession"}],
                    "mappings": [{
                        "pillar_id": "succession",
                        "territory_candidate_ids": [scenarios[0].candidate_id],
                        "source_discovery_item_ids": ["actor-admin"],
                    }],
                    "significant_non_pillar_territory_ids": [territory_ids[0]],
                    "unresolved_risk_ids": [],
                },
            ]
        })
        fake.responses.append({
            "product_domain_coverage_score": 80,
            "actor_coverage_score": 85,
            "lifecycle_coverage_score": 75,
            "enterprise_obligation_coverage_score": 80,
            "differentiation_score": 78,
            "coherence_score": 82,
            "overbroad_pillar_ids": [],
            "fragmented_pillar_ids": [],
            "hidden_territory_candidate_ids": [],
            "unresolved_high_severity_risk_ids": [],
            "needs_additional_exploration_lens": False,
            "recommended_lens": "",
            "ready_for_human_review": True,
            "rationale": "Both views retain mapped authority territory.",
        })
        architectures = service.generate_layer1_architecture_candidates(
            run.id,
            runtime_profile=profile,
        )
        self.assertEqual(len(architectures), 2)
        context = service.build_layer1_synthesis_context(run.id)
        self.assertNotIn("raw_model_payload", str(context))
        self.assertNotIn("raw_response", str(context))
        self.assertEqual(
            len(self.db.list_layer1_global_architecture_assessments(run.id)),
            1,
        )
        self.assertEqual(
            self.db.list_nodes(
                self.project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
            ),
            [],
            "Synthesis options must not mutate human-reviewed Layer 1 pillars.",
        )

    def test_canonical_start_command_is_idempotent_and_human_routing_is_protected(self) -> None:
        """Commands reuse the audit boundary and reject system candidate overrides."""
        class FakeJobs:
            """Persist jobs without provider readiness checks or background execution."""

            def __init__(self, db: Database) -> None:
                self.db = db

            def enqueue(self, **kwargs: object) -> object:
                """Mirror the durable enqueue contract."""
                return self.db.create_platform_job(**kwargs)

        generation = GenerationService(self.db, SimpleNamespace())
        services = SimpleNamespace(
            db=self.db,
            generation_service=generation,
            job_service=FakeJobs(self.db),
        )
        commands = CommandService(services)
        command = StartLayer1TerritoryExpansion(
            project_id=self.project.id,
            actor=CommandActor.human_ui(),
            idempotency_key="start-territory-idempotent",
            config={"enable_adversarial_pass": False},
        )
        first = commands.handle(command)
        second = commands.handle(command)
        self.assertFalse(first.idempotent)
        self.assertTrue(second.idempotent)
        self.assertEqual(first.data["run"]["id"], second.data["run"]["id"])

        run_id = first.data["run"]["id"]
        lens = self.db.list_layer1_lens_work_items(run_id)[0]
        attempt = self.db.create_layer1_lens_attempt(
            lens_execution_id=lens.id,
            attempt_number=1,
            attempt_kind="divergence",
            settings={},
            source_projection={},
            closed_territory_revision_ids=[],
            anti_generic_pattern_revision_ids=[],
            prompt_key="fixture",
            prompt_version="1",
            prompt_projection_hash="fixture",
            runtime_provenance=self.runtime,
        )
        candidate = self.create_candidate(attempt)
        with self.assertRaises(HumanAuthorityRequiredError):
            commands.handle(ClassifyTerritoryCandidate(
                project_id=self.project.id,
                actor=CommandActor(
                    actor_id="system",
                    actor_type=ActorType.SYSTEM,
                    origin=CommandOrigin.SYSTEM_WORKFLOW,
                ),
                candidate_id=candidate.id,
                destination="strategic_opportunity",
            ))

    def test_failed_global_critic_preserves_synthesis_and_earlier_checkpoints(self) -> None:
        """A later critic failure cannot erase candidates or architecture options."""
        lens = self.create_lens()
        candidate = self.create_candidate(self.create_attempt(lens))
        self.db.append_layer1_candidate_disposition(
            candidate_id=candidate.id,
            destination=TerritoryDestination.STANDALONE_PILLAR_CANDIDATE,
            source=CandidateDispositionSource.HUMAN,
            reason="Use in synthesis.",
            actor="user",
            command_id="accept-territory",
        )
        self.db.refresh_layer1_territory_clusters(self.run.id)
        self.db.persist_layer1_coverage_state(
            run_id=self.run.id,
            discovery_coverage={},
            territory_diversity={},
            lens_adherence={},
            candidate_integrity=self.db.layer1_candidate_integrity_metrics(self.run.id),
            architecture_breadth={},
            runtime_cost={},
            unresolved_high_severity_item_ids=[],
            ready_for_synthesis=True,
            incomplete_reasons=[],
        )

        class SynthesisThenFailure:
            """Return valid synthesis, then fail the separate global critic."""

            calls = 0

            def generate_json(self, **_: object) -> LLMResponse:
                """Return one architecture response before raising a critic error."""
                self.calls += 1
                if self.calls > 1:
                    raise LLMError("Global critic timed out")
                payload = {
                    "architectures": [
                        {
                            "kind": "coherent_core",
                            "title": "Core",
                            "pillars": [{"id": "core", "title": "Core authority"}],
                            "mappings": [{
                                "pillar_id": "core",
                                "territory_candidate_ids": [candidate.id],
                            }],
                            "significant_non_pillar_territory_ids": [],
                            "unresolved_risk_ids": [],
                        },
                        {
                            "kind": "expansive_differentiation",
                            "title": "Expansive",
                            "pillars": [{"id": "expanded", "title": "Expanded authority"}],
                            "mappings": [{
                                "pillar_id": "expanded",
                                "territory_candidate_ids": [candidate.id],
                            }],
                            "significant_non_pillar_territory_ids": [],
                            "unresolved_risk_ids": [],
                        },
                    ]
                }
                return LLMResponse(
                    content=str(payload),
                    parsed_json=payload,
                    model_name="fixture-model",
                    raw_payload={},
                )

        service = GenerationService(self.db, SynthesisThenFailure())
        with self.assertRaisesRegex(LLMError, "Global critic timed out"):
            service.generate_layer1_architecture_candidates(
                self.run.id,
                runtime_profile={
                    "id": "fixture",
                    "label": "Fixture",
                    "model_name": "fixture-model",
                    "base_url": "http://fixture.invalid",
                },
            )
        self.assertEqual(
            len(self.db.list_layer1_architecture_candidates(self.run.id)),
            2,
        )
        self.assertEqual(len(self.db.list_layer1_raw_candidates(self.run.id)), 1)
        self.assertEqual(
            self.db.get_layer1_territory_run(self.run.id).status,
            TerritoryRunStatus.INCOMPLETE,
        )

        class CriticSuccess:
            def generate_json(self, **_: object) -> LLMResponse:
                payload = {"ready_for_human_review": True}
                return LLMResponse(
                    content=str(payload),
                    parsed_json=payload,
                    model_name="fixture-model",
                    raw_payload={},
                )

        resumed = GenerationService(self.db, CriticSuccess())
        reviewed = resumed.review_existing_layer1_architecture_candidates(
            self.run.id,
            runtime_profile={
                "id": "fixture",
                "label": "Fixture",
                "model_name": "fixture-model",
                "base_url": "http://fixture.invalid",
            },
        )
        self.assertEqual(len(reviewed), 2)
        completed = self.db._fetchone(
            "SELECT COUNT(*) AS count FROM layer1_synthesis_results "
            "WHERE run_id = ? AND status = 'completed'",
            (self.run.id,),
        )
        self.assertEqual(int(completed["count"]), 1)

    def test_no_new_pillar_can_complete_lens_with_subordinate_territory(self) -> None:
        """Useful below-pillar territory counts as lens coverage without pillar inflation."""
        lens = self.create_lens()
        attempt = self.create_attempt(lens)
        service = GenerationService(self.db, SimpleNamespace())
        service._persist_territory_attempt_candidates(
            attempt_id=attempt.id,
            candidates=[{
                "title": "Delegation audit workflow",
                "description": "Review expired delegated rights.",
                "source_discovery_item_ids": lens.source_discovery_item_ids,
                "lens_specific_mechanism": "Expiry review",
                "non_generic_rationale": "Creates explicit delegated-rights review.",
                "proposed_destination": "layer_2_feature_family",
            }],
            runtime_provenance=self.runtime,
        )
        normalized = self.db.list_layer1_normalized_territories(self.run.id)
        self.assertEqual(normalized[0].semantic_family, "delegation audit")
        self.assertTrue(normalized[0].cluster_id.startswith("identity:"))
        coverage = service._deterministic_lens_coverage(lens, 1)
        self.assertEqual(
            coverage.recommendation.value,
            "covered_with_subordinate_territory",
        )
        self.assertEqual(coverage.unresolved_discovery_item_ids, [])

    def test_independent_retry_preserves_raw_but_does_not_duplicate_acceptance(self) -> None:
        """Repeated output remains auditable while only the first copy stays accepted."""
        lens = self.create_lens()
        first_attempt = self.create_attempt(lens, number=1)
        second_attempt = self.create_attempt(lens, number=2)
        service = GenerationService(self.db, SimpleNamespace())
        payload = {
            "title": "Scoped authority delegation",
            "description": "Assign bounded rights to tenant operators.",
            "source_discovery_item_ids": ["actor-admin"],
            "lens_specific_mechanism": "Bounded delegation",
            "non_generic_rationale": "Introduces scoped issuance and revocation rights.",
            "proposed_destination": "actor_workspace",
        }
        service._persist_territory_attempt_candidates(
            attempt_id=first_attempt.id,
            candidates=[payload],
            runtime_provenance=self.runtime,
        )
        service._persist_territory_attempt_candidates(
            attempt_id=second_attempt.id,
            candidates=[payload],
            runtime_provenance=self.runtime,
        )
        candidates = self.db.list_layer1_raw_candidates(self.run.id)
        destinations = [
            self.db.get_current_layer1_candidate_disposition(item.id).destination
            for item in candidates
        ]
        self.assertEqual(len(candidates), 2)
        self.assertEqual(destinations.count(TerritoryDestination.ACTOR_WORKSPACE), 1)
        self.assertEqual(destinations.count(TerritoryDestination.DUPLICATE), 1)
        self.assertTrue(
            all(item.runtime_provenance.exact_model_identifier for item in candidates)
        )

    def test_project_archive_round_trip_keeps_territory_lineage(self) -> None:
        """Clone/import portability includes canonical exploration checkpoints."""
        candidate = self.create_candidate(self.create_attempt(self.create_lens()))
        payload = self.db.project_archive_payload(
            self.project.id,
            include_full_history=True,
        )
        self.assertEqual(len(payload["tables"]["layer1_territory_runs"]), 1)
        self.assertEqual(len(payload["tables"]["layer1_territory_candidates"]), 1)
        imported = self.db.import_project_archive_payload(
            payload,
            name_override="Imported territory",
        )
        imported_project_id = imported["project"].id
        imported_runs = self.db.list_layer1_territory_runs(imported_project_id)
        self.assertEqual(len(imported_runs), 1)
        imported_candidates = self.db.list_layer1_raw_candidates(imported_runs[0].id)
        self.assertEqual(len(imported_candidates), 1)
        self.assertNotEqual(imported_candidates[0].id, candidate.id)
        self.assertEqual(
            imported_candidates[0].source_discovery_revision_id,
            imported_runs[0].source_discovery_revision_id,
        )


if __name__ == "__main__":
    unittest.main()
