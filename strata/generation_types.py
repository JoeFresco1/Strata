from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from strata.models import Node


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


class Layer1SummaryResult(BaseModel):
    """JSON-safe terminal metadata for a Layer 1 generation workflow."""

    created_node_ids: list[str] = Field(default_factory=list)
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

    @classmethod
    def from_summary(cls, summary: IterativeGenerationSummary) -> "Layer1SummaryResult":
        """Project persisted nodes to stable IDs instead of embedding mutable domain objects."""
        return cls(
            created_node_ids=[node.id for node in summary.created_nodes],
            total_rounds=summary.total_rounds,
            duplicate_candidates=summary.duplicate_candidates,
            filtered_candidates=summary.filtered_candidates,
            unique_family_count=summary.unique_family_count,
            stop_reason=summary.stop_reason,
            per_round_new_counts=summary.per_round_new_counts,
            per_round_new_family_counts=summary.per_round_new_family_counts,
            final_coverage_summary=summary.final_coverage_summary,
            final_novelty_score=summary.final_novelty_score,
            lenses_used=summary.lenses_used,
            models_used=summary.models_used,
            round_summaries=summary.round_summaries,
            thinking_enabled=summary.thinking_enabled,
        )


class Layer1JobResult(BaseModel):
    """Typed, concise durable result for Layer 1 generation."""

    summary: Layer1SummaryResult
    research_jobs: list[dict[str, Any]] = Field(default_factory=list)

