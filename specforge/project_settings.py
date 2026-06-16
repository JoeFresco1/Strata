from __future__ import annotations

from copy import deepcopy
from typing import Any

from specforge.config import AppConfig


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
    }


def default_app_model_settings(config: AppConfig) -> dict[str, Any]:
    """Return the reusable global model-profile and assignment defaults."""
    return deepcopy(_base_model_settings(config))


def normalize_model_settings(payload: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    """Validate and normalize an app-level or project-level model settings payload."""
    normalized = _base_model_settings(config)
    seen_llm_ids: set[str] = set()
    llm_profiles: list[dict[str, str]] = []
    for raw_profile in payload.get("llm_profiles", []):
        profile_id = str(raw_profile.get("id", "")).strip()
        label = str(raw_profile.get("label", "")).strip()
        base_url = str(raw_profile.get("base_url", "")).strip().rstrip("/")
        model_name = str(raw_profile.get("model_name", "")).strip()
        local_path = str(raw_profile.get("local_path", "")).strip()
        if not profile_id or not label or profile_id in seen_llm_ids:
            continue
        if not model_name and not local_path:
            continue
        seen_llm_ids.add(profile_id)
        llm_profiles.append(
            {
                "id": profile_id,
                "label": label,
                "base_url": base_url,
                "model_name": model_name,
                "local_path": local_path,
            }
        )
    if llm_profiles:
        normalized["llm_profiles"] = llm_profiles

    seen_embedding_ids: set[str] = set()
    embedding_profiles: list[dict[str, str]] = []
    for raw_profile in payload.get("embedding_profiles", []):
        profile_id = str(raw_profile.get("id", "")).strip()
        label = str(raw_profile.get("label", "")).strip()
        model_name = str(raw_profile.get("model_name", "")).strip()
        if not profile_id or not label or not model_name or profile_id in seen_embedding_ids:
            continue
        seen_embedding_ids.add(profile_id)
        embedding_profiles.append(
            {
                "id": profile_id,
                "label": label,
                "model_name": model_name,
            }
        )
    if embedding_profiles:
        normalized["embedding_profiles"] = embedding_profiles

    llm_profile_ids = {profile["id"] for profile in normalized["llm_profiles"]}
    embedding_profile_ids = {profile["id"] for profile in normalized["embedding_profiles"]}
    assignments = normalized["assignments"]
    raw_assignments = payload.get("assignments", {})
    if isinstance(raw_assignments, dict):
        for assignment in PROJECT_LLM_ASSIGNMENTS:
            if assignment == "layer1_generation":
                value = raw_assignments.get(assignment, assignments[assignment])
                if isinstance(value, list):
                    resolved = [str(item).strip() for item in value if str(item).strip() in llm_profile_ids]
                    assignments[assignment] = resolved or [normalized["llm_profiles"][0]["id"]]
            else:
                value = str(raw_assignments.get(assignment, assignments[assignment])).strip()
                if value in llm_profile_ids:
                    assignments[assignment] = value
        for assignment in PROJECT_EMBEDDING_ASSIGNMENTS:
            value = str(raw_assignments.get(assignment, assignments[assignment])).strip()
            if value in embedding_profile_ids:
                assignments[assignment] = value
    normalized["assignments"] = assignments
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
