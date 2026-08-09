from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from strata.models import PlatformJob
from strata.json_safety import ensure_json_safe


UNSET = object()


def utc_now() -> str:
    """Return an ISO timestamp in UTC for durable job records."""
    return datetime.now(timezone.utc).isoformat()


class PlatformJobDatabaseMixin:
    """Persist the shared control-plane job lifecycle."""

    def create_platform_job(
        self,
        *,
        project_id: str,
        kind: str,
        workflow: str,
        scope: str,
        scope_id: str | None = None,
        request_payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> PlatformJob:
        """Create a queued job, or return the active duplicate for the same dedupe key."""
        if dedupe_key:
            existing = self.get_active_platform_job_by_dedupe(project_id, dedupe_key)
            if existing is not None:
                return existing
        job_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO platform_jobs (
                id, project_id, kind, workflow, scope, scope_id, status, progress, current_step,
                request_payload, result_payload, error_type, error_message, dedupe_key,
                cancel_requested, attempt, created_at, started_at, updated_at, completed_at
            ) VALUES ({', '.join([self.param] * 20)})
            """,
            (
                job_id, project_id, kind, workflow, scope, scope_id, "queued", 0, "Queued",
                self._dump_json(request_payload or {}), self._dump_json({}), None, None, dedupe_key,
                False, 1, now, None, now, None,
            ),
        )
        return self.get_platform_job(job_id)

    def get_platform_job(self, job_id: str) -> PlatformJob:
        """Return one durable platform job."""
        row = self._fetchone(f"SELECT * FROM platform_jobs WHERE id = {self.param}", (job_id,))
        if row is None:
            raise ValueError(f"Platform job not found: {job_id}")
        return self._row_to_platform_job(row)

    def get_active_platform_job_by_dedupe(self, project_id: str, dedupe_key: str) -> PlatformJob | None:
        """Return an active duplicate job for the same project and dedupe key."""
        row = self._fetchone(
            f"""
            SELECT * FROM platform_jobs
            WHERE project_id = {self.param}
              AND dedupe_key = {self.param}
              AND status IN ('queued', 'running')
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (project_id, dedupe_key),
        )
        return self._row_to_platform_job(row) if row is not None else None

    def list_platform_jobs(self, project_id: str, *, limit: int = 100) -> list[PlatformJob]:
        """List newest durable jobs for one project."""
        rows = self._fetchall(
            f"""
            SELECT * FROM platform_jobs
            WHERE project_id = {self.param}
            ORDER BY updated_at DESC
            LIMIT {self.param}
            """,
            (project_id, limit),
        )
        return [self._row_to_platform_job(row) for row in rows]

    def list_queued_platform_jobs(self) -> list[PlatformJob]:
        """Return queued jobs in creation order for startup recovery."""
        rows = self._fetchall("SELECT * FROM platform_jobs WHERE status = 'queued' ORDER BY created_at ASC")
        return [self._row_to_platform_job(row) for row in rows]

    def claim_platform_job(self, job_id: str) -> PlatformJob | None:
        """Atomically transition one queued job to running for exactly one worker."""
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    UPDATE platform_jobs
                    SET status = {self.param},
                        progress = CASE WHEN progress < 1 THEN 1 ELSE progress END,
                        current_step = {self.param},
                        started_at = {self.param},
                        completed_at = NULL,
                        error_type = NULL,
                        error_message = NULL,
                        updated_at = {self.param}
                    WHERE id = {self.param} AND status = {self.param}
                    RETURNING *
                    """,
                    ("running", "Starting", now, now, job_id, "queued"),
                )
                row = cursor.fetchone()
            finally:
                cursor.close()
        return self._row_to_platform_job(row) if row is not None else None

    def cancel_queued_platform_job(self, job_id: str) -> PlatformJob | None:
        """Atomically cancel a queued job without overwriting a concurrent claim."""
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    UPDATE platform_jobs
                    SET status = {self.param}, progress = 100,
                        current_step = {self.param}, cancel_requested = {self.param},
                        completed_at = {self.param}, updated_at = {self.param}
                    WHERE id = {self.param} AND status = {self.param}
                    RETURNING *
                    """,
                    ("cancelled", "Cancelled before start", True, now, now, job_id, "queued"),
                )
                row = cursor.fetchone()
            finally:
                cursor.close()
        return self._row_to_platform_job(row) if row is not None else None

    def update_platform_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        current_step: str | None = None,
        result_payload: dict[str, Any] | None = None,
        error_type: str | None | object = UNSET,
        error_message: str | None | object = UNSET,
        cancel_requested: bool | None = None,
        attempt: int | None = None,
        started_at: str | None | object = UNSET,
        completed_at: str | None | object = UNSET,
    ) -> PlatformJob:
        """Update one job lifecycle record."""
        updates: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("status", status),
            ("progress", progress),
            ("current_step", current_step),
            ("cancel_requested", cancel_requested),
            ("attempt", attempt),
        ):
            if value is not None:
                updates.append(f"{column} = {self.param}")
                params.append(value)
        if result_payload is not None:
            updates.append(f"result_payload = {self.param}")
            params.append(self._dump_json(ensure_json_safe(result_payload, path="job.result_payload")))
        if error_type is not UNSET:
            updates.append(f"error_type = {self.param}")
            params.append(error_type)
        if error_message is not UNSET:
            updates.append(f"error_message = {self.param}")
            params.append(error_message)
        if started_at is not UNSET:
            updates.append(f"started_at = {self.param}")
            params.append(started_at)
        if completed_at is not UNSET:
            updates.append(f"completed_at = {self.param}")
            params.append(completed_at)
        updates.append(f"updated_at = {self.param}")
        params.extend([utc_now(), job_id])
        self._execute(f"UPDATE platform_jobs SET {', '.join(updates)} WHERE id = {self.param}", tuple(params))
        return self.get_platform_job(job_id)

    def request_platform_job_cancel(self, job_id: str) -> PlatformJob:
        """Request cancellation; queued jobs can be cancelled immediately."""
        job = self.get_platform_job(job_id)
        if job.status == "queued":
            cancelled = self.cancel_queued_platform_job(job_id)
            if cancelled is not None:
                return cancelled
            job = self.get_platform_job(job_id)
        if job.status == "running":
            return self.update_platform_job(job_id, cancel_requested=True, current_step="Cancellation requested")
        return job

    def retry_platform_job(self, job_id: str) -> PlatformJob:
        """Requeue a failed, cancelled, or interrupted job."""
        job = self.get_platform_job(job_id)
        if job.status not in {"failed", "cancelled", "interrupted"}:
            raise ValueError("Only failed, cancelled, or interrupted jobs can be retried.")
        return self.update_platform_job(
            job_id,
            status="queued",
            progress=0,
            current_step="Queued for retry",
            error_type=None,
            error_message=None,
            cancel_requested=False,
            attempt=job.attempt + 1,
            started_at=None,
            completed_at=None,
        )

    def recover_interrupted_platform_jobs(self) -> int:
        """Mark running jobs as interrupted after a process restart."""
        rows = self._fetchall("SELECT id FROM platform_jobs WHERE status = 'running'")
        now = utc_now()
        for row in rows:
            self.update_platform_job(
                str(row["id"]),
                status="interrupted",
                current_step="Interrupted by an application restart",
                error_type="Interrupted",
                error_message="This job was interrupted by an application restart. Retry it to run again.",
                completed_at=now,
            )
        return len(rows)

    def platform_job_summary(self, project_id: str) -> dict[str, Any]:
        """Return compact counts and recent failure context for health views."""
        jobs = self.list_platform_jobs(project_id, limit=200)
        return {
            "queued": sum(job.status == "queued" for job in jobs),
            "running": sum(job.status == "running" for job in jobs),
            "failed": sum(job.status == "failed" for job in jobs),
            "cancelled": sum(job.status == "cancelled" for job in jobs),
            "interrupted": sum(job.status == "interrupted" for job in jobs),
            "last_success": next((job.updated_at.isoformat() for job in jobs if job.status == "completed"), None),
            "last_error": next((job.error_message for job in jobs if job.status in {"failed", "interrupted"} and job.error_message), None),
            "recent": [job.model_dump(mode="json") for job in jobs[:25]],
        }

    def _row_to_platform_job(self, row: Any) -> PlatformJob:
        """Convert a raw database row into a platform job model."""
        return PlatformJob(
            id=row["id"],
            project_id=row["project_id"],
            kind=row["kind"],
            workflow=row["workflow"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            status=row["status"],
            progress=int(row["progress"]),
            current_step=row["current_step"] or "",
            request_payload=self._load_json(row["request_payload"]),
            result_payload=self._load_json(row["result_payload"]),
            error_type=row["error_type"],
            error_message=row["error_message"],
            dedupe_key=row["dedupe_key"],
            cancel_requested=bool(row["cancel_requested"]),
            attempt=int(row["attempt"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            started_at=datetime.fromisoformat(str(row["started_at"])) if row["started_at"] else None,
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            completed_at=datetime.fromisoformat(str(row["completed_at"])) if row["completed_at"] else None,
        )
