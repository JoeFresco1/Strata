from __future__ import annotations

import json
import sqlite3
import threading
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

from strata.db_embeddings import DatabaseEmbeddingMixin
from strata.db_data_ownership import DataOwnershipDatabaseMixin
from strata.db_jobs import PlatformJobDatabaseMixin
from strata.db_lifecycle import ProjectLifecycleDatabaseMixin
from strata.discovery_db import DiscoveryDatabaseMixin
from strata.dependency_db import DependencyDatabaseMixin
from strata.db_overlap import OverlapDatabaseMixin
from strata.critic_db import CriticDatabaseMixin
from strata.assistant_db import AssistantDatabaseMixin
from strata.db_rows import DatabaseRowMixin
from strata.db_research import ResearchDatabaseMixin
from strata.db_telemetry import TelemetryDatabaseMixin
from strata.db_schema import DatabaseSchemaMixin
from strata.layer2_db import Layer2DatabaseMixin
from strata.layer3_db import Layer3DatabaseMixin
from strata.specification_db import SpecificationDatabaseMixin
from strata.layer1_expansion_db import Layer1ExpansionDatabaseMixin
from strata.layer1_territory_db import Layer1TerritoryDatabaseMixin
from strata.layer1_candidate_db import Layer1CandidateDatabaseMixin
from strata.layer1_synthesis_db import Layer1SynthesisDatabaseMixin
from strata.models import (
    BriefConversationTurn,
    Layer1PillarRecord,
    Node,
    Project,
    ProjectBrief,
    ProjectModelSettings,
    ProjectMemory,
    ProjectWorkspaceState,
    ResearchChunk,
    ResearchFinding,
    ResearchJob,
    ResearchSource,
)


UNSET = object()


def utc_now() -> str:
    """Return an ISO timestamp in UTC for persistent records."""
    return datetime.now(timezone.utc).isoformat()


