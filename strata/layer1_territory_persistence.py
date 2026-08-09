from __future__ import annotations

import hashlib
from typing import Any

from strata.layer1_territory_models import (
    ArchitectureKind,
    CandidateDispositionSource,
    ClosedTerritoryScope,
    Layer1ExpansionJobResult,
    LensCoverageRecommendation,
    LensTerminalState,
    ModelRuntimeProvenance,
    PolicyHumanState,
    TerritoryDestination,
    TerritoryRunStage,
    TerritoryRunStatus,
)
from strata.layer1_territory_policy import global_completion
from strata.llm import LLMError


class Layer1TerritoryPersistenceMixin:
    def _persist_adversarial_scenarios(
        self,
        *,
        attempt_id: str,
        role: str,
        scenarios: list[dict[str, Any]],
        provenance: ModelRuntimeProvenance,
    ) -> None:
        """Persist adversarial findings through the same raw and disposition pipeline."""
        candidate_payloads = [
            {
                "candidate_id": str(item.get("candidate_id") or ""),
                "title": str(item.get("missing_product_territory") or "Unspecified blind spot"),
                "description": str(item.get("concrete_failure") or item.get("scenario") or ""),
                "concrete_product_behavior": str(item.get("missing_product_territory") or ""),
                "user_or_operator_value": str(item.get("scenario") or ""),
                "affected_actor_ids": [str(item.get("affected_actor_id"))]
                if item.get("affected_actor_id")
                else [],
                "source_discovery_item_ids": item.get("source_discovery_item_ids", []),
                "lens_specific_mechanism": str(item.get("distinctness_rationale") or ""),
                "non_generic_rationale": str(item.get("distinctness_rationale") or ""),
                "proposed_destination": str(
                    item.get("proposed_destination") or "deferred_human_review"
                ),
                "novelty_claim": "Adversarial production failure scenario.",
                "confidence": 0.5,
            }
            for item in scenarios
        ]
        self._persist_territory_attempt_candidates(
            attempt_id=attempt_id,
            candidates=candidate_payloads,
            runtime_provenance=provenance,
        )
        attempt_candidates = [
            item
            for item in self.db.list_layer1_raw_candidates(
                self.db.get_layer1_lens_attempt(attempt_id).run_id
            )
            if item.lens_attempt_id == attempt_id
        ]
        for candidate, scenario in zip(attempt_candidates, scenarios, strict=False):
            self.db.persist_layer1_adversarial_scenario(
                candidate_id=candidate.id,
                payload={**scenario, "role": role},
            )

    def _persist_architecture_payload(
        self,
        *,
        run_id: str,
        payload: dict[str, Any],
        provenance: ModelRuntimeProvenance,
    ) -> Any:
        """Validate and persist one configured architecture response."""
        try:
            kind = ArchitectureKind(str(payload.get("kind") or ""))
        except ValueError as exc:
            raise LLMError(f"Unknown architecture kind: {payload.get('kind')}") from exc
        pillars = payload.get("pillars")
        mappings = payload.get("mappings")
        if not isinstance(pillars, list) or not isinstance(mappings, list):
            raise LLMError("Architecture pillars and mappings must be lists.")
        return self.db.persist_layer1_architecture_candidate(
            run_id=run_id,
            kind=kind,
            title=str(payload.get("title") or kind.value.replace("_", " ").title()),
            rationale=str(payload.get("rationale") or ""),
            pillars=[item for item in pillars if isinstance(item, dict)],
            mappings=[item for item in mappings if isinstance(item, dict)],
            significant_non_pillar_territory_ids=self._string_values(
                payload.get("significant_non_pillar_territory_ids")
            ),
            unresolved_risk_ids=self._string_values(payload.get("unresolved_risk_ids")),
            runtime_provenance=provenance,
        )

    def _persist_territory_attempt_candidates(
        self,
        *,
        attempt_id: str,
        candidates: list[dict[str, Any]],
        runtime_provenance: ModelRuntimeProvenance,
    ) -> None:
        """Persist a complete attempt atomically so retries never see torn state."""
        with self.db.unit_of_work():
            self._persist_territory_attempt_candidates_in_unit(
                attempt_id=attempt_id,
                candidates=candidates,
                runtime_provenance=runtime_provenance,
            )

    def _persist_territory_attempt_candidates_in_unit(
        self,
        *,
        attempt_id: str,
        candidates: list[dict[str, Any]],
        runtime_provenance: ModelRuntimeProvenance,
    ) -> None:
        """Write raw rows first, then append normalization, assessment, and disposition."""
        attempt = self.db.get_layer1_lens_attempt(attempt_id)
        existing_keys = self._accepted_territory_keys(attempt.run_id)
        persisted = [
            self.db.persist_layer1_raw_candidate(
                lens_attempt_id=attempt_id,
                raw_ordinal=index,
                payload=payload,
                runtime_provenance=runtime_provenance,
            )
            for index, payload in enumerate(candidates)
        ]
        normalized = self.db.complete_layer1_normalization_batch(
            run_id=attempt.run_id,
            normalization_attempt_id=f"identity:{attempt_id}",
            normalized_by_candidate_id={
                item.id: {
                    "normalized_title": item.title,
                    "normalized_description": item.description,
                    "semantic_family": self._deterministic_semantic_family(
                        item.title,
                        item.description,
                    ),
                    "cluster_id": (
                        "identity:"
                        + hashlib.sha256(
                            self._deterministic_semantic_family(
                                item.title,
                                item.description,
                            ).encode("utf-8")
                        ).hexdigest()[:16]
                    ),
                    "destination_recommendation": item.proposed_destination.value,
                }
                for item in persisted
            },
            candidate_ids=[item.id for item in persisted],
        )
        normalized_by_id = {item.candidate_id: item for item in normalized}
        for candidate in persisted:
            key = self._territory_key(candidate.title, candidate.description)
            destination = candidate.proposed_destination
            reason = "Model-proposed routing preserved for human review."
            closed_violation_ids, generic_pattern_ids = self._territory_policy_violations(
                candidate
            )
            if candidate.weakly_attributable:
                destination = TerritoryDestination.DEFERRED_HUMAN_REVIEW
                reason = "Candidate lacks discovery-item or lens-mechanism attribution."
            elif closed_violation_ids or generic_pattern_ids:
                destination = TerritoryDestination.REJECTED_GENERIC_REPETITION
                reason = (
                    "Candidate repeats closed or active generic territory without "
                    "a material mechanism."
                )
            elif key in existing_keys:
                destination = TerritoryDestination.DUPLICATE
                reason = "Exact normalized territory already has a non-duplicate disposition."
            existing_keys.add(key)
            self.db.persist_layer1_territory_assessment(
                candidate_id=candidate.id,
                assessor=CandidateDispositionSource.DETERMINISTIC,
                payload={
                    "destination_recommendation": destination.value,
                    "lens_adherence_score": 25 if candidate.weakly_attributable else 80,
                    "useful_novelty_score": (
                        20 if destination == TerritoryDestination.DUPLICATE else 65
                    ),
                    "generic_repetition_score": (
                        90
                        if closed_violation_ids or generic_pattern_ids
                        else 70 if candidate.weakly_attributable else 20
                    ),
                    "quality_score": 60,
                    "attribution_score": 20 if candidate.weakly_attributable else 85,
                    "closed_territory_violation_ids": closed_violation_ids,
                    "anti_generic_pattern_ids": generic_pattern_ids,
                    "rationale": reason,
                },
            )
            self.db.append_layer1_candidate_disposition(
                candidate_id=candidate.id,
                destination=destination,
                source=CandidateDispositionSource.DETERMINISTIC,
                reason=reason,
                actor="layer1_territory_engine",
                command_id=f"classify:{attempt_id}",
            )
            if normalized_by_id[candidate.id].normalization_dropped:
                raise RuntimeError("Identity normalization unexpectedly dropped a candidate.")
        self._refresh_deterministic_closed_territory(attempt.run_id)

    def _refresh_deterministic_closed_territory(self, run_id: str) -> None:
        """Close accepted top-level semantic families for later independent calls."""
        candidates = self.db.list_layer1_raw_candidates(run_id)
        accepted_destinations = {
            TerritoryDestination.STANDALONE_PILLAR_CANDIDATE,
            TerritoryDestination.CROSS_CUTTING_PRODUCT_CONCERN,
            TerritoryDestination.ENTERPRISE_PLATFORM_OBLIGATION,
            TerritoryDestination.STRATEGIC_OPPORTUNITY,
        }
        added = 0
        for candidate in candidates:
            if added >= 12:
                break
            disposition = self.db.get_current_layer1_candidate_disposition(candidate.id)
            if (
                disposition is None
                or disposition.source != CandidateDispositionSource.HUMAN
                or disposition.destination not in accepted_destinations
            ):
                continue
            family_key = self._territory_key(candidate.title, "")
            logical_id = (
                f"accepted:{run_id}:"
                f"{hashlib.sha256(family_key.encode('utf-8')).hexdigest()[:16]}"
            )
            existing = self.db._fetchone(
                f"""
                SELECT id FROM layer1_closed_territory_revisions
                WHERE logical_id = {self.db.param} LIMIT 1
                """,
                (logical_id,),
            )
            if existing is not None:
                continue
            self.db.append_closed_territory_revision(
                project_id=candidate.project_id,
                logical_id=logical_id,
                run_id=run_id,
                title=candidate.title,
                description=candidate.description,
                semantic_examples=[candidate.title],
                source_family_ids=[candidate.id],
                source="accepted_semantic_family",
                scope=ClosedTerritoryScope.RUN,
                active=True,
                human_state=PolicyHumanState.APPROVED,
                reason="Application-derived from accepted top-level territory.",
                actor="layer1_territory_engine",
                command_id=f"close-accepted:{candidate.id}",
            )
            added += 1

    def _territory_policy_violations(self, candidate: Any) -> tuple[list[str], list[str]]:
        """Detect explicit semantic-policy repetition while allowing supported mechanisms."""
        text = self._territory_key(
            candidate.title,
            f"{candidate.description} {candidate.lens_specific_mechanism}",
        )
        closed_ids = [
            item.id
            for item in self.db.list_active_closed_territories(
                candidate.project_id,
                run_id=candidate.expansion_run_id,
            )
            if self._matches_policy_text(
                text,
                [item.title, *item.semantic_examples],
            )
        ]
        pattern_ids = [
            item.id
            for item in self.db.list_active_anti_generic_patterns(candidate.project_id)
            if self._matches_policy_text(
                text,
                [item.title, *item.semantic_examples],
            )
        ]
        if (closed_ids or pattern_ids) and self._materially_extends_closed_territory(candidate):
            return [], []
        return closed_ids, pattern_ids

    @staticmethod
    def _materially_extends_closed_territory(candidate: Any) -> bool:
        """Allow a closed-family interaction only when a concrete new mechanism is named."""
        if (
            not candidate.source_discovery_item_ids
            or len(candidate.lens_specific_mechanism.strip()) < 12
            or len(candidate.non_generic_rationale.strip()) < 20
        ):
            return False
        mechanism = (
            f"{candidate.lens_specific_mechanism} {candidate.non_generic_rationale}"
        ).casefold()
        concrete_markers = (
            "tenant", "role", "permission", "approval", "delegat", "workspace",
            "configur", "operator", "admin", "integration", "contract", "schema",
            "provenance", "lineage", "access", "billing", "support", "migration",
            "override", "consent", "retention", "audit", "incident", "runbook",
            "sla", "procurement", "pricing", "sdk", "api", "sandbox", "webhook",
        )
        return any(marker in mechanism for marker in concrete_markers)

    @classmethod
    def _matches_policy_text(cls, text: str, examples: list[str]) -> bool:
        """Match normalized multi-token policy examples without fuzzy overreach."""
        for example in examples:
            normalized = cls._territory_key(example, "")
            meaningful = [token for token in normalized.split() if len(token) > 4]
            if normalized and (normalized in text or (
                len(meaningful) >= 2 and all(token in text for token in meaningful)
            )):
                return True
        return False

    def _deterministic_lens_coverage(self, lens: Any, attempt_number: int) -> Any:
        """Produce reproducible lens-local coverage from durable candidate attribution."""
        candidates = self.db.list_layer1_raw_candidates(
            lens.run_id,
            lens_execution_id=lens.id,
        )
        addressed = sorted(
            {
                item_id
                for candidate in candidates
                for item_id in candidate.source_discovery_item_ids
                if item_id in lens.source_discovery_item_ids
            }
        )
        unresolved = sorted(set(lens.source_discovery_item_ids) - set(addressed))
        weak_count = sum(1 for item in candidates if item.weakly_attributable)
        dispositions = [
            self.db.get_current_layer1_candidate_disposition(item.id)
            for item in candidates
        ]
        duplicate_count = sum(
            1
            for item in dispositions
            if item is not None and item.destination == TerritoryDestination.DUPLICATE
        )
        generic_count = sum(
            1
            for item in dispositions
            if item is not None
            and item.destination == TerritoryDestination.REJECTED_GENERIC_REPETITION
        )
        count = max(1, len(candidates))
        adherence = round(100 * (1 - weak_count / count))
        useful_novelty = round(100 * (1 - (duplicate_count + generic_count) / count))
        if not unresolved and candidates:
            standalone_count = sum(
                1
                for item in dispositions
                if item is not None
                and item.destination
                == TerritoryDestination.STANDALONE_PILLAR_CANDIDATE
            )
            useful_subordinate_count = sum(
                1
                for item in dispositions
                if item is not None
                and item.destination in {
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
            )
            recommendation = (
                LensCoverageRecommendation.COVERED_WITH_SUBORDINATE_TERRITORY
                if standalone_count == 0 and useful_subordinate_count > 0
                else LensCoverageRecommendation.MARK_SATURATED
            )
        elif attempt_number >= lens.max_attempts:
            recommendation = LensCoverageRecommendation.REQUIRES_HUMAN_REVIEW
        elif (weak_count + generic_count) / count > 0.35:
            recommendation = LensCoverageRecommendation.RETRY_WITH_STRONGER_EXCLUSIONS
        else:
            recommendation = LensCoverageRecommendation.RETRY_WITH_HIGHER_TEMPERATURE
        return self.db.persist_layer1_lens_coverage(
            lens_execution_id=lens.id,
            attempt_number=attempt_number,
            payload={
                "addressed_discovery_item_ids": addressed,
                "unresolved_discovery_item_ids": unresolved,
                "high_severity_unresolved_item_ids": unresolved,
                "lens_adherence_score": adherence,
                "useful_novelty_score": useful_novelty,
                "generic_repetition_rate": generic_count / count,
                "duplicate_rate": duplicate_count / count,
                "weak_attribution_rate": weak_count / count,
                "recommendation": recommendation.value,
                "rationale": "Deterministic coverage from preserved attribution and dispositions.",
            },
        )

    def _failed_attempt_coverage(
        self,
        lens: Any,
        attempt_number: int,
        error_message: str,
    ) -> Any:
        """Record an explicit blocked recommendation for a failed independent call."""
        recommendation = (
            LensCoverageRecommendation.BLOCKED_BY_MODEL
            if attempt_number >= lens.max_attempts
            else LensCoverageRecommendation.RETRY_WITH_ALTERNATE_PROMPT
        )
        return self.db.persist_layer1_lens_coverage(
            lens_execution_id=lens.id,
            attempt_number=attempt_number,
            payload={
                "addressed_discovery_item_ids": [],
                "unresolved_discovery_item_ids": lens.source_discovery_item_ids,
                "high_severity_unresolved_item_ids": lens.source_discovery_item_ids,
                "lens_adherence_score": 0,
                "useful_novelty_score": 0,
                "generic_repetition_rate": 0,
                "duplicate_rate": 0,
                "weak_attribution_rate": 1,
                "recommendation": recommendation.value,
                "rationale": error_message,
            },
        )

    def _finish_territory_divergence(
        self,
        run_id: str,
        *,
        model_calls: int,
        hard_budget_exhausted: bool,
    ) -> Layer1ExpansionJobResult:
        """Persist global completion truth without conflating it with a lens verdict."""
        run = self.db.get_layer1_territory_run(run_id)
        lenses = self.db.list_layer1_lens_work_items(run_id)
        candidate_metrics = self.db.layer1_candidate_integrity_metrics(run_id)
        self.db.refresh_layer1_territory_clusters(run_id)
        latest_assessments = [
            assessments[-1]
            for lens in lenses
            if (assessments := self.db.list_layer1_lens_coverage(lens.id))
        ]
        unresolved = sorted(
            {
                item_id
                for assessment in latest_assessments
                for item_id in assessment.high_severity_unresolved_item_ids
            }
        )
        discovery_metrics, actor_gaps, obligation_gaps = (
            self._discovery_coverage_metrics(run, lenses)
        )
        decision = global_completion(
            required_lens_states=[lens.state for lens in lenses if lens.required],
            unresolved_high_severity_item_ids=unresolved,
            required_actor_gaps=actor_gaps,
            enterprise_obligation_gaps=obligation_gaps,
            undispositioned_candidate_count=candidate_metrics["undispositioned_candidates"],
            adversarial_complete_or_skipped=(
                not bool(run.config.get("enable_adversarial_pass", True))
                or bool(run.metrics.get("adversarial_complete"))
            ),
            hard_budget_exhausted=hard_budget_exhausted,
        )
        metrics = {
            **run.metrics,
            "candidate_integrity": candidate_metrics,
            "required_lenses": sum(1 for lens in lenses if lens.required),
            "completed_required_lenses": sum(
                1
                for lens in lenses
                if lens.required
                and lens.state
                not in {LensTerminalState.PENDING, LensTerminalState.ACTIVE}
            ),
            "model_calls": model_calls,
            "unresolved_high_severity_item_ids": unresolved,
        }
        coverage = self.db.persist_layer1_coverage_state(
            run_id=run_id,
            discovery_coverage=discovery_metrics,
            territory_diversity=self._territory_diversity_metrics(run_id),
            lens_adherence=self._lens_adherence_metrics(run_id, latest_assessments),
            candidate_integrity=candidate_metrics,
            architecture_breadth={},
            runtime_cost=self._runtime_cost_metrics(run_id),
            unresolved_high_severity_item_ids=unresolved,
            ready_for_synthesis=decision.ready_for_synthesis,
            incomplete_reasons=list(decision.reasons),
        )
        status = (
            TerritoryRunStatus.READY_FOR_SYNTHESIS
            if decision.ready_for_synthesis
            else TerritoryRunStatus.INCOMPLETE
        )
        self.db.update_layer1_territory_run(
            run_id,
            status=status,
            stage=TerritoryRunStage.ADVERSARIAL
            if run.config.get("enable_adversarial_pass", True)
            else TerritoryRunStage.SYNTHESIS,
            metrics={**metrics, "coverage_state_id": coverage.id},
            incomplete_reason=" ".join(decision.reasons),
        )
        return Layer1ExpansionJobResult(
            run_id=run_id,
            status=status,
            stage=TerritoryRunStage.ADVERSARIAL
            if run.config.get("enable_adversarial_pass", True)
            else TerritoryRunStage.SYNTHESIS,
            completed_lens_ids=[
                lens.id
                for lens in lenses
                if lens.state not in {LensTerminalState.PENDING, LensTerminalState.ACTIVE}
            ],
            unresolved_lens_ids=[
                lens.id
                for lens in lenses
                if lens.state in {
                    LensTerminalState.REQUIRES_HUMAN_DECISION,
                    LensTerminalState.BLOCKED_BY_MODEL,
                    LensTerminalState.BUDGET_EXHAUSTED,
                }
            ],
            raw_candidate_count=candidate_metrics["raw_candidates"],
            classified_candidate_count=candidate_metrics["classified_candidates"],
            undispositioned_candidate_count=candidate_metrics["undispositioned_candidates"],
            metrics=metrics,
            partial_completion=decision.incomplete,
            incomplete_reasons=list(decision.reasons),
        )
