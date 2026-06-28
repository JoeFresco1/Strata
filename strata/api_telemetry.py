from __future__ import annotations

from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException

from strata.api_models import TelemetrySettingsUpdateRequest
from strata.api_support import AppServices
from strata.execution_policy import resolved_runtime_request


def register_telemetry_routes(app: FastAPI, services: AppServices) -> None:
    """Register analytics, run-inspection, diagnostics, replay, and health routes."""

    @app.get("/api/projects/{project_id}/analytics")
    def get_project_analytics(project_id: str) -> dict[str, object]:
        services.db.get_project(project_id)
        return services.db.telemetry_summary(project_id)

    @app.patch("/api/projects/{project_id}/analytics/settings")
    def update_project_analytics_settings(
        project_id: str,
        request: TelemetrySettingsUpdateRequest,
    ) -> dict[str, bool]:
        services.db.get_project(project_id)
        return services.db.upsert_telemetry_settings(project_id, request.model_dump())

    @app.get("/api/projects/{project_id}/analytics/runs/{call_id}")
    def inspect_project_run(project_id: str, call_id: str) -> dict[str, object]:
        try:
            return services.db.get_model_call(project_id, call_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/analytics/runs/{call_id}/replay")
    def replay_project_run(project_id: str, call_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
        run = services.db.get_model_call(project_id, call_id)
        if not run.get("system_prompt") or not run.get("user_prompt"):
            raise HTTPException(status_code=409, detail="This run cannot be replayed because prompt bodies were not retained.")
        try:
            job = services.job_service.enqueue(
                project_id=project_id,
                kind="replay",
                workflow="telemetry_replay",
                scope="telemetry",
                scope_id=call_id,
                request_payload={"call_id": call_id},
                dedupe_key=f"replay:{call_id}",
            )
            background_tasks.add_task(services.job_service.run_job, job.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"job": job.model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/diagnostics/export")
    def export_project_diagnostics(project_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
        services.db.get_project(project_id)
        job = services.job_service.enqueue(
            project_id=project_id,
            kind="diagnostics",
            workflow="diagnostics_export",
            scope="project",
            request_payload={},
            dedupe_key=f"diagnostics:{project_id}",
        )
        background_tasks.add_task(services.job_service.run_job, job.id)
        return {"job": job.model_dump(mode="json")}

    @app.get("/api/projects/{project_id}/admin-health")
    def get_project_admin_health(project_id: str) -> dict[str, object]:
        services.db.get_project(project_id)
        database_ok, database_message, embedding_count = _database_health(services, project_id)
        model_ok, model_message = services.generation_service.llm_client.healthcheck()
        jobs = services.db.platform_job_summary(project_id)
        recent_calls = services.db.list_model_calls(project_id, limit=1)
        return {
            "schema_version": 1,
            "database": {"ok": database_ok, "backend": services.config.database_backend, "message": database_message},
            "pgvector": {"enabled": services.db.is_postgres, "embedding_count": embedding_count},
            "model_server": {"ok": model_ok, "message": model_message},
            "jobs": jobs,
            "last_model_call": recent_calls[0] if recent_calls else None,
        }


def _runtime_for_run(services: AppServices, project_id: str, run: dict[str, Any]) -> dict[str, Any]:
    """Resolve the saved profile used by a replay, falling back to current runtime defaults."""
    settings = services.db.get_project_model_settings(project_id)
    profiles = settings.llm_profiles if settings is not None else []
    profile = next(
        (item.model_dump(mode="json") for item in profiles if item.id == run.get("model_profile_id")),
        None,
    )
    return resolved_runtime_request(
        profile,
        llm_client=services.generation_service.llm_client,
        server_manager=services.generation_service.server_manager,
    )


def _database_health(services: AppServices, project_id: str) -> tuple[bool, str, int]:
    """Probe project embeddings while converting dependency failures into health data."""
    try:
        row = services.db._fetchone(
            f"SELECT COUNT(*) AS count FROM node_embeddings WHERE project_id = {services.db.param}",
            (project_id,),
        )
        return True, "Database query succeeded.", int(row["count"]) if row else 0
    except Exception as exc:  # noqa: BLE001 - health responses should report dependency failures.
        return False, str(exc), 0
