from __future__ import annotations

from typing import Any

from strata.project_settings import profile_provider_kind


def model_call_context(
    *,
    project_id: str,
    layer: str,
    workflow: str,
    runtime_profile: dict[str, Any] | None = None,
    run_id: str | None = None,
    prompt_key: str | None = None,
    retry_count: int = 0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the shared metadata envelope attached to every model request."""
    profile = runtime_profile or {}
    resolved_provider = profile.get("provider_kind") if profile else None
    if resolved_provider not in {"local", "api"} and profile:
        resolved_provider = profile_provider_kind(profile)
    provider_kind = "remote" if resolved_provider == "api" else resolved_provider
    return {
        "project_id": project_id,
        "layer": layer,
        "workflow": workflow,
        "run_id": run_id,
        "model_profile_id": profile.get("id"),
        "provider_kind": provider_kind,
        "prompt_key": prompt_key,
        "retry_count": retry_count,
        "input_cost_per_million": profile.get("input_cost_per_million", 0),
        "output_cost_per_million": profile.get("output_cost_per_million", 0),
        "metadata": metadata or {},
    }
