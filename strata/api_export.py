from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from strata.api_models import ExportResponse, SpecificationCompileRequest, SpecificationRenderRequest
from strata.api_support import AppServices
from strata.command_types import CommandActor, CommandError, CompileSpecificationManifest, RenderSpecificationManifest
from strata.api_support import _command_http_error
from strata.export import export_layer2_markdown, export_layer3_feature_expansions
from strata.layer3_service import validate_product_level_content
from strata.freshness import FreshnessValidationService


def register_export_routes(app: FastAPI, services: AppServices) -> None:
    """Register project and layer export routes outside the main API module."""

    @app.post("/api/projects/{project_id}/export", response_model=ExportResponse)
    def export_current_project(project_id: str) -> ExportResponse:
        """Compile and render the approved canonical specification through durable commands."""
        try:
            project = services.db.get_project(project_id)
            token = services.command_service.specification_source_state_token(project_id)
            compile_result = services.command_service.handle(CompileSpecificationManifest(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=str(uuid.uuid4()),
                expected_state_token=token, mode="approved",
            ))
            manifest = compile_result.data["manifest"]
            if not manifest["exportable"]:
                raise ValueError("The approved manifest was persisted but failed export validation.")
            render_result = services.command_service.handle(RenderSpecificationManifest(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=str(uuid.uuid4()),
                expected_state_token=manifest["content_hash"], manifest_id=manifest["manifest_id"],
            ))
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        rendered = render_result.data["rendered"]
        return ExportResponse(
            markdown_path=rendered["markdown_path"], json_path=rendered["json_path"],
            manifest_id=manifest["manifest_id"], manifest_version=manifest["sequence_number"],
            manifest_status=manifest["status"], exportable=manifest["exportable"], issues=manifest["issues"],
        )

    @app.post("/api/projects/{project_id}/specification/manifests/compile")
    def compile_specification_manifest(project_id: str, request: SpecificationCompileRequest) -> dict[str, object]:
        """Compile and persist one immutable manifest with strict optimistic concurrency."""
        try:
            result = services.command_service.handle(CompileSpecificationManifest(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id,
                expected_state_token=request.expected_state_token, mode=request.mode,
                historical_brief_revision_id=request.historical_brief_revision_id,
            ))
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        return {**result.data, "state_token": result.state_token, "idempotent": result.idempotent}

    @app.get("/api/projects/{project_id}/specification/compilation-context")
    def specification_compilation_context(project_id: str) -> dict[str, object]:
        """Expose the exact optimistic token and current durable manifest headers."""
        try:
            services.db.get_project(project_id)
            return {
                "source_state_token": services.command_service.specification_source_state_token(project_id),
                "manifests": services.db.list_specification_manifests(project_id),
            }
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/specification/manifests")
    def list_specification_manifests(project_id: str) -> list[dict[str, object]]:
        """List durable manifest identities without loading their full payloads."""
        try:
            services.db.get_project(project_id)
            return services.db.list_specification_manifests(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/specification/manifests/{manifest_id}")
    def get_specification_manifest(project_id: str, manifest_id: str) -> dict[str, object]:
        """Return one complete typed durable manifest."""
        try:
            return services.db.get_specification_manifest(project_id, manifest_id).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/specification/manifests/{manifest_id}/render")
    def render_specification_manifest(project_id: str, manifest_id: str, request: SpecificationRenderRequest) -> dict[str, object]:
        """Render selected formats exclusively from a stored manifest payload."""
        try:
            result = services.command_service.handle(RenderSpecificationManifest(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id,
                expected_state_token=request.expected_state_token, manifest_id=manifest_id,
                formats=tuple(request.formats),
            ))
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        return {**result.data, "state_token": result.state_token, "idempotent": result.idempotent}

    @app.get("/api/projects/{project_id}/specification/manifests/{manifest_id}/artifacts/{format_name}")
    def download_specification_artifact(project_id: str, manifest_id: str, format_name: str) -> FileResponse:
        """Download a recorded renderer output without accepting arbitrary filesystem paths."""
        if format_name not in {"json", "markdown"}:
            raise HTTPException(status_code=404, detail="Unsupported specification artifact format.")
        try:
            artifact = services.db.get_rendered_specification_artifact(project_id, manifest_id, format_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        target = Path(str(artifact["path"])).resolve()
        export_root = Path(services.config.exports_dir).resolve()
        if not target.is_relative_to(export_root) or not target.is_file():
            raise HTTPException(status_code=404, detail="Rendered specification artifact is unavailable.")
        media_type = "application/json" if format_name == "json" else "text/markdown"
        return FileResponse(target, media_type=media_type, filename=target.name)

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
        return {"classification": "diagnostic", "markdown_path": str(markdown_path), "json_path": str(output_path), "layer2_graph": graph}

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
        return {"classification": "diagnostic", "json_path": str(output_path), "freshness": freshness, "approved_expansion_count": sum(
            1 for expansion in layer3.get("expansions", []) if expansion.get("review_state") == "approved"
        )}
