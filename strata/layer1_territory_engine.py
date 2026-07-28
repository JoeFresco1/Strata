from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from strata.layer1_territory_models import (
    ArchitectureKind,
    AttemptStatus,
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
from strata.layer1_territory_policy import (
    DivergencePolicy,
    ExplorationBudget,
    global_completion,
    lens_terminal_state,
    next_temperature,
)
from strata.layer1_territory_prompts import (
    build_adversarial_territory_prompt,
    build_architecture_synthesis_prompt,
    build_global_architecture_critic_prompt,
    build_territory_divergence_prompt,
)
from strata.llm import LLMError
from strata.telemetry import model_call_context


class Layer1TerritoryEngineMixin:
    """Run independent lossless territory exploration before any pillar synthesis."""

    def start_layer1_territory_expansion(
        self,
        project_id: str,
        *,
        policy: DivergencePolicy | None = None,
        budget: ExplorationBudget | None = None,
    ) -> Any:
        """Create an exact-lineage run and its deterministic Product Discovery queue."""
        effective_policy = policy or DivergencePolicy()
        effective_budget = budget or ExplorationBudget()
        brief_head = self.db.ensure_brief_revision_head(project_id)
        brief_revision_id = str(brief_head.get("current_published_revision_id") or "")
        snapshot = self.db.discovery_snapshot(project_id)
        published = snapshot.get("published") if isinstance(snapshot, dict) else None
        if not brief_revision_id or not isinstance(published, dict) or not published.get("id"):
            raise ValueError("Publish Layer 0 and Product Discovery before Layer 1 exploration.")
        run = self.db.create_layer1_territory_run(
            project_id=project_id,
            source_brief_revision_id=brief_revision_id,
            source_discovery_revision_id=str(published["id"]),
            config=effective_policy.as_dict(),
            budget=effective_budget.as_dict(),
        )
        for spec in self._territory_lens_specs(published):
            self.db.create_layer1_lens_work_item(
                run_id=run.id,
                max_attempts=effective_policy.max_attempts_per_lens,
                **spec,
            )
        return run

    def run_layer1_territory_expansion(
        self,
        run_id: str,
        *,
        runtime_profile: dict[str, Any] | None = None,
        lens_execution_id: str | None = None,
        temperature_override: float | None = None,
        stronger_exclusions: bool = False,
    ) -> Layer1ExpansionJobResult:
        """Execute resumable lens work and return an explicitly JSON-safe checkpoint."""
        run = self.db.get_layer1_territory_run(run_id)
        if run.status == TerritoryRunStatus.CANCELLED:
            metrics = self.db.layer1_candidate_integrity_metrics(run_id)
            return Layer1ExpansionJobResult(
                run_id=run.id,
                status=run.status,
                stage=run.stage,
                raw_candidate_count=metrics["raw_candidates"],
                classified_candidate_count=metrics["classified_candidates"],
                undispositioned_candidate_count=metrics["undispositioned_candidates"],
                metrics=run.metrics,
                partial_completion=True,
                incomplete_reasons=["Run was cancelled."],
            )
        policy = self._territory_policy(run.config)
        budget = self._territory_budget(run.budget)
        profile = runtime_profile or self._resolve_layer1_profiles(run.project_id, None)[0]
        policy = self._territory_policy_for_profile(policy, profile)
        self._ensure_profile_loaded(profile)
        model_calls = self._run_model_call_count(run_id)
        hard_budget_exhausted = False

        for lens in self.db.list_layer1_lens_work_items(run_id):
            if lens_execution_id is not None and lens.id != lens_execution_id:
                continue
            if lens.state not in {LensTerminalState.PENDING, LensTerminalState.ACTIVE}:
                continue
            model_calls, hard_budget_exhausted = self._run_territory_lens_work_item(
                run=run,
                lens=lens,
                policy=policy,
                budget=budget,
                runtime_profile=profile,
                model_calls=model_calls,
                temperature_override=temperature_override,
                stronger_exclusions=stronger_exclusions,
            )
            if hard_budget_exhausted:
                break

        if hard_budget_exhausted:
            self._mark_unvisited_lenses_budget_exhausted(run_id)
        return self._finish_territory_divergence(
            run_id,
            model_calls=model_calls,
            hard_budget_exhausted=hard_budget_exhausted,
        )

    def _run_territory_lens_work_item(
        self,
        *,
        run: Any,
        lens: Any,
        policy: DivergencePolicy,
        budget: ExplorationBudget,
        runtime_profile: dict[str, Any],
        model_calls: int,
        temperature_override: float | None,
        stronger_exclusions: bool,
    ) -> tuple[int, bool]:
        """Advance one durable lens until terminal state or a hard budget boundary."""
        while lens.attempt_count < lens.max_attempts:
            if self._territory_hard_budget_reached(run, budget, model_calls):
                self.db.update_layer1_lens_state(
                    lens.id,
                    state=LensTerminalState.BUDGET_EXHAUSTED,
                    attempt_count=lens.attempt_count,
                )
                return model_calls, True
            lens, attempted, terminal = self._advance_territory_lens_attempt(
                run=run,
                lens=lens,
                policy=policy,
                budget=budget,
                runtime_profile=runtime_profile,
                temperature_override=temperature_override,
                stronger_exclusions=stronger_exclusions,
            )
            model_calls += int(attempted)
            if terminal:
                return model_calls, False
        if lens.state in {LensTerminalState.PENDING, LensTerminalState.ACTIVE}:
            self.db.update_layer1_lens_state(
                lens.id,
                state=LensTerminalState.REQUIRES_HUMAN_DECISION,
                attempt_count=lens.attempt_count,
            )
        return model_calls, False

    def _advance_territory_lens_attempt(
        self,
        *,
        run: Any,
        lens: Any,
        policy: DivergencePolicy,
        budget: ExplorationBudget,
        runtime_profile: dict[str, Any],
        temperature_override: float | None,
        stronger_exclusions: bool,
    ) -> tuple[Any, bool, bool]:
        """Execute one frozen independent attempt and apply its lens-local terminal result."""
        prior = self.db.list_layer1_lens_coverage(lens.id)
        temperature = next_temperature(
            policy=policy,
            attempt_number=lens.attempt_count + 1,
            assessment=prior[-1] if prior else None,
            budget_remaining=True,
        )
        if temperature_override is not None:
            temperature = max(0.0, min(2.0, float(temperature_override)))
        if temperature is None:
            return lens, False, True
        lens = self.db.update_layer1_lens_state(
            lens.id,
            state=LensTerminalState.ACTIVE,
            attempt_count=lens.attempt_count,
        )
        assessment = self._run_independent_territory_attempt(
            run=run,
            lens=lens,
            attempt_number=lens.attempt_count + 1,
            temperature=temperature,
            policy=self._territory_attempt_policy(run.id, policy, budget),
            runtime_profile=runtime_profile,
            stronger_exclusions=stronger_exclusions,
        )
        lens = self.db.update_layer1_lens_state(
            lens.id,
            state=LensTerminalState.ACTIVE,
            attempt_count=lens.attempt_count + 1,
        )
        terminal = lens_terminal_state(
            assessment,
            attempts_exhausted=lens.attempt_count >= lens.max_attempts,
            budget_exhausted=False,
        )
        if terminal is not None:
            lens = self.db.update_layer1_lens_state(
                lens.id,
                state=terminal,
                attempt_count=lens.attempt_count,
            )
        return lens, True, terminal is not None

    def _territory_attempt_policy(
        self,
        run_id: str,
        policy: DivergencePolicy,
        budget: ExplorationBudget,
    ) -> DivergencePolicy:
        """Clamp one attempt's candidate contract to the remaining hard budget."""
        remaining = max(
            1,
            budget.max_total_candidates - len(self.db.list_layer1_raw_candidates(run_id)),
        )
        target = min(policy.target_raw_candidates, remaining)
        return replace(
            policy,
            target_raw_candidates=target,
            minimum_raw_candidates=min(policy.minimum_raw_candidates, target),
            maximum_raw_candidates=min(policy.maximum_raw_candidates, remaining),
        )

    def _territory_hard_budget_reached(
        self,
        run: Any,
        budget: ExplorationBudget,
        model_calls: int,
    ) -> bool:
        """Return whether time, call, or candidate limits forbid another model call."""
        elapsed = (
            datetime.now(timezone.utc) - run.created_at.astimezone(timezone.utc)
        ).total_seconds()
        return (
            model_calls >= budget.max_model_calls
            or elapsed >= budget.max_elapsed_seconds
            or len(self.db.list_layer1_raw_candidates(run.id)) >= budget.max_total_candidates
        )

    def run_layer1_adversarial_pass(
        self,
        run_id: str,
        *,
        role: str = "skeptical implementation consultant",
        runtime_profile: dict[str, Any] | None = None,
    ) -> Layer1ExpansionJobResult:
        """Add scenario-specific blind spots to the same immutable candidate ledger."""
        run = self.db.get_layer1_territory_run(run_id)
        if run.status == TerritoryRunStatus.CANCELLED:
            raise ValueError("Cancelled Layer 1 runs cannot start adversarial work.")
        profile = runtime_profile or self._resolve_layer1_profiles(run.project_id, None)[0]
        self._ensure_profile_loaded(profile)
        lens, attempt, prompt, provenance = self._prepare_adversarial_attempt(
            run=run,
            role=role,
            runtime_profile=profile,
        )
        try:
            scenarios, exact_provenance = self._call_adversarial_model(
                run=run,
                role=role,
                runtime_profile=profile,
                attempt=attempt,
                prompt=prompt,
                provenance=provenance,
            )
            self._persist_adversarial_scenarios(
                attempt_id=attempt.id,
                role=role,
                scenarios=scenarios,
                provenance=exact_provenance,
            )
            self.db.checkpoint_layer1_lens_attempt(
                attempt.id,
                status=AttemptStatus.COMPLETED,
                parsed_candidate_count=len(scenarios),
            )
            self.db.update_layer1_lens_state(
                lens.id,
                state=LensTerminalState.SATURATED,
                attempt_count=attempt.attempt_number,
            )
            self.db.update_layer1_territory_run(
                run.id,
                status=TerritoryRunStatus.RUNNING,
                stage=TerritoryRunStage.ADVERSARIAL,
                metrics={
                    **run.metrics,
                    "adversarial_complete": True,
                    "adversarial_role": role,
                },
            )
        except (LLMError, ValueError, TypeError) as exc:
            self._record_adversarial_failure(lens, attempt, exc)
        return self._finish_territory_divergence(
            run.id,
            model_calls=self._run_model_call_count(run.id),
            hard_budget_exhausted=False,
        )

    def _prepare_adversarial_attempt(
        self,
        *,
        run: Any,
        role: str,
        runtime_profile: dict[str, Any],
    ) -> tuple[Any, Any, str, ModelRuntimeProvenance]:
        """Freeze an adversarial request before inference and return its durable attempt."""
        source = self._territory_adversarial_context(run)
        prompt = build_adversarial_territory_prompt(
            role=role,
            brief_projection=source["brief"],
            discovery_projection=source["discovery"],
            current_territory_projection=source["territory"],
        )
        lens = self._ensure_adversarial_lens(run, role)
        provenance = self._territory_runtime_provenance(
            runtime_profile,
            temperature=0.75,
            prompt_key="layer1_adversarial_territory",
            prompt_version="1",
            timeout_seconds=self._territory_policy(run.config).model_call_timeout_seconds,
            output_limit=5000,
        )
        attempt = self.db.create_layer1_lens_attempt(
            lens_execution_id=lens.id,
            attempt_number=lens.attempt_count + 1,
            attempt_kind="adversarial",
            settings={"temperature": 0.75, "role": role, "independent_context": True},
            source_projection=source,
            closed_territory_revision_ids=[],
            anti_generic_pattern_revision_ids=[],
            prompt_key="layer1_adversarial_territory",
            prompt_version="1",
            prompt_projection_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            runtime_provenance=provenance,
        )
        self.db.checkpoint_layer1_lens_attempt(attempt.id, status=AttemptStatus.RUNNING)
        return lens, attempt, prompt, provenance

    def _call_adversarial_model(
        self,
        *,
        run: Any,
        role: str,
        runtime_profile: dict[str, Any],
        attempt: Any,
        prompt: str,
        provenance: ModelRuntimeProvenance,
    ) -> tuple[list[dict[str, Any]], ModelRuntimeProvenance]:
        """Call the adversarial schema and checkpoint its raw response before parsing."""
        response = self.llm_client.generate_json(
            system_prompt=self._system_prompt(run.project_id),
            user_prompt=prompt,
            model_name=self._runtime_model_name(runtime_profile),
            base_url=self._runtime_base_url(runtime_profile),
            max_tokens=int(provenance.output_limit or 5000),
            temperature=0.75,
            timeout_seconds=provenance.timeout_seconds,
            telemetry=model_call_context(
                project_id=run.project_id,
                layer="layer1",
                workflow="layer1_adversarial_territory",
                runtime_profile=runtime_profile,
                run_id=run.id,
                prompt_key="layer1_adversarial_territory",
                retry_count=attempt.attempt_number - 1,
                metadata={"role": role, "attempt_id": attempt.id},
            ),
        )
        self.db.checkpoint_layer1_lens_attempt(
            attempt.id,
            status=AttemptStatus.RAW_RECEIVED,
            raw_response=response.content,
        )
        scenarios = response.parsed_json.get("scenarios")
        if not isinstance(scenarios, list):
            raise LLMError("Adversarial response must contain a scenarios list.")
        return (
            [item for item in scenarios if isinstance(item, dict)],
            provenance.model_copy(
                update={"exact_model_identifier": str(response.model_name or "")}
            ),
        )

    def _record_adversarial_failure(self, lens: Any, attempt: Any, error: Exception) -> None:
        """Preserve an adversarial failure without erasing prior exploration work."""
        status = (
            AttemptStatus.TIMED_OUT
            if "timed out" in str(error).casefold()
            else AttemptStatus.SCHEMA_FAILED
        )
        self.db.checkpoint_layer1_lens_attempt(
            attempt.id,
            status=status,
            error_type=status.value,
            error_message=str(error),
        )
        self.db.update_layer1_lens_state(
            lens.id,
            state=LensTerminalState.BLOCKED_BY_MODEL,
            attempt_count=attempt.attempt_number,
        )

    def generate_layer1_architecture_candidates(
        self,
        run_id: str,
        *,
        runtime_profile: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Generate mapped immutable architecture options from accepted territory only."""
        run = self.db.get_layer1_territory_run(run_id)
        if run.status == TerritoryRunStatus.CANCELLED:
            raise ValueError("Cancelled Layer 1 runs cannot generate architectures.")
        coverage = self.db.get_latest_layer1_coverage_state(run_id)
        if coverage is None or not coverage.ready_for_synthesis:
            raise ValueError("Layer 1 exploration is not ready for architecture synthesis.")
        profile = runtime_profile or self._resolve_layer1_profiles(run.project_id, None)[0]
        self._ensure_profile_loaded(profile)
        context = self.build_layer1_synthesis_context(run_id)
        requested_views = list(run.config.get("architecture_views") or [
            ArchitectureKind.COHERENT_CORE.value,
            ArchitectureKind.EXPANSIVE_DIFFERENTIATION.value,
        ])
        if len(requested_views) < 2:
            raise ValueError("Layer 1 synthesis requires at least two configured views.")
        prompt = build_architecture_synthesis_prompt(
            brief_projection=context["brief"],
            discovery_projection=context["discovery"],
            territory_projection=context["territory"],
            semantic_clusters=context["semantic_clusters"],
            unresolved_high_severity_risk_ids=coverage.unresolved_high_severity_item_ids,
            requested_views=requested_views,
        )
        provenance = self._territory_runtime_provenance(
            profile,
            temperature=0.35,
            prompt_key="layer1_architecture_synthesis",
            prompt_version="1",
            timeout_seconds=self._territory_policy(run.config).model_call_timeout_seconds,
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
        except (LLMError, ValueError) as exc:
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
        architectures = [
            self._persist_architecture_payload(
                run_id=run.id,
                payload=item,
                provenance=exact_provenance,
            )
            for item in raw_architectures
            if isinstance(item, dict)
        ]
        missing = set(requested_views) - {item.kind.value for item in architectures}
        if missing:
            raise LLMError(f"Synthesis omitted configured architecture views: {sorted(missing)}")
        return architectures

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
            error_type="schema_failed",
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
                        item.significant_non_pillar_territory_ids,
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
            output_limit=3500,
        )
        try:
            response = self.llm_client.generate_json(
                system_prompt=self._system_prompt(run.project_id),
                user_prompt=prompt,
                model_name=self._runtime_model_name(runtime_profile),
                base_url=self._runtime_base_url(runtime_profile),
                max_tokens=3500,
                temperature=0.2,
                timeout_seconds=provenance.timeout_seconds,
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
        except LLMError:
            return None
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

    def _run_independent_territory_attempt(
        self,
        *,
        run: Any,
        lens: Any,
        attempt_number: int,
        temperature: float,
        policy: DivergencePolicy,
        runtime_profile: dict[str, Any],
        stronger_exclusions: bool = False,
    ) -> Any:
        """Persist request state, call one lens without history, and checkpoint every stage."""
        attempt, prompt, provenance = self._prepare_territory_attempt(
            run=run,
            lens=lens,
            attempt_number=attempt_number,
            temperature=temperature,
            policy=policy,
            runtime_profile=runtime_profile,
            stronger_exclusions=stronger_exclusions,
        )
        try:
            candidates, exact_provenance = self._call_territory_model(
                run=run,
                lens=lens,
                attempt=attempt,
                prompt=prompt,
                temperature=temperature,
                policy=policy,
                runtime_profile=runtime_profile,
                provenance=provenance,
            )
            self._persist_territory_attempt_candidates(
                attempt_id=attempt.id,
                candidates=candidates,
                runtime_provenance=exact_provenance,
            )
            self.db.checkpoint_layer1_lens_attempt(
                attempt.id,
                status=AttemptStatus.COMPLETED,
                parsed_candidate_count=len(candidates),
            )
        except (LLMError, ValueError, TypeError) as exc:
            self._record_territory_attempt_failure(attempt, exc)
            return self._failed_attempt_coverage(lens, attempt_number, str(exc))
        return self._deterministic_lens_coverage(lens, attempt_number)

    def _prepare_territory_attempt(
        self,
        *,
        run: Any,
        lens: Any,
        attempt_number: int,
        temperature: float,
        policy: DivergencePolicy,
        runtime_profile: dict[str, Any],
        stronger_exclusions: bool,
    ) -> tuple[Any, str, ModelRuntimeProvenance]:
        """Freeze one lens-local prompt, exclusion set, settings, and model provenance."""
        source_projection = self._territory_source_projection(run, lens)
        closed = self.db.list_active_closed_territories(
            run.project_id,
            run_id=run.id,
        )
        patterns = self.db.list_active_anti_generic_patterns(run.project_id)
        prompt = build_territory_divergence_prompt(
            brief_projection=source_projection["brief"],
            discovery_revision_id=run.source_discovery_revision_id,
            lens=source_projection["lens"],
            relevant_discovery_items=source_projection["relevant_discovery_items"],
            required_source_ids=source_projection["required_source_ids"],
            closed_territories=closed,
            anti_generic_patterns=patterns,
            target_count=policy.target_raw_candidates,
            minimum_count=policy.minimum_raw_candidates,
        )
        if stronger_exclusions:
            prompt += (
                "\n\nThis retry uses stronger exclusions: reject generic relabeling and any "
                "semantic neighbor of the closed territory unless it introduces a concrete "
                "lens-specific authority, workflow, operating, or value mechanism."
            )
        provenance = self._territory_runtime_provenance(
            runtime_profile,
            temperature=temperature,
            prompt_key="layer1_territory_divergence",
            prompt_version="2",
            timeout_seconds=policy.model_call_timeout_seconds,
            output_limit=min(
                policy.divergence_max_output_tokens,
                int(runtime_profile.get("max_output_tokens") or policy.divergence_max_output_tokens),
            ),
        )
        attempt = self.db.create_layer1_lens_attempt(
            lens_execution_id=lens.id,
            attempt_number=attempt_number,
            attempt_kind="divergence",
            settings={
                "temperature": temperature,
                "candidate_target": policy.target_raw_candidates,
                "minimum_candidates": policy.minimum_raw_candidates,
                "maximum_candidates": policy.maximum_raw_candidates,
                "independent_context": True,
                "stronger_exclusions": stronger_exclusions,
                "output_limit": provenance.output_limit,
            },
            source_projection=source_projection,
            closed_territory_revision_ids=[item.id for item in closed],
            anti_generic_pattern_revision_ids=[item.id for item in patterns],
            prompt_key="layer1_territory_divergence",
            prompt_version="2",
            prompt_projection_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            runtime_provenance=provenance,
        )
        self.db.checkpoint_layer1_lens_attempt(attempt.id, status=AttemptStatus.RUNNING)
        return attempt, prompt, provenance

    def _call_territory_model(
        self,
        *,
        run: Any,
        lens: Any,
        attempt: Any,
        prompt: str,
        temperature: float,
        policy: DivergencePolicy,
        runtime_profile: dict[str, Any],
        provenance: ModelRuntimeProvenance,
    ) -> tuple[list[dict[str, Any]], ModelRuntimeProvenance]:
        """Call one independent divergence prompt and checkpoint raw output immediately."""
        response = self.llm_client.generate_json(
            system_prompt=self._system_prompt(run.project_id),
            user_prompt=prompt,
            model_name=self._runtime_model_name(runtime_profile),
            base_url=self._runtime_base_url(runtime_profile),
            max_tokens=int(provenance.output_limit or policy.divergence_max_output_tokens),
            temperature=temperature,
            timeout_seconds=provenance.timeout_seconds,
            telemetry=model_call_context(
                project_id=run.project_id,
                layer="layer1",
                workflow="layer1_territory_divergence",
                runtime_profile=runtime_profile,
                run_id=run.id,
                prompt_key="layer1_territory_divergence",
                retry_count=attempt.attempt_number - 1,
                metadata={
                    "lens_execution_id": lens.id,
                    "attempt_id": attempt.id,
                    "independent_context": True,
                },
            ),
        )
        self.db.checkpoint_layer1_lens_attempt(
            attempt.id,
            status=AttemptStatus.RAW_RECEIVED,
            raw_response=response.content,
        )
        return (
            self._territory_candidate_payloads(response.parsed_json, policy),
            provenance.model_copy(
                update={"exact_model_identifier": str(response.model_name or "")}
            ),
        )

    def _record_territory_attempt_failure(self, attempt: Any, error: Exception) -> None:
        """Record timeout or schema failure without deleting an earlier checkpoint."""
        status = (
            AttemptStatus.TIMED_OUT
            if "timed out" in str(error).casefold()
            else AttemptStatus.SCHEMA_FAILED
        )
        self.db.checkpoint_layer1_lens_attempt(
            attempt.id,
            status=status,
            error_type=status.value,
            error_message=str(error),
        )

    def _ensure_adversarial_lens(self, run: Any, role: str) -> Any:
        """Return or create a synthetic non-required lens for one adversarial role."""
        source_lens_id = f"adversarial:{self._territory_key(role, '')}"
        for lens in self.db.list_layer1_lens_work_items(run.id):
            if lens.source_lens_id == source_lens_id:
                return lens
        return self.db.create_layer1_lens_work_item(
            run_id=run.id,
            source_lens_id=source_lens_id,
            source_discovery_item_ids=[],
            title=f"Adversarial: {role}",
            instruction="Find concrete scenarios the accepted territory cannot support.",
            required=False,
            discovery_order=10_000,
            risk_priority=0,
            relevance_score=0.5,
            missing_coverage_priority=0,
            human_priority=0,
            max_attempts=2,
        )

    def _territory_adversarial_context(self, run: Any) -> dict[str, Any]:
        """Build bounded adversarial input without raw transcripts or rejected nonsense."""
        synthesis = self.build_layer1_synthesis_context(run.id)
        return {
            "brief": synthesis["brief"],
            "discovery": synthesis["discovery"],
            "territory": synthesis["territory"],
        }

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
                reason = "Candidate repeats closed or active generic territory without a material mechanism."
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
                    "useful_novelty_score": 20 if destination == TerritoryDestination.DUPLICATE else 65,
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

    @staticmethod
    def _matches_policy_text(text: str, examples: list[str]) -> bool:
        """Match normalized multi-token policy examples without fuzzy overreach."""
        for example in examples:
            normalized = Layer1TerritoryEngineMixin._territory_key(example, "")
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
            "candidate_integrity": candidate_metrics,
            "required_lenses": sum(1 for lens in lenses if lens.required),
            "completed_required_lenses": sum(
                1
                for lens in lenses
                if lens.required and lens.state not in {LensTerminalState.PENDING, LensTerminalState.ACTIVE}
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

    def _territory_source_projection(self, run: Any, lens: Any) -> dict[str, Any]:
        """Build the bounded source-only context used by every independent retry."""
        brief = self.db.get_project_brief(run.project_id)
        snapshot = self.db.discovery_snapshot(run.project_id)
        published = snapshot.get("published", {})
        discovery = published.get("discovery", {})
        relevant = [
            item
            for collection in self._discovery_collections(discovery)
            for item in collection
            if str(item.get("id") or "") in lens.source_discovery_item_ids
        ]
        return {
            "brief": {
                "product_idea": brief.product_idea,
                "problem": brief.problem,
                "target_users": brief.target_users,
                "constraints": brief.constraints,
                "goals": brief.goals,
                "preferred_directions": brief.preferred_directions,
                "rejected_directions": brief.rejected_directions,
            },
            "lens": {
                "id": lens.source_lens_id,
                "title": lens.title,
                "instruction": lens.instruction,
                "required": lens.required,
            },
            "relevant_discovery_items": relevant,
            "required_source_ids": {"discovery_item_ids": lens.source_discovery_item_ids},
        }

    def _territory_source_projection_for_run(self, run: Any) -> dict[str, Any]:
        """Return bounded published Layer 0 and Product Discovery synthesis context."""
        brief = self.db.get_project_brief(run.project_id)
        snapshot = self.db.discovery_snapshot(run.project_id)
        published = snapshot.get("published", {})
        discovery = published.get("discovery", {})
        return {
            "brief": {
                "product_idea": brief.product_idea,
                "problem": brief.problem,
                "target_users": brief.target_users,
                "constraints": brief.constraints,
                "goals": brief.goals,
                "preferred_directions": brief.preferred_directions,
                "rejected_directions": brief.rejected_directions,
            },
            "discovery": {
                name: discovery.get(name, [])
                for name in (
                    "lenses",
                    "actors",
                    "lifecycle_stages",
                    "domains",
                    "enterprise_obligations",
                    "coverage_risks",
                )
            },
        }

    @staticmethod
    def _territory_lens_specs(published: dict[str, Any]) -> list[dict[str, Any]]:
        """Compile non-alphabetical scheduling inputs from the published discovery."""
        discovery = published.get("discovery", {})
        human = published.get("human_owned_fields", {})
        states = human.get("item_states", {}) if isinstance(human, dict) else {}
        priorities = human.get("item_priorities", {}) if isinstance(human, dict) else {}
        human_order = human.get("lens_order", []) if isinstance(human, dict) else []
        explicit_order = {
            str(lens_id): index
            for index, lens_id in enumerate(human_order)
        } if isinstance(human_order, list) else {}
        specs: list[dict[str, Any]] = []
        for order, lens in enumerate(discovery.get("lenses", [])):
            lens_id = str(lens.get("id") or "")
            state = str(states.get(lens_id) or lens.get("downstream_state") or "")
            if not lens_id or state in {"excluded", "rejected"}:
                continue
            source_ids = Layer1TerritoryEngineMixin._lens_source_ids(lens, discovery)
            linked_risks = [
                item
                for item in discovery.get("coverage_risks", [])
                if isinstance(item, dict) and str(item.get("id") or "") in source_ids
            ]
            severity_weight = {"low": 1, "medium": 2, "high": 3, "critical": 4}
            risk_priority = max(
                (
                    severity_weight.get(str(item.get("severity") or ""), 0)
                    for item in linked_risks
                ),
                default=0,
            )
            actor_and_obligation_ids = {
                str(item.get("id") or "")
                for name in ("actors", "enterprise_obligations")
                for item in discovery.get(name, [])
                if isinstance(item, dict)
            }
            specs.append(
                {
                    "source_lens_id": lens_id,
                    "source_discovery_item_ids": source_ids,
                    "title": str(lens.get("title") or "Untitled lens"),
                    "instruction": " ".join(
                        str(lens.get(field) or "")
                        for field in (
                            "description",
                            "why_it_matters",
                            "expected_product_territory",
                        )
                    ).strip(),
                    "required": str(lens.get("recommendation") or "") == "required"
                    or state == "required",
                    "discovery_order": explicit_order.get(lens_id, order),
                    "risk_priority": risk_priority,
                    "relevance_score": float(lens.get("relevance_score") or 0.5),
                    "missing_coverage_priority": len(
                        set(source_ids) & actor_and_obligation_ids
                    ),
                    "human_priority": int(priorities.get(lens_id) or 0),
                    "human_order_position": explicit_order.get(lens_id),
                }
            )
        if not specs:
            raise ValueError("Published Product Discovery contains no active Layer 1 lenses.")
        return specs

    @staticmethod
    def _lens_source_ids(
        lens: dict[str, Any],
        discovery: dict[str, Any] | None = None,
    ) -> list[str]:
        """Collect explicit forward and reverse discovery relationships."""
        values: list[str] = []
        known_ids = {
            str(item.get("id") or "")
            for collection in Layer1TerritoryEngineMixin._discovery_collections(
                discovery or {}
            )
            for item in collection
        }
        for key, value in lens.items():
            if key.endswith("_ids") and isinstance(value, list):
                values.extend(
                    str(item)
                    for item in value
                    if str(item).strip() and (not known_ids or str(item) in known_ids)
                )
        lens_id = str(lens.get("id") or "")
        for collection in Layer1TerritoryEngineMixin._discovery_collections(
            discovery or {}
        ):
            for item in collection:
                related_lens_ids = [
                    str(reference)
                    for key, references in item.items()
                    if key.endswith("lens_ids") and isinstance(references, list)
                    for reference in references
                ]
                if lens_id in related_lens_ids and item.get("id"):
                    values.append(str(item["id"]))
        return list(dict.fromkeys(values))

    @staticmethod
    def _discovery_collections(discovery: dict[str, Any]) -> list[list[dict[str, Any]]]:
        """Return typed discovery collections relevant to territory attribution."""
        names = (
            "actors",
            "lifecycle_stages",
            "domains",
            "enterprise_obligations",
            "coverage_risks",
            "cross_domain_opportunities",
        )
        return [
            [item for item in discovery.get(name, []) if isinstance(item, dict)]
            for name in names
        ]

    @staticmethod
    def _territory_candidate_payloads(
        payload: dict[str, Any],
        policy: DivergencePolicy,
    ) -> list[dict[str, Any]]:
        """Validate only the response envelope while preserving every raw item."""
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            raise LLMError("Territory response must contain a candidates list.")
        valid = [item for item in candidates if isinstance(item, dict)]
        if len(valid) > policy.maximum_raw_candidates:
            valid = valid[: policy.maximum_raw_candidates]
        return valid

    @staticmethod
    def _territory_runtime_provenance(
        profile: dict[str, Any],
        *,
        temperature: float,
        prompt_key: str,
        prompt_version: str,
        timeout_seconds: int | None = None,
        output_limit: int = 7000,
    ) -> ModelRuntimeProvenance:
        """Freeze requested and resolved model facts before inference."""
        return ModelRuntimeProvenance(
            requested_profile_id=str(profile.get("id") or ""),
            resolved_profile_id=str(profile.get("id") or ""),
            provider=str(profile.get("provider") or ""),
            endpoint=str(profile.get("base_url") or ""),
            model_alias=str(profile.get("label") or profile.get("id") or ""),
            exact_model_identifier=str(profile.get("model_name") or ""),
            model_file_hash=str(profile.get("model_file_hash") or ""),
            runtime_build=str(profile.get("runtime_build") or ""),
            prompt_key=prompt_key,
            prompt_version=prompt_version,
            effective_temperature=temperature,
            seed=profile.get("seed"),
            context_limit=profile.get("context_limit"),
            output_limit=output_limit,
            timeout_seconds=(
                timeout_seconds
                or profile.get("timeout_seconds")
                or 900
            ),
        )

    def _accepted_territory_keys(self, run_id: str) -> set[str]:
        """Return normalized keys already routed somewhere other than duplicate/reject."""
        keys: set[str] = set()
        rejected = {
            TerritoryDestination.DUPLICATE,
            TerritoryDestination.REJECTED_QUALITY,
            TerritoryDestination.REJECTED_GENERIC_REPETITION,
            TerritoryDestination.REJECTED_UNSUPPORTED,
            TerritoryDestination.REJECTED_BIZARRE,
            TerritoryDestination.OUT_OF_SCOPE,
        }
        for candidate in self.db.list_layer1_raw_candidates(run_id):
            disposition = self.db.get_current_layer1_candidate_disposition(candidate.id)
            if disposition is not None and disposition.destination not in rejected:
                keys.add(self._territory_key(candidate.title, candidate.description))
        return keys

    @staticmethod
    def _territory_key(title: str, description: str) -> str:
        """Build a deterministic exact-normalized retry deduplication key."""
        text = f"{title} {description}".casefold()
        return " ".join("".join(char if char.isalnum() else " " for char in text).split())

    @staticmethod
    def _deterministic_semantic_family(title: str, description: str) -> str:
        """Create a stable coarse family label for identity normalization."""
        stop_words = {
            "a", "an", "and", "for", "from", "in", "of", "on", "the", "to",
            "platform", "service", "system", "workflow",
        }
        title_tokens = Layer1TerritoryEngineMixin._territory_key(title, "").split()
        family_tokens = [token for token in title_tokens if token not in stop_words][:3]
        if not family_tokens:
            description_tokens = Layer1TerritoryEngineMixin._territory_key(
                description,
                "",
            ).split()
            family_tokens = [
                token for token in description_tokens if token not in stop_words
            ][:3]
        return " ".join(family_tokens) or "uncategorized territory"

    @staticmethod
    def _string_values(value: Any) -> list[str]:
        """Return only non-blank string values from model arrays."""
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def _run_model_call_count(self, run_id: str) -> int:
        """Count persisted attempts so resumed runs honor the original hard budget."""
        row = self.db._fetchone(
            f"SELECT COUNT(*) AS count FROM layer1_lens_attempts WHERE run_id = {self.db.param}",
            (run_id,),
        )
        return int(row["count"])

    def _mark_unvisited_lenses_budget_exhausted(self, run_id: str) -> None:
        """Make hard truncation visible on every still-unvisited lens."""
        for lens in self.db.list_layer1_lens_work_items(run_id):
            if lens.state in {LensTerminalState.PENDING, LensTerminalState.ACTIVE}:
                self.db.update_layer1_lens_state(
                    lens.id,
                    state=LensTerminalState.BUDGET_EXHAUSTED,
                    attempt_count=lens.attempt_count,
                )

    @staticmethod
    def _territory_policy(config: dict[str, Any]) -> DivergencePolicy:
        """Rehydrate the frozen run policy."""
        return DivergencePolicy(
            target_raw_candidates=int(config.get("target_raw_candidates", 18)),
            minimum_raw_candidates=int(config.get("minimum_raw_candidates", 12)),
            maximum_raw_candidates=int(config.get("maximum_raw_candidates", 30)),
            temperature_schedule=tuple(
                float(item)
                for item in config.get("temperature_schedule", (0.65, 0.8, 0.95, 1.05))
            ),
            minimum_lens_adherence=int(config.get("minimum_lens_adherence", 65)),
            minimum_useful_novelty=int(config.get("minimum_useful_novelty", 45)),
            maximum_generic_repetition_rate=float(
                config.get("maximum_generic_repetition_rate", 0.35)
            ),
            max_attempts_per_lens=int(config.get("max_attempts_per_lens", 4)),
            model_call_timeout_seconds=int(
                config.get("model_call_timeout_seconds", 900)
            ),
            divergence_max_output_tokens=int(
                config.get("divergence_max_output_tokens", 7000)
            ),
            enable_adversarial_pass=bool(config.get("enable_adversarial_pass", True)),
            architecture_views=tuple(config.get("architecture_views", ())),
        )

    @staticmethod
    def _territory_budget(config: dict[str, Any]) -> ExplorationBudget:
        """Rehydrate the frozen hard budget."""
        return ExplorationBudget(
            max_model_calls=int(config.get("max_model_calls", 40)),
            max_elapsed_seconds=int(config.get("max_elapsed_seconds", 3600)),
            max_total_candidates=int(config.get("max_total_candidates", 900)),
        )

    @staticmethod
    def _territory_policy_for_profile(
        policy: DivergencePolicy,
        profile: dict[str, Any],
    ) -> DivergencePolicy:
        """Apply optional model-profile workflow overrides to the frozen base policy."""
        workflow_overrides = profile.get("workflow_overrides", {})
        override = (
            workflow_overrides.get("layer1_territory", {})
            if isinstance(workflow_overrides, dict)
            else {}
        )
        if not isinstance(override, dict) or not override:
            return policy
        payload = policy.as_dict()
        allowed = set(payload)
        payload.update({
            key: value for key, value in override.items() if key in allowed
        })
        if "temperature_schedule" in payload:
            payload["temperature_schedule"] = tuple(payload["temperature_schedule"])
        if "architecture_views" in payload:
            payload["architecture_views"] = tuple(payload["architecture_views"])
        return DivergencePolicy(**payload)

    def _territory_diversity_metrics(self, run_id: str) -> dict[str, int]:
        """Calculate durable destination and attribution diversity proxies."""
        candidates = self.db.list_layer1_raw_candidates(run_id)
        destinations = {
            disposition.destination.value
            for item in candidates
            if (disposition := self.db.get_current_layer1_candidate_disposition(item.id))
        }
        return {
            "unique_semantic_families": len(
                self.db.list_layer1_territory_clusters(run_id)
            ),
            "unique_destinations": len(destinations),
            "unique_actor_ids": len(
                {actor for item in candidates for actor in item.affected_actor_ids}
            ),
            "unique_domain_ids": len(
                {domain for item in candidates for domain in item.affected_domain_ids}
            ),
            "unique_lens_mechanisms": len(
                {item.lens_specific_mechanism.casefold() for item in candidates if item.lens_specific_mechanism}
            ),
            "unique_workflow_families": sum(
                1 for value in destinations if value == TerritoryDestination.WORKFLOW_FAMILY.value
            ),
            "unique_administrative_responsibilities": sum(
                1 for value in destinations if value in {
                    TerritoryDestination.ENTERPRISE_PLATFORM_OBLIGATION.value,
                    TerritoryDestination.ACTOR_WORKSPACE.value,
                }
            ),
            "unique_decision_mechanisms": sum(
                1 for value in destinations if value == TerritoryDestination.DECISION_MECHANISM.value
            ),
            "unique_data_responsibilities": sum(
                1 for value in destinations if value == TerritoryDestination.DATA_RESPONSIBILITY.value
            ),
            "unique_commercial_capabilities": sum(
                1 for value in destinations if value == TerritoryDestination.COMMERCIAL_CAPABILITY.value
            ),
            "unique_operational_capabilities": sum(
                1 for value in destinations if value == TerritoryDestination.OPERATIONAL_CAPABILITY.value
            ),
        }

    def _discovery_coverage_metrics(
        self,
        run: Any,
        lenses: list[Any],
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        """Calculate required discovery coverage and explicit actor/obligation gaps."""
        snapshot = self.db.discovery_snapshot(run.project_id)
        discovery = snapshot.get("published", {}).get("discovery", {})
        candidates = self.db.list_layer1_raw_candidates(run.id)
        addressed_ids = {
            item_id
            for candidate in candidates
            for item_id in (
                candidate.source_discovery_item_ids
                + candidate.affected_actor_ids
                + candidate.affected_lifecycle_stage_ids
                + candidate.affected_domain_ids
                + candidate.affected_enterprise_obligation_ids
                + candidate.affected_coverage_risk_ids
            )
        }
        required_actor_ids = {
            str(item.get("id") or "")
            for item in discovery.get("actors", [])
            if isinstance(item, dict)
            and str(item.get("downstream_state") or "optional") == "required"
        }
        obligation_ids = {
            str(item.get("id") or "")
            for item in discovery.get("enterprise_obligations", [])
            if isinstance(item, dict)
            and str(item.get("downstream_state") or "required") != "excluded"
        }
        high_risk_ids = {
            str(item.get("id") or "")
            for item in discovery.get("coverage_risks", [])
            if isinstance(item, dict)
            and str(item.get("severity") or "") in {"high", "critical"}
        }
        actor_gaps = sorted(required_actor_ids - addressed_ids)
        obligation_gaps = sorted(obligation_ids - addressed_ids)
        return {
            "required_lenses_visited": sum(
                1 for lens in lenses if lens.required and lens.attempt_count > 0
            ),
            "required_lenses_completed": sum(
                1
                for lens in lenses
                if lens.required
                and lens.state not in {LensTerminalState.PENDING, LensTerminalState.ACTIVE}
            ),
            "required_lenses_total": sum(1 for lens in lenses if lens.required),
            "discovery_domains_addressed": len({
                str(item.get("id") or "")
                for item in discovery.get("domains", [])
                if isinstance(item, dict) and str(item.get("id") or "") in addressed_ids
            }),
            "actors_addressed": len({
                str(item.get("id") or "")
                for item in discovery.get("actors", [])
                if isinstance(item, dict) and str(item.get("id") or "") in addressed_ids
            }),
            "lifecycle_stages_addressed": len({
                str(item.get("id") or "")
                for item in discovery.get("lifecycle_stages", [])
                if isinstance(item, dict) and str(item.get("id") or "") in addressed_ids
            }),
            "enterprise_obligations_addressed": len(obligation_ids & addressed_ids),
            "high_severity_coverage_risks_resolved": len(high_risk_ids & addressed_ids),
            "required_actor_gaps": actor_gaps,
            "enterprise_obligation_gaps": obligation_gaps,
        }, actor_gaps, obligation_gaps

    def _runtime_cost_metrics(self, run_id: str) -> dict[str, Any]:
        """Aggregate durable attempts into reproducible runtime-cost counters."""
        attempts = self.db.list_layer1_lens_attempts(run_id)
        events = self.db._fetchall(
            f"""
            SELECT status, latency_ms, prompt_tokens, completion_tokens,
                   retry_count, error_type
            FROM model_call_events WHERE run_id = {self.db.param}
            """,
            (run_id,),
        )
        elapsed_seconds = sum(int(row["latency_ms"] or 0) for row in events) / 1000
        model_calls = len(events) if events else len(attempts)
        accepted = self.db.layer1_candidate_integrity_metrics(run_id)["accepted_candidates"]
        return {
            "model_calls": model_calls,
            "tokens": sum(
                int(row["prompt_tokens"] or 0) + int(row["completion_tokens"] or 0)
                for row in events
            ),
            "elapsed_seconds": elapsed_seconds,
            "retries": (
                sum(int(row["retry_count"] or 0) for row in events)
                if events
                else sum(max(0, item.attempt_number - 1) for item in attempts)
            ),
            "timeouts": sum(
                1
                for row in events
                if "timeout" in str(row["error_type"] or "").casefold()
            ) if events else sum(
                1 for item in attempts if item.status == AttemptStatus.TIMED_OUT
            ),
            "repair_attempts": sum(
                1 for item in attempts if item.attempt_kind == "repair"
            ),
            "candidate_yield_per_call": (
                sum(item.parsed_candidate_count for item in attempts) / model_calls
                if model_calls
                else 0
            ),
            "useful_territory_per_minute": (
                accepted / (elapsed_seconds / 60) if elapsed_seconds else 0
            ),
        }

    @staticmethod
    def _architecture_breadth_metrics(architectures: list[Any]) -> dict[str, Any]:
        """Calculate mapped breadth and concentration across immutable options."""
        mapping_sizes = [
            len(mapping.territory_candidate_ids)
            for architecture in architectures
            for mapping in architecture.mappings
        ]
        all_mapped_ids = {
            candidate_id
            for architecture in architectures
            for mapping in architecture.mappings
            for candidate_id in mapping.territory_candidate_ids
        }
        cross_cutting_ids = {
            candidate_id
            for architecture in architectures
            for mapping in architecture.mappings
            for candidate_id in mapping.cross_cutting_concern_ids
        }
        obligation_ids = {
            obligation_id
            for architecture in architectures
            for mapping in architecture.mappings
            for obligation_id in mapping.covered_enterprise_obligation_ids
        }
        retained_ids = {
            candidate_id
            for architecture in architectures
            for candidate_id in architecture.significant_non_pillar_territory_ids
        }
        total_mappings = sum(mapping_sizes)
        return {
            "architecture_options": len(architectures),
            "semantic_territories_represented": len(all_mapped_ids),
            "cross_cutting_territories_represented": len(cross_cutting_ids),
            "enterprise_obligations_represented": len(obligation_ids),
            "important_retained_non_pillar_territory": len(retained_ids),
            "largest_pillar_territory_concentration": (
                max(mapping_sizes, default=0) / total_mappings
                if total_mappings else 0
            ),
            "pillars_with_multiple_feature_families": sum(
                1 for size in mapping_sizes if size > 1
            ),
        }

    def _lens_adherence_metrics(
        self,
        run_id: str,
        assessments: list[Any],
    ) -> dict[str, float]:
        """Aggregate latest lens-local metrics without treating them as global judgment."""
        candidates = self.db.list_layer1_raw_candidates(run_id)
        closed_violations = sum(
            1
            for candidate in candidates
            if any(
                item.closed_territory_violation_ids
                for item in self.db.list_layer1_territory_assessments(candidate.id)
            )
        )
        if not assessments:
            return {
                "average_lens_adherence_score": 0,
                "average_generic_repetition_rate": 0,
                "average_weak_attribution_rate": 0,
                "discovery_item_mapping_completeness": 0,
                "closed_territory_violation_rate": 0,
            }
        count = len(assessments)
        return {
            "average_lens_adherence_score": sum(
                item.lens_adherence_score for item in assessments
            ) / count,
            "average_generic_repetition_rate": sum(
                item.generic_repetition_rate for item in assessments
            ) / count,
            "average_weak_attribution_rate": sum(
                item.weak_attribution_rate for item in assessments
            ) / count,
            "discovery_item_mapping_completeness": (
                sum(1 for item in candidates if item.source_discovery_item_ids)
                / len(candidates)
                if candidates else 0
            ),
            "closed_territory_violation_rate": (
                closed_violations / len(candidates) if candidates else 0
            ),
        }