class Database(ProjectLifecycleDatabaseMixin, SpecificationDatabaseMixin, Layer1SynthesisDatabaseMixin, Layer1CandidateDatabaseMixin, Layer1TerritoryDatabaseMixin, Layer1ExpansionDatabaseMixin, DiscoveryDatabaseMixin, DependencyDatabaseMixin, DataOwnershipDatabaseMixin, TelemetryDatabaseMixin, PlatformJobDatabaseMixin, OverlapDatabaseMixin, CriticDatabaseMixin, AssistantDatabaseMixin, Layer3DatabaseMixin, Layer2DatabaseMixin, ResearchDatabaseMixin, DatabaseEmbeddingMixin, DatabaseSchemaMixin, DatabaseRowMixin):
    """Store SpecForge state in either PostgreSQL or SQLite through one stable API."""

    def __init__(self, target: str | Path, *, postgres_admin_url: str | None = None):
        """Configure the database backend and initialize required schema objects."""
        self.target = target
        self._transaction_state = threading.local()
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
        ambient = getattr(self._transaction_state, "connection", None)
        if ambient is not None:
            yield ambient
            return
        connection = self._open_connection()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _open_connection(self) -> Any:
        """Create one backend connection without applying transaction ownership semantics."""
        if self.is_postgres:
            connection = psycopg.connect(self.database_url, row_factory=dict_row)
            try:
                register_vector(connection)
            except psycopg.ProgrammingError as exc:
                # A brand-new PostgreSQL database has no vector type until schema
                # initialization creates the pgvector extension on this connection.
                if "vector type not found" not in str(exc).lower():
                    connection.close()
                    raise
        else:
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def unit_of_work(self) -> Iterable[Any]:
        """Share one transaction across nested persistence helpers for an authoritative command."""
        ambient = getattr(self._transaction_state, "connection", None)
        if ambient is not None:
            yield ambient
            return
        connection = self._open_connection()
        self._transaction_state.connection = connection
        try:
            if not self.is_postgres:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._transaction_state.connection = None
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
            INSERT INTO projects (id, name, idea, created_at, updated_at, lifecycle_state)
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
        """
        self._execute(query, (project_id, name, idea, created_at, created_at, "active"))
        return self.get_project(project_id)

    def list_projects(self, *, state: str = "active", query: str = "", sort: str = "updated") -> list[Project]:
        """Return projects in reverse creation order with lightweight workspace metadata."""
        filters = []
        params: list[Any] = []
        if state != "all":
            filters.append(f"projects.lifecycle_state = {self.param}")
            params.append("archived" if state == "archived" else "active")
        if query.strip():
            filters.append(f"(LOWER(projects.name) LIKE {self.param} OR LOWER(projects.idea) LIKE {self.param})")
            search = f"%{query.strip().lower()}%"
            params.extend([search, search])
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        order_by = {
            "oldest": "projects.created_at ASC",
            "newest": "projects.created_at DESC",
            "name": "LOWER(projects.name) ASC",
            "updated": "projects.updated_at DESC",
            "last_opened": "projects.last_opened_at DESC NULLS LAST, projects.updated_at DESC" if self.is_postgres else "projects.last_opened_at IS NULL ASC, projects.last_opened_at DESC, projects.updated_at DESC",
        }.get(sort, "projects.updated_at DESC")
        rows = self._fetchall(
            f"""
            SELECT
                projects.id,
                projects.name,
                projects.idea,
                projects.created_at,
                projects.updated_at,
                projects.last_opened_at,
                projects.archived_at,
                projects.lifecycle_state,
                projects.source_project_id,
                source.name AS source_project_name,
                COALESCE(project_briefs.status, 'draft') AS brief_status,
                project_briefs.updated_at AS brief_updated_at,
                COALESCE(COUNT(DISTINCT nodes.id), 0) AS node_count,
                COALESCE(SUM(CASE WHEN nodes.node_type = 'pillar' THEN 1 ELSE 0 END), 0) AS pillar_count
            FROM projects
            LEFT JOIN project_briefs ON project_briefs.project_id = projects.id
            LEFT JOIN projects source ON source.id = projects.source_project_id
            LEFT JOIN nodes ON nodes.project_id = projects.id
            {where}
            GROUP BY projects.id, projects.name, projects.idea, projects.created_at, projects.updated_at,
                projects.last_opened_at, projects.archived_at, projects.lifecycle_state,
                projects.source_project_id, source.name, project_briefs.status, project_briefs.updated_at
            ORDER BY {order_by}
            """,
            tuple(params),
        )
        return [self._row_to_project_summary(row) for row in rows]

    def get_project(self, project_id: str) -> Project:
        """Look up a single project by id."""
        row = self._fetchone(
            f"""
            SELECT id, name, idea, created_at, updated_at, last_opened_at,
                   archived_at, lifecycle_state, source_project_id
            FROM projects
            WHERE id = {self.param}
            """,
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
        problem: str = "",
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
                    id, project_id, product_idea, problem, known_competitors, constraints, target_users,
                    goals, preferred_directions, rejected_directions, notes, status, created_at, updated_at
                )
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
                """,
                (
                    brief_id,
                    project_id,
                    product_idea,
                    problem,
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
                    problem = {self.param},
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
                    problem,
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
        brief = self._row_to_project_brief(row)
        if "brief_heads" not in self._table_names():
            return brief
        head = self._fetchone(f"SELECT * FROM brief_heads WHERE project_id = {self.param}", (project_id,))
        if head is None:
            return brief
        draft_id = str(head["current_draft_revision_id"] or "")
        draft = self._fetchone(f"SELECT revision_number, content_hash FROM brief_revisions WHERE id = {self.param}", (draft_id,)) if draft_id else None
        return brief.model_copy(update={
            "current_draft_revision_id": draft_id or None,
            "current_published_revision_id": str(head["current_published_revision_id"] or "") or None,
            "revision_number": int(draft["revision_number"]) if draft else int(head["revision_counter"]),
            "content_hash": str(draft["content_hash"]) if draft else "",
        })

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
        execution_intent: str,
        routing_policy: dict[str, Any],
        concurrency_policy: dict[str, Any],
        assignments: dict[str, Any],
        prompt_catalog: dict[str, Any],
        competitive_intelligence_enabled: bool = True,
        discovery_settings: dict[str, Any] | None = None,
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
                    project_id, llm_profiles, embedding_profiles, execution_intent, routing_policy, concurrency_policy,
                    assignments, prompt_catalog, competitive_intelligence_enabled, discovery_settings, created_at, updated_at
                )
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
                """,
                (
                    project_id,
                    self._dump_json(llm_profiles),
                    self._dump_json(embedding_profiles),
                    execution_intent,
                    self._dump_json(routing_policy),
                    self._dump_json(concurrency_policy),
                    self._dump_json(assignments),
                    self._dump_json(prompt_catalog),
                    competitive_intelligence_enabled,
                    self._dump_json(discovery_settings or {}),
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
                    execution_intent = {self.param},
                    routing_policy = {self.param},
                    concurrency_policy = {self.param},
                    assignments = {self.param},
                    prompt_catalog = {self.param},
                    competitive_intelligence_enabled = {self.param},
                    discovery_settings = {self.param},
                    updated_at = {self.param}
                WHERE project_id = {self.param}
                """,
                (
                    self._dump_json(llm_profiles),
                    self._dump_json(embedding_profiles),
                    execution_intent,
                    self._dump_json(routing_policy),
                    self._dump_json(concurrency_policy),
                    self._dump_json(assignments),
                    self._dump_json(prompt_catalog),
                    competitive_intelligence_enabled,
                    self._dump_json(discovery_settings or {}),
                    now,
                    project_id,
                ),
            )
        return self.get_project_model_settings(project_id)

    def get_project_workspace_state(self, project_id: str) -> ProjectWorkspaceState | None:
        """Return the durable living-workspace state for one project."""
        row = self._fetchone(
            f"SELECT * FROM project_workspace_state WHERE project_id = {self.param}",
            (project_id,),
        )
        if row is None:
            return None
        return ProjectWorkspaceState(
            project_id=str(self._row_value(row, "project_id")),
            view_mode=str(self._row_value(row, "view_mode")),
            selected_entity_type=str(self._row_value(row, "selected_entity_type")),
            selected_entity_id=str(self._row_value(row, "selected_entity_id")),
            table_scope=str(self._row_value(row, "table_scope")),
            map_state=self._load_json(self._row_value(row, "map_state")),
            table_state=self._load_json(self._row_value(row, "table_state")),
            created_at=self._row_value(row, "created_at"),
            updated_at=self._row_value(row, "updated_at"),
        )

    def upsert_project_workspace_state(
        self,
        *,
        project_id: str,
        view_mode: str,
        selected_entity_type: str,
        selected_entity_id: str,
        table_scope: str,
        map_state: dict[str, Any],
        table_state: dict[str, Any],
    ) -> ProjectWorkspaceState:
        """Persist navigation, selection, and filter state for the living workspace."""
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO project_workspace_state (
                project_id, view_mode, selected_entity_type, selected_entity_id,
                table_scope, map_state, table_state, created_at, updated_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            ON CONFLICT (project_id) DO UPDATE SET
                view_mode = EXCLUDED.view_mode,
                selected_entity_type = EXCLUDED.selected_entity_type,
                selected_entity_id = EXCLUDED.selected_entity_id,
                table_scope = EXCLUDED.table_scope,
                map_state = EXCLUDED.map_state,
                table_state = EXCLUDED.table_state,
                updated_at = EXCLUDED.updated_at
            """,
            (
                project_id,
                view_mode,
                selected_entity_type,
                selected_entity_id,
                table_scope,
                self._dump_json(map_state),
                self._dump_json(table_state),
                now,
                now,
            ),
        )
        return self.get_project_workspace_state(project_id)

    def append_brief_conversation_turn(
        self,
        *,
        project_id: str,
        role: str,
        content: str,
        request_id: str | None = None,
        extracted_updates: dict[str, Any] | None = None,
    ) -> BriefConversationTurn:
        """Store one Plan-mode chat turn or extracted turn summary separate from the brief."""
        turn_id = str(uuid.uuid4())
        created_at = utc_now()
        self._execute(
            f"""
            INSERT INTO brief_conversations (
                id, project_id, role, content, request_id, extracted_updates, created_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            ON CONFLICT DO NOTHING
            """,
            (
                turn_id,
                project_id,
                role,
                content,
                request_id,
                self._dump_json(extracted_updates or {}),
                created_at,
            ),
        )
        if request_id:
            existing = self.get_brief_conversation_by_request(project_id, request_id, role)
            if existing is not None:
                return existing
        return self.get_brief_conversation_turn(turn_id)

    def get_brief_conversation_by_request(
        self,
        project_id: str,
        request_id: str,
        role: str,
    ) -> BriefConversationTurn | None:
        """Find an idempotent Plan-mode turn by client request and role."""
        row = self._fetchone(
            f"""
            SELECT * FROM brief_conversations
            WHERE project_id = {self.param} AND request_id = {self.param} AND role = {self.param}
            """,
            (project_id, request_id, role),
        )
        return self._row_to_brief_conversation_turn(row) if row is not None else None

    def get_brief_conversation_turn(self, turn_id: str) -> BriefConversationTurn:
        """Return one stored Layer 0 Plan-mode turn."""
        row = self._fetchone(
            f"SELECT * FROM brief_conversations WHERE id = {self.param}",
            (turn_id,),
        )
        if row is None:
            raise ValueError(f"Brief conversation turn not found: {turn_id}")
        return self._row_to_brief_conversation_turn(row)

    def update_brief_conversation_turn(
        self,
        turn_id: str,
        *,
        content: str | None = None,
        extracted_updates: dict[str, Any] | None = None,
    ) -> BriefConversationTurn:
        """Persist streamed content or proposal state on an existing Layer 0 turn."""
        current = self.get_brief_conversation_turn(turn_id)
        next_content = current.content if content is None else content
        next_updates = current.extracted_updates if extracted_updates is None else extracted_updates
        self._execute(
            f"""
            UPDATE brief_conversations
            SET content = {self.param}, extracted_updates = {self.param}
            WHERE id = {self.param}
            """,
            (next_content, self._dump_json(next_updates), turn_id),
        )
        return self.get_brief_conversation_turn(turn_id)

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
        memory = self.get_project_memory(
            project_id=project_id,
            scope=scope,
            scope_id=scope_id,
            memory_type=memory_type,
        )
        if "artifact_dependencies" in self._table_names():
            self.register_project_memory_lineage(memory)
        return memory

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

    def upsert_layer1_pillar(self, node: Node) -> Layer1PillarRecord:
        """Mirror an approved Layer 1 node into the graph schema used by Layer 2."""
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO layer1_pillars (id, project_id, node_id, title, description, status, created_at, updated_at)
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            ON CONFLICT (node_id) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at
            """,
            (
                node.id,
                node.project_id,
                node.id,
                node.title,
                node.description or "",
                node.status,
                now,
                now,
            ),
        )
        return self.get_layer1_pillar(node.id)

    def get_layer1_pillar(self, pillar_id: str) -> Layer1PillarRecord:
        """Return one Layer 1 pillar record by pillar/node id."""
        row = self._fetchone(f"SELECT * FROM layer1_pillars WHERE id = {self.param}", (pillar_id,))
        if row is None:
            raise ValueError(f"Layer 1 pillar not found: {pillar_id}")
        return self._row_to_layer1_pillar(row)

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
