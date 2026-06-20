from __future__ import annotations

from dataclasses import dataclass

from specforge.models import Node


@dataclass(slots=True)
class IterativeGenerationSummary:
    """Common response envelope for exhaustive generation loops across layers."""

    created_nodes: list[Node]
    total_rounds: int
    duplicate_candidates: int
    filtered_candidates: int
    unique_family_count: int
    stop_reason: str
    per_round_new_counts: list[int]
    per_round_new_family_counts: list[int]
    final_coverage_summary: str
    final_novelty_score: int | None
    lenses_used: list[str]
    models_used: list[str]
    round_summaries: list[str]
    thinking_enabled: bool

