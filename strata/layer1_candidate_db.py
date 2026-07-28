from __future__ import annotations

import uuid
from typing import Any

from strata.layer1_territory_db import territory_now
from strata.layer1_territory_models import (
    AdversarialScenarioCandidate,
    CandidateDisposition,
    CandidateDispositionSource,
    ModelRuntimeProvenance,
    NormalizedTerritoryRepresentation,
    ProductTerritoryCandidate,
    TerritoryAssessment,
    TerritoryCluster,
    TerritoryDestination,
)


class Layer1CandidateDatabaseMixin:
    """Store immutable raw territory and append-only normalization and routing state."""

    def persist_layer1_raw_candidate(
        self,
        *,
        lens_attempt_id: str,
        raw_ordinal: int,
        payload: dict[str, Any],
        runtime_provenance: ModelRuntimeProvenance,
    ) -> ProductTerritoryCandidate:
        """Persist one raw candidate immediately, before normalization or assessment."""
        attempt = self.get_layer1_lens_attempt(lens_attempt_id)
        lens = self.get_layer1_lens_work_item(attempt.lens_execution_id)
        source_item_ids = self._string_list(payload.get("source_discovery_item_ids"))
        lens_specific_mechanism = str(payload.get("lens_specific_mechanism") or "").strip()
        candidate = ProductTerritoryCandidate(
            id=str(uuid.uuid4()),
            project_id=attempt.project_id,
            expansion_run_id=attempt.run_id,
            lens_execution_id=attempt.lens_execution_id,
            lens_attempt_id=attempt.id,
            source_discovery_revision_id=lens.source_discovery_revision_id,
            source_lens_id=lens.source_lens_id,
            source_discovery_item_ids=source_item_ids,
            title=str(payload.get("title") or "Untitled territory").strip(),
            description=str(payload.get("description") or "").strip(),
            concrete_product_behavior=str(payload.get("concrete_product_behavior") or "").strip(),
            user_or_operator_value=str(payload.get("user_or_operator_value") or "").strip(),
            affected_actor_ids=self._string_list(payload.get("affected_actor_ids")),
            affected_lifecycle_stage_ids=self._string_list(payload.get("affected_lifecycle_stage_ids")),
            affected_domain_ids=self._string_list(payload.get("affected_domain_ids")),
            affected_enterprise_obligation_ids=self._string_list(
                payload.get("affected_enterprise_obligation_ids")
            ),
            affected_coverage_risk_ids=self._string_list(payload.get("affected_coverage_risk_ids")),
            lens_specific_mechanism=lens_specific_mechanism,
            non_generic_rationale=str(payload.get("non_generic_rationale") or "").strip(),
            proposed_destination=self._destination(
                payload.get("proposed_destination"),
                TerritoryDestination.DEFERRED_HUMAN_REVIEW,
            ),
            standalone_pillar_potential=self._bounded_float(
                payload.get("standalone_pillar_potential"),
                0.5,
            ),
            novelty_claim=str(payload.get("novelty_claim") or "").strip(),
            feasibility_note=str(payload.get("feasibility_note") or "").strip(),
            confidence=self._bounded_float(payload.get("confidence"), 0.5),
            weakly_attributable=not source_item_ids or not lens_specific_mechanism,
            raw_ordinal=raw_ordinal,
            raw_model_payload=dict(payload),
            runtime_provenance=runtime_provenance,
            created_at=territory_now(),
        )
        self._insert_layer1_raw_candidate(candidate)
        self.append_layer1_candidate_disposition(
            candidate_id=candidate.id,
            destination=TerritoryDestination.DEFERRED_HUMAN_REVIEW,
            source=CandidateDispositionSource.SYSTEM,
            reason="Pending downstream normalization and classification.",
            actor="layer1_candidate_ledger",
            command_id=f"pending:{candidate.lens_attempt_id}:{candidate.raw_ordinal}",
        )
        return candidate

    def _insert_layer1_raw_candidate(self, candidate: ProductTerritoryCandidate) -> None:
        """Insert immutable raw content; duplicate attempt ordinals fail deterministically."""
        self._execute(
            f"""
            INSERT INTO layer1_territory_candidates (
                id, project_id, expansion_run_id, lens_execution_id, lens_attempt_id,
                source_discovery_revision_id, source_lens_id, source_discovery_item_ids,
                title, description, concrete_product_behavior, user_or_operator_value,
                affected_actor_ids, affected_lifecycle_stage_ids, affected_domain_ids,
                affected_enterprise_obligation_ids, affected_coverage_risk_ids,
                lens_specific_mechanism, non_generic_rationale, proposed_destination,
                standalone_pillar_potential, novelty_claim, feasibility_note, confidence,
                weakly_attributable, raw_ordinal, raw_model_payload, runtime_provenance, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}
            )
            """,
            (
                candidate.id,
                candidate.project_id,
                candidate.expansion_run_id,
                candidate.lens_execution_id,
                candidate.lens_attempt_id,
                candidate.source_discovery_revision_id,
                candidate.source_lens_id,
                self._dump_json(candidate.source_discovery_item_ids),
                candidate.title,
                candidate.description,
                candidate.concrete_product_behavior,
                candidate.user_or_operator_value,
                self._dump_json(candidate.affected_actor_ids),
                self._dump_json(candidate.affected_lifecycle_stage_ids),
                self._dump_json(candidate.affected_domain_ids),
                self._dump_json(candidate.affected_enterprise_obligation_ids),
                self._dump_json(candidate.affected_coverage_risk_ids),
                candidate.lens_specific_mechanism,
                candidate.non_generic_rationale,
                candidate.proposed_destination.value,
                candidate.standalone_pillar_potential,
                candidate.novelty_claim,
                candidate.feasibility_note,
                candidate.confidence,
                candidate.weakly_attributable,
                candidate.raw_ordinal,
                self._dump_json(candidate.raw_model_payload),
                self._dump_json(candidate.runtime_provenance.model_dump(mode="json")),
                candidate.created_at.isoformat(),
            ),
        )

    def get_layer1_raw_candidate(self, candidate_id: str) -> ProductTerritoryCandidate:
        """Load an immutable raw candidate with exact attempt and discovery lineage."""
        row = self._fetchone(
            f"SELECT * FROM layer1_territory_candidates WHERE id = {self.param}",
            (candidate_id,),
        )
        if row is None:
            raise ValueError(f"Layer 1 territory candidate not found: {candidate_id}")
        return ProductTerritoryCandidate.model_validate(self._candidate_payload(dict(row)))

    def list_layer1_raw_candidates(
        self,
        run_id: str,
        *,
        lens_execution_id: str | None = None,
    ) -> list[ProductTerritoryCandidate]:
        """Return the complete immutable reservoir in deterministic generation order."""
        if lens_execution_id is None:
            rows = self._fetchall(
                f"""
                SELECT * FROM layer1_territory_candidates
                WHERE expansion_run_id = {self.param}
                ORDER BY created_at, raw_ordinal
                """,
                (run_id,),
            )
        else:
            rows = self._fetchall(
                f"""
                SELECT * FROM layer1_territory_candidates
                WHERE expansion_run_id = {self.param} AND lens_execution_id = {self.param}
                ORDER BY created_at, raw_ordinal
                """,
                (run_id, lens_execution_id),
            )
        return [
            ProductTerritoryCandidate.model_validate(self._candidate_payload(dict(row)))
            for row in rows
        ]

    def complete_layer1_normalization_batch(
        self,
        *,
        run_id: str,
        normalization_attempt_id: str,
        normalized_by_candidate_id: dict[str, dict[str, Any]],
        repair_attempt: int = 0,
        candidate_ids: list[str] | None = None,
    ) -> list[NormalizedTerritoryRepresentation]:
        """Create one normalization projection for every raw candidate, including omissions."""
        all_candidates = self.list_layer1_raw_candidates(run_id)
        selected_ids = set(candidate_ids) if candidate_ids is not None else None
        candidates = [
            candidate
            for candidate in all_candidates
            if selected_ids is None or candidate.id in selected_ids
        ]
        candidate_ids = {candidate.id for candidate in candidates}
        unknown_ids = set(normalized_by_candidate_id) - candidate_ids
        if unknown_ids:
            raise ValueError(f"Normalization referenced unknown candidate IDs: {sorted(unknown_ids)}")
        results: list[NormalizedTerritoryRepresentation] = []
        for candidate in candidates:
            payload = normalized_by_candidate_id.get(candidate.id)
            if payload is None:
                payload = {
                    "normalized_title": candidate.title,
                    "normalized_description": candidate.description,
                    "destination_recommendation": TerritoryDestination.DEFERRED_HUMAN_REVIEW.value,
                    "normalization_dropped": True,
                    "drop_reason": "Candidate omitted from normalized model response.",
                }
            results.append(self.persist_layer1_normalized_territory(
                candidate=candidate,
                normalization_attempt_id=normalization_attempt_id,
                payload=payload,
                repair_attempt=repair_attempt,
            ))
        return results

    def persist_layer1_normalized_territory(
        self,
        *,
        candidate: ProductTerritoryCandidate,
        normalization_attempt_id: str,
        payload: dict[str, Any],
        repair_attempt: int,
    ) -> NormalizedTerritoryRepresentation:
        """Append a normalized projection without modifying its raw source."""
        normalized = NormalizedTerritoryRepresentation(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            run_id=candidate.expansion_run_id,
            project_id=candidate.project_id,
            normalization_attempt_id=normalization_attempt_id,
            normalized_title=str(payload.get("normalized_title") or candidate.title).strip(),
            normalized_description=str(
                payload.get("normalized_description") or candidate.description
            ).strip(),
            semantic_family=str(payload.get("semantic_family") or "").strip(),
            cluster_id=str(payload["cluster_id"]) if payload.get("cluster_id") else None,
            canonical_terminology=str(payload.get("canonical_terminology") or "").strip(),
            duplicate_of_candidate_id=(
                str(payload["duplicate_of_candidate_id"])
                if payload.get("duplicate_of_candidate_id")
                else None
            ),
            merge_recommendation=str(payload.get("merge_recommendation") or "").strip(),
            abstraction_level_recommendation=str(
                payload.get("abstraction_level_recommendation") or ""
            ).strip(),
            destination_recommendation=self._destination(
                payload.get("destination_recommendation"),
                candidate.proposed_destination,
            ),
            normalization_dropped=bool(payload.get("normalization_dropped", False)),
            drop_reason=str(payload.get("drop_reason") or "").strip(),
            repair_attempt=repair_attempt,
            human_review_eligible=bool(payload.get("human_review_eligible", True)),
            created_at=territory_now(),
        )
        self._execute(
            f"""
            INSERT INTO layer1_normalized_territories (
                id, candidate_id, run_id, project_id, normalization_attempt_id,
                normalized_title, normalized_description, semantic_family, cluster_id,
                canonical_terminology, duplicate_of_candidate_id, merge_recommendation,
                abstraction_level_recommendation, destination_recommendation,
                normalization_dropped, drop_reason, repair_attempt,
                human_review_eligible, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}
            )
            """,
            (
                normalized.id,
                normalized.candidate_id,
                normalized.run_id,
                normalized.project_id,
                normalized.normalization_attempt_id,
                normalized.normalized_title,
                normalized.normalized_description,
                normalized.semantic_family,
                normalized.cluster_id,
                normalized.canonical_terminology,
                normalized.duplicate_of_candidate_id,
                normalized.merge_recommendation,
                normalized.abstraction_level_recommendation,
                normalized.destination_recommendation.value,
                normalized.normalization_dropped,
                normalized.drop_reason,
                normalized.repair_attempt,
                normalized.human_review_eligible,
                normalized.created_at.isoformat(),
            ),
        )
        return normalized

    def list_layer1_normalized_territories(
        self,
        run_id: str,
    ) -> list[NormalizedTerritoryRepresentation]:
        """Return all append-only normalized projections for a run."""
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_normalized_territories
            WHERE run_id = {self.param} ORDER BY created_at
            """,
            (run_id,),
        )
        return [
            NormalizedTerritoryRepresentation.model_validate(dict(row))
            for row in rows
        ]

    def append_layer1_candidate_disposition(
        self,
        *,
        candidate_id: str,
        destination: TerritoryDestination,
        source: CandidateDispositionSource,
        reason: str,
        actor: str,
        command_id: str,
        target_artifact_id: str | None = None,
    ) -> CandidateDisposition:
        """Append an authoritative routing decision; human revisions supersede model output."""
        candidate = self.get_layer1_raw_candidate(candidate_id)
        current = self.get_current_layer1_candidate_disposition(candidate_id)
        sequence_number = current.sequence_number + 1 if current else 1
        disposition = CandidateDisposition(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            run_id=candidate.expansion_run_id,
            project_id=candidate.project_id,
            sequence_number=sequence_number,
            destination=destination,
            source=source,
            reason=reason,
            supersedes_disposition_id=current.id if current else None,
            target_artifact_id=target_artifact_id,
            actor=actor,
            command_id=command_id,
            created_at=territory_now(),
        )
        self._execute(
            f"""
            INSERT INTO layer1_territory_dispositions (
                id, candidate_id, run_id, project_id, sequence_number, destination,
                source, reason, supersedes_disposition_id, target_artifact_id,
                actor, command_id, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}
            )
            """,
            (
                disposition.id,
                disposition.candidate_id,
                disposition.run_id,
                disposition.project_id,
                disposition.sequence_number,
                disposition.destination.value,
                disposition.source.value,
                disposition.reason,
                disposition.supersedes_disposition_id,
                disposition.target_artifact_id,
                disposition.actor,
                disposition.command_id,
                disposition.created_at.isoformat(),
            ),
        )
        return disposition

    def persist_layer1_territory_assessment(
        self,
        *,
        candidate_id: str,
        assessor: CandidateDispositionSource,
        payload: dict[str, Any],
    ) -> TerritoryAssessment:
        """Append an evaluator judgment while retaining the immutable raw candidate."""
        candidate = self.get_layer1_raw_candidate(candidate_id)
        assessment = TerritoryAssessment(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            run_id=candidate.expansion_run_id,
            project_id=candidate.project_id,
            assessor=assessor,
            destination_recommendation=self._destination(
                payload.get("destination_recommendation"),
                TerritoryDestination.DEFERRED_HUMAN_REVIEW,
            ),
            lens_adherence_score=self._score_100(payload.get("lens_adherence_score"), 0),
            useful_novelty_score=self._score_100(payload.get("useful_novelty_score"), 0),
            generic_repetition_score=self._score_100(
                payload.get("generic_repetition_score"),
                0,
            ),
            quality_score=self._score_100(payload.get("quality_score"), 0),
            attribution_score=self._score_100(payload.get("attribution_score"), 0),
            closed_territory_violation_ids=self._string_list(
                payload.get("closed_territory_violation_ids")
            ),
            anti_generic_pattern_ids=self._string_list(
                payload.get("anti_generic_pattern_ids")
            ),
            rationale=str(payload.get("rationale") or ""),
            created_at=territory_now(),
        )
        self._execute(
            f"""
            INSERT INTO layer1_territory_assessments (
                id, candidate_id, run_id, project_id, assessor,
                destination_recommendation, lens_adherence_score, useful_novelty_score,
                generic_repetition_score, quality_score, attribution_score,
                closed_territory_violation_ids, anti_generic_pattern_ids,
                rationale, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}
            )
            """,
            (
                assessment.id,
                assessment.candidate_id,
                assessment.run_id,
                assessment.project_id,
                assessment.assessor.value,
                assessment.destination_recommendation.value,
                assessment.lens_adherence_score,
                assessment.useful_novelty_score,
                assessment.generic_repetition_score,
                assessment.quality_score,
                assessment.attribution_score,
                self._dump_json(assessment.closed_territory_violation_ids),
                self._dump_json(assessment.anti_generic_pattern_ids),
                assessment.rationale,
                assessment.created_at.isoformat(),
            ),
        )
        return assessment

    def list_layer1_territory_assessments(
        self,
        candidate_id: str,
    ) -> list[TerritoryAssessment]:
        """Return every append-only assessment for one candidate."""
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_territory_assessments
            WHERE candidate_id = {self.param} ORDER BY created_at
            """,
            (candidate_id,),
        )
        results: list[TerritoryAssessment] = []
        for row in rows:
            payload = dict(row)
            payload["closed_territory_violation_ids"] = self._load_json(
                payload["closed_territory_violation_ids"]
            )
            payload["anti_generic_pattern_ids"] = self._load_json(
                payload["anti_generic_pattern_ids"]
            )
            results.append(TerritoryAssessment.model_validate(payload))
        return results

    def persist_layer1_adversarial_scenario(
        self,
        *,
        candidate_id: str,
        payload: dict[str, Any],
    ) -> AdversarialScenarioCandidate:
        """Link an adversarial scenario to a candidate in the same raw ledger."""
        candidate = self.get_layer1_raw_candidate(candidate_id)
        scenario = AdversarialScenarioCandidate(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            run_id=candidate.expansion_run_id,
            project_id=candidate.project_id,
            role=str(payload.get("role") or "skeptical implementation consultant"),
            scenario=str(payload.get("scenario") or ""),
            affected_actor_id=str(payload.get("affected_actor_id") or ""),
            insufficient_territory_ids=self._string_list(
                payload.get("insufficient_territory_ids")
            ),
            concrete_failure=str(payload.get("concrete_failure") or ""),
            missing_product_territory=str(payload.get("missing_product_territory") or ""),
            distinctness_rationale=str(payload.get("distinctness_rationale") or ""),
            proposed_destination=self._destination(
                payload.get("proposed_destination"),
                candidate.proposed_destination,
            ),
            severity=str(payload.get("severity") or "medium"),
            source_discovery_item_ids=self._string_list(
                payload.get("source_discovery_item_ids")
            ),
            created_at=territory_now(),
        )
        self._execute(
            f"""
            INSERT INTO layer1_adversarial_scenarios (
                id, candidate_id, run_id, project_id, role, scenario,
                affected_actor_id, insufficient_territory_ids, concrete_failure,
                missing_product_territory, distinctness_rationale,
                proposed_destination, severity, source_discovery_item_ids, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}
            )
            """,
            (
                scenario.id,
                scenario.candidate_id,
                scenario.run_id,
                scenario.project_id,
                scenario.role,
                scenario.scenario,
                scenario.affected_actor_id,
                self._dump_json(scenario.insufficient_territory_ids),
                scenario.concrete_failure,
                scenario.missing_product_territory,
                scenario.distinctness_rationale,
                scenario.proposed_destination.value,
                scenario.severity,
                self._dump_json(scenario.source_discovery_item_ids),
                scenario.created_at.isoformat(),
            ),
        )
        return scenario

    def list_layer1_adversarial_scenarios(
        self,
        run_id: str,
    ) -> list[AdversarialScenarioCandidate]:
        """Return all adversarial findings in durable generation order."""
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_adversarial_scenarios
            WHERE run_id = {self.param} ORDER BY created_at
            """,
            (run_id,),
        )
        results: list[AdversarialScenarioCandidate] = []
        for row in rows:
            payload = dict(row)
            payload["insufficient_territory_ids"] = self._load_json(
                payload["insufficient_territory_ids"]
            )
            payload["source_discovery_item_ids"] = self._load_json(
                payload["source_discovery_item_ids"]
            )
            results.append(AdversarialScenarioCandidate.model_validate(payload))
        return results

    def get_current_layer1_candidate_disposition(
        self,
        candidate_id: str,
    ) -> CandidateDisposition | None:
        """Return the latest append-only model, deterministic, or human decision."""
        row = self._fetchone(
            f"""
            SELECT * FROM layer1_territory_dispositions
            WHERE candidate_id = {self.param}
            ORDER BY sequence_number DESC LIMIT 1
            """,
            (candidate_id,),
        )
        return CandidateDisposition.model_validate(dict(row)) if row is not None else None

    def list_layer1_candidate_disposition_history(
        self,
        run_id: str,
    ) -> list[CandidateDisposition]:
        """Return complete model, deterministic, system, and human routing history."""
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_territory_dispositions
            WHERE run_id = {self.param} ORDER BY created_at, sequence_number
            """,
            (run_id,),
        )
        return [CandidateDisposition.model_validate(dict(row)) for row in rows]

    def layer1_candidate_integrity_metrics(self, run_id: str) -> dict[str, int]:
        """Calculate reproducible raw, normalized, classified, and pending counts."""
        raw_count = int(self._fetchone(
            f"""
            SELECT COUNT(*) AS count FROM layer1_territory_candidates
            WHERE expansion_run_id = {self.param}
            """,
            (run_id,),
        )["count"])
        normalized_count = int(self._fetchone(
            f"""
            SELECT COUNT(DISTINCT candidate_id) AS count FROM layer1_normalized_territories
            WHERE run_id = {self.param}
            """,
            (run_id,),
        )["count"])
        classified_count = int(self._fetchone(
            f"""
            SELECT COUNT(DISTINCT candidate_id) AS count FROM layer1_territory_dispositions
            WHERE run_id = {self.param}
            """,
            (run_id,),
        )["count"])
        dropped_count = int(self._fetchone(
            f"""
            SELECT COUNT(DISTINCT candidate_id) AS count FROM layer1_normalized_territories
            WHERE run_id = {self.param} AND normalization_dropped = {self.param}
            """,
            (run_id, True),
        )["count"])
        candidates = self.list_layer1_raw_candidates(run_id)
        destinations = [
            disposition.destination
            for candidate in candidates
            if (
                disposition :=
                self.get_current_layer1_candidate_disposition(candidate.id)
            ) is not None
        ]
        rejected = {
            TerritoryDestination.REJECTED_QUALITY,
            TerritoryDestination.REJECTED_GENERIC_REPETITION,
            TerritoryDestination.REJECTED_UNSUPPORTED,
            TerritoryDestination.REJECTED_BIZARRE,
            TerritoryDestination.OUT_OF_SCOPE,
        }
        below_layer1 = {
            TerritoryDestination.PILLAR_EXTENSION,
            TerritoryDestination.LAYER_2_FEATURE_FAMILY,
            TerritoryDestination.ACTOR_WORKSPACE,
            TerritoryDestination.OPERATIONAL_CAPABILITY,
            TerritoryDestination.COMMERCIAL_CAPABILITY,
            TerritoryDestination.DEVELOPER_PLATFORM_CAPABILITY,
            TerritoryDestination.WORKFLOW_FAMILY,
            TerritoryDestination.DECISION_MECHANISM,
            TerritoryDestination.DATA_RESPONSIBILITY,
            TerritoryDestination.GOVERNANCE_MECHANISM,
        }
        return {
            "raw_candidates": raw_count,
            "normalized_candidates": normalized_count,
            "classified_candidates": classified_count,
            "accepted_candidates": sum(
                1
                for destination in destinations
                if destination not in rejected
                and destination not in {
                    TerritoryDestination.DUPLICATE,
                    TerritoryDestination.DEFERRED_HUMAN_REVIEW,
                }
            ),
            "routed_below_layer1": sum(
                1 for destination in destinations if destination in below_layer1
            ),
            "duplicates": destinations.count(TerritoryDestination.DUPLICATE),
            "generic_repetitions": destinations.count(
                TerritoryDestination.REJECTED_GENERIC_REPETITION
            ),
            "normalization_drops": dropped_count,
            "undispositioned_candidates": max(0, raw_count - classified_count),
            "budget_deferred_candidates": destinations.count(
                TerritoryDestination.DEFERRED_HUMAN_REVIEW
            ),
        }

    def refresh_layer1_territory_clusters(self, run_id: str) -> list[TerritoryCluster]:
        """Rebuild deterministic destination families from current append-only routing."""
        run = self.get_layer1_territory_run(run_id)
        grouped: dict[str, list[str]] = {}
        for candidate in self.list_layer1_raw_candidates(run_id):
            disposition = self.get_current_layer1_candidate_disposition(candidate.id)
            family = (
                disposition.destination.value
                if disposition is not None
                else TerritoryDestination.DEFERRED_HUMAN_REVIEW.value
            )
            grouped.setdefault(family, []).append(candidate.id)
        for family, candidate_ids in grouped.items():
            existing = self._fetchone(
                f"""
                SELECT id FROM layer1_territory_clusters
                WHERE run_id = {self.param} AND semantic_family = {self.param}
                """,
                (run_id, family),
            )
            title = family.replace("_", " ").title()
            summary = {family: len(candidate_ids)}
            if existing is None:
                self._execute(
                    f"""
                    INSERT INTO layer1_territory_clusters (
                        id, run_id, project_id, title, description, semantic_family,
                        candidate_ids, representative_candidate_id,
                        destination_summary, created_at
                    ) VALUES (
                        {self.param}, {self.param}, {self.param}, {self.param},
                        {self.param}, {self.param}, {self.param}, {self.param},
                        {self.param}, {self.param}
                    )
                    """,
                    (
                        str(uuid.uuid4()),
                        run.id,
                        run.project_id,
                        title,
                        "Deterministic family based on the current candidate destination.",
                        family,
                        self._dump_json(candidate_ids),
                        candidate_ids[0],
                        self._dump_json(summary),
                        territory_now(),
                    ),
                )
            else:
                self._execute(
                    f"""
                    UPDATE layer1_territory_clusters
                    SET candidate_ids = {self.param},
                        representative_candidate_id = {self.param},
                        destination_summary = {self.param}
                    WHERE id = {self.param}
                    """,
                    (
                        self._dump_json(candidate_ids),
                        candidate_ids[0],
                        self._dump_json(summary),
                        str(existing["id"]),
                    ),
                )
        return self.list_layer1_territory_clusters(run_id)

    def list_layer1_territory_clusters(self, run_id: str) -> list[TerritoryCluster]:
        """Return current deterministic semantic families for review and synthesis."""
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_territory_clusters
            WHERE run_id = {self.param} ORDER BY semantic_family
            """,
            (run_id,),
        )
        results: list[TerritoryCluster] = []
        for row in rows:
            payload = dict(row)
            payload["candidate_ids"] = self._load_json(payload["candidate_ids"])
            payload["destination_summary"] = self._load_json(
                payload["destination_summary"]
            )
            results.append(TerritoryCluster.model_validate(payload))
        return results

    @staticmethod
    def _candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Decode all JSON columns before typed candidate validation."""
        import json
        for field in (
            "source_discovery_item_ids",
            "affected_actor_ids",
            "affected_lifecycle_stage_ids",
            "affected_domain_ids",
            "affected_enterprise_obligation_ids",
            "affected_coverage_risk_ids",
            "raw_model_payload",
            "runtime_provenance",
        ):
            if isinstance(payload[field], str):
                payload[field] = json.loads(payload[field])
        return payload

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        """Normalize model list drift without inventing discovery IDs."""
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    @staticmethod
    def _bounded_float(value: Any, default: float) -> float:
        """Clamp common model scoring drift to the canonical zero-to-one range."""
        try:
            score = float(value)
        except (TypeError, ValueError):
            return default
        if score > 1 and score <= 100:
            score /= 100
        return max(0.0, min(1.0, score))

    @staticmethod
    def _destination(value: Any, default: TerritoryDestination) -> TerritoryDestination:
        """Resolve a destination while routing unknown model labels to human review."""
        try:
            return TerritoryDestination(str(value))
        except ValueError:
            return default

    @staticmethod
    def _score_100(value: Any, default: int) -> int:
        """Clamp evaluator scoring drift to the canonical zero-to-100 range."""
        try:
            return max(0, min(100, int(float(value))))
        except (TypeError, ValueError):
            return default
