from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException

from strata.api_models import (
    Layer1AdversarialRequest,
    Layer1AntiGenericPatternRequest,
    Layer1ArchitectureSelectionRequest,
    Layer1BulkActionRequest,
    Layer1ClosedTerritoryRequest,
    Layer1HybridArchitectureRequest,
    Layer1LensActionRequest,
    Layer1PillarCreateRequest,
    Layer1TerritoryClassificationRequest,
    Layer1TerritoryStartRequest,
)
from strata.api_support import AppServices, _command_http_error, _project_snapshot
from strata.command_types import (
    AddAntiGenericPattern,
    AddClosedTerritory,
    BulkSetPillarState,
    CancelLayer1ExpansionRun,
    ClassifyTerritoryCandidate,
    CommandActor,
    CommandError,
    CreateHybridLayer1Architecture,
    CreatePillar,
    DisableAntiGenericPattern,
    GenerateLayer1ArchitectureCandidates,
    MarkLayer1LensComplete,
    ReopenLayer1Lens,
    RemoveClosedTerritory,
    RetryLayer1LensWithStrongerExclusions,
    RetryLayer1LensWithTemperature,
    RunLayer1AdversarialPass,
    RunLayer1LensAttempt,
    SelectLayer1ArchitectureCandidate,
    StartLayer1TerritoryExpansion,
)


