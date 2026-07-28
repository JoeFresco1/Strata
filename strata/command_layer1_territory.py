from __future__ import annotations

from typing import Any

from strata.command_types import (
    AddAntiGenericPattern,
    AddClosedTerritory,
    ApplicationCommand,
    BuildLayer1SynthesisContext,
    CancelLayer1ExpansionRun,
    ClassifyTerritoryCandidate,
    CommandResult,
    CreateHybridLayer1Architecture,
    DisableAntiGenericPattern,
    GenerateLayer1ArchitectureCandidates,
    MarkLayer1LensComplete,
    PromoteTerritoryToPillarCandidate,
    ReclassifyTerritoryCandidate,
    RemoveClosedTerritory,
    ReopenLayer1Lens,
    RetryLayer1LensWithStrongerExclusions,
    RetryLayer1LensWithTemperature,
    RouteTerritoryToLayer2,
    RunLayer1AdversarialPass,
    RunLayer1LensAttempt,
    SelectLayer1ArchitectureCandidate,
    StartLayer1TerritoryExpansion,
    StaleEffect,
    state_token,
)
from strata.layer1_territory_models import (
    ArchitectureKind,
    ArchitectureState,
    CandidateDispositionSource,
    ClosedTerritoryScope,
    LensTerminalState,
    ModelRuntimeProvenance,
    PolicyHumanState,
    TerritoryDestination,
    TerritoryRunStage,
    TerritoryRunStatus,
)
from strata.layer1_territory_policy import DivergencePolicy, ExplorationBudget


