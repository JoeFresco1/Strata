from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException

from strata.api_models import ExportResponse
from strata.api_support import AppServices
from strata.export import export_layer2_markdown, export_layer3_feature_expansions, export_project
from strata.layer3_service import validate_product_level_content
from strata.freshness import FreshnessValidationService


def register_export_routes(app: FastAPI, services: AppServices) -> None:
    """Register project and layer export routes outside the main API module."""

    @app.post("/api/projects/{project_id}/export", response_model=ExportResponse)
    def export_current_project(project_id: str) -> ExportResponse:
        """Export the full product tree to Markdown and JSON and return the saved paths."""
        try:
            project = services.db.get_project(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        markdown_path, json_path = export_project(
            project,
            services.db.list_all_nodes(project_id),
            Path(services.config.exports_dir),
        )
        return ExportResponse(markdown_path=str(markdown_path), json_path=str(json_path))

    @app.post("/api/projects/{project_id}/export/layer2")
    def export_layer2_graph(project_id: str) -> dict[str, object]:
        """Export Layer 2 Markdown and JSON with current review state included."""
        try:
            project = services.db.get_project(project_id)
            graph = services.db.layer2_graph_snapshot(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in project.name).strip("-")
        markdown_path = export_layer2_markdown(project, graph, Path(services.config.exports_dir))
        output_path = Path(services.config.exports_dir) / f"{slug or project.id}-layer2-graph.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({"project": project.model_dump(mode="json"), "layer2_graph": graph}, indent=2),
            encoding="utf-8",
        )
        return {"markdown_path": str(markdown_path), "json_path": str(output_path), "layer2_graph": graph}

    @app.post("/api/projects/{project_id}/export/layer3")
    def export_layer3_expansions(project_id: str) -> dict[str, object]:
        """Export approved Feature Expansions as a structured Layer 3 manifest."""
        try:
            project = services.db.get_project(project_id)
            brief = services.brief_service.ensure_brief(project_id).model_dump(mode="json")
            layer2_graph = services.db.layer2_graph_snapshot(project_id)
            layer3 = services.db.layer3_snapshot(project_id)
            approved_expansions = [
                expansion for expansion in layer3.get("expansions", [])
                if expansion.get("review_state") == "approved"
            ]
            if not approved_expansions:
                raise ValueError("Approve at least one Feature Expansion before export.")
            feature_statuses = {
                feature.id: feature.status
                for feature in services.db.list_layer2_features(project_id)
            }
            stale_expansion_ids = [
                expansion["id"]
                for expansion in approved_expansions
                if feature_statuses.get(expansion.get("feature_id")) != "approved"
            ]
            if stale_expansion_ids:
                raise ValueError("Approved Layer 3 expansions have Layer 2 sources that are no longer approved.")
            freshness = FreshnessValidationService(services.db).validate_layer3_export(
                project_id, [str(expansion["id"]) for expansion in approved_expansions],
            )
            if not freshness["coherent"]:
                raise ValueError("Layer 3 export is blocked because selected revisions are stale or have mixed/missing lineage: " + "; ".join(freshness["actionable_reasons"]))
            for expansion in approved_expansions:
                validate_product_level_content(expansion)
            output_path = export_layer3_feature_expansions(
                project,
                brief,
                layer2_graph,
                layer3,
                Path(services.config.exports_dir),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"json_path": str(output_path), "freshness": freshness, "approved_expansion_count": sum(
            1 for expansion in layer3.get("expansions", []) if expansion.get("review_state") == "approved"
        )}
