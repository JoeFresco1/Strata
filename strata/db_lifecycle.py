from __future__ import annotations

import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pgvector import Vector

from strata.data_ownership import matching_project_artifacts, project_slug


PROJECT_ARCHIVE_VERSION = 1

DIRECT_PROJECT_TABLES = [
    "project_briefs",
    "brief_heads",
    "brief_revisions",
    "project_model_settings",
    "project_workspace_state",
    "project_telemetry_settings",
    "project_data_ownership_settings",
    "platform_jobs",
    "model_call_events",
    "brief_conversations",
    "nodes",
    "generations",
    "project_memory",
    "research_jobs",
    "research_sources",
    "research_chunks",
    "research_findings",
    "node_embeddings",
    "layer1_pillars",
    "layer2_generation_runs",
    "layer2_raw_candidates",
    "layer2_features",
    "layer2_feature_relationships",
    "layer2_pillar_affinity",
    "layer2_negative_cache",
    "layer2_coverage_matrix",
    "layer2_shared_concern_clusters",
    "layer2_feature_evidence",
    "layer2_competitive_settings",
    "layer2_review_actions",
    "artifact_authority_actions",
    "critic_findings",
    "command_executions",
    "assistant_conversations",
    "assistant_messages",
    "assistant_documents",
    "assistant_action_proposals",
    "layer3_feature_expansions",
    "layer3_expansion_actions",
    "layer3_expansion_revisions",
    "layer3_expansion_heads",
    "layer3_revision_actions",
    "artifact_dependencies",
    "artifact_freshness_states",
    "artifact_stale_transitions",
]

DEPENDENT_TABLES = {
    "layer2_feature_aliases": ("feature_id", "layer2_features", "id"),
    "assistant_runs": ("assistant_message_id", "assistant_messages", "id"),
    "assistant_specialist_runs": ("assistant_run_id", "assistant_runs", "id"),
    "layer3_expansion_revision_states": ("revision_id", "layer3_expansion_revisions", "id"),
}

CLONE_EXCLUDED_TABLES = {
    "project_workspace_state",
    "project_telemetry_settings",
    "project_data_ownership_settings",
    "model_call_events",
    "assistant_conversations",
    "assistant_messages",
    "assistant_documents",
    "assistant_runs",
    "assistant_specialist_runs",
    "assistant_action_proposals",
}

CLONE_RESET_JOB_STATUSES = {"queued", "running", "failed", "interrupted"}


