from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg import sql
from psycopg.errors import DuplicateDatabase, InvalidCatalogName
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from specforge.models import (
    BriefConversationTurn,
    Node,
    Project,
    ProjectBrief,
    ProjectModelSettings,
    ProjectMemory,
    ResearchChunk,
    ResearchFinding,
    ResearchJob,
    ResearchSource,
    SimilarityMatch,
)


UNSET = object()


def utc_now() -> str:
    """Return an ISO timestamp in UTC for persistent records."""
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Store SpecForge state in either PostgreSQL or SQLite through one stable API."""

    def __init__(self, target: str | Path, *, postgres_admin_url: str | None = None):
        self.target = target
        self.postgres_admin_url = postgres_admin_url
        self.is_postgres = self._is_postgres_target(target)
        self.param = "%s" if self.is_postgres else "?"
        if self.is_postgres:
            self.database_url = str(target)
            self.db_path = None
            self._ensure_postgres_database()
        else:
            self.database_url = None
            self.db_path = Path(target)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterable[Any]:
        """Open a database connection with the correct row format for the active backend."""
        if self.is_postgres:
            connection = psycopg.connect(self.database_url, row_factory=dict_row)
            register_vector(connection)
        else:
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the required schema, indexes, and pgvector extension when available."""
        if self.is_postgres:
            self._initialize_postgres()
            return
        self._initialize_sqlite()

    def create_project(self, name: str, idea: str) -> Project:
        """Create and persist a new SpecForge project."""
        project_id = str(uuid.uuid4())
        created_at = utc_now()
        query = f"""
            INSERT INTO projects (id, name, idea, created_at)
            VALUES ({self.param}, {self.param}, {self.param}, {self.param})
        """
        self._execute(query, (project_id, name, idea, created_at))
        return self.get_project(project_id)

    def list_projects(self) -> list[Project]:
        """Return projects in reverse creation order with lightweight workspace metadata."""
        rows = self._fetchall(
            """
            SELECT
                projects.id,
                projects.name,
                projects.idea,
                projects.created_at,
                COALESCE(project_briefs.status, 'draft') AS brief_status,
                project_briefs.updated_at AS brief_updated_at,
                COALESCE(COUNT(DISTINCT nodes.id), 0) AS node_count,
                COALESCE(SUM(CASE WHEN nodes.node_type = 'pillar' THEN 1 ELSE 0 END), 0) AS pillar_count
            FROM projects
            LEFT JOIN project_briefs ON project_briefs.project_id = projects.id
            LEFT JOIN nodes ON nodes.project_id = projects.id
            GROUP BY projects.id, projects.name, projects.idea, projects.created_at, project_briefs.status, project_briefs.updated_at
            ORDER BY projects.created_at DESC
            """
        )
        return [self._row_to_project_summary(row) for row in rows]

    def get_project(self, project_id: str) -> Project:
        """Look up a single project by id."""
        row = self._fetchone(
            f"SELECT id, name, idea, created_at FROM projects WHERE id = {self.param}",
            (project_id,),
        )
        if row is None:
            raise ValueError(f"Project not found: {project_id}")
        return self._row_to_project(row)

    def upsert_project_brief(
        self,
        *,
        project_id: str,
        product_idea: str,
        known_competitors: list[str],
        constraints: str,
        target_users: str = "",
        goals: list[str] | None = None,
        preferred_directions: list[str] | None = None,
        rejected_directions: list[str] | None = None,
        notes: str = "",
        status: str = "draft",
    ) -> ProjectBrief:
        """Create or update the structured Layer 0 brief used by local competitor research."""
        now = utc_now()
        goals = goals or []
        preferred_directions = preferred_directions or []
        rejected_directions = rejected_directions or []
        existing = self._fetchone(
            f"SELECT id FROM project_briefs WHERE project_id = {self.param}",
            (project_id,),
        )
        if existing is None:
            brief_id = str(uuid.uuid4())
            self._execute(
                f"""
                INSERT INTO project_briefs (
                    id, project_id, product_idea, known_competitors, constraints, target_users,
                    goals, preferred_directions, rejected_directions, notes, status, created_at, updated_at
                )
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
                """,
                (
                    brief_id,
                    project_id,
                    product_idea,
                    self._dump_json(known_competitors),
                    constraints,
                    target_users,
                    self._dump_json(goals),
                    self._dump_json(preferred_directions),
                    self._dump_json(rejected_directions),
                    notes,
                    status,
                    now,
                    now,
                ),
            )
        else:
            brief_id = str(self._row_value(existing, "id"))
            self._execute(
                f"""
                UPDATE project_briefs
                SET product_idea = {self.param},
                    known_competitors = {self.param},
                    constraints = {self.param},
                    target_users = {self.param},
                    goals = {self.param},
                    preferred_directions = {self.param},
                    rejected_directions = {self.param},
                    notes = {self.param},
                    status = {self.param},
                    updated_at = {self.param}
                WHERE id = {self.param}
                """,
                (
                    product_idea,
                    self._dump_json(known_competitors),
                    constraints,
                    target_users,
                    self._dump_json(goals),
                    self._dump_json(preferred_directions),
                    self._dump_json(rejected_directions),
                    notes,
                    status,
                    now,
                    brief_id,
                ),
            )
        return self.get_project_brief(project_id)

    def get_project_brief(self, project_id: str) -> ProjectBrief | None:
        """Return the structured Layer 0 brief if it exists."""
        row = self._fetchone(
            f"SELECT * FROM project_briefs WHERE project_id = {self.param}",
            (project_id,),
        )
        if row is None:
            return None
        return self._row_to_project_brief(row)

    def get_app_setting(self, key: str) -> str | None:
        """Fetch a persisted app-level setting value."""
        row = self._fetchone(
            f"SELECT value FROM app_settings WHERE key = {self.param}",
            (key,),
        )
        if row is None:
            return None
        return str(self._row_value(row, "value"))

    def set_app_setting(self, key: str, value: str) -> None:
        """Persist an app-level setting so runtime choices survive a restart."""
        self._execute(
            f"""
            INSERT INTO app_settings (key, value)
            VALUES ({self.param}, {self.param})
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (key, value),
        )

    def get_project_model_settings(self, project_id: str) -> ProjectModelSettings | None:
        """Return the persisted per-project model routing settings if present."""
        row = self._fetchone(
            f"SELECT * FROM project_model_settings WHERE project_id = {self.param}",
            (project_id,),
        )
        if row is None:
            return None
        return self._row_to_project_model_settings(row)

    def upsert_project_model_settings(
        self,
        *,
        project_id: str,
        llm_profiles: list[dict[str, Any]],
        embedding_profiles: list[dict[str, Any]],
        assignments: dict[str, Any],
        prompt_catalog: dict[str, Any],
    ) -> ProjectModelSettings:
        """Create or update the per-project model profile and assignment map."""
        now = utc_now()
        existing = self._fetchone(
            f"SELECT project_id FROM project_model_settings WHERE project_id = {self.param}",
            (project_id,),
        )
        if existing is None:
            self._execute(
                f"""
                INSERT INTO project_model_settings (
                    project_id, llm_profiles, embedding_profiles, assignments, prompt_catalog, created_at, updated_at
                )
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
                """,
                (
                    project_id,
                    self._dump_json(llm_profiles),
                    self._dump_json(embedding_profiles),
                    self._dump_json(assignments),
                    self._dump_json(prompt_catalog),
                    now,
                    now,
                ),
            )
        else:
            self._execute(
                f"""
                UPDATE project_model_settings
                SET llm_profiles = {self.param},
                    embedding_profiles = {self.param},
                    assignments = {self.param},
                    prompt_catalog = {self.param},
                    updated_at = {self.param}
                WHERE project_id = {self.param}
                """,
                (
                    self._dump_json(llm_profiles),
                    self._dump_json(embedding_profiles),
                    self._dump_json(assignments),
                    self._dump_json(prompt_catalog),
                    now,
                    project_id,
                ),
            )
        return self.get_project_model_settings(project_id)

    def append_brief_conversation_turn(
        self,
        *,
        project_id: str,
        role: str,
        content: str,
        extracted_updates: dict[str, Any] | None = None,
    ) -> BriefConversationTurn:
        """Store one Plan-mode chat turn or extracted turn summary separate from the brief."""
        turn_id = str(uuid.uuid4())
        created_at = utc_now()
        self._execute(
            f"""
            INSERT INTO brief_conversations (
                id, project_id, role, content, extracted_updates, created_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                turn_id,
                project_id,
                role,
                content,
                self._dump_json(extracted_updates or {}),
                created_at,
            ),
        )
        return self.get_brief_conversation_turn(turn_id)

    def get_brief_conversation_turn(self, turn_id: str) -> BriefConversationTurn:
        """Return one stored Layer 0 Plan-mode turn."""
        row = self._fetchone(
            f"SELECT * FROM brief_conversations WHERE id = {self.param}",
            (turn_id,),
        )
        if row is None:
            raise ValueError(f"Brief conversation turn not found: {turn_id}")
        return self._row_to_brief_conversation_turn(row)

    def list_brief_conversation(self, project_id: str, *, limit: int = 80) -> list[BriefConversationTurn]:
        """Return recent Plan-mode turns in chronological order for the workspace."""
        rows = self._fetchall(
            f"""
            SELECT * FROM brief_conversations
            WHERE project_id = {self.param}
            ORDER BY created_at DESC
            LIMIT {self.param}
            """,
            (project_id, limit),
        )
        return [self._row_to_brief_conversation_turn(row) for row in reversed(rows)]

    def create_node(
        self,
        *,
        project_id: str,
        parent_id: str | None,
        layer: int,
        node_type: str,
        title: str,
        description: str | None,
        json_payload: dict[str, Any] | None = None,
        status: str = "generated",
        priority: int | None = None,
    ) -> Node:
        """Create and persist a tree node under the active project."""
        node_id = str(uuid.uuid4())
        created_at = utc_now()
        payload = self._dump_json(json_payload or {})
        query = f"""
            INSERT INTO nodes (
                id, project_id, parent_id, layer, node_type, title, description,
                json_payload, status, priority, created_at
            )
            VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}
            )
        """
        self._execute(
            query,
            (
                node_id,
                project_id,
                parent_id,
                layer,
                node_type,
                title,
                description,
                payload,
                status,
                priority,
                created_at,
            ),
        )
        return self.get_node(node_id)

    def get_node(self, node_id: str) -> Node:
        """Look up a single node by id."""
        row = self._fetchone(f"SELECT * FROM nodes WHERE id = {self.param}", (node_id,))
        if row is None:
            raise ValueError(f"Node not found: {node_id}")
        return self._row_to_node(row)

    def list_nodes(
        self,
        project_id: str,
        *,
        parent_id: str | None = None,
        layer: int | None = None,
        node_type: str | None = None,
    ) -> list[Node]:
        """List nodes with optional parent/layer/type filters."""
        query = f"SELECT * FROM nodes WHERE project_id = {self.param}"
        params: list[Any] = [project_id]
        if parent_id is None:
            query += " AND parent_id IS NULL"
        elif parent_id != "__any__":
            query += f" AND parent_id = {self.param}"
            params.append(parent_id)
        if layer is not None:
            query += f" AND layer = {self.param}"
            params.append(layer)
        if node_type is not None:
            query += f" AND node_type = {self.param}"
            params.append(node_type)
        query += " ORDER BY layer ASC, created_at ASC"
        rows = self._fetchall(query, tuple(params))
        return [self._row_to_node(row) for row in rows]

    def list_all_nodes(self, project_id: str) -> list[Node]:
        """Return every node in the project tree."""
        return self.list_nodes(project_id, parent_id="__any__")

    def update_node(
        self,
        node_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        json_payload: dict[str, Any] | None = None,
        status: str | None = None,
        priority: int | None | object = UNSET,
    ) -> Node:
        """Update only the provided node fields and return the fresh record."""
        updates: list[str] = []
        params: list[Any] = []
        if title is not None:
            updates.append(f"title = {self.param}")
            params.append(title)
        if description is not None:
            updates.append(f"description = {self.param}")
            params.append(description)
        if json_payload is not None:
            updates.append(f"json_payload = {self.param}")
            params.append(self._dump_json(json_payload))
        if status is not None:
            updates.append(f"status = {self.param}")
            params.append(status)
        if priority is not UNSET:
            updates.append(f"priority = {self.param}")
            params.append(priority)
        if not updates:
            return self.get_node(node_id)
        params.append(node_id)
        query = f"UPDATE nodes SET {', '.join(updates)} WHERE id = {self.param}"
        self._execute(query, tuple(params))
        return self.get_node(node_id)

    def save_generation(
        self,
        *,
        project_id: str,
        node_id: str | None,
        prompt: str,
        raw_response: str,
        parsed_json: dict[str, Any] | None,
        model_name: str | None,
    ) -> str:
        """Persist a raw generation log for debugging and auditability."""
        generation_id = str(uuid.uuid4())
        query = f"""
            INSERT INTO generations (
                id, project_id, node_id, prompt, raw_response,
                parsed_json, model_name, created_at
            )
            VALUES (
                {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}
            )
        """
        self._execute(
            query,
            (
                generation_id,
                project_id,
                node_id,
                prompt,
                raw_response,
                self._dump_json(parsed_json) if parsed_json else None,
                model_name,
                utc_now(),
            ),
        )
        return generation_id

    def upsert_project_memory(
        self,
        *,
        project_id: str,
        scope: str,
        scope_id: str | None,
        memory_type: str,
        content: dict[str, Any],
    ) -> ProjectMemory:
        """Create or update a single scoped project-memory record."""
        now = utc_now()
        memory_id = str(uuid.uuid4())
        existing = self._fetchone(
            f"""
            SELECT id FROM project_memory
            WHERE project_id = {self.param}
              AND scope = {self.param}
              AND COALESCE(scope_id, '') = COALESCE({self.param}, '')
              AND memory_type = {self.param}
            """,
            (project_id, scope, scope_id, memory_type),
        )
        if existing:
            self._execute(
                f"""
                UPDATE project_memory
                SET content = {self.param}, updated_at = {self.param}
                WHERE id = {self.param}
                """,
                (self._dump_json(content), now, self._row_value(existing, "id")),
            )
            memory_id = str(self._row_value(existing, "id"))
        else:
            self._execute(
                f"""
                INSERT INTO project_memory (
                    id, project_id, scope, scope_id, memory_type, content, created_at, updated_at
                )
                VALUES (
                    {self.param}, {self.param}, {self.param}, {self.param},
                    {self.param}, {self.param}, {self.param}, {self.param}
                )
                """,
                (
                    memory_id,
                    project_id,
                    scope,
                    scope_id,
                    memory_type,
                    self._dump_json(content),
                    now,
                    now,
                ),
            )
        return self.get_project_memory(
            project_id=project_id,
            scope=scope,
            scope_id=scope_id,
            memory_type=memory_type,
        )

    def get_project_memory(
        self,
        *,
        project_id: str,
        scope: str,
        scope_id: str | None,
        memory_type: str,
    ) -> ProjectMemory | None:
        """Return one scoped project-memory record if it exists."""
        row = self._fetchone(
            f"""
            SELECT * FROM project_memory
            WHERE project_id = {self.param}
              AND scope = {self.param}
              AND COALESCE(scope_id, '') = COALESCE({self.param}, '')
              AND memory_type = {self.param}
            """,
            (project_id, scope, scope_id, memory_type),
        )
        if row is None:
            return None
        return self._row_to_project_memory(row)

    def list_project_memory(self, project_id: str) -> list[ProjectMemory]:
        """Return every project-memory record ordered by most recent update."""
        rows = self._fetchall(
            f"SELECT * FROM project_memory WHERE project_id = {self.param} ORDER BY updated_at DESC",
            (project_id,),
        )
        return [self._row_to_project_memory(row) for row in rows]

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

    def get_rejected_ideas(self, project_id: str) -> list[str]:
        """Return user-cut nodes as promptable rejected directions."""
        rows = self._fetchall(
            f"""
            SELECT title, description
            FROM nodes
            WHERE project_id = {self.param} AND status = 'cut'
            ORDER BY created_at ASC
            """,
            (project_id,),
        )
        rejected = []
        for row in rows:
            title = str(self._row_value(row, "title"))
            description = self._row_value(row, "description")
            rejected.append(f"{title}: {description}" if description else title)
        return rejected

    def import_sqlite_file(self, sqlite_path: Path) -> None:
        """Seed the current database from a legacy SQLite file while preserving record ids."""
        if not sqlite_path.exists():
            return
        with sqlite3.connect(sqlite_path) as sqlite_conn:
            sqlite_conn.row_factory = sqlite3.Row
            self._copy_rows(
                "projects",
                ("id", "name", "idea", "created_at"),
                sqlite_conn.execute("SELECT id, name, idea, created_at FROM projects").fetchall(),
            )
            self._copy_rows(
                "nodes",
                (
                    "id",
                    "project_id",
                    "parent_id",
                    "layer",
                    "node_type",
                    "title",
                    "description",
                    "json_payload",
                    "status",
                    "priority",
                    "created_at",
                ),
                sqlite_conn.execute(
                    """
                    SELECT id, project_id, parent_id, layer, node_type, title, description,
                           json_payload, status, priority, created_at
                    FROM nodes
                    """
                ).fetchall(),
            )
            self._copy_rows(
                "generations",
                ("id", "project_id", "node_id", "prompt", "raw_response", "parsed_json", "model_name", "created_at"),
                sqlite_conn.execute(
                    """
                    SELECT id, project_id, node_id, prompt, raw_response,
                           parsed_json, model_name, created_at
                    FROM generations
                    """
                ).fetchall(),
            )
            self._copy_rows(
                "project_memory",
                ("id", "project_id", "scope", "scope_id", "memory_type", "content", "created_at", "updated_at"),
                sqlite_conn.execute(
                    """
                    SELECT id, project_id, scope, scope_id, memory_type, content, created_at, updated_at
                    FROM project_memory
                    """
                ).fetchall(),
            )

    def get_node_embedding_hash(self, node_id: str, embedding_model: str) -> str | None:
        """Return the stored content hash for a node embedding when it exists."""
        if not self.is_postgres:
            return None
        row = self._fetchone(
            f"""
            SELECT content_hash
            FROM node_embeddings
            WHERE node_id = {self.param} AND embedding_model = {self.param}
            """,
            (node_id, embedding_model),
        )
        if row is None:
            return None
        value = self._row_value(row, "content_hash")
        return str(value) if value is not None else None

    def upsert_node_embedding(
        self,
        *,
        project_id: str,
        node_id: str,
        embedding_model: str,
        embedding: list[float],
        content_hash: str,
    ) -> None:
        """Store or refresh a node embedding in pgvector-backed storage."""
        if not self.is_postgres:
            return
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO node_embeddings (
                id, project_id, node_id, embedding_model, embedding, content_hash, created_at, updated_at
            )
            VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}
            )
            ON CONFLICT (node_id, embedding_model)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                content_hash = EXCLUDED.content_hash,
                updated_at = EXCLUDED.updated_at
            """,
            (
                str(uuid.uuid4()),
                project_id,
                node_id,
                embedding_model,
                Vector(embedding),
                content_hash,
                now,
                now,
            ),
        )

    def find_similar_nodes(
        self,
        *,
        project_id: str,
        embedding_model: str,
        embedding: list[float],
        layer: int | None = None,
        node_type: str | None = None,
        exclude_node_ids: list[str] | None = None,
        min_similarity: float = 0.0,
        limit: int = 5,
    ) -> list[SimilarityMatch]:
        """Return the most cosine-similar nodes for the supplied embedding."""
        if not self.is_postgres:
            return []
        query = f"""
            SELECT
                nodes.id AS node_id,
                nodes.title,
                nodes.description,
                nodes.layer,
                nodes.node_type,
                1 - (node_embeddings.embedding <=> {self.param}) AS score
            FROM node_embeddings
            JOIN nodes ON nodes.id = node_embeddings.node_id
            WHERE node_embeddings.project_id = {self.param}
              AND node_embeddings.embedding_model = {self.param}
        """
        vector = Vector(embedding)
        params: list[Any] = [vector, project_id, embedding_model]
        if layer is not None:
            query += f" AND nodes.layer = {self.param}"
            params.append(layer)
        if node_type is not None:
            query += f" AND nodes.node_type = {self.param}"
            params.append(node_type)
        if exclude_node_ids:
            placeholders = ", ".join([self.param] * len(exclude_node_ids))
            query += f" AND nodes.id NOT IN ({placeholders})"
            params.extend(exclude_node_ids)
        query += f" AND 1 - (node_embeddings.embedding <=> {self.param}) >= {self.param}"
        params.extend([vector, min_similarity])
        query += f" ORDER BY node_embeddings.embedding <=> {self.param} ASC LIMIT {self.param}"
        params.extend([vector, limit])
        rows = self._fetchall(query, tuple(params))
        return [
            SimilarityMatch(
                node_id=str(self._row_value(row, "node_id")),
                title=str(self._row_value(row, "title")),
                description=self._row_value(row, "description"),
                layer=int(self._row_value(row, "layer")),
                node_type=str(self._row_value(row, "node_type")),
                score=float(self._row_value(row, "score")),
            )
            for row in rows
        ]

    def _copy_rows(self, table: str, columns: tuple[str, ...], rows: list[Any]) -> None:
        """Insert legacy rows into the current database only when they are not already present."""
        if not rows:
            return
        placeholders = ", ".join([self.param] * len(columns))
        column_list = ", ".join(columns)
        for row in rows:
            values = [self._prepare_import_value(self._row_value(row, column)) for column in columns]
            query = f"INSERT INTO {table} ({column_list}) VALUES ({placeholders})"
            if self.is_postgres:
                query += " ON CONFLICT (id) DO NOTHING"
            else:
                query = query.replace("INSERT INTO", "INSERT OR IGNORE INTO", 1)
            self._execute(query, tuple(values))

    def _prepare_import_value(self, value: Any) -> Any:
        """Normalize imported SQLite values before inserting them into the active backend."""
        if isinstance(value, (dict, list)):
            return self._dump_json(value)
        return value

    def _initialize_sqlite(self) -> None:
        """Create the SQLite schema used by tests and legacy local setups."""
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    idea TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_briefs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL UNIQUE,
                    product_idea TEXT NOT NULL,
                    known_competitors TEXT NOT NULL,
                    constraints TEXT NOT NULL,
                    target_users TEXT NOT NULL DEFAULT '',
                    goals TEXT NOT NULL DEFAULT '[]',
                    preferred_directions TEXT NOT NULL DEFAULT '[]',
                    rejected_directions TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_model_settings (
                    project_id TEXT PRIMARY KEY,
                    llm_profiles TEXT NOT NULL,
                    embedding_profiles TEXT NOT NULL,
                    assignments TEXT NOT NULL,
                    prompt_catalog TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS brief_conversations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    extracted_updates TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    parent_id TEXT,
                    layer INTEGER NOT NULL,
                    node_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    json_payload TEXT,
                    status TEXT DEFAULT 'generated',
                    priority INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(parent_id) REFERENCES nodes(id)
                );

                CREATE TABLE IF NOT EXISTS generations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    node_id TEXT,
                    prompt TEXT NOT NULL,
                    raw_response TEXT NOT NULL,
                    parsed_json TEXT,
                    model_name TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_memory (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_jobs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    details TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS research_sources (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    competitor_name TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    url TEXT NOT NULL,
                    page_type TEXT NOT NULL,
                    title TEXT,
                    status_code INTEGER,
                    fetched_at TEXT NOT NULL,
                    content_hash TEXT,
                    metadata TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE TABLE IF NOT EXISTS research_chunks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    source_id TEXT NOT NULL,
                    competitor_name TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding TEXT,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id),
                    FOREIGN KEY(source_id) REFERENCES research_sources(id)
                );

                CREATE TABLE IF NOT EXISTS research_findings (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    scope_id TEXT,
                    finding_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_project_memory_scope
                ON project_memory(project_id, scope, COALESCE(scope_id, ''), memory_type);

                CREATE INDEX IF NOT EXISTS idx_nodes_project_parent_layer_type
                ON nodes(project_id, COALESCE(parent_id, ''), layer, node_type);

                CREATE INDEX IF NOT EXISTS idx_brief_conversations_project_created
                ON brief_conversations(project_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_nodes_project_status
                ON nodes(project_id, status);

                CREATE INDEX IF NOT EXISTS idx_app_settings_key
                ON app_settings(key);

                CREATE INDEX IF NOT EXISTS idx_project_model_settings_project
                ON project_model_settings(project_id);

                CREATE INDEX IF NOT EXISTS idx_generations_project_node
                ON generations(project_id, node_id, created_at);

                CREATE INDEX IF NOT EXISTS idx_research_jobs_project_scope
                ON research_jobs(project_id, scope, COALESCE(scope_id, ''), updated_at);

                CREATE INDEX IF NOT EXISTS idx_research_sources_project_scope
                ON research_sources(project_id, scope, COALESCE(scope_id, ''), fetched_at);

                CREATE INDEX IF NOT EXISTS idx_research_findings_project_scope
                ON research_findings(project_id, scope, COALESCE(scope_id, ''), updated_at);
                """
            )
        try:
            self._execute(
                "ALTER TABLE project_model_settings ADD COLUMN prompt_catalog TEXT NOT NULL DEFAULT '{}'"
            )
        except Exception as exc:
            if "duplicate column name" not in str(exc).lower():
                raise

    def _initialize_postgres(self) -> None:
        """Create the PostgreSQL schema and enable pgvector for future retrieval work."""
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS projects (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        idea TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_briefs (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
                        product_idea TEXT NOT NULL,
                        known_competitors JSONB NOT NULL,
                        constraints TEXT NOT NULL,
                        target_users TEXT NOT NULL DEFAULT '',
                        goals JSONB NOT NULL DEFAULT '[]'::jsonb,
                        preferred_directions JSONB NOT NULL DEFAULT '[]'::jsonb,
                        rejected_directions JSONB NOT NULL DEFAULT '[]'::jsonb,
                        notes TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'draft',
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_model_settings (
                        project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                        llm_profiles JSONB NOT NULL,
                        embedding_profiles JSONB NOT NULL,
                        assignments JSONB NOT NULL,
                        prompt_catalog JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS target_users TEXT NOT NULL DEFAULT ''")
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS goals JSONB NOT NULL DEFAULT '[]'::jsonb")
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS preferred_directions JSONB NOT NULL DEFAULT '[]'::jsonb")
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS rejected_directions JSONB NOT NULL DEFAULT '[]'::jsonb")
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS notes TEXT NOT NULL DEFAULT ''")
                cursor.execute("ALTER TABLE project_briefs ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft'")
                cursor.execute("ALTER TABLE project_model_settings ADD COLUMN IF NOT EXISTS prompt_catalog JSONB NOT NULL DEFAULT '{}'::jsonb")
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS brief_conversations (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        extracted_updates JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS nodes (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        parent_id TEXT REFERENCES nodes(id) ON DELETE CASCADE,
                        layer INTEGER NOT NULL,
                        node_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        description TEXT,
                        json_payload JSONB,
                        status TEXT DEFAULT 'generated',
                        priority INTEGER,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS generations (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        node_id TEXT REFERENCES nodes(id) ON DELETE SET NULL,
                        prompt TEXT NOT NULL,
                        raw_response TEXT NOT NULL,
                        parsed_json JSONB,
                        model_name TEXT,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS project_memory (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        memory_type TEXT NOT NULL,
                        content JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS node_embeddings (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        node_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                        embedding_model TEXT NOT NULL,
                        embedding vector(384) NOT NULL,
                        content_hash TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_jobs (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        job_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        progress INTEGER NOT NULL,
                        details JSONB NOT NULL,
                        error TEXT,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_sources (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        competitor_name TEXT NOT NULL,
                        domain TEXT NOT NULL,
                        url TEXT NOT NULL,
                        page_type TEXT NOT NULL,
                        title TEXT,
                        status_code INTEGER,
                        fetched_at TIMESTAMPTZ NOT NULL,
                        content_hash TEXT,
                        metadata JSONB NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_chunks (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        source_id TEXT NOT NULL REFERENCES research_sources(id) ON DELETE CASCADE,
                        competitor_name TEXT NOT NULL,
                        domain TEXT NOT NULL,
                        url TEXT NOT NULL,
                        title TEXT,
                        chunk_index INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        embedding_model TEXT NOT NULL,
                        embedding vector(384) NOT NULL,
                        metadata JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS research_findings (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        scope TEXT NOT NULL,
                        scope_id TEXT,
                        finding_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_project_memory_scope
                    ON project_memory(project_id, scope, COALESCE(scope_id, ''), memory_type)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_nodes_project_parent_layer_type
                    ON nodes(project_id, COALESCE(parent_id, ''), layer, node_type)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_brief_conversations_project_created
                    ON brief_conversations(project_id, created_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_nodes_project_status
                    ON nodes(project_id, status)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_app_settings_key
                    ON app_settings(key)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_project_model_settings_project
                    ON project_model_settings(project_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_generations_project_node
                    ON generations(project_id, node_id, created_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_node_embeddings_project_node
                    ON node_embeddings(project_id, node_id)
                    """
                )
                cursor.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_node_embeddings_node_model
                    ON node_embeddings(node_id, embedding_model)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_research_jobs_project_scope
                    ON research_jobs(project_id, scope, COALESCE(scope_id, ''), updated_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_research_sources_project_scope
                    ON research_sources(project_id, scope, COALESCE(scope_id, ''), fetched_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_research_findings_project_scope
                    ON research_findings(project_id, scope, COALESCE(scope_id, ''), updated_at)
                    """
                )
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_research_chunks_project_scope
                    ON research_chunks(project_id, scope, COALESCE(scope_id, ''), source_id)
                    """
                )

    def _ensure_postgres_database(self) -> None:
        """Create the target PostgreSQL database if it does not already exist."""
        parsed = urlparse(self.database_url)
        database_name = parsed.path.lstrip("/")
        if not database_name:
            raise RuntimeError("PostgreSQL database URL must include a database name.")
        admin_url = self.postgres_admin_url or self._postgres_admin_url(parsed)
        try:
            with psycopg.connect(self.database_url, row_factory=dict_row):
                return
        except InvalidCatalogName:
            pass
        except psycopg.OperationalError as exc:
            if "does not exist" not in str(exc).lower():
                raise RuntimeError(f"Unable to connect to PostgreSQL target '{self.database_url}': {exc}") from exc

        try:
            with psycopg.connect(admin_url, autocommit=True, row_factory=dict_row) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
                    if cursor.fetchone() is None:
                        cursor.execute(
                            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
                        )
        except DuplicateDatabase:
            return
        except psycopg.OperationalError as exc:
            raise RuntimeError(
                f"Unable to connect to PostgreSQL admin database '{admin_url}'. "
                "Set SPECFORGE_POSTGRES_ADMIN_URL if the default admin connection is wrong."
            ) from exc

    def _postgres_admin_url(self, parsed_target: Any) -> str:
        """Build an admin connection URL that points at the default postgres database."""
        return urlunparse(parsed_target._replace(path="/postgres"))

    def _execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        """Execute a write statement against the active backend."""
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
            finally:
                cursor.close()

    def _fetchone(self, query: str, params: tuple[Any, ...] = ()) -> Any | None:
        """Fetch one row from the active backend."""
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                return cursor.fetchone()
            finally:
                cursor.close()

    def _fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[Any]:
        """Fetch every matching row from the active backend."""
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                return list(cursor.fetchall())
            finally:
                cursor.close()

    @staticmethod
    def _is_postgres_target(target: str | Path) -> bool:
        """Detect whether the given target represents a PostgreSQL connection URL."""
        return isinstance(target, str) and target.startswith(("postgresql://", "postgres://"))

    @staticmethod
    def _row_value(row: Any, key: str) -> Any:
        """Read a field from either a sqlite row, psycopg dict row, or plain dict."""
        return row[key]

    def _dump_json(self, payload: Any) -> Any:
        """Serialize JSON for the active backend so both SQLite and Postgres accept writes cleanly."""
        if self.is_postgres:
            return Jsonb(payload)
        return json.dumps(payload, ensure_ascii=True)

    def _load_json(self, payload: Any) -> dict[str, Any]:
        """Normalize JSON fields from either backend into Python dictionaries."""
        if payload is None:
            return {}
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            return json.loads(payload or "{}")
        return dict(payload)

    def _load_json_list(self, payload: Any) -> list[Any]:
        """Normalize JSON fields that should contain arrays, tolerating legacy object defaults."""
        if payload is None:
            return []
        if isinstance(payload, list):
            return payload
        if isinstance(payload, str):
            value = json.loads(payload or "[]")
            return value if isinstance(value, list) else []
        return []

    @staticmethod
    def _row_to_project(row: Any) -> Project:
        """Convert a raw database row into a Project model."""
        return Project(
            id=row["id"],
            name=row["name"],
            idea=row["idea"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_project_summary(self, row: Any) -> dict[str, Any]:
        """Convert a project row with summary metadata into a plain payload for the hub."""
        brief_updated_at = row["brief_updated_at"]
        return {
            "id": row["id"],
            "name": row["name"],
            "idea": row["idea"],
            "created_at": datetime.fromisoformat(str(row["created_at"])),
            "brief_status": row["brief_status"],
            "brief_updated_at": datetime.fromisoformat(str(brief_updated_at)) if brief_updated_at else None,
            "node_count": int(row["node_count"]),
            "pillar_count": int(row["pillar_count"]),
        }

    def _row_to_project_brief(self, row: Any) -> ProjectBrief:
        """Convert a raw database row into a ProjectBrief model."""
        return ProjectBrief(
            id=row["id"],
            project_id=row["project_id"],
            product_idea=row["product_idea"],
            known_competitors=self._load_json_list(row["known_competitors"]),
            constraints=row["constraints"],
            target_users=row["target_users"],
            goals=self._load_json_list(row["goals"]),
            preferred_directions=self._load_json_list(row["preferred_directions"]),
            rejected_directions=self._load_json_list(row["rejected_directions"]),
            notes=row["notes"],
            status=row["status"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_project_model_settings(self, row: Any) -> ProjectModelSettings:
        """Convert a raw database row into a ProjectModelSettings model."""
        return ProjectModelSettings(
            project_id=row["project_id"],
            llm_profiles=self._load_json_list(row["llm_profiles"]),
            embedding_profiles=self._load_json_list(row["embedding_profiles"]),
            assignments=self._load_json(row["assignments"]),
            prompt_catalog=self._load_json(row["prompt_catalog"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_brief_conversation_turn(self, row: Any) -> BriefConversationTurn:
        """Convert a raw database row into a BriefConversationTurn model."""
        return BriefConversationTurn(
            id=row["id"],
            project_id=row["project_id"],
            role=row["role"],
            content=row["content"],
            extracted_updates=self._load_json(row["extracted_updates"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_node(self, row: Any) -> Node:
        """Convert a raw database row into a Node model."""
        return Node(
            id=row["id"],
            project_id=row["project_id"],
            parent_id=row["parent_id"],
            layer=row["layer"],
            node_type=row["node_type"],
            title=row["title"],
            description=row["description"],
            json_payload=self._load_json(row["json_payload"]),
            status=row["status"],
            priority=row["priority"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_project_memory(self, row: Any) -> ProjectMemory:
        """Convert a raw database row into a ProjectMemory model."""
        return ProjectMemory(
            id=row["id"],
            project_id=row["project_id"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            memory_type=row["memory_type"],
            content=self._load_json(row["content"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_research_job(self, row: Any) -> ResearchJob:
        """Convert a raw database row into a ResearchJob model."""
        return ResearchJob(
            id=row["id"],
            project_id=row["project_id"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            job_type=row["job_type"],
            status=row["status"],
            progress=int(row["progress"]),
            details=self._load_json(row["details"]),
            error=row["error"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_research_source(self, row: Any) -> ResearchSource:
        """Convert a raw database row into a ResearchSource model."""
        return ResearchSource(
            id=row["id"],
            project_id=row["project_id"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            competitor_name=row["competitor_name"],
            domain=row["domain"],
            url=row["url"],
            page_type=row["page_type"],
            title=row["title"],
            status_code=row["status_code"],
            fetched_at=datetime.fromisoformat(str(row["fetched_at"])),
            content_hash=row["content_hash"],
            metadata=self._load_json(row["metadata"]),
        )

    def _row_to_research_chunk(self, row: Any) -> ResearchChunk:
        """Convert a raw database row into a ResearchChunk model."""
        return ResearchChunk(
            id=row["id"],
            project_id=row["project_id"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            source_id=row["source_id"],
            competitor_name=row["competitor_name"],
            domain=row["domain"],
            url=row["url"],
            title=row["title"],
            chunk_index=int(row["chunk_index"]),
            text=row["text"],
            metadata=self._load_json(row["metadata"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_research_finding(self, row: Any) -> ResearchFinding:
        """Convert a raw database row into a ResearchFinding model."""
        return ResearchFinding(
            id=row["id"],
            project_id=row["project_id"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            finding_type=row["finding_type"],
            title=row["title"],
            summary=row["summary"],
            payload=self._load_json(row["payload"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
