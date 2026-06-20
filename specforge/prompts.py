from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from specforge.config import DEFAULT_PROMPTS_PATH


def _format_list(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


def _format_scalar(value: str | None, *, fallback: str = "None") -> str:
    """Render a single prompt value without forcing callers to special-case missing data."""
    if value is None or not str(value).strip():
        return fallback
    return str(value).strip()


def _format_memory_items(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- None"
    lines = []
    for item in items:
        title = item.get("title", "")
        description = item.get("description", "")
        tags = ", ".join(item.get("tags", []))
        fingerprint = item.get("fingerprint", "")
        lines.append(
            f"- {title} | {description} | tags: {tags or 'none'} | concept: {fingerprint or 'n/a'}"
        )
    return "\n".join(lines)


@lru_cache(maxsize=4)
def _load_prompt_catalog(path_str: str) -> dict[str, str]:
    path = Path(path_str)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Prompt catalog must be a JSON object: {path}")
    return {str(key): str(value) for key, value in payload.items()}


def load_prompt_catalog(prompts_path: Path | None = None) -> dict[str, str]:
    """Load the prompt catalog from disk so callers can snapshot or edit it in memory."""
    return dict(_load_prompt_catalog(str(prompts_path or DEFAULT_PROMPTS_PATH)))


def get_prompt_template(
    prompt_key: str,
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    catalog = prompt_catalog or _load_prompt_catalog(str(prompts_path or DEFAULT_PROMPTS_PATH))
    try:
        return catalog[prompt_key]
    except KeyError as exc:
        raise KeyError(f"Prompt template not found: {prompt_key}") from exc


def render_prompt(
    prompt_key: str,
    variables: dict[str, Any],
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    rendered = get_prompt_template(prompt_key, prompts_path=prompts_path, prompt_catalog=prompt_catalog)
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered.strip()


def build_system_prompt(
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    return get_prompt_template("system_json_generator", prompts_path=prompts_path, prompt_catalog=prompt_catalog).strip()


def build_pillar_prompt(
    product_idea: str,
    user_rejected_ideas: list[str],
    user_approved_directions: list[str],
    persisted_pillars: list[dict[str, Any]],
    persisted_families: list[str],
    critic_coverage_summary: str,
    critic_uncovered_areas: list[str],
    critic_recommended_lens: str | None,
    lens_name: str,
    lens_instruction: str,
    model_role: str,
    role_instruction: str,
    target_count: int = 12,
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    return render_prompt(
        "layer1_pillar_generation",
        {
            "lens_name": lens_name,
            "lens_instruction": lens_instruction,
            "model_role": model_role,
            "role_instruction": role_instruction,
            "target_count": target_count,
            "user_rejected_ideas": _format_list(user_rejected_ideas),
            "user_approved_directions": _format_list(user_approved_directions),
            "persisted_pillars": _format_memory_items(persisted_pillars),
            "persisted_families": _format_list(persisted_families),
            "critic_coverage_summary": _format_scalar(critic_coverage_summary, fallback="No critic summary yet."),
            "critic_uncovered_areas": _format_list(critic_uncovered_areas),
            "critic_recommended_lens": _format_scalar(critic_recommended_lens, fallback="None"),
            "product_idea": product_idea,
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_pillar_normalization_prompt(
    *,
    product_idea: str,
    lens_name: str,
    existing_pillars: list[dict[str, Any]],
    raw_candidates: list[dict[str, Any]],
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    return render_prompt(
        "layer1_pillar_normalization",
        {
            "product_idea": product_idea,
            "lens_name": lens_name,
            "existing_pillars": _format_memory_items(existing_pillars),
            "raw_candidates": _format_memory_items(raw_candidates),
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_pillar_assessment_prompt(
    *,
    product_idea: str,
    existing_pillars: list[dict[str, Any]],
    candidate_pillars: list[dict[str, Any]],
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    return render_prompt(
        "layer1_pillar_assessment",
        {
            "product_idea": product_idea,
            "existing_pillars": _format_memory_items(existing_pillars),
            "candidate_pillars": _format_memory_items(candidate_pillars),
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_subfeature_prompt(
    product_idea: str,
    pillar_title: str,
    pillar_description: str,
    existing_sibling_features: list[dict[str, Any]],
    shared_project_features: list[dict[str, Any]],
    rejected_ideas: list[str],
    approved_directions: list[str],
    coverage_summary: str,
    uncovered_areas: list[str],
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    return render_prompt(
        "layer2_subfeature_generation",
        {
            "product_idea": product_idea,
            "pillar_title": pillar_title,
            "pillar_description": pillar_description,
            "existing_sibling_features": _format_memory_items(existing_sibling_features),
            "shared_project_features": _format_memory_items(shared_project_features),
            "uncovered_areas": _format_list(uncovered_areas),
            "coverage_summary": coverage_summary,
            "rejected_ideas": _format_list(rejected_ideas),
            "approved_directions": _format_list(approved_directions),
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_layer2_feature_prompt(
    *,
    product_idea: str,
    pillar_title: str,
    pillar_description: str,
    lens_name: str,
    lens_instruction: str,
    scope_contract: dict[str, Any],
    coverage_families: list[str],
    coverage_summary: str,
    sibling_features: list[dict[str, Any]],
    cross_pillar_features: list[dict[str, Any]],
    negative_cache: list[str],
    target_count: int,
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    """Render the graph-native Layer 2 prompt for one scoped lens pass."""
    return render_prompt(
        "layer2_feature_graph_generation",
        {
            "product_idea": product_idea,
            "pillar_title": pillar_title,
            "pillar_description": pillar_description,
            "lens_name": lens_name,
            "lens_instruction": lens_instruction,
            "scope_contract": json.dumps(scope_contract, indent=2),
            "coverage_families": _format_list(coverage_families),
            "coverage_summary": _format_scalar(coverage_summary, fallback="No Layer 2 coverage assessment yet."),
            "sibling_features": _format_memory_items(sibling_features),
            "cross_pillar_features": _format_memory_items(cross_pillar_features),
            "negative_cache": _format_list(negative_cache),
            "target_count": target_count,
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_layer2_coverage_prompt(
    *,
    product_idea: str,
    scope_contract: dict[str, Any],
    coverage_families: list[str],
    current_features: list[dict[str, Any]],
    newest_features: list[dict[str, Any]],
    previous_summary: str,
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    """Render the Layer 2 scoped coverage critic prompt."""
    return render_prompt(
        "layer2_scope_coverage_critic",
        {
            "product_idea": product_idea,
            "scope_contract": json.dumps(scope_contract, indent=2),
            "coverage_families": _format_list(coverage_families),
            "current_features": _format_memory_items(current_features),
            "newest_features": _format_memory_items(newest_features),
            "previous_summary": _format_scalar(previous_summary, fallback="No prior Layer 2 coverage summary."),
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_layer2_scope_discovery_prompt(
    *,
    product_idea: str,
    pillar_title: str,
    pillar_description: str,
    project_pillars: list[dict[str, Any]],
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    """Render the pre-pass prompt that discovers Layer 2 pillar boundaries."""
    return render_prompt(
        "layer2_dynamic_coverage_family_discovery",
        {
            "product_idea": product_idea,
            "pillar_title": pillar_title,
            "pillar_description": pillar_description,
            "project_pillars": _format_memory_items(project_pillars),
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_layer2_integrity_critic_prompt(
    *,
    product_idea: str,
    scope_contract: dict[str, Any],
    normalized_features: list[dict[str, Any]],
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    """Render the batched Layer 2 integrity critic prompt."""
    return render_prompt(
        "layer2_integrity_critic",
        {
            "product_idea": product_idea,
            "scope_contract": json.dumps(scope_contract, indent=2),
            "normalized_features": json.dumps(normalized_features, indent=2),
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_layer2_graph_critic_prompt(
    *,
    product_idea: str,
    current_round_features: list[dict[str, Any]],
    existing_project_features: list[dict[str, Any]],
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    """Render the batched Layer 2 graph critic prompt."""
    return render_prompt(
        "layer2_graph_critic",
        {
            "product_idea": product_idea,
            "current_round_features": json.dumps(current_round_features, indent=2),
            "existing_project_features": json.dumps(existing_project_features, indent=2),
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_critic_prompt(
    *,
    layer_name: str,
    product_idea: str,
    parent_context: str,
    existing_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    previous_summary: str,
    available_lenses: list[str],
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    return render_prompt(
        "coverage_critic",
        {
            "layer_name": layer_name,
            "product_idea": product_idea,
            "parent_context": parent_context,
            "previous_summary": previous_summary,
            "existing_items": _format_memory_items(existing_items),
            "new_items": _format_memory_items(new_items),
            "available_lenses": _format_list(available_lenses),
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_pillar_research_assessment_prompt(
    *,
    product_idea: str,
    pillar_title: str,
    pillar_description: str,
    competitor_matrix: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    return render_prompt(
        "layer1_pillar_research_assessment",
        {
            "product_idea": product_idea,
            "pillar_title": pillar_title,
            "pillar_description": pillar_description,
            "competitor_matrix": json.dumps(competitor_matrix, ensure_ascii=True, indent=2),
            "evidence": json.dumps(evidence, ensure_ascii=True, indent=2),
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_spec_prompt(
    product_idea: str,
    pillar_title: str,
    subfeature_title: str,
    subfeature_description: str,
    shared_project_features: list[dict[str, Any]],
    rejected_ideas: list[str],
    approved_directions: list[str],
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    return render_prompt(
        "layer3_spec_generation",
        {
            "product_idea": product_idea,
            "pillar_title": pillar_title,
            "subfeature_title": subfeature_title,
            "subfeature_description": subfeature_description,
            "shared_project_features": _format_memory_items(shared_project_features),
            "rejected_ideas": _format_list(rejected_ideas),
            "approved_directions": _format_list(approved_directions),
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_json_repair_prompt(
    *,
    schema_label: str,
    schema_instructions: str,
    candidate_content: str,
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    return render_prompt(
        "json_schema_repair",
        {
            "schema_label": schema_label,
            "schema_instructions": schema_instructions,
            "candidate_content": candidate_content,
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_layer0_brief_extraction_prompt(
    *,
    current_brief: dict[str, Any],
    conversation_tail: list[dict[str, str]],
    user_message: str,
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    """Ask the local model to convert a Plan-mode turn into canonical brief edits."""
    return render_prompt(
        "layer0_brief_extraction",
        {
            "current_brief": json.dumps(current_brief, ensure_ascii=True, indent=2),
            "conversation_tail": json.dumps(conversation_tail[-8:], ensure_ascii=True, indent=2),
            "user_message": user_message,
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )


def build_layer0_plan_reply_prompt(
    *,
    current_brief: dict[str, Any],
    conversation_tail: list[dict[str, str]],
    user_message: str,
    extracted_updates: dict[str, Any],
    open_fields: list[str],
    prompts_path: Path | None = None,
    prompt_catalog: dict[str, str] | None = None,
) -> str:
    """Ask the local model for a structured intake reply after extracting brief fields."""
    return render_prompt(
        "layer0_plan_guidance",
        {
            "current_brief": json.dumps(current_brief, ensure_ascii=True, indent=2),
            "conversation_tail": json.dumps(conversation_tail[-8:], ensure_ascii=True, indent=2),
            "user_message": user_message,
            "extracted_updates": json.dumps(extracted_updates, ensure_ascii=True, indent=2),
            "open_fields": json.dumps(open_fields, ensure_ascii=True),
        },
        prompts_path=prompts_path,
        prompt_catalog=prompt_catalog,
    )
