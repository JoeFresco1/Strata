from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from strata.api_support import AppServices
from strata.delivery_handoff import export_spec_kit_handoff, spec_kit_handoff_preview
from strata.layer3_service import validate_product_level_content


class SpecKitHandoffRequest(BaseModel):
    """Request body for exporting selected Layer 3 cards into Spec Kit seed files."""

    card_ids: list[str] = Field(default_factory=list)


def _feature_statuses(services: AppServices, project_id: str) -> dict[str, str]:
    """Return current Layer 2 feature states for Layer 3 handoff gates."""
    return {
        feature.id: feature.status
        for feature in services.db.list_layer2_features(project_id)
    }


def _handoff_context(services: AppServices, project_id: str) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    """Load the bounded project context needed to preview or export delivery handoffs."""
    project = services.db.get_project(project_id)
    brief = services.brief_service.ensure_brief(project_id).model_dump(mode="json")
    layer2_graph = services.db.layer2_graph_snapshot(project_id)
    layer3 = services.db.layer3_snapshot(project_id)
    statuses = _feature_statuses(services, project_id)
    return project, brief, layer2_graph, layer3, statuses


def register_delivery_routes(app: FastAPI, services: AppServices) -> None:
    """Register Delivery endpoints without growing the main API module."""

    @app.get("/api/projects/{project_id}/delivery/speckit")
    def preview_speckit_handoff(project_id: str) -> dict[str, object]:
        """Return readiness for moving approved Layer 3 cards into Spec Kit."""
        try:
            _, _, _, layer3, statuses = _handoff_context(services, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return spec_kit_handoff_preview(layer3_snapshot=layer3, feature_statuses=statuses)

    @app.post("/api/projects/{project_id}/delivery/speckit")
    def create_speckit_handoff(project_id: str, request: SpecKitHandoffRequest) -> dict[str, object]:
        """Create a local Spec Kit handoff folder and zip archive from ready cards."""
        try:
            project, brief, layer2_graph, layer3, statuses = _handoff_context(services, project_id)
            selected = set(request.card_ids or [])
            for card in layer3.get("cards", []):
                if selected and card.get("id") not in selected:
                    continue
                validate_product_level_content(card)
            result = export_spec_kit_handoff(
                project=project,
                brief=brief,
                layer2_graph=layer2_graph,
                layer3_snapshot=layer3,
                feature_statuses=statuses,
                exports_dir=Path(services.config.exports_dir),
                card_ids=request.card_ids,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result
