from __future__ import annotations

from copy import deepcopy
from typing import Any

from specforge.config import AppConfig
from specforge.prompts import load_prompt_catalog


PROJECT_LLM_ASSIGNMENTS = (
    "layer0_plan",
    "layer0_extraction",
    "layer1_generation",
    "layer2_generation",
    "layer3_generation",
    "layer0_research",
    "layer1_research",
)

PROJECT_EMBEDDING_ASSIGNMENTS = (
    "layer1_similarity_embeddings",
    "research_embeddings",
)

DEFAULT_LLM_PROFILE_ID = "default-chat"
DEFAULT_EMBEDDING_PROFILE_ID = "default-embedding"


def _base_model_settings(config: AppConfig) -> dict[str, Any]:
    """Build the baseline reusable model settings shape from runtime defaults."""
    return {
        "llm_profiles": [
            {
                "id": DEFAULT_LLM_PROFILE_ID,
                "label": "Default Chat Model",
                "base_url": config.llama_base_url,
                "model_name": config.model_name,
                "local_path": config.preferred_model_path or "",
            }
        ],
        "embedding_profiles": [
            {
                "id": DEFAULT_EMBEDDING_PROFILE_ID,
                "label": "Default Embeddings",
                "model_name": config.embeddings_model_name,
            }
        ],
        "assignments": {
            "layer0_plan": DEFAULT_LLM_PROFILE_ID,
            "layer0_extraction": DEFAULT_LLM_PROFILE_ID,
            "layer1_generation": [DEFAULT_LLM_PROFILE_ID],
            "layer2_generation": DEFAULT_LLM_PROFILE_ID,
            "layer3_generation": DEFAULT_LLM_PROFILE_ID,
            "layer0_research": DEFAULT_LLM_PROFILE_ID,
            "layer1_research": DEFAULT_LLM_PROFILE_ID,
            "layer1_similarity_embeddings": DEFAULT_EMBEDDING_PROFILE_ID,
            "research_embeddings": DEFAULT_EMBEDDING_PROFILE_ID,
        },
        "prompt_catalog": load_prompt_catalog(),
    }


def default_app_model_settings(config: AppConfig) -> dict[str, Any]:
    """Return the reusable global model-profile and assignment defaults."""
    return deepcopy(_base_model_settings(config))


