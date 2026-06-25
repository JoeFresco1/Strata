from __future__ import annotations

from collections import defaultdict
from typing import Any

from strata.models import Node


def build_tree(nodes: list[Node]) -> list[dict[str, Any]]:
    by_parent: dict[str | None, list[Node]] = defaultdict(list)
    for node in nodes:
        by_parent[node.parent_id].append(node)
    for children in by_parent.values():
        children.sort(key=lambda item: (item.layer, item.priority is None, item.priority or 0, item.title.lower()))

    def _build(parent_id: str | None) -> list[dict[str, Any]]:
        branch: list[dict[str, Any]] = []
        for node in by_parent.get(parent_id, []):
            children = _build(node.id)
            branch.append(
                {
                    "id": node.id,
                    "parent_id": node.parent_id,
                    "title": node.title,
                    "description": node.description,
                    "layer": node.layer,
                    "node_type": node.node_type,
                    "status": node.status,
                    "priority": node.priority,
                    "json_payload": node.json_payload,
                    "child_count": len(children),
                    "children": children,
                }
            )
        return branch

    return _build(None)


def collect_approved_directions(nodes: list[Node]) -> list[str]:
    approved: list[str] = []
    for node in nodes:
        if node.status in {"kept", "prioritized"}:
            approved.append(node.title)
    return approved
