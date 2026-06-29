from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from strata.config import ROOT_DIR, AppConfig
from strata.migrations import migration_status


BUNDLE_SCHEMA_ID = "strata.diagnostics.bundle.v2"
MAX_LOG_LINES = 1000
DEFAULT_LOG_LINES = 400


@dataclass(slots=True)
class DiagnosticsOptions:
    include_logs: bool = True
    include_recent_errors: bool = True
    include_traces: bool = True
    log_line_limit: int = DEFAULT_LOG_LINES
    redaction_profile: str = "standard"

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "DiagnosticsOptions":
        data = payload or {}
        limit = int(data.get("log_line_limit") or DEFAULT_LOG_LINES)
        return cls(
            include_logs=bool(data.get("include_logs", True)),
            include_recent_errors=bool(data.get("include_recent_errors", True)),
            include_traces=bool(data.get("include_traces", True)),
            log_line_limit=max(1, min(MAX_LOG_LINES, limit)),
            redaction_profile=str(data.get("redaction_profile") or "standard"),
        )

    def model_dump(self) -> dict[str, Any]:
        return {
            "include_logs": self.include_logs,
            "include_recent_errors": self.include_recent_errors,
            "include_traces": self.include_traces,
            "log_line_limit": self.log_line_limit,
            "redaction_profile": self.redaction_profile,
        }


