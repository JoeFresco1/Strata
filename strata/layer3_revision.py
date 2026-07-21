from __future__ import annotations

import copy
import re
import uuid
from typing import Any


TOP_LEVEL_SECTIONS = ("feature_intent", "expansion_groups", "overlap_review", "open_questions")
GROUP_FIELDS = ("name", "description")
OPTION_FIELDS = (
    "name",
    "description",
    "selection_state",
    "configuration_kind",
    "default_recommendation",
    "rationale",
    "dependencies",
    "overlaps_feature_ids",
)


def canonical_match_key(value: Any) -> str:
    """Return the deterministic case-insensitive key used for nested identity matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def empty_diff() -> dict[str, list[dict[str, Any]]]:
    """Create the stable structured-diff shape persisted for every Layer 3 revision."""
    return {key: [] for key in ("added", "removed", "modified", "unchanged", "id_matches", "unresolved_matches")}


def _owned_value(ownership: dict[str, Any], path: str, before: Any, generated: Any) -> Any:
    """Keep a human-owned value while allowing generated fields to change."""
    return copy.deepcopy(before if path in ownership else generated)


def _unique_name_map(items: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Index only unambiguous canonical names and separately report collisions."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        buckets.setdefault(canonical_match_key(item.get("name")), []).append(item)
    collisions = {key for key, values in buckets.items() if key and len(values) > 1}
    return {key: values[0] for key, values in buckets.items() if key and len(values) == 1}, collisions


def _reconcile_options(
    active_group: dict[str, Any],
    generated_group: dict[str, Any],
    ownership: dict[str, Any],
    diff: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Reconcile option identity within one deterministically matched group."""
    existing = [dict(item) for item in active_group.get("options", [])]
    existing_by_name, existing_collisions = _unique_name_map(existing)
    generated_options = [dict(item) for item in generated_group.get("options", [])]
    _, generated_collisions = _unique_name_map(generated_options)
    matched_ids: set[str] = set()
    reconciled: list[dict[str, Any]] = []
    for generated in generated_options:
        key = canonical_match_key(generated.get("name"))
        prior = existing_by_name.get(key) if key not in generated_collisions and key not in existing_collisions else None
        if prior is None:
            option_id = str(uuid.uuid4())
            reconciled.append({
                "id": option_id,
                **{field: copy.deepcopy(generated.get(field, [] if field in {"dependencies", "overlaps_feature_ids"} else "")) for field in OPTION_FIELDS},
                "selection_state": "undecided",
            })
            if key in generated_collisions or key in existing_collisions:
                diff["unresolved_matches"].append({"entity_type": "option", "name": generated.get("name", ""), "reason": "ambiguous_canonical_name"})
            continue
        option_id = str(prior["id"])
        matched_ids.add(option_id)
        option = {"id": option_id}
        for field in OPTION_FIELDS:
            generated_value = generated.get(field, [] if field in {"dependencies", "overlaps_feature_ids"} else "")
            path = f"option:{option_id}.{field}"
            option[field] = _owned_value(ownership, path, prior.get(field), generated_value)
        option["selection_state"] = copy.deepcopy(prior.get("selection_state", "undecided"))
        diff["id_matches"].append({"entity_type": "option", "id": option_id, "match_key": key})
        reconciled.append(option)
    for prior in existing:
        option_id = str(prior.get("id", ""))
        if option_id not in matched_ids and f"option:{option_id}.__entity__" in ownership:
            reconciled.append(copy.deepcopy(prior))
    return reconciled


