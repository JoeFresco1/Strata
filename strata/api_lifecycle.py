from __future__ import annotations

import re
import uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from strata.api_models import (
    ProjectArchiveExportResponse,
    ProjectArchiveImportRequest,
    ProjectArchiveImportResponse,
    ProjectCloneRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
)
from strata.api_support import AppServices, _command_http_error, _load_app_model_settings
from strata.command_types import (
    ActorType, ArchiveProject, CommandActor, CommandError, CommandOrigin,
    ImportProjectArchive, UnarchiveProject, UpdateBriefDraft, UpdateProjectMetadata,
)
from strata.project_settings import default_project_model_settings


PROJECT_ID_PATTERN = re.compile(r"^/api/projects/([^/]+)(?:/.*)?$")
ARCHIVED_ALLOWED_MUTATIONS = (
    "/archive",
    "/unarchive",
    "/clone",
    "/archive/export",
    "/export",
    "/export/layer2",
    "/export/layer3",
    "/delivery/",
    "/diagnostics/export",
)


def register_lifecycle_routes(app: FastAPI, services: AppServices) -> None:
    """Register project lifecycle, clone, portable archive, and import routes."""

    @app.middleware("http")
    async def archived_project_guard(request: Request, call_next) -> Response:
        project_id = _project_id_from_path(request.url.path)
        if request.method in {"POST", "PATCH", "DELETE"} and project_id and not _archived_mutation_allowed(request.url.path):
            try:
                services.db.ensure_project_writable(project_id)
            except ValueError as exc:
                return JSONResponse(status_code=409, content={"detail": str(exc), "lifecycle_warnings": [str(exc)]})
        response = await call_next(request)
        if response.status_code < 400 and request.method in {"POST", "PATCH", "DELETE"} and project_id and _should_touch_project(request.url.path):
            try:
                services.db.touch_project(project_id, opened=False, updated=True)
            except ValueError:
                pass
        return response

    @app.get("/api/projects")
    def list_projects(state: str = "active", query: str = "", sort: str = "updated") -> list[dict[str, object]]:
        return [_project_summary_payload(project, services) for project in services.db.list_projects(state=state, query=query, sort=sort)]

    @app.post("/api/projects")
    def create_project(request: ProjectCreateRequest) -> dict[str, object]:
        with services.db.unit_of_work():
            project = services.db.create_project(request.name.strip(), request.idea.strip())
            services.db.upsert_project_model_settings(
                project_id=project.id,
                **default_project_model_settings(services.config, _load_app_model_settings(services)),
            )
            brief = services.brief_service.ensure_brief(project.id)
            services.command_service.handle(UpdateBriefDraft(
                project_id=project.id, actor=CommandActor.human_ui(), expected_state_token=services.command_service.brief_state_token(brief),
                idempotency_key=str(uuid.uuid4()), updates={
                "product_idea": request.idea,
                "known_competitors": request.known_competitors,
                "constraints": request.constraints,
                "target_users": request.target_users,
                "goals": request.goals,
                "preferred_directions": request.preferred_directions,
                "rejected_directions": request.rejected_directions,
                "notes": request.notes,
                },
            ))
        return project.model_dump(mode="json")

    @app.patch("/api/projects/{project_id}")
    def update_project(project_id: str, request: ProjectUpdateRequest) -> dict[str, object]:
        try:
            result = services.command_service.handle(UpdateProjectMetadata(
                project_id=project_id, actor=CommandActor.human_ui(), expected_state_token=request.expected_state_token,
                idempotency_key=request.request_id or str(uuid.uuid4()), name=request.name, idea=request.idea,
            ))
            project = {**result.data["project"], "state_token": result.state_token}
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return project

    @app.post("/api/projects/{project_id}/archive")
    def archive_project(project_id: str, expected_state_token: str | None = None, request_id: str | None = None) -> dict[str, object]:
        try:
            result = services.command_service.handle(ArchiveProject(project_id=project_id, actor=CommandActor.human_ui(), expected_state_token=expected_state_token, idempotency_key=request_id or str(uuid.uuid4())))
            project = {**result.data["project"], "state_token": result.state_token}
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return project

    @app.post("/api/projects/{project_id}/unarchive")
    def unarchive_project(project_id: str, expected_state_token: str | None = None, request_id: str | None = None) -> dict[str, object]:
        try:
            result = services.command_service.handle(UnarchiveProject(project_id=project_id, actor=CommandActor.human_ui(), expected_state_token=expected_state_token, idempotency_key=request_id or str(uuid.uuid4())))
            project = {**result.data["project"], "state_token": result.state_token}
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return project

    @app.post("/api/projects/{project_id}/clone")
    def clone_project(project_id: str, request: ProjectCloneRequest) -> dict[str, object]:
        try:
            project = services.db.clone_project(project_id, name=request.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return project.model_dump(mode="json")

    @app.post("/api/projects/{project_id}/archive/export", response_model=ProjectArchiveExportResponse)
    def export_project_archive(project_id: str) -> ProjectArchiveExportResponse:
        try:
            archive_path = services.db.export_project_archive(project_id, Path(services.config.exports_dir))
            with zipfile.ZipFile(archive_path, "r") as archive:
                import json
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ProjectArchiveExportResponse(archive_path=str(archive_path), manifest=manifest)

    @app.post("/api/projects/import", response_model=ProjectArchiveImportResponse)
    def import_project_archive(request: ProjectArchiveImportRequest) -> ProjectArchiveImportResponse:
        path = Path(request.archive_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Project archive not found: {path}")
        try:
            result = services.command_service.handle(ImportProjectArchive(
                project_id="import", actor=CommandActor(actor_id="archive_import", actor_type=ActorType.IMPORT, origin=CommandOrigin.IMPORT),
                idempotency_key=request.request_id or str(uuid.uuid4()), archive_path=str(path),
            )).data
        except (ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ProjectArchiveImportResponse(
            project=result["project"],
            lifecycle_warnings=result.get("lifecycle_warnings", []),
        )


def _project_summary_payload(project: dict[str, Any], services: AppServices) -> dict[str, object]:
    """Serialize a project list row and attach its canonical concurrency token."""
    payload = {
        **project,
        "created_at": project["created_at"].isoformat(),
        "updated_at": project["updated_at"].isoformat() if project.get("updated_at") else None,
        "last_opened_at": project["last_opened_at"].isoformat() if project.get("last_opened_at") else None,
        "archived_at": project["archived_at"].isoformat() if project.get("archived_at") else None,
        "brief_updated_at": project["brief_updated_at"].isoformat() if project.get("brief_updated_at") else None,
    }
    payload["state_token"] = services.command_service.project_state_token(services.db.get_project(str(project["id"])))
    return payload


def _project_id_from_path(path: str) -> str | None:
    match = PROJECT_ID_PATTERN.match(path)
    if not match:
        return None
    project_id = match.group(1)
    if project_id in {"import"}:
        return None
    return project_id


def _archived_mutation_allowed(path: str) -> bool:
    return any(path.endswith(suffix) or suffix in path for suffix in ARCHIVED_ALLOWED_MUTATIONS)


def _should_touch_project(path: str) -> bool:
    return not _archived_mutation_allowed(path) and not path.endswith("/jobs") and "/jobs/" not in path
