from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from strata.data_ownership import (
    DATA_OWNERSHIP_DEFAULTS,
    artifact_payload,
    matching_project_artifacts,
    normalize_retention_days,
    retention_cutoff,
)


class DataOwnershipDatabaseMixin:
    """Project-level retention settings, cleanup operations, and purge previews."""

    def get_data_ownership_settings(self, project_id: str) -> dict[str, int | None]:
        self.get_project(project_id)
        row = self._fetchone(
            f"SELECT * FROM project_data_ownership_settings WHERE project_id = {self.param}",
            (project_id,),
        )
        if row is None:
            return dict(DATA_OWNERSHIP_DEFAULTS)
        return {
            key: normalize_retention_days(row[key])
            for key in DATA_OWNERSHIP_DEFAULTS
        }

    def upsert_data_ownership_settings(self, project_id: str, settings: dict[str, Any]) -> dict[str, int | None]:
        self.get_project(project_id)
        normalized = {
            key: normalize_retention_days(settings.get(key))
            for key in DATA_OWNERSHIP_DEFAULTS
        }
        now = self._now()
        self._execute(
            f"""
            INSERT INTO project_data_ownership_settings (
                project_id, telemetry_retention_days, telemetry_body_retention_days,
                research_retention_days, assistant_retention_days, exports_retention_days,
                created_at, updated_at
            ) VALUES ({', '.join([self.param] * 8)})
            ON CONFLICT(project_id) DO UPDATE SET
                telemetry_retention_days = excluded.telemetry_retention_days,
                telemetry_body_retention_days = excluded.telemetry_body_retention_days,
                research_retention_days = excluded.research_retention_days,
                assistant_retention_days = excluded.assistant_retention_days,
                exports_retention_days = excluded.exports_retention_days,
                updated_at = excluded.updated_at
            """,
            (
                project_id,
                normalized["telemetry_retention_days"],
                normalized["telemetry_body_retention_days"],
                normalized["research_retention_days"],
                normalized["assistant_retention_days"],
                normalized["exports_retention_days"],
                now,
                now,
            ),
        )
        return normalized

    def data_ownership_summary(self, project_id: str, *, exports_dir: Path | None = None) -> dict[str, Any]:
        project = self.get_project(project_id)
        settings = self.get_data_ownership_settings(project_id)
        return {
            "settings": settings,
            "counts": self.project_purge_preview(project_id, exports_dir=exports_dir)["table_counts"],
            "matching_artifacts": artifact_payload(matching_project_artifacts(exports_dir, project_id=project_id, project_name=project.name)),
        }

    def cleanup_project_telemetry(self, project_id: str, *, retention_days: int | None = None, body_retention_days: int | None = None) -> dict[str, int]:
        self.get_project(project_id)
        settings = self.get_data_ownership_settings(project_id)
        retention_days = normalize_retention_days(retention_days if retention_days is not None else settings["telemetry_retention_days"])
        body_retention_days = normalize_retention_days(body_retention_days if body_retention_days is not None else settings["telemetry_body_retention_days"])
        deleted_rows = 0
        redacted_rows = 0
        body_cutoff = retention_cutoff(body_retention_days)
        if body_cutoff is not None:
            redacted_rows = self._rowcount(
                f"""
                UPDATE model_call_events
                SET system_prompt = NULL, user_prompt = NULL, raw_response = NULL, parsed_result = {self.param}
                WHERE project_id = {self.param} AND completed_at < {self.param}
                """,
                (self._dump_json({}), project_id, body_cutoff),
            )
        row_cutoff = retention_cutoff(retention_days)
        if row_cutoff is not None:
            deleted_rows = self._rowcount(
                f"DELETE FROM model_call_events WHERE project_id = {self.param} AND completed_at < {self.param}",
                (project_id, row_cutoff),
            )
        return {"deleted_rows": deleted_rows, "redacted_rows": redacted_rows}

    def cleanup_project_research(self, project_id: str, *, retention_days: int | None = None) -> dict[str, int]:
        self.get_project(project_id)
        days = normalize_retention_days(retention_days if retention_days is not None else self.get_data_ownership_settings(project_id)["research_retention_days"])
        cutoff = retention_cutoff(days)
        if cutoff is None:
            return {"research_chunks": 0, "research_findings": 0, "research_sources": 0}
        deleted = {
            "research_chunks": self._rowcount(
                f"DELETE FROM research_chunks WHERE project_id = {self.param} AND created_at < {self.param}",
                (project_id, cutoff),
            ),
            "research_findings": self._rowcount(
                f"DELETE FROM research_findings WHERE project_id = {self.param} AND updated_at < {self.param}",
                (project_id, cutoff),
            ),
            "research_sources": self._rowcount(
                f"DELETE FROM research_sources WHERE project_id = {self.param} AND fetched_at < {self.param}",
                (project_id, cutoff),
            ),
        }
        return deleted

    def cleanup_project_assistant_history(self, project_id: str, *, retention_days: int | None = None) -> dict[str, int]:
        self.get_project(project_id)
        days = normalize_retention_days(retention_days if retention_days is not None else self.get_data_ownership_settings(project_id)["assistant_retention_days"])
        cutoff = retention_cutoff(days)
        if cutoff is None:
            return {"assistant_action_proposals": 0, "assistant_specialist_runs": 0, "assistant_runs": 0, "assistant_messages": 0, "assistant_conversations": 0, "assistant_documents": 0}
        message_ids = self._ids("assistant_messages", "id", f"project_id = {self.param} AND updated_at < {self.param}", (project_id, cutoff))
        run_ids = self._ids_for_values("assistant_runs", "id", "assistant_message_id", message_ids)
        deleted_action_proposals = self._delete_for_values("assistant_action_proposals", "message_id", message_ids)
        deleted_specialist_runs = self._delete_for_values("assistant_specialist_runs", "assistant_run_id", run_ids)
        deleted_runs = self._delete_for_values("assistant_runs", "assistant_message_id", message_ids)
        deleted_messages = self._delete_for_values("assistant_messages", "id", message_ids)
        conversation_ids = self._ids(
            "assistant_conversations",
            "id",
            f"""
            project_id = {self.param}
            AND updated_at < {self.param}
            AND NOT EXISTS (
                SELECT 1 FROM assistant_messages
                WHERE assistant_messages.conversation_id = assistant_conversations.id
            )
            """,
            (project_id, cutoff),
        )
        deleted = {
            "assistant_action_proposals": deleted_action_proposals,
            "assistant_specialist_runs": deleted_specialist_runs,
            "assistant_runs": deleted_runs,
            "assistant_messages": deleted_messages,
            "assistant_conversations": self._delete_for_values("assistant_conversations", "id", conversation_ids),
            "assistant_documents": self._rowcount(
                f"DELETE FROM assistant_documents WHERE project_id = {self.param} AND updated_at < {self.param}",
                (project_id, cutoff),
            ),
        }
        return deleted

    def cleanup_project_exports(self, project_id: str, *, exports_dir: Path | None, retention_days: int | None = None) -> dict[str, Any]:
        project = self.get_project(project_id)
        days = normalize_retention_days(retention_days if retention_days is not None else self.get_data_ownership_settings(project_id)["exports_retention_days"])
        cutoff = retention_cutoff(days)
        if cutoff is None:
            return {"deleted_artifacts": []}
        deleted: list[str] = []
        for path in matching_project_artifacts(exports_dir, project_id=project_id, project_name=project.name):
            if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat() >= cutoff:
                continue
            path.unlink()
            deleted.append(str(path))
        return {"deleted_artifacts": deleted}

    def project_purge_preview(self, project_id: str, *, exports_dir: Path | None = None) -> dict[str, Any]:
        project = self.get_project(project_id)
        table_counts: dict[str, int] = {}
        source_ids: dict[str, list[str]] = {}
        for table in self._project_scoped_tables():
            table_counts[table] = self._count_table_rows(table, project_id)
            source_ids[table] = self._ids(table, "id", f"project_id = {self.param}", (project_id,)) if "id" in self._table_columns(table) else []
        for table, (column, source_table, source_column) in self._dependent_table_specs().items():
            ids = source_ids.get(source_table, [])
            table_counts[table] = len(ids) and self._count_dependent_rows(table, column, ids) or 0
            source_ids[table] = self._dependent_ids(table, "id", column, ids) if "id" in self._table_columns(table) else []
        return {
            "project_id": project_id,
            "table_counts": dict(sorted(table_counts.items())),
            "matching_artifacts": artifact_payload(matching_project_artifacts(exports_dir, project_id=project_id, project_name=project.name)),
        }

    def _project_scoped_tables(self) -> list[str]:
        return sorted(table for table in self._table_names() if "project_id" in self._table_columns(table) and table != "projects")

    def _dependent_table_specs(self) -> dict[str, tuple[str, str, str]]:
        return {
            "layer2_feature_aliases": ("feature_id", "layer2_features", "id"),
            "assistant_runs": ("assistant_message_id", "assistant_messages", "id"),
            "assistant_specialist_runs": ("assistant_run_id", "assistant_runs", "id"),
        }

    def _count_table_rows(self, table: str, project_id: str) -> int:
        row = self._fetchone(f"SELECT COUNT(*) AS count FROM {table} WHERE project_id = {self.param}", (project_id,))
        return int(row["count"]) if row else 0

    def _count_dependent_rows(self, table: str, column: str, source_ids: list[str]) -> int:
        return sum(
            int((self._fetchone(f"SELECT COUNT(*) AS count FROM {table} WHERE {column} = {self.param}", (source_id,)) or {"count": 0})["count"])
            for source_id in source_ids
        )

    def _dependent_ids(self, table: str, id_column: str, value_column: str, values: list[str]) -> list[str]:
        if table not in self._table_names():
            return []
        ids: list[str] = []
        for value in values:
            rows = self._fetchall(f"SELECT {id_column} AS id FROM {table} WHERE {value_column} = {self.param}", (value,))
            ids.extend(str(row["id"]) for row in rows)
        return ids

    def _ids(self, table: str, column: str, where: str, params: tuple[Any, ...]) -> list[str]:
        if table not in self._table_names():
            return []
        rows = self._fetchall(f"SELECT {column} AS id FROM {table} WHERE {where}", params)
        return [str(row["id"]) for row in rows]

    def _ids_for_values(self, table: str, id_column: str, value_column: str, values: list[str]) -> list[str]:
        if table not in self._table_names():
            return []
        ids: list[str] = []
        for value in values:
            rows = self._fetchall(f"SELECT {id_column} AS id FROM {table} WHERE {value_column} = {self.param}", (value,))
            ids.extend(str(row["id"]) for row in rows)
        return ids

    def _delete_for_values(self, table: str, column: str, values: list[str]) -> int:
        if table not in self._table_names():
            return 0
        deleted = 0
        for value in values:
            deleted += self._rowcount(f"DELETE FROM {table} WHERE {column} = {self.param}", (value,))
        return deleted

    def _rowcount(self, query: str, params: tuple[Any, ...]) -> int:
        with self.connect() as conn:
            cursor = conn.execute(query, params) if not self.is_postgres else conn.execute(query, params)
            return int(cursor.rowcount or 0)

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()