def lifecycle_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectLifecycleDatabaseMixin:
    """Project lifecycle operations, clone/archive portability, and admin purge."""

    def update_project_metadata(self, project_id: str, *, name: str, idea: str) -> Any:
        now = lifecycle_now()
        self.get_project(project_id)
        self._execute(
            f"""
            UPDATE projects
            SET name = {self.param}, idea = {self.param}, updated_at = {self.param}
            WHERE id = {self.param}
            """,
            (name, idea, now, project_id),
        )
        return self.get_project(project_id)

    def archive_project(self, project_id: str) -> Any:
        now = lifecycle_now()
        self.get_project(project_id)
        self._execute(
            f"""
            UPDATE projects
            SET lifecycle_state = 'archived', archived_at = {self.param}, updated_at = {self.param}
            WHERE id = {self.param}
            """,
            (now, now, project_id),
        )
        return self.get_project(project_id)

    def unarchive_project(self, project_id: str) -> Any:
        now = lifecycle_now()
        self.get_project(project_id)
        self._execute(
            f"""
            UPDATE projects
            SET lifecycle_state = 'active', archived_at = NULL, updated_at = {self.param}
            WHERE id = {self.param}
            """,
            (now, project_id),
        )
        return self.get_project(project_id)

    def touch_project(self, project_id: str, *, opened: bool = False, updated: bool = True) -> Any:
        self.get_project(project_id)
        now = lifecycle_now()
        updates: list[str] = []
        params: list[Any] = []
        if updated:
            updates.append(f"updated_at = {self.param}")
            params.append(now)
        if opened:
            updates.append(f"last_opened_at = {self.param}")
            params.append(now)
        if not updates:
            return self.get_project(project_id)
        params.append(project_id)
        self._execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = {self.param}", tuple(params))
        return self.get_project(project_id)

    def ensure_project_writable(self, project_id: str) -> None:
        project = self.get_project(project_id)
        if project.lifecycle_state == "archived":
            raise ValueError("Archived projects are read-only. Unarchive this project before making changes.")

    def clone_project(self, project_id: str, *, name: str | None = None) -> Any:
        payload = self.project_archive_payload(project_id, include_full_history=False)
        original = payload["project"]
        clone_name = self._unique_project_name(name or f"{original['name']} Copy")
        return self.import_project_archive_payload(
            payload,
            name_override=clone_name,
            source_project_id=project_id,
            include_full_history=False,
        )["project"]

    def export_project_archive(self, project_id: str, target_dir: Path) -> Path:
        payload = self.project_archive_payload(project_id, include_full_history=True)
        project = payload["project"]
        slug = self._project_slug(project["name"]) or project_id
        target_dir.mkdir(parents=True, exist_ok=True)
        archive_path = target_dir / f"{slug}-{project_id[:8]}-project-archive.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(payload["manifest"], indent=2, ensure_ascii=True, default=str))
            archive.writestr("project.json", json.dumps(project, indent=2, ensure_ascii=True, default=str))
            for table, rows in payload["tables"].items():
                archive.writestr(f"tables/{table}.json", json.dumps(rows, indent=2, ensure_ascii=True, default=str))
        return archive_path

    def import_project_archive(self, archive_path: Path) -> dict[str, Any]:
        with zipfile.ZipFile(archive_path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            project = json.loads(archive.read("project.json").decode("utf-8"))
            tables: dict[str, list[dict[str, Any]]] = {}
            for name in archive.namelist():
                if name.startswith("tables/") and name.endswith(".json"):
                    tables[Path(name).stem] = json.loads(archive.read(name).decode("utf-8"))
        return self.import_project_archive_payload({"manifest": manifest, "project": project, "tables": tables})

    def project_archive_payload(self, project_id: str, *, include_full_history: bool) -> dict[str, Any]:
        project = self.get_project(project_id).model_dump(mode="json")
        tables: dict[str, list[dict[str, Any]]] = {}
        id_maps: dict[str, set[str]] = {}
        for table in DIRECT_PROJECT_TABLES:
            if not include_full_history and table in CLONE_EXCLUDED_TABLES:
                continue
            rows = self._project_table_rows(table, project_id)
            if not include_full_history and table in {"research_jobs", "platform_jobs"}:
                rows = [row for row in rows if row.get("status") not in CLONE_RESET_JOB_STATUSES]
            tables[table] = rows
            id_maps[table] = {str(row["id"]) for row in rows if "id" in row and row.get("id")}
        for table, (column, source_table, source_column) in DEPENDENT_TABLES.items():
            if not include_full_history and table in CLONE_EXCLUDED_TABLES:
                continue
            source_ids = id_maps.get(source_table, set())
            rows = self._dependent_table_rows(table, column, source_ids)
            tables[table] = rows
            id_maps[table] = {str(row["id"]) for row in rows if "id" in row and row.get("id")}
        return {
            "manifest": {
                "manifest_version": PROJECT_ARCHIVE_VERSION,
                "schema_version": 1,
                "exported_at": lifecycle_now(),
                "project_id": project_id,
                "include_full_history": include_full_history,
                "tables": sorted(tables),
            },
            "project": project,
            "tables": tables,
        }

    def import_project_archive_payload(
        self,
        payload: dict[str, Any],
        *,
        name_override: str | None = None,
        source_project_id: str | None = None,
        include_full_history: bool = True,
    ) -> dict[str, Any]:
        manifest = payload.get("manifest") or {}
        if int(manifest.get("manifest_version", 0)) > PROJECT_ARCHIVE_VERSION:
            raise ValueError("This project archive was created by a newer Strata version.")
        source_project = payload["project"]
        warnings: list[str] = []
        now = lifecycle_now()
        new_project_id = str(uuid.uuid4())
        source_id = source_project["id"]
        name = self._unique_project_name(name_override or source_project["name"])
        id_map: dict[str, str] = {source_id: new_project_id}
        tables = dict(payload.get("tables") or {})
        if not include_full_history:
            for table in CLONE_EXCLUDED_TABLES:
                tables.pop(table, None)
        for rows in tables.values():
            for row in rows:
                if row.get("id"):
                    id_map.setdefault(str(row["id"]), str(uuid.uuid4()))
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"""
                    INSERT INTO projects (
                        id, name, idea, created_at, updated_at, last_opened_at, archived_at,
                        lifecycle_state, source_project_id
                    ) VALUES ({', '.join([self.param] * 9)})
                    """,
                    (
                        new_project_id,
                        name,
                        source_project.get("idea", ""),
                        now,
                        now,
                        None,
                        None,
                        "active",
                        source_project_id,
                    ),
                )
                for table in self._archive_insert_order(tables):
                    rows = tables.get(table, [])
                    if table == "project_model_settings":
                        rows = [self._sanitize_imported_model_settings(row, warnings) for row in rows]
                    for row in rows:
                        self._insert_imported_row(table, row, new_project_id, id_map, now, cursor=cursor)
            finally:
                cursor.close()
        return {
            "project": self.get_project(new_project_id),
            "lifecycle_warnings": warnings,
            "source_project_id": source_id,
        }

    def purge_project(self, project_id: str, *, confirmation_token: str | None = None, delete_artifacts: bool = False, exports_dir: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
        expected = f"PURGE-{project_id[:8]}"
        if dry_run:
            return self.project_purge_preview(project_id, exports_dir=exports_dir)
        if confirmation_token != expected:
            raise ValueError(f"Confirmation token must be {expected}.")
        project = self.get_project(project_id)
        deleted_artifacts: list[str] = []
        if delete_artifacts and exports_dir is not None and exports_dir.exists():
            for path in matching_project_artifacts(exports_dir, project_id=project_id, project_name=project.name):
                path.unlink()
                deleted_artifacts.append(str(path))
        self._delete_project_rows(project_id)
        self._execute(f"DELETE FROM projects WHERE id = {self.param}", (project_id,))
        return {"purged_project_id": project_id, "deleted_artifacts": deleted_artifacts}

    def _delete_project_rows(self, project_id: str) -> None:
        """Delete all project-scoped rows in one transaction so deferred integrity checks see the final state."""
        source_ids: dict[str, set[str]] = {}
        project_tables = self._purge_project_tables()
        for table in project_tables:
            rows = self._project_table_rows(table, project_id)
            source_ids[table] = {str(row["id"]) for row in rows if row.get("id")}
        table_names = self._table_names()
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                for table, (column, source_table, _) in DEPENDENT_TABLES.items():
                    if table not in table_names:
                        continue
                    for source_id in source_ids.get(source_table, set()):
                        cursor.execute(f"DELETE FROM {table} WHERE {column} = {self.param}", (source_id,))
                for table in reversed(project_tables):
                    if table in table_names:
                        cursor.execute(f"DELETE FROM {table} WHERE project_id = {self.param}", (project_id,))
            finally:
                cursor.close()

    def _purge_project_tables(self) -> list[str]:
        """Return all discovered project-scoped tables while preserving known FK order."""
        known = [table for table in DIRECT_PROJECT_TABLES if table in self._table_names()]
        discovered = [
            table
            for table in sorted(self._table_names())
            if table not in known and table != "projects" and "project_id" in self._table_columns(table)
        ]
        return known + discovered

    def _project_table_rows(self, table: str, project_id: str) -> list[dict[str, Any]]:
        if table not in self._table_names():
            return []
        rows = self._fetchall(f"SELECT * FROM {table} WHERE project_id = {self.param}", (project_id,))
        return [self._plain_row(row) for row in rows]

    def _dependent_table_rows(self, table: str, column: str, source_ids: set[str]) -> list[dict[str, Any]]:
        if not source_ids or table not in self._table_names():
            return []
        rows: list[dict[str, Any]] = []
        for source_id in sorted(source_ids):
            rows.extend(self._plain_row(row) for row in self._fetchall(f"SELECT * FROM {table} WHERE {column} = {self.param}", (source_id,)))
        return rows

    def _insert_imported_row(
        self,
        table: str,
        row: dict[str, Any],
        project_id: str,
        id_map: dict[str, str],
        now: str,
        *,
        cursor: Any | None = None,
    ) -> None:
        """Insert one remapped archive row, reusing the caller's transaction when provided."""
        if table not in self._table_names():
            return
        columns = self._table_columns(table)
        payload = {key: self._remap_value(value, id_map) for key, value in row.items() if key in columns}
        if "project_id" in columns:
            payload["project_id"] = project_id
        if "id" in columns and row.get("id"):
            old_id = str(row["id"])
            id_map.setdefault(old_id, str(uuid.uuid4()))
            payload["id"] = id_map[old_id]
        if table == "layer3_revision_actions" and "request_id" in columns:
            payload["request_id"] = f"import:{uuid.uuid4()}"
        if "created_at" in columns:
            payload["created_at"] = now
        if "updated_at" in columns:
            payload["updated_at"] = now
        if table == "project_workspace_state":
            payload["selected_entity_id"] = "layer0-root"
            payload["selected_entity_type"] = "brief"
            payload["map_state"] = {}
            payload["table_state"] = {}
        insert_columns = [column for column in columns if column in payload]
        if not insert_columns:
            return
        placeholders = ", ".join([self.param] * len(insert_columns))
        values = tuple(self._prepare_lifecycle_import_value(column, payload[column]) for column in insert_columns)
        query = f"INSERT INTO {table} ({', '.join(insert_columns)}) VALUES ({placeholders})"
        if cursor is not None:
            cursor.execute(query, values)
        else:
            self._execute(query, values)

    def _archive_insert_order(self, tables: dict[str, list[dict[str, Any]]]) -> list[str]:
        preferred = [
            "project_briefs",
            "brief_heads",
            "brief_revisions",
            "project_model_settings",
            "project_workspace_state",
            "project_telemetry_settings",
            "project_data_ownership_settings",
            "platform_jobs",
            "brief_conversations",
            "nodes",
            "generations",
            "project_memory",
            "research_jobs",
            "research_sources",
            "research_chunks",
            "research_findings",
            "node_embeddings",
            "layer1_pillars",
            "layer2_generation_runs",
            "layer2_raw_candidates",
            "layer2_features",
            "layer2_feature_aliases",
            "layer2_feature_relationships",
            "layer2_pillar_affinity",
            "layer2_negative_cache",
            "layer2_coverage_matrix",
            "layer2_shared_concern_clusters",
            "layer2_feature_evidence",
            "layer2_competitive_settings",
            "layer2_review_actions",
            "artifact_authority_actions",
            "critic_findings",
            "command_executions",
            "layer3_feature_expansions",
            "layer3_expansion_actions",
            "layer3_expansion_heads",
            "layer3_expansion_revisions",
            "layer3_expansion_revision_states",
            "layer3_revision_actions",
            "artifact_dependencies",
            "artifact_freshness_states",
            "artifact_stale_transitions",
            "assistant_conversations",
            "assistant_messages",
            "assistant_documents",
            "assistant_runs",
            "assistant_specialist_runs",
            "assistant_action_proposals",
            "model_call_events",
        ]
        return [table for table in preferred if table in tables]

    def _sanitize_imported_model_settings(self, row: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
        cleaned = dict(row)
        profiles = self._json_value(cleaned.get("llm_profiles"), [])
        changed = False
        for profile in profiles:
            path = str(profile.get("local_path") or "")
            if path and not Path(path).exists():
                profile["local_path"] = ""
                profile["runtime_kind"] = "auto"
                changed = True
        if changed:
            warnings.append("Some imported local model paths were unavailable and were reset to automatic runtime resolution.")
            cleaned["llm_profiles"] = profiles
        return cleaned

    def _table_names(self) -> set[str]:
        if self.is_postgres:
            rows = self._fetchall("SELECT tablename AS name FROM pg_tables WHERE schemaname = 'public'")
        else:
            rows = self._fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")
        return {str(row["name"]) for row in rows}

    def _table_columns(self, table: str) -> list[str]:
        if self.is_postgres:
            rows = self._fetchall(
                """
                SELECT column_name AS name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s AND is_generated = 'NEVER'
                ORDER BY ordinal_position
                """,
                (table,),
            )
        else:
            rows = self._fetchall(f"PRAGMA table_info({table})")
        return [str(row["name"]) for row in rows]

    def _plain_row(self, row: Any) -> dict[str, Any]:
        return {key: self._json_safe(value) for key, value in dict(row).items()}

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "tolist"):
            return value.tolist()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return value
        return value

    def _json_value(self, value: Any, fallback: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return fallback
        return value if value is not None else fallback

    def _prepare_lifecycle_import_value(self, column: str, value: Any) -> Any:
        if self.is_postgres and column == "embedding" and isinstance(value, list):
            return Vector(value)
        if isinstance(value, (dict, list)):
            return self._dump_json(value)
        return value

    def _remap_value(self, value: Any, id_map: dict[str, str]) -> Any:
        if isinstance(value, str):
            return id_map.get(value, value)
        if isinstance(value, list):
            return [self._remap_value(item, id_map) for item in value]
        if isinstance(value, dict):
            return {key: self._remap_value(item, id_map) for key, item in value.items()}
        return value

    def _unique_project_name(self, base_name: str) -> str:
        root = base_name.strip() or "Imported Project"
        existing = {str(row["name"]).casefold() for row in self._fetchall("SELECT name FROM projects")}
        if root.casefold() not in existing:
            return root
        index = 2
        while f"{root} {index}".casefold() in existing:
            index += 1
        return f"{root} {index}"

    @staticmethod
    def _project_slug(name: str) -> str:
        return project_slug(name)
