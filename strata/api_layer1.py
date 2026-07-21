from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException

from strata.api_models import Layer1BulkActionRequest, Layer1PillarCreateRequest
from strata.api_support import AppServices, _command_http_error, _project_snapshot
from strata.command_types import BulkSetPillarState, CommandActor, CommandError, CreatePillar


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
