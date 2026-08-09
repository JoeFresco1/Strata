from __future__ import annotations

from typing import Any

from strata.layer1_territory_models import (
    ArchitectureKind,
    ModelRuntimeProvenance,
    TerritoryDestination,
    TerritoryRunStage,
    TerritoryRunStatus,
)
from strata.layer1_territory_prompts import (
    build_architecture_synthesis_prompt,
    build_global_architecture_critic_prompt,
)
from strata.llm import LLMError
from strata.telemetry import model_call_context


class Layer1TerritorySynthesisMixin:
    def generate_layer1_architecture_candidates(
        self,
        run_id: str,
        *,
        runtime_profile: dict[str, Any] | None = None,
        allow_unresolved_risks_for_evaluation: bool = False,
    ) -> list[Any]:
        """Generate mapped immutable architecture options from accepted territory only.

        The evaluation override permits option generation when unresolved risks are
        the only gate. Those risks remain explicit in the prompt and no architecture
        is selected or applied.
        """
        run = self.db.get_layer1_territory_run(run_id)
        if run.status == TerritoryRunStatus.CANCELLED:
            raise ValueError("Cancelled Layer 1 runs cannot generate architectures.")
        coverage = self.db.get_latest_layer1_coverage_state(run_id)
        risk_retaining_evaluation = bool(
            coverage
            and allow_unresolved_risks_for_evaluation
            and coverage.unresolved_high_severity_item_ids
            and set(coverage.incomplete_reasons)
            == {"High-severity discovery risks remain unresolved."}
        )
        if coverage is None or (
            not coverage.ready_for_synthesis and not risk_retaining_evaluation
        ):
            raise ValueError("Layer 1 exploration is not ready for architecture synthesis.")
        profile = runtime_profile or self._resolve_layer1_profiles(run.project_id, None)[0]
        self._ensure_profile_loaded(profile)
        context = self.build_layer1_synthesis_context(run_id)
        model_context = self._bounded_territory_model_context(context)
        requested_views = list(run.config.get("architecture_views") or [
            ArchitectureKind.COHERENT_CORE.value,
            ArchitectureKind.EXPANSIVE_DIFFERENTIATION.value,
        ])
        if len(requested_views) < 2:
            raise ValueError("Layer 1 synthesis requires at least two configured views.")
        prompt = build_architecture_synthesis_prompt(
            brief_projection=model_context["brief"],
            discovery_projection=model_context["discovery"],
            territory_projection=model_context["territory"],
            territory_inventory=model_context["territory_inventory"],
            territory_population_summary=model_context["territory_population_summary"],
            semantic_clusters=model_context["semantic_clusters"],
            unresolved_high_severity_risk_ids=coverage.unresolved_high_severity_item_ids,
            requested_views=requested_views,
        )
        provenance = self._territory_runtime_provenance(
            profile,
            temperature=0.35,
            prompt_key="layer1_architecture_synthesis",
            prompt_version="1",
            timeout_seconds=self._territory_policy(run.config).model_call_timeout_seconds,
            output_limit=4000,
        )
        try:
            architectures = self._call_architecture_synthesis(
                run=run,
                coverage=coverage,
                requested_views=requested_views,
                prompt=prompt,
                runtime_profile=profile,
                provenance=provenance,
            )
            self.db.persist_layer1_synthesis_result(
                run_id=run.id,
                source_coverage_state_id=coverage.id,
                architecture_candidate_ids=[item.id for item in architectures],
                retained_non_pillar_territory_ids=sorted({
                    territory_id
                    for item in architectures
                    for territory_id in item.significant_non_pillar_territory_ids
                }),
                runtime_provenance=provenance,
            )
            global_assessment = self._run_global_architecture_critic(
                run=run,
                coverage=coverage,
                architectures=architectures,
                runtime_profile=profile,
            )
            self._finalize_architecture_synthesis(
                run=run,
                coverage=coverage,
                architectures=architectures,
                global_assessment=global_assessment,
            )
            return architectures
        except Exception as exc:  # preserve the phase checkpoint for any failed write/parse
            self._record_architecture_synthesis_failure(
                run=run,
                coverage=coverage,
                provenance=provenance,
                error=exc,
            )
            raise

    def _call_architecture_synthesis(
        self,
        *,
        run: Any,
        coverage: Any,
        requested_views: list[str],
        prompt: str,
        runtime_profile: dict[str, Any],
        provenance: ModelRuntimeProvenance,
    ) -> list[Any]:
        """Call synthesis once and persist every returned immutable mapped option."""
        response = self.llm_client.generate_json(
            system_prompt=self._system_prompt(run.project_id),
            user_prompt=prompt,
            model_name=self._runtime_model_name(runtime_profile),
            base_url=self._runtime_base_url(runtime_profile),
            max_tokens=int(provenance.output_limit or 7000),
            temperature=0.35,
            timeout_seconds=provenance.timeout_seconds,
            context_limit=provenance.context_limit,
            telemetry=model_call_context(
                project_id=run.project_id,
                layer="layer1",
                workflow="layer1_architecture_synthesis",
                runtime_profile=runtime_profile,
                run_id=run.id,
                prompt_key="layer1_architecture_synthesis",
                retry_count=0,
                metadata={"coverage_state_id": coverage.id},
            ),
        )
        raw_architectures = response.parsed_json.get("architectures")
        if not isinstance(raw_architectures, list):
            raise LLMError("Synthesis response must contain an architectures list.")
        exact_provenance = provenance.model_copy(
            update={"exact_model_identifier": str(response.model_name or "")}
        )
        accepted_ids = {
            str(item.get("candidate_id") or "")
            for item in self.build_layer1_synthesis_context(run.id)["territory"]
        }
        normalized_payloads = [
            self._retain_unmapped_territory(item, accepted_ids)
            for item in raw_architectures
            if isinstance(item, dict)
        ]
        returned_kinds: set[str] = set()
        for payload in normalized_payloads:
            try:
                kind = ArchitectureKind(str(payload.get("kind") or ""))
            except ValueError as exc:
                raise LLMError(f"Unknown architecture kind: {payload.get('kind')}") from exc
            pillars = payload.get("pillars")
            mappings = payload.get("mappings")
            if not isinstance(pillars, list) or not isinstance(mappings, list):
                raise LLMError("Architecture pillars and mappings must be lists.")
            if any(not isinstance(item, dict) for item in [*pillars, *mappings]):
                raise LLMError("Architecture pillars and mappings must contain objects only.")
            self.db._validate_architecture_mappings(run.id, pillars, mappings)
            returned_kinds.add(kind.value)
        missing = set(requested_views) - returned_kinds
        if missing:
            raise LLMError(f"Synthesis omitted configured architecture views: {sorted(missing)}")
        with self.db.unit_of_work():
            architectures = [
                self._persist_architecture_payload(
                    run_id=run.id,
                    payload=payload,
                    provenance=exact_provenance,
                )
                for payload in normalized_payloads
            ]
        return architectures

    @classmethod
    def _retain_unmapped_territory(
        cls,
        payload: dict[str, Any],
        accepted_ids: set[str],
    ) -> dict[str, Any]:
        """Keep every accepted candidate visible when the model maps only a sample."""
        mapped_ids = {
            candidate_id
            for mapping in payload.get("mappings", [])
            if isinstance(mapping, dict)
            for candidate_id in cls._string_values(mapping.get("territory_candidate_ids"))
        }
        model_retained = cls._string_values(
            payload.get("significant_non_pillar_territory_ids")
        )
        return {
            **payload,
            "significant_non_pillar_territory_ids": sorted(
                set(model_retained) | (accepted_ids - mapped_ids)
            ),
        }

    def _finalize_architecture_synthesis(
        self,
        *,
        run: Any,
        coverage: Any,
        architectures: list[Any],
        global_assessment: Any | None,
    ) -> None:
        """Persist post-critic coverage and move the run to honest review state."""
        reviewed = self.db.persist_layer1_coverage_state(
            run_id=run.id,
            discovery_coverage=coverage.discovery_coverage,
            territory_diversity=coverage.territory_diversity,
            lens_adherence=coverage.lens_adherence,
            candidate_integrity=coverage.candidate_integrity,
            architecture_breadth=self._architecture_breadth_metrics(architectures),
            runtime_cost={
                **coverage.runtime_cost,
                "model_calls": int(coverage.runtime_cost.get("model_calls", 0)) + 2,
            },
            unresolved_high_severity_item_ids=(
                global_assessment.unresolved_high_severity_risk_ids
                if global_assessment
                else coverage.unresolved_high_severity_item_ids
            ),
            ready_for_synthesis=True,
            incomplete_reasons=[],
        )
        ready = bool(global_assessment and global_assessment.ready_for_human_review)
        self.db.update_layer1_territory_run(
            run.id,
            status=(
                TerritoryRunStatus.READY_FOR_HUMAN_REVIEW
                if ready
                else TerritoryRunStatus.INCOMPLETE
            ),
            stage=TerritoryRunStage.HUMAN_REVIEW if ready else TerritoryRunStage.GLOBAL_REVIEW,
            metrics={
                **run.metrics,
                "architecture_candidates": len(architectures),
                "coverage_state_id": reviewed.id,
            },
            incomplete_reason=(
                "" if ready
                else "Global architecture critic requires additional review or exploration."
            ),
        )

    def review_existing_layer1_architecture_candidates(
        self,
        run_id: str,
        *,
        runtime_profile: dict[str, Any],
    ) -> list[Any]:
        """Resume after synthesis persistence without generating duplicate options."""
        run = self.db.get_layer1_territory_run(run_id)
        coverage = self.db.get_latest_layer1_coverage_state(run_id)
        requested_views = set(run.config.get("architecture_views") or [
            ArchitectureKind.COHERENT_CORE.value,
            ArchitectureKind.EXPANSIVE_DIFFERENTIATION.value,
        ])
        latest_by_kind: dict[str, Any] = {}
        for item in self.db.list_layer1_architecture_candidates(run_id):
            current = latest_by_kind.get(item.kind.value)
            if current is None or item.version > current.version:
                latest_by_kind[item.kind.value] = item
        architectures = [
            latest_by_kind[kind]
            for kind in sorted(requested_views)
            if kind in latest_by_kind
        ]
        if coverage is None or not requested_views <= set(latest_by_kind):
            raise ValueError("Persisted architecture options are not ready for review.")
        architecture_ids = {item.id for item in architectures}
        assessments = [
            item
            for item in self.db.list_layer1_global_architecture_assessments(run_id)
            if set(item.architecture_candidate_ids) == architecture_ids
        ]
        global_assessment = (
            assessments[-1]
            if assessments
            else self._run_global_architecture_critic(
                run=run,
                coverage=coverage,
                architectures=architectures,
                runtime_profile=runtime_profile,
            )
        )
        if not any(
            item.status == "completed"
            and set(item.architecture_candidate_ids) == architecture_ids
            for item in self.db.list_layer1_synthesis_results(run.id)
        ):
            self.db.persist_layer1_synthesis_result(
                run_id=run.id,
                source_coverage_state_id=coverage.id,
                architecture_candidate_ids=[item.id for item in architectures],
                retained_non_pillar_territory_ids=sorted({
                    territory_id
                    for item in architectures
                    for territory_id in item.significant_non_pillar_territory_ids
                }),
                runtime_provenance=architectures[0].runtime_provenance,
            )
        self._finalize_architecture_synthesis(
            run=run,
            coverage=coverage,
            architectures=architectures,
            global_assessment=global_assessment,
        )
        return architectures

    def _record_architecture_synthesis_failure(
        self,
        *,
        run: Any,
        coverage: Any,
        provenance: ModelRuntimeProvenance,
        error: Exception,
    ) -> None:
        """Record synthesis failure while retaining any previously persisted options."""
        self.db.persist_layer1_synthesis_result(
            run_id=run.id,
            source_coverage_state_id=coverage.id,
            architecture_candidate_ids=[],
            retained_non_pillar_territory_ids=[],
            runtime_provenance=provenance,
            status="failed",
            error_type=str(getattr(error, "error_type", error.__class__.__name__)),
            error_message=str(error),
        )
        self.db.update_layer1_territory_run(
            run.id,
            status=TerritoryRunStatus.INCOMPLETE,
            stage=TerritoryRunStage.SYNTHESIS,
            metrics=run.metrics,
            incomplete_reason=str(error),
        )

    def _run_global_architecture_critic(
        self,
        *,
        run: Any,
        coverage: Any,
        architectures: list[Any],
        runtime_profile: dict[str, Any],
    ) -> Any | None:
        """Run the architecture critic separately and preserve synthesis if it fails."""
        prompt = build_global_architecture_critic_prompt(
            architectures=[
                {
                    "id": item.id,
                    "kind": item.kind.value,
                    "title": item.title,
                    "rationale": item.rationale,
                    "pillars": item.pillars,
                    "mappings": [
                        mapping.model_dump(mode="json") for mapping in item.mappings
                    ],
                    "significant_non_pillar_territory_ids":
                        item.significant_non_pillar_territory_ids[:48],
                    "significant_non_pillar_territory_count": len(
                        item.significant_non_pillar_territory_ids
                    ),
                    "unresolved_risk_ids": item.unresolved_risk_ids,
                }
                for item in architectures
            ],
            coverage_state=coverage.model_dump(mode="json"),
        )
        provenance = self._territory_runtime_provenance(
            runtime_profile,
            temperature=0.2,
            prompt_key="layer1_global_architecture_critic",
            prompt_version="1",
            timeout_seconds=self._territory_policy(run.config).model_call_timeout_seconds,
            output_limit=2500,
        )
        response = self.llm_client.generate_json(
            system_prompt=self._system_prompt(run.project_id),
            user_prompt=prompt,
            model_name=self._runtime_model_name(runtime_profile),
            base_url=self._runtime_base_url(runtime_profile),
            max_tokens=2500,
            temperature=0.2,
            timeout_seconds=provenance.timeout_seconds,
            context_limit=provenance.context_limit,
            telemetry=model_call_context(
                project_id=run.project_id,
                layer="layer1",
                workflow="layer1_global_architecture_critic",
                runtime_profile=runtime_profile,
                run_id=run.id,
                prompt_key="layer1_global_architecture_critic",
                retry_count=0,
                metadata={
                    "architecture_candidate_ids": [item.id for item in architectures]
                },
            ),
        )
        return self.db.persist_layer1_global_architecture_assessment(
            run_id=run.id,
            architecture_candidate_ids=[item.id for item in architectures],
            payload=response.parsed_json,
            runtime_provenance=provenance.model_copy(
                update={"exact_model_identifier": str(response.model_name or "")}
            ),
        )

    def build_layer1_synthesis_context(self, run_id: str) -> dict[str, Any]:
        """Build bounded synthesis input without raw payloads or rejected candidates."""
        run = self.db.get_layer1_territory_run(run_id)
        source = self._territory_source_projection_for_run(run)
        rejected = {
            TerritoryDestination.DUPLICATE,
            TerritoryDestination.OUT_OF_SCOPE,
            TerritoryDestination.REJECTED_QUALITY,
            TerritoryDestination.REJECTED_GENERIC_REPETITION,
            TerritoryDestination.REJECTED_UNSUPPORTED,
            TerritoryDestination.REJECTED_BIZARRE,
        }
        territory: list[dict[str, Any]] = []
        for candidate in self.db.list_layer1_raw_candidates(run_id):
            disposition = self.db.get_current_layer1_candidate_disposition(candidate.id)
            if disposition is None or disposition.destination in rejected:
                continue
            territory.append(
                {
                    "candidate_id": candidate.id,
                    "title": candidate.title,
                    "description": candidate.description,
                    "destination": disposition.destination.value,
                    "source_discovery_item_ids": candidate.source_discovery_item_ids,
                    "affected_actor_ids": candidate.affected_actor_ids,
                    "affected_domain_ids": candidate.affected_domain_ids,
                    "affected_enterprise_obligation_ids":
                        candidate.affected_enterprise_obligation_ids,
                    "affected_coverage_risk_ids": candidate.affected_coverage_risk_ids,
                    "lens_specific_mechanism": candidate.lens_specific_mechanism,
                }
            )
        accepted_ids = {item["candidate_id"] for item in territory}
        clusters = [
            {
                "id": item.id,
                "title": item.title,
                "semantic_family": item.semantic_family,
                "candidate_ids": [
                    candidate_id
                    for candidate_id in item.candidate_ids
                    if candidate_id in accepted_ids
                ],
                "destination_summary": item.destination_summary,
            }
            for item in self.db.list_layer1_territory_clusters(run_id)
            if any(
                candidate_id in accepted_ids for candidate_id in item.candidate_ids
            )
        ]
        return {
            **source,
            "territory": territory,
            "semantic_clusters": clusters,
        }
