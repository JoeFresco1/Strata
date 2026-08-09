from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from strata.layer1_territory_models import (
    AttemptStatus,
    Layer1ExpansionJobResult,
    LensTerminalState,
    ModelRuntimeProvenance,
    TerritoryRunStage,
    TerritoryRunStatus,
)
from strata.layer1_territory_policy import (
    DivergencePolicy,
    ExplorationBudget,
    lens_terminal_state,
    next_temperature,
)
from strata.layer1_territory_prompts import (
    build_adversarial_territory_prompt,
    build_territory_divergence_prompt,
)
from strata.llm import LLMError
from strata.telemetry import model_call_context
from strata.layer1_territory_context import Layer1TerritoryContextMixin
from strata.layer1_territory_metrics import Layer1TerritoryMetricsMixin
from strata.layer1_territory_persistence import Layer1TerritoryPersistenceMixin
from strata.layer1_territory_synthesis import Layer1TerritorySynthesisMixin


class Layer1TerritoryEngineMixin(
    Layer1TerritorySynthesisMixin,
    Layer1TerritoryContextMixin,
    Layer1TerritoryPersistenceMixin,
    Layer1TerritoryMetricsMixin,
):
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
            with self.db.unit_of_work():
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
        except Exception as exc:  # durable attempt boundary includes persistence failures
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
            territory_inventory=source["territory_inventory"],
            territory_population_summary=source["territory_population_summary"],
            semantic_clusters=source["semantic_clusters"],
        )
        lens = self._ensure_adversarial_lens(run, role)
        provenance = self._territory_runtime_provenance(
            runtime_profile,
            temperature=0.75,
            prompt_key="layer1_adversarial_territory",
            prompt_version="1",
            timeout_seconds=self._territory_policy(run.config).model_call_timeout_seconds,
            output_limit=2000,
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
            context_limit=provenance.context_limit,
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
        if not scenarios or any(not isinstance(item, dict) for item in scenarios):
            raise LLMError("Adversarial scenarios must be a non-empty list of objects.")
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
            raw_response=str(getattr(error, "raw_content", "")) or None,
            error_type=str(getattr(error, "error_type", status.value)),
            error_message=str(error),
        )
        self.db.update_layer1_lens_state(
            lens.id,
            state=LensTerminalState.BLOCKED_BY_MODEL,
            attempt_count=attempt.attempt_number,
        )









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
            with self.db.unit_of_work():
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
        except Exception as exc:  # durable attempt boundary includes persistence failures
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
                int(
                    runtime_profile.get("max_output_tokens")
                    or policy.divergence_max_output_tokens
                ),
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
            context_limit=provenance.context_limit,
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
            raw_response=str(getattr(error, "raw_content", "")) or None,
            error_type=str(getattr(error, "error_type", status.value)),
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