class Redactor:
    """Apply stable, counted replacements to diagnostics support data."""

    def __init__(self, profile: str = "standard"):
        self.profile = profile or "standard"
        self.counts: dict[str, int] = {}
        self._patterns: list[tuple[str, re.Pattern[str]]] = [
            ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE)),
            ("basic_token", re.compile(r"\bBasic\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE)),
            ("api_key", re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\b\s*[:=]\s*['\"]?[^'\"\s,;}{]+")),
            ("database_url", re.compile(r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb|redis)://[^\s'\",)}]+", re.IGNORECASE)),
            ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
            ("windows_path", re.compile(r"\b[A-Za-z]:\\(?:[^\\/:*?\"<>|\s\[\]\r\n]+\\)*[^\\/:*?\"<>|\s\[\]\r\n]*")),
            ("home_path", re.compile(r"(?<!\w)/(?:Users|home)/[^\s'\",)}]+")),
            ("long_secret", re.compile(r"\b(?=[A-Za-z0-9+/=_-]{32,}\b)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9+/=_-]{32,}\b")),
        ]

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._redact_text(value)
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return [self.redact(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self.redact(item) for key, item in value.items()}
        return value

    def _redact_text(self, text: str) -> str:
        redacted = text
        for label, pattern in self._patterns:
            redacted = pattern.sub(lambda match, item=label: self._replace(item), redacted)
        return redacted

    def _replace(self, label: str) -> str:
        self.counts[label] = self.counts.get(label, 0) + 1
        return f"[REDACTED:{label}]"


def build_diagnostics_bundle(services: Any, project_id: str, options: DiagnosticsOptions | None = None) -> dict[str, Any]:
    opts = options or DiagnosticsOptions()
    redactor = Redactor(opts.redaction_profile)
    warnings: list[str] = []
    schema_version = migration_status(services.db)
    project = services.db.get_project(project_id).model_dump(mode="json")
    project_settings = services.db.get_project_model_settings(project_id)
    jobs = services.db.platform_job_summary(project_id)
    dependency_health = _dependency_health(services, project_id)
    sections = [
        "dependency_health",
        "jobs",
        "platform_jobs",
        "project",
        "project_model_settings",
        "research_jobs",
        "schema_version",
        "telemetry",
    ]
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "dependency_health": dependency_health,
        "telemetry": services.db.telemetry_summary(project_id),
        "jobs": jobs,
        "platform_jobs": [item.model_dump(mode="json") for item in services.db.list_platform_jobs(project_id, limit=100)],
        "research_jobs": [item.model_dump(mode="json") for item in services.db.list_research_jobs(project_id)],
        "project_model_settings": project_settings.model_dump(mode="json") if project_settings else None,
    }
    if opts.include_logs:
        sections.append("logs")
        payload["logs"] = _collect_logs(services.config, opts.log_line_limit, warnings)
    if opts.include_recent_errors:
        sections.append("recent_errors")
        payload["recent_errors"] = _recent_errors(services.db, project_id)
    if opts.include_traces:
        sections.append("recent_traces")
        payload["recent_traces"] = _recent_traces(services.db, project_id)

    redacted_payload = redactor.redact(payload)
    redacted_warnings = redactor.redact(warnings)
    manifest = {
        "bundle_version": 2,
        "bundle_schema_id": BUNDLE_SCHEMA_ID,
        "generator_version": _generator_version(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "schema_version": schema_version,
        "included_sections": sorted(sections),
        "redaction": {
            "profile": opts.redaction_profile,
            "options": opts.model_dump(),
            "replacement_counts": dict(sorted(redactor.counts.items())),
        },
        "warnings": redacted_warnings,
        "content_hash": "",
    }
    redacted_payload["manifest"] = manifest
    manifest["content_hash"] = diagnostics_content_hash(redacted_payload)
    return redacted_payload


def diagnostics_preview(services: Any, project_id: str, options: DiagnosticsOptions | None = None) -> dict[str, Any]:
    bundle = build_diagnostics_bundle(services, project_id, options)
    return {
        "manifest": bundle["manifest"],
        "sections": [
            {"name": key, "count": _section_count(value), "sample": _sample(value)}
            for key, value in bundle.items()
            if key != "manifest"
        ],
    }


def diagnostics_content_hash(bundle: dict[str, Any]) -> str:
    stable = json.loads(json.dumps(bundle, sort_keys=True, default=str))
    manifest = stable.get("manifest") or {}
    manifest.pop("generated_at", None)
    manifest.pop("content_hash", None)
    stable.pop("exported_at", None)
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _collect_logs(config: AppConfig, line_limit: int, warnings: list[str]) -> dict[str, Any]:
    log_dir = ROOT_DIR / ".runtime" / "logs"
    candidates = [
        log_dir / "strata-api.log",
        log_dir / "strata-worker.log",
        log_dir / "uvicorn.log",
        log_dir / "llama-server.stdout.log",
        log_dir / "llama-server.stderr.log",
    ]
    if config.exports_dir:
        candidates.append(Path(config.exports_dir) / "diagnostics.log")
    entries: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not path.exists():
            warnings.append(f"Log file not found: {path.name}")
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-line_limit:]
        except OSError as exc:
            warnings.append(f"Could not read log file {path.name}: {exc}")
            continue
        entries.append({"name": path.name, "path": str(path), "line_count": len(lines), "lines": lines})
    return {"line_limit": line_limit, "files": entries}


def _recent_errors(db: Any, project_id: str) -> dict[str, Any]:
    jobs = [
        {
            "id": job.id,
            "workflow": job.workflow,
            "status": job.status,
            "error_type": job.error_type,
            "error_message": job.error_message,
            "updated_at": job.updated_at.isoformat(),
        }
        for job in db.list_platform_jobs(project_id, limit=100)
        if job.status in {"failed", "interrupted"} or job.error_message
    ][:25]
    model_calls = [
        {
            "id": call["id"],
            "workflow": call["workflow"],
            "status": call["status"],
            "error_type": call["error_type"],
            "error_message": call["error_message"],
            "started_at": call["started_at"],
        }
        for call in db.list_model_calls(project_id, limit=100)
        if call.get("status") != "completed" or call.get("error_message")
    ][:25]
    return {"platform_jobs": jobs, "model_calls": model_calls}


def _recent_traces(db: Any, project_id: str) -> dict[str, Any]:
    jobs = [
        {
            "id": job.id,
            "workflow": job.workflow,
            "status": job.status,
            "current_step": job.current_step,
            "result_payload": job.result_payload,
            "error_type": job.error_type,
            "error_message": job.error_message,
            "updated_at": job.updated_at.isoformat(),
        }
        for job in db.list_platform_jobs(project_id, limit=25)
    ]
    model_calls = [
        {
            "id": call["id"],
            "workflow": call["workflow"],
            "run_id": call["run_id"],
            "status": call["status"],
            "provider_kind": call["provider_kind"],
            "model_name": call["model_name"],
            "prompt_key": call["prompt_key"],
            "prompt_version": call["prompt_version"],
            "metadata": call["metadata"],
            "started_at": call["started_at"],
            "completed_at": call["completed_at"],
        }
        for call in db.list_model_calls(project_id, limit=25)
    ]
    assistant_traces = _assistant_traces(db, project_id)
    return {"platform_jobs": jobs, "model_calls": model_calls, "assistant": assistant_traces}


def _assistant_traces(db: Any, project_id: str) -> list[dict[str, Any]]:
    try:
        rows = db._fetchall(
            f"""
            SELECT m.id, m.conversation_id, m.retrieval_trace, m.error, m.updated_at
            FROM assistant_messages m
            JOIN assistant_conversations c ON c.id = m.conversation_id
            WHERE c.project_id = {db.param}
              AND (m.retrieval_trace IS NOT NULL OR m.error IS NOT NULL)
            ORDER BY m.updated_at DESC
            LIMIT {db.param}
            """,
            (project_id, 25),
        )
    except Exception:  # noqa: BLE001 - diagnostics should degrade gracefully across migrations.
        return []
    traces: list[dict[str, Any]] = []
    for row in rows:
        trace = db._load_json(row["retrieval_trace"])
        if not trace and not row["error"]:
            continue
        traces.append({
            "message_id": row["id"],
            "conversation_id": row["conversation_id"],
            "retrieval_trace": trace,
            "error": row["error"],
            "updated_at": str(row["updated_at"]),
        })
    return traces


def _dependency_health(services: Any, project_id: str) -> dict[str, Any]:
    database_ok = True
    database_message = "Database query succeeded."
    embedding_count = 0
    try:
        row = services.db._fetchone(
            f"SELECT COUNT(*) AS count FROM node_embeddings WHERE project_id = {services.db.param}",
            (project_id,),
        )
        embedding_count = int(row["count"]) if row else 0
    except Exception as exc:  # noqa: BLE001 - diagnostics should capture dependency state, not fail the bundle.
        database_ok = False
        database_message = str(exc)
    model_ok, model_message = services.generation_service.llm_client.healthcheck()
    return {
        "database": {
            "ok": database_ok,
            "backend": services.config.database_backend,
            "message": database_message,
        },
        "pgvector": {
            "enabled": services.db.is_postgres,
            "embedding_count": embedding_count,
        },
        "model_server": {
            "ok": model_ok,
            "message": model_message,
        },
    }


def _generator_version() -> str:
    try:
        version = metadata.version("strata-product-discovery")
    except metadata.PackageNotFoundError:
        version = "0.1.0.dev0"
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=ROOT_DIR,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - version metadata should not block diagnostics.
        commit = ""
    return f"{version}+{commit}" if commit else version


def _section_count(value: Any) -> int:
    if isinstance(value, dict):
        if "files" in value and isinstance(value["files"], list):
            return len(value["files"])
        return len(value)
    if isinstance(value, list):
        return len(value)
    return 1 if value is not None else 0


def _sample(value: Any) -> Any:
    if isinstance(value, dict):
        if "files" in value and value["files"]:
            first = value["files"][0]
            return {"name": first.get("name"), "lines": first.get("lines", [])[:3]}
        return {key: value[key] for key in list(value)[:3]}
    if isinstance(value, list):
        return value[:3]
    return value
