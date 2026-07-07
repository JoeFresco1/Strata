from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI, HTTPException

from strata.api_models import OverlapVerdictResolutionRequest
from strata.api_support import AppServices, _project_snapshot


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
        return {"overlap": services.db.overlap_snapshot(project_id)[layer]}

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
            services.db.get_project(project_id)
            verdict = services.db.get_overlap_verdict(verdict_id)
            if verdict.project_id != project_id or verdict.layer != layer:
                raise ValueError("Overlap verdict does not belong to this project/layer")
            current_hashes = services.db.current_overlap_item_hashes(project_id, layer)
            target_hash = current_hashes.get(verdict.target_id)
            neighbor_hash = current_hashes.get(verdict.neighbor_id)
            if not target_hash or not neighbor_hash:
                raise ValueError("Overlap verdict is stale because one or both items are no longer active")
            resolution = services.db.create_overlap_verdict_resolution(
                project_id=project_id,
                verdict_id=verdict.id,
                layer=layer,
                target_id=verdict.target_id,
                neighbor_id=verdict.neighbor_id,
                action=request.action,
                note=request.note,
                resolved_by=request.resolved_by,
                target_hash=target_hash,
                neighbor_hash=neighbor_hash,
                metadata={"critic_relation": verdict.relation, "critic_confidence": verdict.confidence},
            )
            _apply_overlap_resolution_side_effects(services, project_id, layer, verdict, request.action)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "resolution": resolution.model_dump(mode="json"),
            "snapshot": _project_snapshot(services, project_id).model_dump(mode="json"),
        }

    def _enqueue_overlap(project_id: str, layer: str, background_tasks: BackgroundTasks) -> dict[str, object]:
        try:
            services.db.get_project(project_id)
            workflow = f"{layer}_overlap_critic"
            job = services.job_service.enqueue(
                project_id=project_id,
                kind="critic",
                workflow=workflow,
                scope=layer,
                request_payload={"layer": layer},
                dedupe_key=f"critic:overlap:{project_id}:{layer}",
            )
            background_tasks.add_task(services.job_service.run_job, job.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "job": job.model_dump(mode="json"),
            "snapshot": _project_snapshot(services, project_id).model_dump(mode="json"),
        }


def _apply_overlap_resolution_side_effects(services: AppServices, project_id: str, layer: str, verdict, action: str) -> None:
    if layer != "layer2" or action not in {"accept_merge", "link"}:
        return
    target = services.db.get_layer2_feature(verdict.target_id)
    neighbor = services.db.get_layer2_feature(verdict.neighbor_id)
    if target.project_id != project_id or neighbor.project_id != project_id:
        raise ValueError("Layer 2 overlap verdict references features outside this project")
    relationship_type = "duplicate_of" if action == "accept_merge" else "overlaps_with"
    services.db.insert_layer2_relationship(
        project_id=project_id,
        source_feature_id=target.id,
        target_feature_id=neighbor.id,
        relationship_type=relationship_type,
        strength=verdict.confidence,
        rationale=f"Overlap critic {verdict.relation}: {verdict.rationale}",
    )
    if action == "accept_merge":
        services.db.update_layer2_feature(target.id, status="merged")
    services.db.record_layer2_review_action(
        project_id=project_id,
        feature_id=target.id,
        action_type="merge" if action == "accept_merge" else "add_relationship",
        payload={
            "source": "overlap_resolution",
            "verdict_id": verdict.id,
            "neighbor_id": neighbor.id,
            "relationship_type": relationship_type,
        },
    )