def register_layer1_routes(app: FastAPI, services: AppServices) -> None:
    """Register manual Layer 1 authoring routes."""

    @app.post("/api/projects/{project_id}/layer1/pillars")
    def create_layer1_pillar(project_id: str, request: Layer1PillarCreateRequest) -> dict[str, object]:
        """Manually add one Layer 1 pillar for projects with a known high-level structure."""
        try:
            services.command_service.handle(CreatePillar(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()),
                title=request.title, description=request.description, status=request.status, priority=request.priority,
            ))
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer1/bulk")
    def bulk_layer1_pillars(project_id: str, request: Layer1BulkActionRequest) -> dict[str, object]:
        """Apply a selected pillar state atomically through the canonical command layer."""
        try:
            services.command_service.handle(BulkSetPillarState(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()),
                pillar_ids=tuple(request.pillar_ids), status=request.status, expected_state_tokens=request.expected_state_tokens,
            ))
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer1/exploration-runs")
    def start_territory_run(
        project_id: str,
        request: Layer1TerritoryStartRequest,
    ) -> dict[str, object]:
        """Start the canonical divergent territory workflow."""
        result = _handle_layer1_command(
            services,
            StartLayer1TerritoryExpansion(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                idempotency_key=request.request_id or str(uuid.uuid4()),
                config=request.config,
                budget=request.budget,
            ),
        )
        return result

    @app.get("/api/projects/{project_id}/layer1/exploration-runs")
    def list_territory_runs(project_id: str) -> dict[str, object]:
        """List exact-lineage exploration history."""
        return {
            "runs": [
                item.model_dump(mode="json")
                for item in services.db.list_layer1_territory_runs(project_id)
            ]
        }

    @app.get("/api/projects/{project_id}/layer1/exploration-runs/{run_id}")
    def get_territory_run(project_id: str, run_id: str) -> dict[str, object]:
        """Return review-oriented run, lens, candidate, coverage, and synthesis state."""
        run = services.db.get_layer1_territory_run(run_id)
        if run.project_id != project_id:
            raise HTTPException(status_code=404, detail="Layer 1 exploration run not found.")
        candidates = services.db.list_layer1_raw_candidates(run_id)
        return {
            "run": run.model_dump(mode="json"),
            "lenses": [
                item.model_dump(mode="json")
                for item in services.db.list_layer1_lens_work_items(run_id)
            ],
            "attempts": [
                item.model_dump(mode="json")
                for item in services.db.list_layer1_lens_attempts(run_id)
            ],
            "raw_candidates": [item.model_dump(mode="json") for item in candidates],
            "normalized_territories": [
                item.model_dump(mode="json")
                for item in services.db.list_layer1_normalized_territories(run_id)
            ],
            "candidate_dispositions": [
                item.model_dump(mode="json")
                for item in services.db.list_layer1_candidate_disposition_history(run_id)
            ],
            "lens_coverage": [
                assessment.model_dump(mode="json")
                for lens in services.db.list_layer1_lens_work_items(run_id)
                for assessment in services.db.list_layer1_lens_coverage(lens.id)
            ],
            "semantic_clusters": [
                item.model_dump(mode="json")
                for item in services.db.list_layer1_territory_clusters(run_id)
            ],
            "global_coverage": (
                coverage.model_dump(mode="json")
                if (coverage := services.db.get_latest_layer1_coverage_state(run_id))
                else None
            ),
            "closed_territories": [
                item.model_dump(mode="json")
                for item in services.db.list_layer1_closed_territory_revisions(project_id)
            ],
            "anti_generic_patterns": [
                item.model_dump(mode="json")
                for item in services.db.list_layer1_anti_generic_pattern_revisions(project_id)
            ],
            "adversarial_findings": [
                item.model_dump(mode="json")
                for item in services.db.list_layer1_adversarial_scenarios(run_id)
            ],
            "architecture_options": [
                item.model_dump(mode="json")
                for item in services.db.list_layer1_architecture_candidates(run_id)
            ],
            "global_architecture_assessments": [
                item.model_dump(mode="json")
                for item in services.db.list_layer1_global_architecture_assessments(run_id)
            ],
            "metrics": run.metrics,
        }

    @app.post(
        "/api/projects/{project_id}/layer1/exploration-runs/{run_id}/lenses/{lens_id}"
    )
    def act_on_lens(
        project_id: str,
        run_id: str,
        lens_id: str,
        request: Layer1LensActionRequest,
    ) -> dict[str, object]:
        """Run, retry, complete, or reopen one durable lens."""
        common = {
            "project_id": project_id,
            "actor": CommandActor.human_ui(),
            "idempotency_key": request.request_id or str(uuid.uuid4()),
            "run_id": run_id,
            "lens_execution_id": lens_id,
        }
        if request.action == "run":
            command = RunLayer1LensAttempt(**common)
        elif request.action == "retry_temperature":
            if request.temperature is None:
                raise HTTPException(status_code=422, detail="temperature is required.")
            command = RetryLayer1LensWithTemperature(
                **common,
                temperature=request.temperature,
            )
        elif request.action == "retry_stronger_exclusions":
            command = RetryLayer1LensWithStrongerExclusions(**common)
        elif request.action == "complete":
            if not request.terminal_state:
                raise HTTPException(status_code=422, detail="terminal_state is required.")
            command = MarkLayer1LensComplete(
                **common,
                state=request.terminal_state,
            )
        elif request.action == "reopen":
            command = ReopenLayer1Lens(**common)
        else:
            raise HTTPException(status_code=422, detail="Unknown Layer 1 lens action.")
        return _handle_layer1_command(services, command)

    @app.post("/api/projects/{project_id}/layer1/territories/{candidate_id}/classification")
    def classify_territory(
        project_id: str,
        candidate_id: str,
        request: Layer1TerritoryClassificationRequest,
    ) -> dict[str, object]:
        """Apply a human candidate destination override."""
        return _handle_layer1_command(
            services,
            ClassifyTerritoryCandidate(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                idempotency_key=request.request_id or str(uuid.uuid4()),
                candidate_id=candidate_id,
                destination=request.destination,
                reason=request.reason,
            ),
        )

    @app.post("/api/projects/{project_id}/layer1/closed-territories")
    def add_closed_territory(
        project_id: str,
        request: Layer1ClosedTerritoryRequest,
    ) -> dict[str, object]:
        """Add a run-specific or persistent semantic exclusion."""
        return _handle_layer1_command(
            services,
            AddClosedTerritory(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                idempotency_key=request.request_id or str(uuid.uuid4()),
                run_id=request.run_id,
                title=request.title,
                description=request.description,
                semantic_examples=tuple(request.semantic_examples),
                scope=request.scope,
                reason=request.reason,
            ),
        )

    @app.delete("/api/projects/{project_id}/layer1/closed-territories/{logical_id}")
    def remove_closed_territory(project_id: str, logical_id: str) -> dict[str, object]:
        """Reopen a semantic family through an append-only revision."""
        return _handle_layer1_command(
            services,
            RemoveClosedTerritory(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                logical_id=logical_id,
            ),
        )

    @app.post("/api/projects/{project_id}/layer1/anti-generic-patterns")
    def add_anti_generic_pattern(
        project_id: str,
        request: Layer1AntiGenericPatternRequest,
    ) -> dict[str, object]:
        """Add a human-approved generic-attractor pattern."""
        return _handle_layer1_command(
            services,
            AddAntiGenericPattern(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                idempotency_key=request.request_id or str(uuid.uuid4()),
                title=request.title,
                description=request.description,
                semantic_examples=tuple(request.semantic_examples),
                source_run_ids=tuple(request.source_run_ids),
                confidence=request.confidence,
                scope=request.scope,
            ),
        )

    @app.delete("/api/projects/{project_id}/layer1/anti-generic-patterns/{logical_id}")
    def disable_anti_generic_pattern(project_id: str, logical_id: str) -> dict[str, object]:
        """Disable a pattern without deleting its audit history."""
        return _handle_layer1_command(
            services,
            DisableAntiGenericPattern(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                logical_id=logical_id,
            ),
        )

    @app.post("/api/projects/{project_id}/layer1/exploration-runs/{run_id}/adversarial")
    def run_adversarial(
        project_id: str,
        run_id: str,
        request: Layer1AdversarialRequest,
    ) -> dict[str, object]:
        """Queue a scenario-specific blind-spot pass."""
        return _handle_layer1_command(
            services,
            RunLayer1AdversarialPass(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                idempotency_key=request.request_id or str(uuid.uuid4()),
                run_id=run_id,
                role=request.role,
            ),
        )

    @app.post("/api/projects/{project_id}/layer1/exploration-runs/{run_id}/synthesis")
    def generate_architectures(project_id: str, run_id: str) -> dict[str, object]:
        """Queue mapped post-exploration architecture synthesis."""
        return _handle_layer1_command(
            services,
            GenerateLayer1ArchitectureCandidates(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                run_id=run_id,
            ),
        )

    @app.post("/api/projects/{project_id}/layer1/exploration-runs/{run_id}/selection")
    def select_architecture(
        project_id: str,
        run_id: str,
        request: Layer1ArchitectureSelectionRequest,
    ) -> dict[str, object]:
        """Select one immutable option without deleting alternatives."""
        return _handle_layer1_command(
            services,
            SelectLayer1ArchitectureCandidate(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                idempotency_key=request.request_id or str(uuid.uuid4()),
                run_id=run_id,
                architecture_candidate_id=request.architecture_candidate_id,
                note=request.note,
            ),
        )

    @app.post("/api/projects/{project_id}/layer1/exploration-runs/{run_id}/hybrid")
    def create_hybrid(
        project_id: str,
        run_id: str,
        request: Layer1HybridArchitectureRequest,
    ) -> dict[str, object]:
        """Create a human-authored hybrid architecture with traceability."""
        return _handle_layer1_command(
            services,
            CreateHybridLayer1Architecture(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                idempotency_key=request.request_id or str(uuid.uuid4()),
                run_id=run_id,
                title=request.title,
                rationale=request.rationale,
                pillars=tuple(request.pillars),
                mappings=tuple(request.mappings),
                significant_non_pillar_territory_ids=tuple(
                    request.significant_non_pillar_territory_ids
                ),
                unresolved_risk_ids=tuple(request.unresolved_risk_ids),
            ),
        )

    @app.delete("/api/projects/{project_id}/layer1/exploration-runs/{run_id}")
    def cancel_territory_run(project_id: str, run_id: str) -> dict[str, object]:
        """Cancel future work while preserving completed checkpoints."""
        return _handle_layer1_command(
            services,
            CancelLayer1ExpansionRun(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                run_id=run_id,
            ),
        )


def _handle_layer1_command(services: AppServices, command: object) -> dict[str, object]:
    """Translate canonical command errors and return portable result data."""
    try:
        result = services.command_service.handle(command)
    except CommandError as exc:
        raise _command_http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.data
