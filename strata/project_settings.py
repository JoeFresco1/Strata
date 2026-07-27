from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlparse

from strata.config import AppConfig
from strata.prompts import load_prompt_catalog


PROJECT_LLM_ASSIGNMENTS = (
    "layer0_plan",
    "layer0_extraction",
    "layer1_generation",
    "layer2_generation",
    "layer1_overlap_critic",
    "layer2_overlap_critic",
    "layer3_generation",
    "layer0_research",
    "product_discovery_generation",
    "cross_domain_exploration",
    "discovery_practicality_review",
    "competitor_evidence_extraction",
    "competitor_pillar_inference",
    "competitor_strategic_comparison",
    "layer1_research",
    "layer2_research",
    "assistant_orchestration",
    "assistant_synthesis",
    "assistant_compaction",
    "assistant_specialists",
)

PROJECT_EMBEDDING_ASSIGNMENTS = (
    "layer1_similarity_embeddings",
    "layer2_similarity_embeddings",
    "research_embeddings",
    "assistant_embeddings",
)

DEFAULT_LLM_PROFILE_ID = "default-chat"
DEFAULT_EMBEDDING_PROFILE_ID = "default-embedding"
EXECUTION_INTENTS = {"local_first", "api_first", "blended"}
ROUTING_DOMAINS = ("layer0", "generation", "research", "review", "assistant")
ROUTING_PREFERENCES = {"local", "api"}
DEFAULT_CONCURRENCY_POLICY = {
    "managed_local_parallelism": 1,
    "remote_parallelism": 4,
}
ASSIGNMENT_TO_DOMAIN = {
    "layer0_plan": "layer0",
    "layer0_extraction": "layer0",
    "layer1_generation": "generation",
    "layer2_generation": "generation",
    "layer1_overlap_critic": "review",
    "layer2_overlap_critic": "review",
    "layer3_generation": "generation",
    "layer0_research": "research",
    "product_discovery_generation": "generation",
    "cross_domain_exploration": "generation",
    "discovery_practicality_review": "review",
    "competitor_evidence_extraction": "research",
    "competitor_pillar_inference": "research",
    "competitor_strategic_comparison": "research",
    "layer1_research": "research",
    "layer2_research": "research",
    "assistant_orchestration": "assistant",
    "assistant_synthesis": "assistant",
    "assistant_compaction": "assistant",
    "assistant_specialists": "assistant",
}


def default_routing_policy(execution_intent: str) -> dict[str, str]:
    """Return the provider preference map that should back a given execution intent."""
    if execution_intent == "api_first":
        return {domain: "api" for domain in ROUTING_DOMAINS}
    if execution_intent == "blended":
        return {
            "layer0": "local",
            "generation": "local",
            "research": "local",
            "review": "local",
            "assistant": "api",
        }
    return {domain: "local" for domain in ROUTING_DOMAINS}


