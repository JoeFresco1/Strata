from __future__ import annotations

import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException

from strata.api_models import OverlapVerdictResolutionRequest
from strata.api_support import AppServices, _command_http_error, _project_snapshot
from strata.command_types import CommandActor, CommandError, RequestOverlapReview, ResolveOverlapVerdict, state_token


def register_overlap_routes(app: FastAPI, services: AppServices) -> None:
    """Register user-triggered full-project overlap critic jobs."""

    @app.post("/api/projects/{project_id}/overlap/layer1")
    def run_layer1_overlap(project_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
        return _enqueue_overlap(project_id, "layer1", background_tasks)

    @app.post("/api/projects/{project_id}/overlap/layer2")
    def run_layer2_overlap(project_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
        return _enqueue_overlap(project_id, "layer2", background_tasks)

    @app.get("/api/projects/{project_id}/overlap/{layer}/review")
    def overlap_review(project_id: str, layer: str) -> dict[str, object]:
        if layer not in {"layer1", "layer2"}:
            raise HTTPException(status_code=404, detail="Unsupported overlap layer")
        try:
            services.db.get_project(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        payload = services.db.overlap_snapshot(project_id)[layer]
        for verdict in payload.get("verdicts", []):
            hashes = services.db.current_overlap_item_hashes(project_id, layer)
            verdict["state_token"] = state_token({"target": hashes.get(verdict["target_id"]), "neighbor": hashes.get(verdict["neighbor_id"]), "verdict": verdict["id"]})
        return {"overlap": payload}

    @app.post("/api/projects/{project_id}/overlap/{layer}/verdicts/{verdict_id}/resolve")
    def resolve_overlap_verdict(
        project_id: str,
        layer: str,
        verdict_id: str,
        request: OverlapVerdictResolutionRequest,
    ) -> dict[str, object]:
        if layer not in {"layer1", "layer2"}:
            raise HTTPException(status_code=404, detail="Unsupported overlap layer")
        try:
            result = services.command_service.handle(ResolveOverlapVerdict(
                project_id=project_id, actor=CommandActor.human_ui(request.resolved_by),
                idempotency_key=request.request_id or str(uuid.uuid4()), expected_state_token=request.expected_state_token,
                layer=layer, verdict_id=verdict_id, action=request.action, note=request.note,
            ))
            resolution = result.data["resolution"]
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "resolution": resolution,
            "snapshot": _project_snapshot(services, project_id).model_dump(mode="json"),
        }

    def _enqueue_overlap(project_id: str, layer: str, background_tasks: BackgroundTasks) -> dict[str, object]:
        try:
            result = services.command_service.handle(RequestOverlapReview(project_id=project_id, actor=CommandActor.human_ui(), layer=layer))
            job = result.data["job"]
            background_tasks.add_task(services.job_service.run_job, job["id"])
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "job": job,
            "snapshot": _project_snapshot(services, project_id).model_dump(mode="json"),
        }
