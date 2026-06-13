from __future__ import annotations

from rapidfuzz import fuzz

from specforge.models import Node


def detect_possible_duplicates(
    *,
    existing_nodes: list[Node],
    title: str,
    description: str | None,
    title_threshold: float = 85.0,
    description_threshold: float = 90.0,
) -> dict[str, str | float] | None:
    for node in existing_nodes:
        title_score = fuzz.ratio(title, node.title)
        description_score = 0.0
        if description and node.description:
            description_score = fuzz.ratio(description, node.description)
        if title_score >= title_threshold or description_score >= description_threshold:
            return {
                "duplicate_node_id": node.id,
                "duplicate_title": node.title,
                "title_score": round(title_score, 2),
                "description_score": round(description_score, 2),
            }
    return None