def assignment_domain(assignment: str) -> str:
    """Map an LLM assignment id to the execution domain used by intent routing."""
    return ASSIGNMENT_TO_DOMAIN.get(assignment, "generation")


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
                "runtime_kind": "managed_local" if config.preferred_model_path else "auto",
                "context_window": config.context_size,
                "supports_reasoning": True,
                "supports_parallel": False,
                "max_parallel_requests": 1,
                "max_specialists": 2,
                "max_output_tokens": config.max_output_tokens,
                "input_cost_per_million": 0.0,
                "output_cost_per_million": 0.0,
            }
        ],
        "embedding_profiles": [
            {
                "id": DEFAULT_EMBEDDING_PROFILE_ID,
                "label": "Default Embeddings",
                "model_name": config.embeddings_model_name,
            }
        ],
        "execution_intent": "local_first",
        "routing_policy": default_routing_policy("local_first"),
        "concurrency_policy": dict(DEFAULT_CONCURRENCY_POLICY),
        "assignments": {
            "layer0_plan": DEFAULT_LLM_PROFILE_ID,
            "layer0_extraction": DEFAULT_LLM_PROFILE_ID,
            "layer1_generation": [DEFAULT_LLM_PROFILE_ID],
            "layer2_generation": DEFAULT_LLM_PROFILE_ID,
            "layer1_overlap_critic": DEFAULT_LLM_PROFILE_ID,
            "layer2_overlap_critic": DEFAULT_LLM_PROFILE_ID,
            "layer3_generation": DEFAULT_LLM_PROFILE_ID,
            "layer0_research": DEFAULT_LLM_PROFILE_ID,
            "product_discovery_generation": DEFAULT_LLM_PROFILE_ID,
            "cross_domain_exploration": DEFAULT_LLM_PROFILE_ID,
            "discovery_practicality_review": DEFAULT_LLM_PROFILE_ID,
            "competitor_evidence_extraction": DEFAULT_LLM_PROFILE_ID,
            "competitor_pillar_inference": DEFAULT_LLM_PROFILE_ID,
            "competitor_strategic_comparison": DEFAULT_LLM_PROFILE_ID,
            "layer1_research": DEFAULT_LLM_PROFILE_ID,
            "layer2_research": DEFAULT_LLM_PROFILE_ID,
            "assistant_orchestration": DEFAULT_LLM_PROFILE_ID,
            "assistant_synthesis": DEFAULT_LLM_PROFILE_ID,
            "assistant_compaction": DEFAULT_LLM_PROFILE_ID,
            "assistant_specialists": DEFAULT_LLM_PROFILE_ID,
            "layer1_similarity_embeddings": DEFAULT_EMBEDDING_PROFILE_ID,
            "layer2_similarity_embeddings": DEFAULT_EMBEDDING_PROFILE_ID,
            "research_embeddings": DEFAULT_EMBEDDING_PROFILE_ID,
            "assistant_embeddings": DEFAULT_EMBEDDING_PROFILE_ID,
        },
        "prompt_catalog": load_prompt_catalog(),
        "competitive_intelligence_enabled": True,
        "discovery_settings": {
            "generation_temperature": 0.7,
            "cross_domain_temperature": 0.9,
            "practicality_review_temperature": 0.2,
            "competitor_evidence_temperature": 0.2,
            "competitor_pillar_temperature": 0.5,
            "competitor_comparison_temperature": 0.5,
            "generation_max_output_tokens": min(12000, max(256, config.max_output_tokens)),
            "practicality_review_max_output_tokens": min(6000, max(256, config.max_output_tokens)),
            "seed": None,
        },
    }


def default_app_model_settings(config: AppConfig) -> dict[str, Any]:
    """Return the reusable global model-profile and assignment defaults."""
    return deepcopy(_base_model_settings(config))