def _normalize_llm_profiles(raw_profiles: Any, fallback_profiles: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep valid unique LLM profiles while falling back to the runtime baseline when needed."""
    seen_ids: set[str] = set()
    normalized_profiles: list[dict[str, str]] = []
    if isinstance(raw_profiles, list):
        for raw_profile in raw_profiles:
            if not isinstance(raw_profile, dict):
                continue
            normalized_profile = _normalize_llm_profile(raw_profile)
            if normalized_profile is None:
                continue
            profile_id = normalized_profile["id"]
            if profile_id in seen_ids:
                continue
            seen_ids.add(profile_id)
            normalized_profiles.append(normalized_profile)
    return normalized_profiles or fallback_profiles


def _normalize_llm_profile(raw_profile: dict[str, Any]) -> dict[str, str] | None:
    """Normalize one LLM profile and reject entries that cannot be used safely."""
    profile_id = str(raw_profile.get("id", "")).strip()
    label = str(raw_profile.get("label", "")).strip()
    base_url = str(raw_profile.get("base_url", "")).strip().rstrip("/")
    model_name = str(raw_profile.get("model_name", "")).strip()
    local_path = str(raw_profile.get("local_path", "")).strip()
    if not profile_id or not label:
        return None
    if not model_name and not local_path:
        return None
    return {
        "id": profile_id,
        "label": label,
        "base_url": base_url,
        "model_name": model_name,
        "local_path": local_path,
    }


def _normalize_embedding_profiles(
    raw_profiles: Any,
    fallback_profiles: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Keep valid unique embedding profiles while preserving a usable fallback option."""
    seen_ids: set[str] = set()
    normalized_profiles: list[dict[str, str]] = []
    if isinstance(raw_profiles, list):
        for raw_profile in raw_profiles:
            if not isinstance(raw_profile, dict):
                continue
            normalized_profile = _normalize_embedding_profile(raw_profile)
            if normalized_profile is None:
                continue
            profile_id = normalized_profile["id"]
            if profile_id in seen_ids:
                continue
            seen_ids.add(profile_id)
            normalized_profiles.append(normalized_profile)
    return normalized_profiles or fallback_profiles


def _normalize_embedding_profile(raw_profile: dict[str, Any]) -> dict[str, str] | None:
    """Normalize one embedding profile and reject incomplete entries."""
    profile_id = str(raw_profile.get("id", "")).strip()
    label = str(raw_profile.get("label", "")).strip()
    model_name = str(raw_profile.get("model_name", "")).strip()
    if not profile_id or not label or not model_name:
        return None
    return {
        "id": profile_id,
        "label": label,
        "model_name": model_name,
    }


def _normalize_assignments(
    raw_assignments: Any,
    fallback_assignments: dict[str, Any],
    llm_profiles: list[dict[str, str]],
    embedding_profiles: list[dict[str, str]],
) -> dict[str, Any]:
    """Validate assignment ids against the normalized profile sets."""
    assignments = deepcopy(fallback_assignments)
    if not isinstance(raw_assignments, dict):
        return assignments

    llm_profile_ids = {profile["id"] for profile in llm_profiles}
    embedding_profile_ids = {profile["id"] for profile in embedding_profiles}
    for assignment in PROJECT_LLM_ASSIGNMENTS:
        if assignment == "layer1_generation":
            assignments[assignment] = _normalize_layer1_assignment(
                raw_assignments.get(assignment, assignments[assignment]),
                llm_profile_ids,
                llm_profiles[0]["id"],
            )
            continue
        value = str(raw_assignments.get(assignment, assignments[assignment])).strip()
        if value in llm_profile_ids:
            assignments[assignment] = value

    for assignment in PROJECT_EMBEDDING_ASSIGNMENTS:
        value = str(raw_assignments.get(assignment, assignments[assignment])).strip()
        if value in embedding_profile_ids:
            assignments[assignment] = value
    return assignments


def _normalize_layer1_assignment(value: Any, allowed_ids: set[str], fallback_id: str) -> list[str]:
    """Keep the multi-model Layer 1 assignment list valid and non-empty."""
    if not isinstance(value, list):
        return [fallback_id]
    resolved = [str(item).strip() for item in value if str(item).strip() in allowed_ids]
    return resolved or [fallback_id]


def normalize_model_settings(payload: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    """Validate and normalize an app-level or project-level model settings payload."""
    normalized = _base_model_settings(config)
    normalized["llm_profiles"] = _normalize_llm_profiles(
        payload.get("llm_profiles"),
        normalized["llm_profiles"],
    )
    normalized["embedding_profiles"] = _normalize_embedding_profiles(
        payload.get("embedding_profiles"),
        normalized["embedding_profiles"],
    )
    normalized["assignments"] = _normalize_assignments(
        payload.get("assignments"),
        normalized["assignments"],
        normalized["llm_profiles"],
        normalized["embedding_profiles"],
    )
    normalized["prompt_catalog"] = _normalize_prompt_catalog(payload.get("prompt_catalog"), normalized["prompt_catalog"])
    return normalized


def _normalize_prompt_catalog(raw_catalog: Any, fallback_catalog: dict[str, str]) -> dict[str, str]:
    """Merge edited prompt templates with the built-in catalog and keep empty values safe."""
    normalized = dict(fallback_catalog)
    if not isinstance(raw_catalog, dict):
        return normalized
    for key, value in raw_catalog.items():
        prompt_key = str(key).strip()
        if not prompt_key:
            continue
        cleaned = str(value).strip()
        if cleaned:
            normalized[prompt_key] = cleaned
    return normalized


def default_project_model_settings(config: AppConfig, seed_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build initial per-project settings from app defaults or the runtime baseline."""
    if seed_payload is None:
        return default_app_model_settings(config)
    return normalize_model_settings(seed_payload, config)


def normalize_project_model_settings(payload: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    """Validate and normalize the per-project settings payload into a safe stored shape."""
    return normalize_model_settings(payload, config)


def llm_profiles_by_id(settings: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Index project LLM profiles by id for assignment lookup."""
    return {
        str(profile.get("id", "")): profile
        for profile in settings.get("llm_profiles", [])
        if isinstance(profile, dict) and str(profile.get("id", "")).strip()
    }


def embedding_profiles_by_id(settings: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Index project embedding profiles by id for assignment lookup."""
    return {
        str(profile.get("id", "")): profile
        for profile in settings.get("embedding_profiles", [])
        if isinstance(profile, dict) and str(profile.get("id", "")).strip()
    }
