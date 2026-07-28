from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from strata.layer1_territory_models import (
    LensCoverageAssessment,
    LensCoverageRecommendation,
    LensTerminalState,
)


DEFAULT_TEMPERATURE_SCHEDULE = (0.65, 0.8, 0.95, 1.05)
TERMINAL_LENS_STATES = frozenset(
    {
        LensTerminalState.SATURATED,
        LensTerminalState.COVERED_WITH_SUBORDINATE_TERRITORY,
        LensTerminalState.INTENTIONALLY_EXCLUDED,
        LensTerminalState.REQUIRES_HUMAN_DECISION,
        LensTerminalState.BLOCKED_BY_MODEL,
        LensTerminalState.BUDGET_EXHAUSTED,
        LensTerminalState.CANCELLED,
    }
)


@dataclass(frozen=True, slots=True)
class DivergencePolicy:
    """Application-owned controls for bounded independent lens attempts."""

    target_raw_candidates: int = 18
    minimum_raw_candidates: int = 12
    maximum_raw_candidates: int = 30
    temperature_schedule: tuple[float, ...] = DEFAULT_TEMPERATURE_SCHEDULE
    minimum_lens_adherence: int = 65
    minimum_useful_novelty: int = 45
    maximum_generic_repetition_rate: float = 0.35
    max_attempts_per_lens: int = 4
    model_call_timeout_seconds: int = 900
    divergence_max_output_tokens: int = 7000
    enable_adversarial_pass: bool = True
    architecture_views: tuple[str, ...] = (
        "coherent_core",
        "expansive_differentiation",
        "enterprise_completeness",
    )

    def __post_init__(self) -> None:
        """Validate policy bounds before any run persists them."""
        if not 1 <= self.minimum_raw_candidates <= self.target_raw_candidates:
            raise ValueError("Minimum candidate count must not exceed the target.")
        if not self.target_raw_candidates <= self.maximum_raw_candidates <= 30:
            raise ValueError("Candidate target must be within the configured maximum of 30.")
        if not self.temperature_schedule:
            raise ValueError("At least one temperature is required.")
        if self.max_attempts_per_lens < 1:
            raise ValueError("Each lens requires at least one bounded attempt.")
        if self.model_call_timeout_seconds < 1:
            raise ValueError("Layer 1 model-call timeout must be positive.")
        if not 256 <= self.divergence_max_output_tokens <= 16000:
            raise ValueError("Divergence output limit must be between 256 and 16000 tokens.")

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe policy snapshot frozen on the exploration run."""
        return {
            "target_raw_candidates": self.target_raw_candidates,
            "minimum_raw_candidates": self.minimum_raw_candidates,
            "maximum_raw_candidates": self.maximum_raw_candidates,
            "temperature_schedule": list(self.temperature_schedule),
            "minimum_lens_adherence": self.minimum_lens_adherence,
            "minimum_useful_novelty": self.minimum_useful_novelty,
            "maximum_generic_repetition_rate": self.maximum_generic_repetition_rate,
            "max_attempts_per_lens": self.max_attempts_per_lens,
            "model_call_timeout_seconds": self.model_call_timeout_seconds,
            "divergence_max_output_tokens": self.divergence_max_output_tokens,
            "enable_adversarial_pass": self.enable_adversarial_pass,
            "architecture_views": list(self.architecture_views),
        }


@dataclass(frozen=True, slots=True)
class ExplorationBudget:
    """Hard limits that produce honest incomplete states when exhausted."""

    max_model_calls: int = 40
    max_elapsed_seconds: int = 3600
    max_total_candidates: int = 900

    def as_dict(self) -> dict[str, int]:
        """Return a JSON-safe budget snapshot."""
        return {
            "max_model_calls": self.max_model_calls,
            "max_elapsed_seconds": self.max_elapsed_seconds,
            "max_total_candidates": self.max_total_candidates,
        }


@dataclass(frozen=True, slots=True)
class GlobalCompletionDecision:
    """Deterministic global stopping result with explicit unresolved work."""

    ready_for_synthesis: bool
    incomplete: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def next_temperature(
    *,
    policy: DivergencePolicy,
    attempt_number: int,
    assessment: LensCoverageAssessment | None,
    budget_remaining: bool,
) -> float | None:
    """Raise temperature only for unresolved low-novelty or repetitive lens output."""
    if not budget_remaining or attempt_number > policy.max_attempts_per_lens:
        return None
    current_index = min(attempt_number - 1, len(policy.temperature_schedule) - 1)
    current = policy.temperature_schedule[current_index]
    if assessment is None or not assessment.unresolved_discovery_item_ids:
        return current
    low_novelty = assessment.useful_novelty_score < policy.minimum_useful_novelty
    low_adherence = assessment.lens_adherence_score < policy.minimum_lens_adherence
    generic = (
        assessment.generic_repetition_rate
        > policy.maximum_generic_repetition_rate
    )
    if not (low_novelty or low_adherence or generic):
        return current
    next_index = min(current_index + 1, len(policy.temperature_schedule) - 1)
    return policy.temperature_schedule[next_index]


def lens_terminal_state(
    assessment: LensCoverageAssessment,
    *,
    attempts_exhausted: bool,
    budget_exhausted: bool,
) -> LensTerminalState | None:
    """Convert bounded evaluator advice into an application-owned lens state."""
    if budget_exhausted:
        return LensTerminalState.BUDGET_EXHAUSTED
    mapping = {
        LensCoverageRecommendation.MARK_SATURATED: LensTerminalState.SATURATED,
        LensCoverageRecommendation.COVERED_WITH_SUBORDINATE_TERRITORY:
            LensTerminalState.COVERED_WITH_SUBORDINATE_TERRITORY,
        LensCoverageRecommendation.REQUIRES_HUMAN_REVIEW:
            LensTerminalState.REQUIRES_HUMAN_DECISION,
        LensCoverageRecommendation.BLOCKED_BY_MODEL: LensTerminalState.BLOCKED_BY_MODEL,
        LensCoverageRecommendation.BUDGET_EXHAUSTED: LensTerminalState.BUDGET_EXHAUSTED,
    }
    terminal = mapping.get(assessment.recommendation)
    if terminal is not None:
        return terminal
    if attempts_exhausted:
        return LensTerminalState.REQUIRES_HUMAN_DECISION
    return None


def global_completion(
    *,
    required_lens_states: list[LensTerminalState],
    unresolved_high_severity_item_ids: list[str],
    required_actor_gaps: list[str],
    enterprise_obligation_gaps: list[str],
    undispositioned_candidate_count: int,
    adversarial_complete_or_skipped: bool,
    hard_budget_exhausted: bool,
) -> GlobalCompletionDecision:
    """Prevent a lens critic or hard budget from falsely claiming global saturation."""
    reasons: list[str] = []
    non_terminal = [state.value for state in required_lens_states if state not in TERMINAL_LENS_STATES]
    unresolved_lenses = [
        state.value
        for state in required_lens_states
        if state in {
            LensTerminalState.BLOCKED_BY_MODEL,
            LensTerminalState.BUDGET_EXHAUSTED,
            LensTerminalState.REQUIRES_HUMAN_DECISION,
        }
    ]
    if non_terminal:
        reasons.append(f"Required lenses remain active or pending: {non_terminal}")
    if unresolved_lenses:
        reasons.append(f"Required lenses need explicit human acceptance: {unresolved_lenses}")
    if unresolved_high_severity_item_ids:
        reasons.append("High-severity discovery risks remain unresolved.")
    if required_actor_gaps:
        reasons.append("Required actors lack meaningful territory or an exclusion.")
    if enterprise_obligation_gaps:
        reasons.append("Enterprise obligations remain unrouted.")
    if undispositioned_candidate_count:
        reasons.append("Candidates remain undispositioned.")
    if not adversarial_complete_or_skipped:
        reasons.append("Adversarial exploration is incomplete.")
    if hard_budget_exhausted:
        reasons.append("A hard exploration budget was exhausted.")
    return GlobalCompletionDecision(
        ready_for_synthesis=not reasons,
        incomplete=bool(reasons),
        reasons=tuple(reasons),
    )
