from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from specforge.models import Node, Project
from specforge.tree import build_tree


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
