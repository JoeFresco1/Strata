from __future__ import annotations

from fastapi import FastAPI, HTTPException

from strata.api_models import Layer1PillarCreateRequest
from strata.api_support import AppServices, _project_snapshot


def register_layer1_routes(app: FastAPI, services: AppServices) -> None:
    """Register manual Layer 1 authoring routes."""

    @app.post("/api/projects/{project_id}/layer1/pillars")
    def create_layer1_pillar(project_id: str, request: Layer1PillarCreateRequest) -> dict[str, object]:
        """Manually add one Layer 1 pillar for projects with a known high-level structure."""
        try:
            services.db.get_project(project_id)
            brief = services.brief_service.ensure_brief(project_id)
            if brief.status != "published":
                raise ValueError("Publish Layer 0 before adding Layer 1 pillars.")
            node = services.db.create_node(
                project_id=project_id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title=request.title.strip(),
                description=request.description.strip(),
                status=request.status,
                priority=request.priority,
                json_payload={"source": "manual", "creation_mode": "manual_layer1"},
            )
            services.generation_service.refresh_pillar_semantic_metadata(node.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}