class CommandLayer1TerritoryMixin:
    """Execute Layer 1 territory mutations through the canonical command ledger."""

    def _start_layer1_territory_expansion(
        self,
        command: StartLayer1TerritoryExpansion,
    ) -> CommandResult:
        """Create an exact-lineage run and enqueue resumable divergence."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Persist the run and its first durable job atomically."""
            run = self.services.generation_service.start_layer1_territory_expansion(
                command.project_id,
                policy=DivergencePolicy(**command.config),
                budget=ExplorationBudget(**command.budget),
            )
            job = self.services.job_service.enqueue(
                project_id=command.project_id,
                kind="generation",
                workflow="layer1_territory_expansion",
                scope="layer1_territory",
                scope_id=run.id,
                request_payload={"run_id": run.id},
                dedupe_key=f"layer1-territory:{run.id}",
            )
            data = {
                "run": run.model_dump(mode="json"),
                "job": job.model_dump(mode="json"),
                "job_ids": [job.id],
            }
            return data, state_token(data["run"]), StaleEffect()

        return self._execute(
            command,
            target_type="layer1_territory_run",
            target_id="new",
            operation=operation,
        )

    def _run_layer1_lens_attempt(
        self,
        command: RunLayer1LensAttempt,
    ) -> CommandResult:
        """Enqueue a resumable run scoped to one lens request."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Validate lens scope and persist the requested job."""
            lens = self.db.get_layer1_lens_work_item(command.lens_execution_id)
            self._require_territory_scope(command.project_id, command.run_id, lens.run_id)
            self._assert_expected(
                command,
                state_token(lens.model_dump(mode="json")),
                lens.id,
            )
            payload: dict[str, Any] = {
                "run_id": command.run_id,
                "lens_execution_id": command.lens_execution_id,
            }
            if isinstance(command, RetryLayer1LensWithTemperature):
                payload["temperature_override"] = command.temperature
            if isinstance(command, RetryLayer1LensWithStrongerExclusions):
                payload["stronger_exclusions"] = True
            if isinstance(
                command,
                (RetryLayer1LensWithTemperature, RetryLayer1LensWithStrongerExclusions),
            ) and lens.state not in {LensTerminalState.PENDING, LensTerminalState.ACTIVE}:
                self.db.update_layer1_lens_state(
                    lens.id,
                    state=LensTerminalState.PENDING,
                    attempt_count=lens.attempt_count,
                )
            job = self.services.job_service.enqueue(
                project_id=command.project_id,
                kind="generation",
                workflow="layer1_territory_expansion",
                scope="layer1_lens",
                scope_id=lens.id,
                request_payload=payload,
                dedupe_key=f"layer1-lens:{lens.id}:{state_token(payload)}",
            )
            return {
                "job": job.model_dump(mode="json"),
                "job_ids": [job.id],
            }, job.id, StaleEffect()

        return self._execute(
            command,
            target_type="layer1_lens_execution",
            target_id=command.lens_execution_id,
            operation=operation,
        )

    def _mark_layer1_lens_complete(
        self,
        command: MarkLayer1LensComplete,
    ) -> CommandResult:
        """Apply an explicit human terminal disposition to one lens."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Persist the human-selected terminal state."""
            lens = self.db.get_layer1_lens_work_item(command.lens_execution_id)
            self._require_territory_scope(command.project_id, command.run_id, lens.run_id)
            self._assert_expected(
                command,
                state_token(lens.model_dump(mode="json")),
                lens.id,
            )
            updated = self.db.update_layer1_lens_state(
                lens.id,
                state=LensTerminalState(command.state),
                attempt_count=lens.attempt_count,
            )
            data = {"lens": updated.model_dump(mode="json")}
            return data, state_token(data["lens"]), StaleEffect()

        return self._execute(
            command,
            target_type="layer1_lens_execution",
            target_id=command.lens_execution_id,
            operation=operation,
        )

    def _reopen_layer1_lens(self, command: ReopenLayer1Lens) -> CommandResult:
        """Return a terminal lens to pending without deleting prior attempts."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Append new work eligibility while preserving attempt history."""
            lens = self.db.get_layer1_lens_work_item(command.lens_execution_id)
            self._require_territory_scope(command.project_id, command.run_id, lens.run_id)
            updated = self.db.update_layer1_lens_state(
                lens.id,
                state=LensTerminalState.PENDING,
                attempt_count=lens.attempt_count,
            )
            data = {"lens": updated.model_dump(mode="json")}
            return data, state_token(data["lens"]), StaleEffect()

        return self._execute(
            command,
            target_type="layer1_lens_execution",
            target_id=command.lens_execution_id,
            operation=operation,
        )

    def _add_closed_territory(self, command: AddClosedTerritory) -> CommandResult:
        """Append a human-approved exclusion revision."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Persist an approved semantic exclusion revision."""
            if command.run_id:
                self._require_territory_scope(command.project_id, command.run_id, command.run_id)
            item = self.db.append_closed_territory_revision(
                project_id=command.project_id,
                logical_id=None,
                run_id=command.run_id,
                title=command.title,
                description=command.description,
                semantic_examples=list(command.semantic_examples),
                source_family_ids=[],
                source="human",
                scope=ClosedTerritoryScope(command.scope),
                active=True,
                human_state=PolicyHumanState.APPROVED,
                reason=command.reason,
                actor=command.actor.actor_id,
                command_id=self._active_command_id(),
            )
            data = {"closed_territory": item.model_dump(mode="json")}
            return data, state_token(data["closed_territory"]), StaleEffect()

        return self._execute(
            command,
            target_type="layer1_closed_territory",
            target_id="new",
            operation=operation,
        )

    def _remove_closed_territory(
        self,
        command: RemoveClosedTerritory,
    ) -> CommandResult:
        """Append an inactive revision so closed territory becomes available again."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Persist the inactive successor exclusion revision."""
            current = self._latest_policy_revision(
                "layer1_closed_territory_revisions",
                command.logical_id,
            )
            if str(current["project_id"]) != command.project_id:
                raise ValueError("Closed territory does not belong to this project.")
            item = self.db.append_closed_territory_revision(
                project_id=command.project_id,
                logical_id=command.logical_id,
                run_id=command.run_id if command.run_id is not None else current["run_id"],
                title=str(current["title"]),
                description=str(current["description"]),
                semantic_examples=self.db._load_json(current["semantic_examples"]),
                source_family_ids=self.db._load_json(current["source_family_ids"]),
                source="human",
                scope=ClosedTerritoryScope(str(current["scope"])),
                active=False,
                human_state=PolicyHumanState.APPROVED,
                reason=command.reason or "Reopened by human.",
                actor=command.actor.actor_id,
                command_id=self._active_command_id(),
            )
            data = {"closed_territory": item.model_dump(mode="json")}
            return data, state_token(data["closed_territory"]), StaleEffect()

        return self._execute(
            command,
            target_type="layer1_closed_territory",
            target_id=command.logical_id,
            operation=operation,
        )

    def _add_anti_generic_pattern(
        self,
        command: AddAntiGenericPattern,
    ) -> CommandResult:
        """Append a human-approved anti-generic pattern."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Persist an approved anti-generic pattern revision."""
            item = self.db.append_anti_generic_pattern_revision(
                project_id=command.project_id,
                logical_id=None,
                title=command.title,
                description=command.description,
                semantic_examples=list(command.semantic_examples),
                source_run_ids=list(command.source_run_ids),
                confidence=command.confidence,
                scope=command.scope,
                active=True,
                human_state=PolicyHumanState.APPROVED,
                actor=command.actor.actor_id,
                command_id=self._active_command_id(),
            )
            data = {"anti_generic_pattern": item.model_dump(mode="json")}
            return data, state_token(data["anti_generic_pattern"]), StaleEffect()

        return self._execute(
            command,
            target_type="layer1_anti_generic_pattern",
            target_id="new",
            operation=operation,
        )

    def _disable_anti_generic_pattern(
        self,
        command: DisableAntiGenericPattern,
    ) -> CommandResult:
        """Append an inactive anti-generic revision without erasing history."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Persist an inactive successor pattern revision."""
            current = self._latest_policy_revision(
                "layer1_anti_generic_pattern_revisions",
                command.logical_id,
            )
            if str(current["project_id"]) != command.project_id:
                raise ValueError("Anti-generic pattern does not belong to this project.")
            item = self.db.append_anti_generic_pattern_revision(
                project_id=command.project_id,
                logical_id=command.logical_id,
                title=str(current["title"]),
                description=str(current["description"]),
                semantic_examples=self.db._load_json(current["semantic_examples"]),
                source_run_ids=self.db._load_json(current["source_run_ids"]),
                confidence=float(current["confidence"]),
                scope=str(current["scope"]),
                active=False,
                human_state=PolicyHumanState.APPROVED,
                actor=command.actor.actor_id,
                command_id=self._active_command_id(),
            )
            data = {"anti_generic_pattern": item.model_dump(mode="json")}
            return data, state_token(data["anti_generic_pattern"]), StaleEffect()

        return self._execute(
            command,
            target_type="layer1_anti_generic_pattern",
            target_id=command.logical_id,
            operation=operation,
        )

    def _classify_territory_candidate(
        self,
        command: ClassifyTerritoryCandidate,
    ) -> CommandResult:
        """Append a human classification that supersedes prior model routing."""
        return self._classify_candidate_command(
            command,
            TerritoryDestination(command.destination),
            command.reason,
        )

    def _classify_candidate_command(
        self,
        command: ApplicationCommand,
        destination: TerritoryDestination,
        reason: str,
    ) -> CommandResult:
        """Share candidate routing while preserving each canonical command type."""
        candidate_id = str(getattr(command, "candidate_id"))

        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Append the human destination after ownership and token checks."""
            candidate = self.db.get_layer1_raw_candidate(candidate_id)
            if candidate.project_id != command.project_id:
                raise ValueError("Territory candidate does not belong to this project.")
            current = self.db.get_current_layer1_candidate_disposition(candidate.id)
            self._assert_expected(
                command,
                state_token(
                    current.model_dump(mode="json")
                    if current is not None
                    else candidate.model_dump(mode="json")
                ),
                candidate.id,
            )
            item = self.db.append_layer1_candidate_disposition(
                candidate_id=candidate.id,
                destination=destination,
                source=CandidateDispositionSource.HUMAN,
                reason=reason,
                actor=command.actor.actor_id,
                command_id=self._active_command_id(),
            )
            data = {"disposition": item.model_dump(mode="json")}
            return data, state_token(data["disposition"]), StaleEffect()

        return self._execute(
            command,
            target_type="layer1_territory_candidate",
            target_id=candidate_id,
            operation=operation,
        )

    def _promote_territory_candidate(
        self,
        command: PromoteTerritoryToPillarCandidate,
    ) -> CommandResult:
        """Route preserved territory to the synthesis pillar-candidate pool."""
        return self._classify_candidate_command(
            command,
            TerritoryDestination.STANDALONE_PILLAR_CANDIDATE,
            command.reason,
        )

    def _route_territory_to_layer2(
        self,
        command: RouteTerritoryToLayer2,
    ) -> CommandResult:
        """Route useful subordinate territory to the future Layer 2 pool."""
        return self._classify_candidate_command(
            command,
            TerritoryDestination.LAYER_2_FEATURE_FAMILY,
            command.reason,
        )

    def _run_layer1_adversarial(
        self,
        command: RunLayer1AdversarialPass,
    ) -> CommandResult:
        """Enqueue a separate adversarial scenario pass."""
        return self._enqueue_territory_job(
            command,
            workflow="layer1_territory_adversarial",
            run_id=command.run_id,
            payload={"run_id": command.run_id, "role": command.role},
        )

    def _build_layer1_synthesis_context(
        self,
        command: BuildLayer1SynthesisContext,
    ) -> CommandResult:
        """Audit a bounded read of the accepted synthesis context."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Build and record the bounded context projection."""
            self._require_territory_scope(command.project_id, command.run_id, command.run_id)
            context = self.services.generation_service.build_layer1_synthesis_context(
                command.run_id
            )
            return {"context": context}, state_token(context), StaleEffect()

        return self._execute(
            command,
            target_type="layer1_synthesis_context",
            target_id=command.run_id,
            operation=operation,
        )

    def _generate_layer1_architectures(
        self,
        command: GenerateLayer1ArchitectureCandidates,
    ) -> CommandResult:
        """Enqueue post-exploration architecture synthesis."""
        return self._enqueue_territory_job(
            command,
            workflow="layer1_architecture_synthesis",
            run_id=command.run_id,
            payload={"run_id": command.run_id},
        )

    def _select_layer1_architecture(
        self,
        command: SelectLayer1ArchitectureCandidate,
    ) -> CommandResult:
        """Select one option without overwriting its siblings."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Append the architecture selection event."""
            self._require_territory_scope(command.project_id, command.run_id, command.run_id)
            event = self.db.select_layer1_architecture(
                run_id=command.run_id,
                architecture_candidate_id=command.architecture_candidate_id,
                state=ArchitectureState.SELECTED,
                actor=command.actor.actor_id,
                command_id=self._active_command_id(),
                note=command.note,
            )
            return {"selection": event}, state_token(event), StaleEffect()

        return self._execute(
            command,
            target_type="layer1_architecture_candidate",
            target_id=command.architecture_candidate_id,
            operation=operation,
        )

    def _create_hybrid_layer1_architecture(
        self,
        command: CreateHybridLayer1Architecture,
    ) -> CommandResult:
        """Persist a human-authored hybrid as another immutable architecture option."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Validate mappings and persist the immutable hybrid."""
            self._require_territory_scope(command.project_id, command.run_id, command.run_id)
            architecture = self.db.persist_layer1_architecture_candidate(
                run_id=command.run_id,
                kind=ArchitectureKind.HUMAN_HYBRID,
                title=command.title,
                rationale=command.rationale,
                pillars=list(command.pillars),
                mappings=list(command.mappings),
                significant_non_pillar_territory_ids=list(
                    command.significant_non_pillar_territory_ids
                ),
                unresolved_risk_ids=list(command.unresolved_risk_ids),
                runtime_provenance=ModelRuntimeProvenance(
                    prompt_key="human_hybrid",
                    prompt_version="1",
                    effective_temperature=0,
                ),
            )
            data = {"architecture": architecture.model_dump(mode="json")}
            return data, architecture.content_hash, StaleEffect()

        return self._execute(
            command,
            target_type="layer1_architecture_candidate",
            target_id="new",
            operation=operation,
        )

    def _cancel_layer1_expansion(
        self,
        command: CancelLayer1ExpansionRun,
    ) -> CommandResult:
        """Cancel future work while preserving every completed checkpoint."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Persist cancellation on the run and unfinished lenses."""
            run = self._require_territory_scope(
                command.project_id,
                command.run_id,
                command.run_id,
            )
            updated = self.db.update_layer1_territory_run(
                run.id,
                status=TerritoryRunStatus.CANCELLED,
                stage=run.stage,
                metrics=run.metrics,
                incomplete_reason="Cancelled by human.",
                completed=True,
            )
            for lens in self.db.list_layer1_lens_work_items(run.id):
                if lens.state in {LensTerminalState.PENDING, LensTerminalState.ACTIVE}:
                    self.db.update_layer1_lens_state(
                        lens.id,
                        state=LensTerminalState.CANCELLED,
                        attempt_count=lens.attempt_count,
                    )
            data = {"run": updated.model_dump(mode="json")}
            return data, state_token(data["run"]), StaleEffect()

        return self._execute(
            command,
            target_type="layer1_territory_run",
            target_id=command.run_id,
            operation=operation,
        )

    def _enqueue_territory_job(
        self,
        command: ApplicationCommand,
        *,
        workflow: str,
        run_id: str,
        payload: dict[str, Any],
    ) -> CommandResult:
        """Enqueue one territory workflow inside the command transaction."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            """Validate run scope and persist a deduplicated job."""
            self._require_territory_scope(command.project_id, run_id, run_id)
            job = self.services.job_service.enqueue(
                project_id=command.project_id,
                kind="generation",
                workflow=workflow,
                scope="layer1_territory",
                scope_id=run_id,
                request_payload=payload,
                dedupe_key=f"{workflow}:{run_id}:{state_token(payload)}",
            )
            return {
                "job": job.model_dump(mode="json"),
                "job_ids": [job.id],
            }, job.id, StaleEffect()

        return self._execute(
            command,
            target_type="layer1_territory_run",
            target_id=run_id,
            operation=operation,
        )

    def _require_territory_scope(
        self,
        project_id: str,
        run_id: str,
        actual_run_id: str,
    ) -> Any:
        """Validate project and run ownership for every territory command."""
        if run_id != actual_run_id:
            raise ValueError("Layer 1 lens or artifact does not belong to this run.")
        run = self.db.get_layer1_territory_run(run_id)
        if run.project_id != project_id:
            raise ValueError("Layer 1 expansion run does not belong to this project.")
        return run

    def _latest_policy_revision(self, table: str, logical_id: str) -> dict[str, Any]:
        """Load the latest append-only policy revision by stable logical ID."""
        allowed = {
            "layer1_closed_territory_revisions",
            "layer1_anti_generic_pattern_revisions",
        }
        if table not in allowed:
            raise ValueError("Unsupported Layer 1 policy table.")
        row = self.db._fetchone(
            f"""
            SELECT * FROM {table} WHERE logical_id = {self.db.param}
            ORDER BY revision_number DESC LIMIT 1
            """,
            (logical_id,),
        )
        if row is None:
            raise ValueError(f"Layer 1 policy not found: {logical_id}")
        return dict(row)

    def _active_command_id(self) -> str:
        """Return the canonical command ID allocated by the transaction boundary."""
        return str(self.db._transaction_state.command_id or "")
