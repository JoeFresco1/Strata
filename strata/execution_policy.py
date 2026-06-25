from __future__ import annotations

from pathlib import Path
from typing import Any

from strata.config import ModelProfile
from strata.llm import LLMError, LlamaCppClient
from strata.project_settings import (
    assignment_domain,
    default_routing_policy,
    embedding_profiles_by_id,
    llm_profiles_by_id,
    profile_provider_kind,
)
from strata.server_manager import LlamaServerManager, ServerManagerError


def effective_execution_intent(settings_payload: dict[str, Any], override: str | None = None) -> str:
    """Choose the run-level override when present, otherwise the persisted project intent."""
    intent = str(override or settings_payload.get("execution_intent") or "local_first").strip()
    return intent if intent in {"local_first", "api_first", "blended"} else "local_first"


def preferred_provider(settings_payload: dict[str, Any], assignment: str, override: str | None = None) -> str:
    """Resolve whether a given assignment should prefer local or API execution."""
    intent = effective_execution_intent(settings_payload, override)
    routing = settings_payload.get("routing_policy") or default_routing_policy(intent)
    domain = assignment_domain(assignment)
    value = str(routing.get(domain, "")).strip()
    if value in {"local", "api"}:
        return value
    return default_routing_policy(intent)[domain]


def _assignment_profiles(settings_payload: dict[str, Any], assignment: str) -> list[dict[str, Any]]:
    """Collect the configured profiles for one assignment without applying execution intent yet."""
    profiles = llm_profiles_by_id(settings_payload)
    raw_assignment = settings_payload.get("assignments", {}).get(assignment, [])
    if assignment == "layer1_generation":
        if isinstance(raw_assignment, list):
            resolved = [profiles[item] for item in raw_assignment if item in profiles]
            if resolved:
                return resolved
    else:
        assignment_id = str(raw_assignment).strip()
        if assignment_id and assignment_id in profiles:
            return [profiles[assignment_id]]
    return list(profiles.values())


def resolve_llm_profile(settings_payload: dict[str, Any], assignment: str, *, override: str | None = None) -> dict[str, Any] | None:
    """Pick one effective LLM profile after applying intent-aware provider preference."""
    profiles = _assignment_profiles(settings_payload, assignment)
    if not profiles:
        return None
    provider = preferred_provider(settings_payload, assignment, override)
    matching = [profile for profile in profiles if profile_provider_kind(profile) == provider]
    if matching:
        return matching[0]
    matching = [profile for profile in settings_payload.get("llm_profiles", []) if profile_provider_kind(profile) == provider]
    if matching:
        return matching[0]
    return profiles[0]


def resolve_llm_profiles(settings_payload: dict[str, Any], assignment: str, *, override: str | None = None) -> list[dict[str, Any]]:
    """Pick the effective ordered LLM profile list for a possibly multi-model assignment."""
    profiles = _assignment_profiles(settings_payload, assignment)
    if not profiles:
        return []
    provider = preferred_provider(settings_payload, assignment, override)
    matching = [profile for profile in profiles if profile_provider_kind(profile) == provider]
    if matching:
        return matching
    return profiles


def resolve_embedding_model_name(settings_payload: dict[str, Any], assignment: str, fallback_model: str) -> str:
    """Resolve one embedding assignment without changing provider behavior."""
    assignment_id = str(settings_payload.get("assignments", {}).get(assignment, "")).strip()
    profile = embedding_profiles_by_id(settings_payload).get(assignment_id)
    if profile is None:
        return fallback_model
    return str(profile.get("model_name", "")).strip() or fallback_model


def runtime_kind(profile: dict[str, Any] | None) -> str:
    """Convert a resolved profile into the runtime-kind string used in persistent traces."""
    if profile is None:
        return "remote_api"
    return "managed_local" if profile_provider_kind(profile) == "local" else "remote_api"


def effective_parallelism(settings_payload: dict[str, Any], profile: dict[str, Any] | None) -> int:
    """Resolve the allowed parallelism for the selected runtime class."""
    policy = settings_payload.get("concurrency_policy", {}) if isinstance(settings_payload, dict) else {}
    if runtime_kind(profile) == "managed_local":
        return max(1, int(policy.get("managed_local_parallelism", 1)))
    return max(1, int(policy.get("remote_parallelism", 4)))


def resolved_runtime_request(
    profile: dict[str, Any] | None,
    *,
    llm_client: LlamaCppClient,
    server_manager: LlamaServerManager | None = None,
    thinking_enabled: bool = False,
) -> dict[str, Any]:
    """Return the concrete request settings for one resolved profile, loading managed GGUF models when needed."""
    if profile is None:
        fallback_alias = llm_client.model_name or "default"
        return {
            "id": fallback_alias,
            "label": fallback_alias,
            "base_url": None,
            "model_name": fallback_alias,
            "local_path": "",
            "runtime_kind": "remote_api",
            "provider_kind": "api",
            "supports_parallel": True,
            "max_parallel_requests": 1,
            "max_specialists": 2,
            "max_output_tokens": 1800,
            "context_window": 32768,
        }

    local_path = str(profile.get("local_path", "")).strip()
    model_name = str(profile.get("model_name", "")).strip() or str(profile.get("id", "")).strip() or None
    if local_path and server_manager is not None:
        alias = str(profile.get("id", "")).strip() or model_name or "local-model"
        try:
            server_manager.ensure_model_loaded(
                ModelProfile(alias=alias, display_name=str(profile.get("label", alias)), path=Path(local_path)),
                thinking_enabled=thinking_enabled and bool(profile.get("supports_reasoning", True)),
            )
            model_name = alias
        except (ServerManagerError, OSError) as exc:
            raise LLMError(str(exc)) from exc
    provider_kind = profile_provider_kind(profile)
    return {
        **profile,
        "base_url": str(profile.get("base_url", "")).strip() or None,
        "model_name": model_name,
        "runtime_kind": "managed_local" if provider_kind == "local" else "remote_api",
        "provider_kind": provider_kind,
    }
