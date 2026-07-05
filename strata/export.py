from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from strata.models import Node, Project
from strata.tree import build_tree


def _markdown_branch(branches: list[dict[str, Any]], depth: int = 0) -> list[str]:
    lines: list[str] = []
    for branch in branches:
        indent = "  " * depth
        status = f" [{branch['status']}]" if branch["status"] else ""
        priority = f" (priority {branch['priority']})" if branch["priority"] is not None else ""
        lines.append(f"{indent}- {branch['title']} ({branch['node_type']}){status}{priority}")
        if branch["description"]:
            lines.append(f"{indent}  - {branch['description']}")
        payload = branch.get("json_payload") or {}
        if branch["node_type"] == "spec" and payload:
            overview = payload.get("overview")
            if overview:
                lines.append(f"{indent}  - Overview: {overview}")
        lines.extend(_markdown_branch(branch["children"], depth + 1))
    return lines


def export_project(project: Project, nodes: list[Node], exports_dir: Path) -> tuple[Path, Path]:
    exports_dir.mkdir(parents=True, exist_ok=True)
    tree = build_tree(nodes)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in project.name).strip("-")
    markdown_path = exports_dir / f"{slug or project.id}.md"
    json_path = exports_dir / f"{slug or project.id}.json"

    markdown = [
        f"# {project.name}",
        "",
        "## Product Idea",
        project.idea,
        "",
        "## Feature Tree",
        *_markdown_branch(tree),
    ]
    markdown_path.write_text("\n".join(markdown), encoding="utf-8")

    payload = {
        "project": project.model_dump(mode="json"),
        "tree": tree,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return markdown_path, json_path


def export_layer2_markdown(project: Project, layer2_graph: dict[str, Any], exports_dir: Path) -> Path:
    """Export the Layer 2 workbench graph as a human-readable Markdown document."""
    exports_dir.mkdir(parents=True, exist_ok=True)
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in project.name).strip("-")
    markdown_path = exports_dir / f"{slug or project.id}-layer2.md"
    rows = layer2_graph.get("workbench", {}).get("rows", layer2_graph.get("features", []))
    pillars = {item.get("id"): item for item in layer2_graph.get("pillars", [])}
    by_owner: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_owner.setdefault(row.get("owner_pillar_id", "unassigned"), []).append(row)

    lines = [
        f"# {project.name} Layer 2",
        "",
        "## Summary",
        f"- Features: {len(rows)}",
        f"- Relationships: {len(layer2_graph.get('relationships', []))}",
        f"- Shared concerns: {len(layer2_graph.get('shared_concerns', []))}",
        f"- Coverage rows: {len(layer2_graph.get('coverage_matrix', []))}",
        "",
        "## Features By Pillar",
    ]
    for owner_id, features in by_owner.items():
        owner_name = pillars.get(owner_id, {}).get("title", owner_id if owner_id != "unassigned" else "Unassigned")
        lines.extend(["", f"### {owner_name}"])
        for feature in features:
            blockers = ", ".join(feature.get("readiness_blockers", [])) or "none"
            evidence_count = feature.get("evidence_count", 0)
            lines.extend(
                [
                    f"- **{feature.get('canonical_name')}** [{feature.get('status')}]",
                    f"  - Description: {feature.get('description')}",
                    f"  - Type: {feature.get('feature_type')} | Granularity: {feature.get('granularity_class')}",
                    f"  - Scores: fit {feature.get('pillar_fit_score')}/100, distinct {feature.get('distinctiveness_score')}/100, strategic {feature.get('strategic_value_score')}/100, leakage {feature.get('implementation_leakage_score')}/100",
                    f"  - Coverage family: {feature.get('coverage_family') or 'unset'}",
                    f"  - Layer 3 ready: {feature.get('layer3_ready')} | blockers: {blockers}",
                    f"  - Evidence entries: {evidence_count} | competitor coverage: {feature.get('competitor_coverage_score', 0)}%",
                ]
            )

    lines.extend(["", "## Shared Concerns"])
    for concern in layer2_graph.get("shared_concerns", []):
        lines.append(
            f"- **{concern.get('name')}** ({concern.get('concern_type')}) [{concern.get('status')}]: "
            f"{len(concern.get('connected_feature_ids', []))} connected features"
        )

    lines.extend(["", "## Coverage Matrix"])
    for row in layer2_graph.get("coverage_matrix", []):
        evidence = ", ".join(row.get("evidence_feature_ids", [])) or "none"
        missing = ", ".join(row.get("missing_examples", [])) or "none"
        lines.append(f"- {row.get('family_name')} [{row.get('status')}]: evidence {evidence}; missing {missing}")

    lines.extend(["", "## Competitive Evidence"])
    for evidence in layer2_graph.get("feature_evidence", []):
        lines.append(
            f"- {evidence.get('competitor_name')} -> {evidence.get('feature_id')} "
            f"[{evidence.get('coverage_status')}, confidence {evidence.get('confidence')}/100]"
        )
        if evidence.get("source_url"):
            lines.append(f"  - Source: {evidence.get('source_url')}")
        if evidence.get("evidence_snippet"):
            lines.append(f"  - Evidence: {evidence.get('evidence_snippet')}")

    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return markdown_path


def export_layer3_feature_expansions(
    project: Project,
    brief: dict[str, Any],
    layer2_graph: dict[str, Any],
    layer3_snapshot: dict[str, Any],
    exports_dir: Path,
) -> Path:
    """Write approved Layer 3 Feature Expansions with complete Layer 0/1/2 lineage."""
    exports_dir.mkdir(parents=True, exist_ok=True)
    approved_expansions = [
        expansion for expansion in layer3_snapshot.get("expansions", [])
        if expansion.get("review_state") == "approved"
    ]
    pillars = {item.get("id"): item for item in layer2_graph.get("pillars", [])}
    features = {item.get("id"): item for item in layer2_graph.get("features", [])}
    manifest_expansions = []
    for expansion in approved_expansions:
        feature = features.get(expansion.get("feature_id"), {})
        pillar = pillars.get(expansion.get("parent_pillar_id"), {})
        manifest_expansions.append({
            "expansion": expansion,
            "lineage": {
                "layer0": {
                    "brief_id": brief.get("id"),
                    "product_idea": brief.get("product_idea", project.idea),
                    "brief_status": brief.get("status"),
                },
                "layer1": {
                    "pillar_id": expansion.get("parent_pillar_id"),
                    "title": pillar.get("title", expansion.get("parent_pillar_title")),
                    "description": pillar.get("description", ""),
                },
                "layer2": {
                    "feature_id": expansion.get("feature_id"),
                    "canonical_name": feature.get("canonical_name", expansion.get("feature_name")),
                    "description": feature.get("description", expansion.get("feature_description")),
                    "candidate_source_ids": feature.get("candidate_source_ids", []),
                    "status": feature.get("status"),
                },
            },
        })
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in project.name).strip("-")
    output_path = exports_dir / f"{slug or project.id}-layer3-feature-expansions.json"
    output_path.write_text(
        json.dumps({
            "manifest_version": "1.0",
            "artifact_type": "strata_layer3_feature_expansion",
            "project": project.model_dump(mode="json"),
            "approved_expansion_count": len(manifest_expansions),
            "feature_expansions": manifest_expansions,
        }, indent=2),
        encoding="utf-8",
    )
    return output_path
