from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pgvector import Vector

from strata.models import ResearchChunk, ResearchFinding, ResearchJob, ResearchSource


UNSET = object()


def utc_now() -> str:
    """Return an ISO timestamp in UTC for persistent research records."""
    return datetime.now(timezone.utc).isoformat()


class ResearchDatabaseMixin:
    """Persist research jobs, sources, chunks, and normalized findings."""

    def create_research_job(
        self,
        *,
        project_id: str,
        scope: str,
        scope_id: str | None,
        job_type: str,
        details: dict[str, Any] | None = None,
    ) -> ResearchJob:
        """Create a durable local research job that background workers can resume or retry."""
        job_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO research_jobs (
                id, project_id, scope, scope_id, job_type, status, progress, details, error, created_at, updated_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                job_id,
                project_id,
                scope,
                scope_id,
                job_type,
                "queued",
                0,
                self._dump_json(details or {}),
                None,
                now,
                now,
            ),
        )
        return self.get_research_job(job_id)

    def update_research_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: int | None = None,
        details: dict[str, Any] | None = None,
        error: str | None | object = UNSET,
    ) -> ResearchJob:
        """Update one research job as the local worker progresses."""
        updates: list[str] = []
        params: list[Any] = []
        if status is not None:
            updates.append(f"status = {self.param}")
            params.append(status)
        if progress is not None:
            updates.append(f"progress = {self.param}")
            params.append(progress)
        if details is not None:
            updates.append(f"details = {self.param}")
            params.append(self._dump_json(details))
        if error is not UNSET:
            updates.append(f"error = {self.param}")
            params.append(error)
        updates.append(f"updated_at = {self.param}")
        params.append(utc_now())
        params.append(job_id)
        self._execute(
            f"UPDATE research_jobs SET {', '.join(updates)} WHERE id = {self.param}",
            tuple(params),
        )
        return self.get_research_job(job_id)

    def get_research_job(self, job_id: str) -> ResearchJob:
        """Return one persisted research job."""
        row = self._fetchone(
            f"SELECT * FROM research_jobs WHERE id = {self.param}",
            (job_id,),
        )
        if row is None:
            raise ValueError(f"Research job not found: {job_id}")
        return self._row_to_research_job(row)

    def list_research_jobs(self, project_id: str) -> list[ResearchJob]:
        """Return research jobs for a project in newest-first order."""
        rows = self._fetchall(
            f"SELECT * FROM research_jobs WHERE project_id = {self.param} ORDER BY updated_at DESC",
            (project_id,),
        )
        return [self._row_to_research_job(row) for row in rows]

    def cancel_active_research_jobs(self, project_id: str, reason: str) -> int:
        """Mark queued/running competitor jobs cancelled when project research is disabled."""
        rows = self._fetchall(
            f"""
            SELECT id FROM research_jobs
            WHERE project_id = {self.param} AND status IN ('queued', 'running')
            """,
            (project_id,),
        )
        for row in rows:
            self.update_research_job(str(row["id"]), status="cancelled", error=reason)
        return len(rows)

    def recover_interrupted_research_jobs(self) -> int:
        """Return interrupted research work to the durable queue after a restart."""
        rows = self._fetchall("SELECT id FROM research_jobs WHERE status = 'running'")
        for row in rows:
            self.update_research_job(
                str(row["id"]),
                status="queued",
                error="Recovered after an interrupted Strata process.",
            )
        return len(rows)

    def list_queued_research_jobs(self) -> list[ResearchJob]:
        """Return durable queued jobs in creation order for startup recovery."""
        rows = self._fetchall(
            "SELECT * FROM research_jobs WHERE status = 'queued' ORDER BY created_at ASC"
        )
        return [self._row_to_research_job(row) for row in rows]

    def clear_research_scope(
        self,
        *,
        project_id: str,
        scope: str,
        scope_id: str | None = None,
    ) -> None:
        """Remove stale findings, sources, and chunks before rerunning local research for a scope."""
        scope_clause = (
            f"project_id = {self.param} AND scope = {self.param} AND COALESCE(scope_id, '') = COALESCE({self.param}, '')"
        )
        params = (project_id, scope, scope_id)
        for table in ("research_chunks", "research_sources", "research_findings"):
            self._execute(f"DELETE FROM {table} WHERE {scope_clause}", params)

    def insert_research_source(
        self,
        *,
        project_id: str,
        scope: str,
        scope_id: str | None,
        competitor_name: str,
        domain: str,
        url: str,
        page_type: str,
        title: str | None,
        status_code: int | None,
        content_hash: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> ResearchSource:
        """Persist one crawled source page used in competitor analysis."""
        source_id = str(uuid.uuid4())
        fetched_at = utc_now()
        self._execute(
            f"""
            INSERT INTO research_sources (
                id, project_id, scope, scope_id, competitor_name, domain, url, page_type,
                title, status_code, fetched_at, content_hash, metadata
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                source_id,
                project_id,
                scope,
                scope_id,
                competitor_name,
                domain,
                url,
                page_type,
                title,
                status_code,
                fetched_at,
                content_hash,
                self._dump_json(metadata or {}),
            ),
        )
        return self.get_research_source(source_id)

    def get_research_source(self, source_id: str) -> ResearchSource:
        """Return one persisted research source."""
        row = self._fetchone(
            f"SELECT * FROM research_sources WHERE id = {self.param}",
            (source_id,),
        )
        if row is None:
            raise ValueError(f"Research source not found: {source_id}")
        return self._row_to_research_source(row)

    def list_research_sources(self, project_id: str, *, scope: str, scope_id: str | None = None) -> list[ResearchSource]:
        """Return crawled sources for a given research scope."""
        rows = self._fetchall(
            f"""
            SELECT * FROM research_sources
            WHERE project_id = {self.param}
              AND scope = {self.param}
              AND COALESCE(scope_id, '') = COALESCE({self.param}, '')
            ORDER BY fetched_at DESC
            """,
            (project_id, scope, scope_id),
        )
        return [self._row_to_research_source(row) for row in rows]

    def insert_research_chunk(
        self,
        *,
        project_id: str,
        scope: str,
        scope_id: str | None,
        source_id: str,
        competitor_name: str,
        domain: str,
        url: str,
        title: str | None,
        chunk_index: int,
        text: str,
        embedding_model: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> ResearchChunk:
        """Persist one extracted evidence chunk plus its local embedding."""
        chunk_id = str(uuid.uuid4())
        created_at = utc_now()
        self._execute(
            f"""
            INSERT INTO research_chunks (
                id, project_id, scope, scope_id, source_id, competitor_name, domain, url,
                title, chunk_index, text, embedding_model, embedding, metadata, created_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                chunk_id,
                project_id,
                scope,
                scope_id,
                source_id,
                competitor_name,
                domain,
                url,
                title,
                chunk_index,
                text,
                embedding_model,
                Vector(embedding) if self.is_postgres else json.dumps(embedding, ensure_ascii=True),
                self._dump_json(metadata or {}),
                created_at,
            ),
        )
        return self.get_research_chunk(chunk_id)

    def get_research_chunk(self, chunk_id: str) -> ResearchChunk:
        """Return one stored research chunk."""
        row = self._fetchone(
            f"SELECT * FROM research_chunks WHERE id = {self.param}",
            (chunk_id,),
        )
        if row is None:
            raise ValueError(f"Research chunk not found: {chunk_id}")
        return self._row_to_research_chunk(row)

    def find_research_chunks(
        self,
        *,
        project_id: str,
        scope: str,
        scope_id: str | None,
        embedding_model: str,
        embedding: list[float],
        limit: int = 8,
    ) -> list[ResearchChunk]:
        """Retrieve the most relevant local evidence chunks for one research scope."""
        if not self.is_postgres:
            return []
        rows = self._fetchall(
            f"""
            SELECT *
            FROM research_chunks
            WHERE project_id = {self.param}
              AND scope = {self.param}
              AND COALESCE(scope_id, '') = COALESCE({self.param}, '')
              AND embedding_model = {self.param}
            ORDER BY embedding <=> {self.param} ASC
            LIMIT {self.param}
            """,
            (project_id, scope, scope_id, embedding_model, Vector(embedding), limit),
        )
        return [self._row_to_research_chunk(row) for row in rows]

    def insert_research_finding(
        self,
        *,
        project_id: str,
        scope: str,
        scope_id: str | None,
        finding_type: str,
        title: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> ResearchFinding:
        """Persist one normalized competitor-intelligence finding."""
        finding_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO research_findings (
                id, project_id, scope, scope_id, finding_type, title, summary, payload, created_at, updated_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                finding_id,
                project_id,
                scope,
                scope_id,
                finding_type,
                title,
                summary,
                self._dump_json(payload or {}),
                now,
                now,
            ),
        )
        return self.get_research_finding(finding_id)

    def get_research_finding(self, finding_id: str) -> ResearchFinding:
        """Return one persisted research finding."""
        row = self._fetchone(
            f"SELECT * FROM research_findings WHERE id = {self.param}",
            (finding_id,),
        )
        if row is None:
            raise ValueError(f"Research finding not found: {finding_id}")
        return self._row_to_research_finding(row)

    def list_research_findings(self, project_id: str) -> list[ResearchFinding]:
        """Return all persisted competitor-intelligence findings for a project."""
        rows = self._fetchall(
            f"SELECT * FROM research_findings WHERE project_id = {self.param} ORDER BY updated_at DESC",
            (project_id,),
        )
        return [self._row_to_research_finding(row) for row in rows]

    def list_research_findings_for_scope(
        self,
        project_id: str,
        *,
        scope: str,
        scope_id: str | None = None,
    ) -> list[ResearchFinding]:
        """Return research findings for one brief or pillar scope."""
        rows = self._fetchall(
            f"""
            SELECT * FROM research_findings
            WHERE project_id = {self.param}
              AND scope = {self.param}
              AND COALESCE(scope_id, '') = COALESCE({self.param}, '')
            ORDER BY updated_at DESC
            """,
            (project_id, scope, scope_id),
        )
        return [self._row_to_research_finding(row) for row in rows]

