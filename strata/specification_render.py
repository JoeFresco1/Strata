from __future__ import annotations

import json

from strata.specification_models import SpecificationManifestV1


RENDERER_VERSION = "specification-renderer.v1"


def render_specification_json(manifest: SpecificationManifestV1) -> str:
    """Render canonical JSON using only the supplied typed manifest."""
    return json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=True, sort_keys=True) + "\n"


def render_specification_markdown(manifest: SpecificationManifestV1) -> str:
    """Render a human handoff document using only the supplied typed manifest."""
    root = manifest.root_lineage
    lines = [
        f"# {manifest.project.get('name', 'Specification')}", "",
        f"Manifest: `{manifest.manifest_id}` (v{manifest.sequence_number}, {manifest.mode.value})", "",
        f"Source brief revision: `{root.get('brief_revision_id', '')}`", "",
        f"Source hash: `{root.get('content_hash', '')}`", "",
        f"Published: {root.get('published_at', '')}", "",
        "## Product Brief", "", str(root.get("payload", {}).get("product_idea", manifest.project.get("idea", ""))), "",
    ]
    problem = str(root.get("payload", {}).get("problem", ""))
    if problem:
        lines.extend(["### Problem", "", problem, ""])
    lines.extend(["## Pillars", ""])
    feature_by_pillar: dict[str, list[dict]] = {}
    for feature in manifest.layer2:
        feature_by_pillar.setdefault(str(feature["source_pillar_id"]), []).append(feature)
    expansions_by_feature = {str(item["canonical_payload"].get("feature_id", "")): item for item in manifest.layer3}
    for pillar in manifest.layer1:
        payload = pillar["canonical_payload"]
        lines.extend([f"### {payload.get('title', pillar['name'])}", "", str(payload.get("description", "")), ""])
        lines.extend([f"Review: {pillar.get('review_state', '')} · Freshness: {pillar.get('freshness_state', '')} · Revision: `{pillar.get('content_token', '')}`", ""])
        for feature in feature_by_pillar.get(str(pillar["logical_pillar_id"]), []):
            feature_payload = feature["canonical_payload"]
            lines.extend([f"#### {feature_payload.get('canonical_name', '')}", "", str(feature_payload.get("description", "")), ""])
            lines.extend([f"Review: {feature.get('review_state', '')} · Freshness: {feature.get('freshness_state', '')} · Revision: `{feature.get('content_token', '')}`", ""])
            expansion = expansions_by_feature.get(str(feature["logical_feature_id"]))
            if not expansion:
                continue
            lines.extend([f"##### Layer 3 expansion (revision {expansion.get('revision_number', '')})", ""])
            lines.extend([f"Review: {expansion.get('review_state', '')} · Freshness: {expansion.get('freshness_state', '')} · Revision ID: `{expansion.get('active_revision_id', '')}`", ""])
            intent = expansion.get("feature_intent")
            if intent:
                lines.extend([f"Intent: {intent}", ""])
            for group in expansion.get("groups", []):
                lines.append(f"- **{group.get('name', group.get('title', 'Options'))}**")
                for option in group.get("options", []):
                    selection = option.get("selection_state", option.get("selected", "undecided"))
                    lines.append(f"  - [{selection}] {option.get('name', option.get('title', 'Option'))}")
            if expansion.get("overlap_review"):
                lines.extend(["", "Overlap review:"])
                lines.extend(f"- {json.dumps(item, sort_keys=True, ensure_ascii=True) if isinstance(item, dict) else item}" for item in expansion["overlap_review"])
            if expansion.get("open_questions"):
                lines.extend(["", "Open questions:"])
                lines.extend(f"- {item}" for item in expansion["open_questions"])
            lines.append("")
    if manifest.relationships:
        lines.extend(["## Relationships", ""])
        for relation in manifest.relationships:
            source_id = relation.get("source_id", relation.get("source_feature_id", ""))
            target_id = relation.get("target_id", relation.get("target_feature_id", ""))
            lines.append(f"- `{source_id}` {relation['relationship_type']} `{target_id}`")
        lines.append("")
    lines.extend(["## Validation", "", f"Exportable: **{'yes' if manifest.exportable else 'no'}**"])
    for issue in manifest.issues:
        lines.append(f"- {issue.severity.upper()} `{issue.code}`: {issue.message}")
    return "\n".join(lines).rstrip() + "\n"
