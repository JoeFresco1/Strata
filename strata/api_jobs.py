from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI, HTTPException

from strata.api_support import AppServices


def register_job_routes(app: FastAPI, services: AppServices) -> None:
    """Register unified durable job queue routes."""

    @app.get("/api/projects/{project_id}/jobs")
    def list_project_jobs(project_id: str) -> dict[str, object]:
        try:
            services.db.get_project(project_id)
            jobs = services.db.list_platform_jobs(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"jobs": [job.model_dump(mode="json") for job in jobs]}

    @app.get("/api/projects/{project_id}/jobs/{job_id}")
    def get_project_job(project_id: str, job_id: str) -> dict[str, object]:
        try:
            job = services.db.get_platform_job(job_id)
            if job.project_id != project_id:
                raise ValueError("Job belongs to another project.")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"job": job.model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/jobs/{job_id}/cancel")
    def cancel_project_job(project_id: str, job_id: str) -> dict[str, object]:
        try:
            job = services.db.get_platform_job(job_id)
            if job.project_id != project_id:
                raise ValueError("Job belongs to another project.")
            updated = services.job_service.cancel(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"job": updated.model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/jobs/{job_id}/retry")
    def retry_project_job(project_id: str, job_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
        try:
            job = services.db.get_platform_job(job_id)
            if job.project_id != project_id:
                raise ValueError("Job belongs to another project.")
            updated = services.job_service.retry(job_id)
            background_tasks.add_task(services.job_service.run_job, updated.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"job": updated.model_dump(mode="json")}