def reconcile_generated_candidate(
    active_payload: dict[str, Any] | None,
    generated_payload: dict[str, Any],
    ownership: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Assign code-owned IDs, preserve human ownership, and produce a structured diff."""
    prior = copy.deepcopy(active_payload or {})
    ownership = copy.deepcopy(ownership or {})
    diff = empty_diff()
    candidate = {
        "feature_intent": _owned_value(ownership, "feature_intent", prior.get("feature_intent", ""), generated_payload.get("feature_intent", "")),
        "expansion_groups": [],
        "overlap_review": _owned_value(ownership, "overlap_review", prior.get("overlap_review", []), generated_payload.get("overlap_review", [])),
        "open_questions": _owned_value(ownership, "open_questions", prior.get("open_questions", []), generated_payload.get("open_questions", [])),
    }
    existing_groups = [dict(item) for item in prior.get("expansion_groups", [])]
    existing_by_name, existing_collisions = _unique_name_map(existing_groups)
    generated_groups = [dict(item) for item in generated_payload.get("expansion_groups", [])]
    _, generated_collisions = _unique_name_map(generated_groups)
    matched_ids: set[str] = set()
    for generated in generated_groups:
        key = canonical_match_key(generated.get("name"))
        active_group = existing_by_name.get(key) if key not in generated_collisions and key not in existing_collisions else None
        if active_group is None:
            group_id = str(uuid.uuid4())
            group = {
                "id": group_id,
                "name": generated.get("name", ""),
                "description": generated.get("description", ""),
                "options": [],
            }
            for option in generated.get("options", []):
                group["options"].append({
                    "id": str(uuid.uuid4()),
                    **{field: copy.deepcopy(option.get(field, [] if field in {"dependencies", "overlaps_feature_ids"} else "")) for field in OPTION_FIELDS},
                    "selection_state": "undecided",
                })
            candidate["expansion_groups"].append(group)
            if key in generated_collisions or key in existing_collisions:
                diff["unresolved_matches"].append({"entity_type": "group", "name": generated.get("name", ""), "reason": "ambiguous_canonical_name"})
            continue
        group_id = str(active_group["id"])
        matched_ids.add(group_id)
        group = {"id": group_id}
        for field in GROUP_FIELDS:
            group[field] = _owned_value(ownership, f"group:{group_id}.{field}", active_group.get(field, ""), generated.get(field, ""))
        group["options"] = _reconcile_options(active_group, generated, ownership, diff)
        diff["id_matches"].append({"entity_type": "group", "id": group_id, "match_key": key})
        candidate["expansion_groups"].append(group)
    for group in existing_groups:
        group_id = str(group.get("id", ""))
        if group_id not in matched_ids and f"group:{group_id}.__entity__" in ownership:
            candidate["expansion_groups"].append(copy.deepcopy(group))
    classified = build_structured_diff(prior, candidate)
    for key in ("added", "removed", "modified", "unchanged"):
        diff[key] = classified[key]
    for group in candidate["expansion_groups"]:
        for option in group.get("options", []):
            ownership[f"option:{option['id']}.selection_state"] = "human"
    return candidate, diff, ownership


def normalize_human_groups(
    active_groups: list[dict[str, Any]], submitted_groups: list[dict[str, Any]], ownership: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Accept only known IDs from edits and assign application IDs to new nested entities."""
    known_groups = {str(group.get("id")): group for group in active_groups}
    result: list[dict[str, Any]] = []
    for submitted in submitted_groups:
        prior_group = known_groups.get(str(submitted.get("id", "")))
        group_id = str(prior_group.get("id")) if prior_group else str(uuid.uuid4())
        group = {"id": group_id, "name": submitted.get("name", ""), "description": submitted.get("description", ""), "options": []}
        if prior_group is None:
            ownership[f"group:{group_id}.__entity__"] = "human"
        known_options = {str(option.get("id")): option for option in (prior_group or {}).get("options", [])}
        for submitted_option in submitted.get("options", []):
            prior_option = known_options.get(str(submitted_option.get("id", "")))
            option_id = str(prior_option.get("id")) if prior_option else str(uuid.uuid4())
            option = {"id": option_id, **{field: copy.deepcopy(submitted_option.get(field, [] if field in {"dependencies", "overlaps_feature_ids"} else "")) for field in OPTION_FIELDS}}
            if prior_option is None:
                ownership[f"option:{option_id}.__entity__"] = "human"
            group["options"].append(option)
        result.append(group)
    return result, ownership


def mark_human_owned_changes(before: dict[str, Any], after: dict[str, Any], ownership: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record stable field paths for every explicit human edit in a new active revision."""
    owned = copy.deepcopy(ownership or {})
    for section in ("feature_intent", "overlap_review", "open_questions"):
        if before.get(section) != after.get(section):
            owned[section] = "human"
    before_groups = {str(item.get("id")): item for item in before.get("expansion_groups", [])}
    for group in after.get("expansion_groups", []):
        group_id = str(group.get("id", ""))
        prior_group = before_groups.get(group_id)
        if prior_group is None:
            owned[f"group:{group_id}.__entity__"] = "human"
        for field in GROUP_FIELDS:
            if prior_group is None or prior_group.get(field) != group.get(field):
                owned[f"group:{group_id}.{field}"] = "human"
        prior_options = {str(item.get("id")): item for item in (prior_group or {}).get("options", [])}
        for option in group.get("options", []):
            option_id = str(option.get("id", ""))
            prior_option = prior_options.get(option_id)
            if prior_option is None:
                owned[f"option:{option_id}.__entity__"] = "human"
            for field in OPTION_FIELDS:
                if field == "selection_state" or prior_option is None or prior_option.get(field) != option.get(field):
                    owned[f"option:{option_id}.{field}"] = "human"
    return owned


def build_structured_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Classify all top-level, group, and option changes without dropping removals."""
    diff = empty_diff()
    for section in ("feature_intent", "overlap_review", "open_questions"):
        entry = {"entity_type": "section", "id": section, "before": copy.deepcopy(before.get(section)), "after": copy.deepcopy(after.get(section))}
        diff["unchanged" if entry["before"] == entry["after"] else "modified"].append(entry)
    before_groups = {str(item.get("id")): item for item in before.get("expansion_groups", [])}
    after_groups = {str(item.get("id")): item for item in after.get("expansion_groups", [])}
    for group_id in sorted(before_groups.keys() | after_groups.keys()):
        prior, current = before_groups.get(group_id), after_groups.get(group_id)
        if prior is None:
            diff["added"].append({"entity_type": "group", "id": group_id, "after": copy.deepcopy(current)})
            continue
        if current is None:
            diff["removed"].append({"entity_type": "group", "id": group_id, "before": copy.deepcopy(prior)})
            continue
        changes = {field: {"before": copy.deepcopy(prior.get(field)), "after": copy.deepcopy(current.get(field))} for field in GROUP_FIELDS if prior.get(field) != current.get(field)}
        diff["modified" if changes else "unchanged"].append({"entity_type": "group", "id": group_id, "fields": changes})
        before_options = {str(item.get("id")): item for item in prior.get("options", [])}
        after_options = {str(item.get("id")): item for item in current.get("options", [])}
        for option_id in sorted(before_options.keys() | after_options.keys()):
            old_option, new_option = before_options.get(option_id), after_options.get(option_id)
            if old_option is None:
                diff["added"].append({"entity_type": "option", "id": option_id, "group_id": group_id, "after": copy.deepcopy(new_option)})
            elif new_option is None:
                diff["removed"].append({"entity_type": "option", "id": option_id, "group_id": group_id, "before": copy.deepcopy(old_option)})
            else:
                option_changes = {field: {"before": copy.deepcopy(old_option.get(field)), "after": copy.deepcopy(new_option.get(field))} for field in OPTION_FIELDS if old_option.get(field) != new_option.get(field)}
                diff["modified" if option_changes else "unchanged"].append({"entity_type": "option", "id": option_id, "group_id": group_id, "fields": option_changes})
    return diff


def merge_selected_sections(active: dict[str, Any], candidate: dict[str, Any], sections: list[str]) -> dict[str, Any]:
    """Create a partial-accept payload by copying only explicitly selected top-level sections."""
    invalid = sorted(set(sections) - set(TOP_LEVEL_SECTIONS))
    if invalid or not sections:
        raise ValueError(f"Select one or more valid Layer 3 sections: {', '.join(TOP_LEVEL_SECTIONS)}")
    merged = copy.deepcopy(active)
    for section in sections:
        merged[section] = copy.deepcopy(candidate[section])
    return merged
