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


def get_prompt_template(prompt_key: str, prompts_path: Path | None = None) -> str:
    catalog = _load_prompt_catalog(str(prompts_path or DEFAULT_PROMPTS_PATH))
    try:
        return catalog[prompt_key]
    except KeyError as exc:
        raise KeyError(f"Prompt template not found: {prompt_key}") from exc


def render_prompt(prompt_key: str, variables: dict[str, Any], prompts_path: Path | None = None) -> str:
    rendered = get_prompt_template(prompt_key, prompts_path=prompts_path)
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered.strip()


def build_system_prompt(prompts_path: Path | None = None) -> str:
    return get_prompt_template("system_json_generator", prompts_path=prompts_path).strip()


def build_pillar_prompt(
    product_idea: str,
    rejected_ideas: list[str],
    approved_directions: list[str],
    existing_pillars: list[dict[str, Any]],
    covered_families: list[str],
    coverage_summary: str,
    uncovered_areas: list[str],
    lens_name: str,
    lens_instruction: str,
    model_role: str,
    role_instruction: str,
    target_count: int = 12,
    prompts_path: Path | None = None,
) -> str:
    return render_prompt(
        "layer1_pillar_generation",
        {
            "lens_name": lens_name,
            "lens_instruction": lens_instruction,
            "model_role": model_role,
            "role_instruction": role_instruction,
            "target_count": target_count,
            "existing_pillars": _format_memory_items(existing_pillars),
            "covered_families": _format_list(covered_families),
            "coverage_summary": coverage_summary,
            "uncovered_areas": _format_list(uncovered_areas),
            "rejected_ideas": _format_list(rejected_ideas),
            "approved_directions": _format_list(approved_directions),
            "product_idea": product_idea,
        },
        prompts_path=prompts_path,
    )


def build_pillar_normalization_prompt(
    *,
    product_idea: str,
    lens_name: str,
    existing_pillars: list[dict[str, Any]],
    raw_candidates: list[dict[str, Any]],
    prompts_path: Path | None = None,
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
    )


def build_pillar_assessment_prompt(
    *,
    product_idea: str,
    existing_pillars: list[dict[str, Any]],
    candidate_pillars: list[dict[str, Any]],
    prompts_path: Path | None = None,
) -> str:
    return render_prompt(
        "layer1_pillar_assessment",
        {
            "product_idea": product_idea,
            "existing_pillars": _format_memory_items(existing_pillars),
            "candidate_pillars": _format_memory_items(candidate_pillars),
        },
        prompts_path=prompts_path,
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
    )


def build_json_repair_prompt(
    *,
    schema_label: str,
    schema_instructions: str,
    candidate_content: str,
    prompts_path: Path | None = None,
) -> str:
    return render_prompt(
        "json_schema_repair",
        {
            "schema_label": schema_label,
            "schema_instructions": schema_instructions,
            "candidate_content": candidate_content,
        },
        prompts_path=prompts_path,
    )
