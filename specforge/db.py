from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from specforge.models import Node, Project, ProjectMemory


UNSET = object()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
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

                CREATE UNIQUE INDEX IF NOT EXISTS idx_project_memory_scope
                ON project_memory(project_id, scope, COALESCE(scope_id, ''), memory_type);

                CREATE INDEX IF NOT EXISTS idx_nodes_project_parent_layer_type
                ON nodes(project_id, COALESCE(parent_id, ''), layer, node_type);

                CREATE INDEX IF NOT EXISTS idx_nodes_project_status
                ON nodes(project_id, status);

                CREATE INDEX IF NOT EXISTS idx_generations_project_node
                ON generations(project_id, node_id, created_at);
                """
            )

    def create_project(self, name: str, idea: str) -> Project:
        project_id = str(uuid.uuid4())
        created_at = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (id, name, idea, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (project_id, name, idea, created_at),
            )
        return self.get_project(project_id)

    def list_projects(self) -> list[Project]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, idea, created_at FROM projects ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_project(row) for row in rows]

    def get_project(self, project_id: str) -> Project:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, name, idea, created_at FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Project not found: {project_id}")
        return self._row_to_project(row)

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
        node_id = str(uuid.uuid4())
        created_at = utc_now()
        payload = json.dumps(json_payload or {}, ensure_ascii=True)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO nodes (
                    id, project_id, parent_id, layer, node_type, title, description,
                    json_payload, status, priority, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
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
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
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
        query = "SELECT * FROM nodes WHERE project_id = ?"
        params: list[Any] = [project_id]
        if parent_id is None:
            query += " AND parent_id IS NULL"
        elif parent_id != "__any__":
            query += " AND parent_id = ?"
            params.append(parent_id)
        if layer is not None:
            query += " AND layer = ?"
            params.append(layer)
        if node_type is not None:
            query += " AND node_type = ?"
            params.append(node_type)
        query += " ORDER BY layer ASC, created_at ASC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_node(row) for row in rows]

    def list_all_nodes(self, project_id: str) -> list[Node]:
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
        updates: list[str] = []
        params: list[Any] = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if json_payload is not None:
            updates.append("json_payload = ?")
            params.append(json.dumps(json_payload, ensure_ascii=True))
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if priority is not UNSET:
            updates.append("priority = ?")
            params.append(priority)
        if not updates:
            return self.get_node(node_id)
        params.append(node_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE nodes SET {', '.join(updates)} WHERE id = ?", params)
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
        generation_id = str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO generations (
                    id, project_id, node_id, prompt, raw_response,
                    parsed_json, model_name, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generation_id,
                    project_id,
                    node_id,
                    prompt,
                    raw_response,
                    json.dumps(parsed_json, ensure_ascii=True) if parsed_json else None,
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
        now = utc_now()
        memory_id = str(uuid.uuid4())
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT id FROM project_memory
                WHERE project_id = ? AND scope = ? AND COALESCE(scope_id, '') = COALESCE(?, '') AND memory_type = ?
                """,
                (project_id, scope, scope_id, memory_type),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE project_memory
                    SET content = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (json.dumps(content, ensure_ascii=True), now, existing["id"]),
                )
                memory_id = existing["id"]
            else:
                conn.execute(
                    """
                    INSERT INTO project_memory (
                        id, project_id, scope, scope_id, memory_type, content, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        project_id,
                        scope,
                        scope_id,
                        memory_type,
                        json.dumps(content, ensure_ascii=True),
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
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM project_memory
                WHERE project_id = ? AND scope = ? AND COALESCE(scope_id, '') = COALESCE(?, '') AND memory_type = ?
                """,
                (project_id, scope, scope_id, memory_type),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_project_memory(row)

    def list_project_memory(self, project_id: str) -> list[ProjectMemory]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM project_memory WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        return [self._row_to_project_memory(row) for row in rows]

    def get_rejected_ideas(self, project_id: str) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT title, description
                FROM nodes
                WHERE project_id = ? AND status = 'cut'
                ORDER BY created_at ASC
                """,
                (project_id,),
            ).fetchall()
        rejected = []
        for row in rows:
            title = row["title"]
            description = row["description"]
            if description:
                rejected.append(f"{title}: {description}")
            else:
                rejected.append(title)
        return rejected

    @staticmethod
    def _row_to_project(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            idea=row["idea"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Node:
        return Node(
            id=row["id"],
            project_id=row["project_id"],
            parent_id=row["parent_id"],
            layer=row["layer"],
            node_type=row["node_type"],
            title=row["title"],
            description=row["description"],
            json_payload=json.loads(row["json_payload"] or "{}"),
            status=row["status"],
            priority=row["priority"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _row_to_project_memory(row: sqlite3.Row) -> ProjectMemory:
        return ProjectMemory(
            id=row["id"],
            project_id=row["project_id"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            memory_type=row["memory_type"],
            content=json.loads(row["content"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