def _normalize_llm_profiles(raw_profiles: Any, fallback_profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep valid unique LLM profiles while falling back to the runtime baseline when needed."""
    seen_ids: set[str] = set()
    normalized_profiles: list[dict[str, Any]] = []
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


def _normalize_llm_profile(raw_profile: dict[str, Any]) -> dict[str, Any] | None:
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
        "runtime_kind": str(raw_profile.get("runtime_kind", "auto")),
        "context_window": max(2048, int(raw_profile.get("context_window", 32768))),
        "supports_reasoning": bool(raw_profile.get("supports_reasoning", True)),
        "supports_parallel": bool(raw_profile.get("supports_parallel", False)),
        "max_parallel_requests": max(1, min(32, int(raw_profile.get("max_parallel_requests", 1)))),
        "max_specialists": max(0, min(16, int(raw_profile.get("max_specialists", 2)))),
        "max_output_tokens": max(256, min(16000, int(raw_profile.get("max_output_tokens", 1800)))),
        "input_cost_per_million": max(0.0, float(raw_profile.get("input_cost_per_million", 0))),
        "output_cost_per_million": max(0.0, float(raw_profile.get("output_cost_per_million", 0))),
    }


def _looks_local_base_url(base_url: str) -> bool:
    """Treat explicit localhost endpoints as local even when no GGUF path is managed directly."""
    if not base_url:
        return False
    parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    host = (parsed.hostname or "").casefold()
    return host in {"localhost", "127.0.0.1", "::1"}


def profile_provider_kind(profile: dict[str, Any]) -> str:
    """Resolve whether a profile should be treated as local or API-backed for routing."""
    runtime_kind = str(profile.get("runtime_kind", "auto")).strip()
    if runtime_kind == "managed_local":
        return "local"
    if runtime_kind == "remote_api":
        return "api"
    if str(profile.get("local_path", "")).strip():
        return "local"
    if _looks_local_base_url(str(profile.get("base_url", "")).strip()):
        return "local"
    return "api"


def _infer_execution_intent(llm_profiles: list[dict[str, Any]]) -> str:
    """Choose a safe default execution intent from the configured profile inventory."""
    providers = {profile_provider_kind(profile) for profile in llm_profiles}
    if providers == {"api"}:
        return "api_first"
    if providers == {"local", "api"}:
        return "blended"
    return "local_first"


def _normalize_execution_intent(raw_intent: Any, llm_profiles: list[dict[str, Any]]) -> str:
    """Validate the intent value or infer one from available profiles when missing."""
    intent = str(raw_intent or "").strip()
    if intent in EXECUTION_INTENTS:
        return intent
    return _infer_execution_intent(llm_profiles)


def _normalize_routing_policy(raw_policy: Any, execution_intent: str) -> dict[str, str]:
    """Merge any edited routing preferences with the chosen intent defaults."""
    normalized = default_routing_policy(execution_intent)
    if not isinstance(raw_policy, dict):
        return normalized
    for domain in ROUTING_DOMAINS:
        value = str(raw_policy.get(domain, "")).strip()
        if value in ROUTING_PREFERENCES:
            normalized[domain] = value
    return normalized


def _normalize_concurrency_policy(raw_policy: Any) -> dict[str, int]:
    """Keep explicit concurrency limits bounded and safe for local/API execution."""
    normalized = dict(DEFAULT_CONCURRENCY_POLICY)
    if not isinstance(raw_policy, dict):
        return normalized
    if "managed_local_parallelism" in raw_policy:
        normalized["managed_local_parallelism"] = max(1, min(4, int(raw_policy.get("managed_local_parallelism", 1))))
    if "remote_parallelism" in raw_policy:
        normalized["remote_parallelism"] = max(1, min(16, int(raw_policy.get("remote_parallelism", 4))))
    return normalized


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
    normalized["execution_intent"] = _normalize_execution_intent(
        payload.get("execution_intent"),
        normalized["llm_profiles"],
    )
    normalized["routing_policy"] = _normalize_routing_policy(
        payload.get("routing_policy"),
        normalized["execution_intent"],
    )
    normalized["concurrency_policy"] = _normalize_concurrency_policy(payload.get("concurrency_policy"))
    normalized["assignments"] = _normalize_assignments(
        payload.get("assignments"),
        normalized["assignments"],
        normalized["llm_profiles"],
        normalized["embedding_profiles"],
    )
    normalized["prompt_catalog"] = _normalize_prompt_catalog(payload.get("prompt_catalog"), normalized["prompt_catalog"])
    normalized["competitive_intelligence_enabled"] = bool(payload.get("competitive_intelligence_enabled", True))
    normalized["discovery_settings"] = _normalize_discovery_settings(
        payload.get("discovery_settings"),
        normalized["discovery_settings"],
    )
    return normalized


def _normalize_discovery_settings(raw: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    """Bound Product Discovery model parameters without hard-coding them in workflows."""
    payload = raw if isinstance(raw, dict) else {}
    normalized = dict(defaults)
    for key in (
        "generation_temperature",
        "cross_domain_temperature",
        "practicality_review_temperature",
        "competitor_evidence_temperature",
        "competitor_pillar_temperature",
        "competitor_comparison_temperature",
    ):
        normalized[key] = max(0.0, min(2.0, float(payload.get(key, defaults[key]))))
    for key in ("generation_max_output_tokens", "practicality_review_max_output_tokens"):
        normalized[key] = max(256, min(16000, int(payload.get(key, defaults[key]))))
    seed = payload.get("seed", defaults.get("seed"))
    normalized["seed"] = int(seed) if seed is not None else None
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
