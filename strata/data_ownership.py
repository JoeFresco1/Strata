from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DATA_OWNERSHIP_DEFAULTS: dict[str, int | None] = {
    "telemetry_retention_days": None,
    "telemetry_body_retention_days": None,
    "research_retention_days": None,
    "assistant_retention_days": None,
    "exports_retention_days": None,
}


def normalize_retention_days(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    days = int(value)
    if days < 1:
        raise ValueError("Retention days must be blank or greater than zero.")
    return days


def retention_cutoff(days: int | None) -> str | None:
    if days is None:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def project_slug(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in name).strip("-")


def matching_project_artifacts(exports_dir: Path | None, *, project_id: str, project_name: str) -> list[Path]:
    if exports_dir is None or not exports_dir.exists():
        return []
    slug = project_slug(project_name)
    matches: list[Path] = []
    for path in exports_dir.iterdir():
        if not path.is_file():
            continue
        if project_id in path.name or (slug and path.name.startswith(slug)):
            matches.append(path)
    return sorted(matches)


def artifact_payload(paths: list[Path]) -> list[str]:
    return [str(path) for path in paths]
