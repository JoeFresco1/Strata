from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    """Return an ISO timestamp for telemetry records."""
    return datetime.now(timezone.utc).isoformat()


class TelemetryDatabaseMixin:
    """Persist privacy-aware model-call telemetry and build project aggregates."""

    def get_telemetry_settings(self, project_id: str) -> dict[str, bool]:
        """Return project capture controls, creating nothing when defaults are sufficient."""
        row = self._fetchone(
            f"SELECT * FROM project_telemetry_settings WHERE project_id = {self.param}",
            (project_id,),
        )
        if row is None:
            return {
                "enabled": True,
                "capture_prompt_bodies": True,
                "capture_response_bodies": True,
                "capture_parsed_results": True,
            }
        return {
            "enabled": bool(row["enabled"]),
            "capture_prompt_bodies": bool(row["capture_prompt_bodies"]),
            "capture_response_bodies": bool(row["capture_response_bodies"]),
            "capture_parsed_results": bool(row["capture_parsed_results"]),
        }

    def upsert_telemetry_settings(self, project_id: str, settings: dict[str, Any]) -> dict[str, bool]:
        """Persist project telemetry and content-retention controls."""
        normalized = {
            "enabled": bool(settings.get("enabled", True)),
            "capture_prompt_bodies": bool(settings.get("capture_prompt_bodies", True)),
            "capture_response_bodies": bool(settings.get("capture_response_bodies", True)),
            "capture_parsed_results": bool(settings.get("capture_parsed_results", True)),
        }
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO project_telemetry_settings (
                project_id, enabled, capture_prompt_bodies, capture_response_bodies,
                capture_parsed_results, created_at, updated_at
            ) VALUES ({', '.join([self.param] * 7)})
            ON CONFLICT(project_id) DO UPDATE SET
                enabled = excluded.enabled,
                capture_prompt_bodies = excluded.capture_prompt_bodies,
                capture_response_bodies = excluded.capture_response_bodies,
                capture_parsed_results = excluded.capture_parsed_results,
                updated_at = excluded.updated_at
            """,
            (
                project_id,
                normalized["enabled"],
                normalized["capture_prompt_bodies"],
                normalized["capture_response_bodies"],
                normalized["capture_parsed_results"],
                now,
                now,
            ),
        )
        return normalized

    def record_model_call(self, payload: dict[str, Any]) -> str | None:
        """Write one completed or failed provider request using current privacy controls."""
        project_id = str(payload.get("project_id", "")).strip()
        if not project_id:
            return None
        settings = self.get_telemetry_settings(project_id)
        if not settings["enabled"]:
            return None
        call_id = str(payload.get("id") or uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO model_call_events (
                id, project_id, layer, workflow, run_id, request_kind, provider_kind,
                model_name, model_profile_id, prompt_key, prompt_version, status,
                attempt, retry_count, latency_ms, prompt_tokens, completion_tokens,
                total_tokens, estimated_cost_usd, request_chars, response_chars,
                system_prompt, user_prompt, raw_response, parsed_result,
                error_type, error_message, started_at, completed_at, metadata
            ) VALUES ({', '.join([self.param] * 30)})
            """,
            (
                call_id,
                project_id,
                payload.get("layer", "unknown"),
                payload.get("workflow", "unscoped"),
                payload.get("run_id"),
                payload.get("request_kind", "chat_completion"),
                payload.get("provider_kind", "local"),
                payload.get("model_name"),
                payload.get("model_profile_id"),
                payload.get("prompt_key"),
                payload.get("prompt_version"),
                payload.get("status", "completed"),
                int(payload.get("attempt", 1)),
                int(payload.get("retry_count", 0)),
                int(payload.get("latency_ms", 0)),
                int(payload.get("prompt_tokens", 0)),
                int(payload.get("completion_tokens", 0)),
                int(payload.get("total_tokens", 0)),
                payload.get("estimated_cost_usd"),
                int(payload.get("request_chars", 0)),
                int(payload.get("response_chars", 0)),
                payload.get("system_prompt") if settings["capture_prompt_bodies"] else None,
                payload.get("user_prompt") if settings["capture_prompt_bodies"] else None,
                payload.get("raw_response") if settings["capture_response_bodies"] else None,
                self._dump_json(payload.get("parsed_result", {})) if settings["capture_parsed_results"] else self._dump_json({}),
                payload.get("error_type"),
                payload.get("error_message"),
                payload.get("started_at", utc_now()),
                payload.get("completed_at", utc_now()),
                self._dump_json(payload.get("metadata", {})),
            ),
        )
        return call_id

    def list_model_calls(self, project_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return newest model calls for the run inspector."""
        rows = self._fetchall(
            f"""
            SELECT * FROM model_call_events
            WHERE project_id = {self.param}
            ORDER BY started_at DESC
            LIMIT {self.param}
            """,
            (project_id, max(1, min(500, limit))),
        )
        return [self._telemetry_row(row) for row in rows]

    def get_model_call(self, project_id: str, call_id: str) -> dict[str, Any]:
        """Return one project-owned model call with retained inspector details."""
        row = self._fetchone(
            f"SELECT * FROM model_call_events WHERE project_id = {self.param} AND id = {self.param}",
            (project_id, call_id),
        )
        if row is None:
            raise ValueError(f"Telemetry run not found: {call_id}")
        return self._telemetry_row(row)

    def telemetry_summary(self, project_id: str) -> dict[str, Any]:
        """Aggregate usage, reliability, latency, model, and workflow totals."""
        rows = self._fetchall(
            f"SELECT * FROM model_call_events WHERE project_id = {self.param} ORDER BY started_at DESC",
            (project_id,),
        )
        calls = [self._telemetry_row(row) for row in rows]
        totals = self._telemetry_totals(calls)
        return {
            "totals": totals,
            "by_layer": self._group_telemetry(calls, "layer"),
            "by_model": self._group_telemetry(calls, "model_name"),
            "by_workflow": self._group_telemetry(calls, "workflow"),
            "recent_runs": calls[:50],
            "settings": self.get_telemetry_settings(project_id),
        }

    @staticmethod
    def _telemetry_totals(calls: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate the common aggregate shape used by every analytics grouping."""
        total_calls = len(calls)
        failures = sum(call["status"] != "completed" for call in calls)
        latency_total = sum(call["latency_ms"] for call in calls)
        return {
            "calls": total_calls,
            "local_calls": sum(call["provider_kind"] == "local" for call in calls),
            "remote_calls": sum(call["provider_kind"] == "remote" for call in calls),
            "failures": failures,
            "timeouts": sum(call["error_type"] == "timeout" for call in calls),
            "retries": sum(call["retry_count"] for call in calls),
            "prompt_tokens": sum(call["prompt_tokens"] for call in calls),
            "completion_tokens": sum(call["completion_tokens"] for call in calls),
            "total_tokens": sum(call["total_tokens"] for call in calls),
            "estimated_cost_usd": round(sum(call["estimated_cost_usd"] or 0 for call in calls), 6),
            "generation_seconds": round(latency_total / 1000, 2),
            "average_latency_ms": round(latency_total / total_calls) if total_calls else 0,
        }

    def _group_telemetry(self, calls: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        """Group calls by one stable dimension and attach aggregate totals."""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for call in calls:
            label = str(call.get(key) or "unknown")
            grouped.setdefault(label, []).append(call)
        return [
            {"name": label, **self._telemetry_totals(items)}
            for label, items in sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)
        ]

    def _telemetry_row(self, row: Any) -> dict[str, Any]:
        """Convert a telemetry database row into a JSON-ready inspector record."""
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "layer": row["layer"],
            "workflow": row["workflow"],
            "run_id": row["run_id"],
            "request_kind": row["request_kind"],
            "provider_kind": row["provider_kind"],
            "model_name": row["model_name"],
            "model_profile_id": row["model_profile_id"],
            "prompt_key": row["prompt_key"],
            "prompt_version": row["prompt_version"],
            "status": row["status"],
            "attempt": int(row["attempt"]),
            "retry_count": int(row["retry_count"]),
            "latency_ms": int(row["latency_ms"]),
            "prompt_tokens": int(row["prompt_tokens"]),
            "completion_tokens": int(row["completion_tokens"]),
            "total_tokens": int(row["total_tokens"]),
            "estimated_cost_usd": float(row["estimated_cost_usd"]) if row["estimated_cost_usd"] is not None else None,
            "request_chars": int(row["request_chars"]),
            "response_chars": int(row["response_chars"]),
            "system_prompt": row["system_prompt"],
            "user_prompt": row["user_prompt"],
            "raw_response": row["raw_response"],
            "parsed_result": self._load_json(row["parsed_result"]),
            "error_type": row["error_type"],
            "error_message": row["error_message"],
            "started_at": str(row["started_at"]),
            "completed_at": str(row["completed_at"]),
            "metadata": self._load_json(row["metadata"]),
        }
