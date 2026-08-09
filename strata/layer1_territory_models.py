from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TerritoryRunStatus(StrEnum):
    """Lifecycle states for one deterministic Layer 1 exploration run."""

    RUNNING = "running"
    INCOMPLETE = "incomplete"
    READY_FOR_SYNTHESIS = "ready_for_synthesis"
    READY_FOR_HUMAN_REVIEW = "ready_for_human_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TerritoryRunStage(StrEnum):
    """Checkpointed stages that never imply later work already succeeded."""

    DIVERGENCE = "divergence"
    NORMALIZATION = "normalization"
    CLASSIFICATION = "classification"
    LENS_COVERAGE = "lens_coverage"
    ADVERSARIAL = "adversarial"
    SYNTHESIS = "synthesis"
    GLOBAL_REVIEW = "global_review"
    HUMAN_REVIEW = "human_review"


class LensTerminalState(StrEnum):
    """Application-owned lens states, including honest incomplete outcomes."""

    PENDING = "pending"
    ACTIVE = "active"
    SATURATED = "saturated"
    COVERED_WITH_SUBORDINATE_TERRITORY = "covered_with_subordinate_territory"
    INTENTIONALLY_EXCLUDED = "intentionally_excluded"
    REQUIRES_HUMAN_DECISION = "requires_human_decision"
    BLOCKED_BY_MODEL = "blocked_by_model"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"


class LensCoverageRecommendation(StrEnum):
    """Bounded evaluator advice interpreted by the application state machine."""

    CONTINUE_SAME_CONFIGURATION = "continue_same_configuration"
    RETRY_WITH_STRONGER_EXCLUSIONS = "retry_with_stronger_exclusions"
    RETRY_WITH_HIGHER_TEMPERATURE = "retry_with_higher_temperature"
    RETRY_WITH_ALTERNATE_PROMPT = "retry_with_alternate_prompt"
    MARK_SATURATED = "mark_saturated"
    COVERED_WITH_SUBORDINATE_TERRITORY = "covered_with_subordinate_territory"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"
    BLOCKED_BY_MODEL = "blocked_by_model"
    BUDGET_EXHAUSTED = "budget_exhausted"


class TerritoryDestination(StrEnum):
    """Current routing destination for a preserved territory candidate."""

    STANDALONE_PILLAR_CANDIDATE = "standalone_pillar_candidate"
    CROSS_CUTTING_PRODUCT_CONCERN = "cross_cutting_product_concern"
    ENTERPRISE_PLATFORM_OBLIGATION = "enterprise_platform_obligation"
    PILLAR_EXTENSION = "pillar_extension"
    LAYER_2_FEATURE_FAMILY = "layer_2_feature_family"
    ACTOR_WORKSPACE = "actor_workspace"
    OPERATIONAL_CAPABILITY = "operational_capability"
    COMMERCIAL_CAPABILITY = "commercial_capability"
    DEVELOPER_PLATFORM_CAPABILITY = "developer_platform_capability"
    WORKFLOW_FAMILY = "workflow_family"
    DECISION_MECHANISM = "decision_mechanism"
    DATA_RESPONSIBILITY = "data_responsibility"
    GOVERNANCE_MECHANISM = "governance_mechanism"
    STRATEGIC_OPPORTUNITY = "strategic_opportunity"
    DEFERRED_HUMAN_REVIEW = "deferred_human_review"
    DUPLICATE = "duplicate"
    OUT_OF_SCOPE = "out_of_scope"
    REJECTED_QUALITY = "rejected_quality"
    REJECTED_GENERIC_REPETITION = "rejected_generic_repetition"
    REJECTED_UNSUPPORTED = "rejected_unsupported"
    REJECTED_BIZARRE = "rejected_bizarre"


class CandidateDispositionSource(StrEnum):
    """Authority responsible for one append-only candidate disposition."""

    MODEL = "model"
    DETERMINISTIC = "deterministic"
    HUMAN = "human"
    SYSTEM = "system"


class AttemptStatus(StrEnum):
    """Checkpoint status for one independent model attempt."""

    QUEUED = "queued"
    RUNNING = "running"
    RAW_RECEIVED = "raw_received"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    SCHEMA_FAILED = "schema_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ClosedTerritoryScope(StrEnum):
    """Persistence boundary for a human-inspectable semantic exclusion."""

    RUN = "run"
    PROJECT = "project"


class PolicyHumanState(StrEnum):
    """Human authority state for exclusions and anti-generic patterns."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ArchitectureKind(StrEnum):
    """Supported immutable Layer 1 architecture perspectives."""

    COHERENT_CORE = "coherent_core"
    EXPANSIVE_DIFFERENTIATION = "expansive_differentiation"
    ENTERPRISE_COMPLETENESS = "enterprise_completeness"
    HUMAN_HYBRID = "human_hybrid"


class ArchitectureState(StrEnum):
    """Review state stored separately from immutable architecture content."""

    CANDIDATE = "candidate"
    SELECTED = "selected"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ModelRuntimeProvenance(BaseModel):
    """Exact requested and resolved inference facts for one model call."""

    requested_profile_id: str = ""
    resolved_profile_id: str = ""
    provider: str = ""
    endpoint: str = ""
    model_alias: str = ""
    exact_model_identifier: str = ""
    model_file_hash: str = ""
    runtime_build: str = ""
    prompt_key: str
    prompt_version: str
    effective_temperature: float = Field(ge=0, le=2)
    seed: int | None = None
    context_limit: int | None = None
    output_limit: int | None = None
    timeout_seconds: int | None = None
    request_id: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    elapsed_seconds: float | None = None


class Layer1ExpansionRun(BaseModel):
    """Canonical exploration run tied to exact published upstream revisions."""

    id: str
    project_id: str
    source_brief_revision_id: str
    source_discovery_revision_id: str
    status: TerritoryRunStatus = TerritoryRunStatus.RUNNING
    stage: TerritoryRunStage = TerritoryRunStage.DIVERGENCE
    config: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    incomplete_reason: str = ""
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class Layer1LensExecution(BaseModel):
    """Durable lens work item ordered by application-owned priority."""

    id: str
    run_id: str
    project_id: str
    source_discovery_revision_id: str
    source_lens_id: str
    source_discovery_item_ids: list[str] = Field(default_factory=list)
    title: str
    instruction: str
    required: bool = False
    discovery_order: int = 0
    risk_priority: int = 0
    relevance_score: float = Field(ge=0, le=1, default=0.5)
    missing_coverage_priority: int = 0
    human_priority: int = 0
    human_order_position: int | None = None
    state: LensTerminalState = LensTerminalState.PENDING
    attempt_count: int = 0
    max_attempts: int = Field(ge=1, default=3)
    created_at: datetime
    updated_at: datetime


class Layer1LensAttempt(BaseModel):
    """Frozen settings and checkpoint state for one context-independent call."""

    id: str
    run_id: str
    lens_execution_id: str
    project_id: str
    attempt_number: int = Field(ge=1)
    attempt_kind: str = "divergence"
    status: AttemptStatus = AttemptStatus.QUEUED
    settings: dict[str, Any] = Field(default_factory=dict)
    source_projection: dict[str, Any] = Field(default_factory=dict)
    closed_territory_revision_ids: list[str] = Field(default_factory=list)
    anti_generic_pattern_revision_ids: list[str] = Field(default_factory=list)
    prompt_key: str
    prompt_version: str
    prompt_projection_hash: str
    raw_response: str = ""
    parsed_candidate_count: int = 0
    error_type: str = ""
    error_message: str = ""
    runtime_provenance: ModelRuntimeProvenance
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ClosedTerritory(BaseModel):
    """One append-only revision of a deterministic or human exclusion."""

    id: str
    logical_id: str
    project_id: str
    run_id: str | None = None
    revision_number: int = Field(ge=1)
    title: str
    description: str = ""
    semantic_examples: list[str] = Field(default_factory=list)
    source_family_ids: list[str] = Field(default_factory=list)
    source: str
    scope: ClosedTerritoryScope
    active: bool = True
    human_state: PolicyHumanState = PolicyHumanState.PENDING
    reason: str = ""
    actor: str = ""
    command_id: str = ""
    created_at: datetime


class AntiGenericPattern(BaseModel):
    """Versioned pattern that identifies repeated non-lens-specific output."""

    id: str
    logical_id: str
    project_id: str
    revision_number: int = Field(ge=1)
    title: str
    description: str = ""
    semantic_examples: list[str] = Field(default_factory=list)
    source_run_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    scope: str = "project"
    active: bool = True
    human_state: PolicyHumanState = PolicyHumanState.PENDING
    actor: str = ""
    command_id: str = ""
    created_at: datetime


class ProductTerritoryCandidate(BaseModel):
    """Immutable raw territory emitted before any normalization or judgment."""

    id: str
    project_id: str
    expansion_run_id: str
    lens_execution_id: str
    lens_attempt_id: str
    source_discovery_revision_id: str
    source_lens_id: str
    source_discovery_item_ids: list[str] = Field(default_factory=list)
    title: str
    description: str
    concrete_product_behavior: str = ""
    user_or_operator_value: str = ""
    affected_actor_ids: list[str] = Field(default_factory=list)
    affected_lifecycle_stage_ids: list[str] = Field(default_factory=list)
    affected_domain_ids: list[str] = Field(default_factory=list)
    affected_enterprise_obligation_ids: list[str] = Field(default_factory=list)
    affected_coverage_risk_ids: list[str] = Field(default_factory=list)
    lens_specific_mechanism: str = ""
    non_generic_rationale: str = ""
    proposed_destination: TerritoryDestination = TerritoryDestination.DEFERRED_HUMAN_REVIEW
    standalone_pillar_potential: float = Field(ge=0, le=1, default=0.5)
    novelty_claim: str = ""
    feasibility_note: str = ""
    confidence: float = Field(ge=0, le=1, default=0.5)
    weakly_attributable: bool = False
    raw_ordinal: int = Field(ge=0)
    raw_model_payload: dict[str, Any] = Field(default_factory=dict)
    runtime_provenance: ModelRuntimeProvenance
    created_at: datetime


class NormalizedTerritoryRepresentation(BaseModel):
    """Append-only normalized projection retaining exact raw-candidate lineage."""

    id: str
    candidate_id: str
    run_id: str
    project_id: str
    normalization_attempt_id: str
    normalized_title: str
    normalized_description: str
    semantic_family: str = ""
    cluster_id: str | None = None
    canonical_terminology: str = ""
    duplicate_of_candidate_id: str | None = None
    merge_recommendation: str = ""
    abstraction_level_recommendation: str = ""
    destination_recommendation: TerritoryDestination
    normalization_dropped: bool = False
    drop_reason: str = ""
    repair_attempt: int = 0
    human_review_eligible: bool = True
    created_at: datetime


class TerritoryAssessment(BaseModel):
    """Model or deterministic assessment that cannot erase the raw candidate."""

    id: str
    candidate_id: str
    run_id: str
    project_id: str
    assessor: CandidateDispositionSource
    destination_recommendation: TerritoryDestination
    lens_adherence_score: int = Field(ge=0, le=100)
    useful_novelty_score: int = Field(ge=0, le=100)
    generic_repetition_score: int = Field(ge=0, le=100)
    quality_score: int = Field(ge=0, le=100)
    attribution_score: int = Field(ge=0, le=100)
    closed_territory_violation_ids: list[str] = Field(default_factory=list)
    anti_generic_pattern_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    created_at: datetime


class CandidateDisposition(BaseModel):
    """Append-only authoritative routing decision for a preserved candidate."""

    id: str
    candidate_id: str
    run_id: str
    project_id: str
    sequence_number: int = Field(ge=1)
    destination: TerritoryDestination
    source: CandidateDispositionSource
    reason: str = ""
    supersedes_disposition_id: str | None = None
    target_artifact_id: str | None = None
    actor: str = ""
    command_id: str = ""
    created_at: datetime


class TerritoryCluster(BaseModel):
    """Semantic family assembled only after the complete raw reservoir exists."""

    id: str
    run_id: str
    project_id: str
    title: str
    description: str = ""
    semantic_family: str
    candidate_ids: list[str] = Field(default_factory=list)
    representative_candidate_id: str | None = None
    destination_summary: dict[str, int] = Field(default_factory=dict)
    created_at: datetime


class LensCoverageAssessment(BaseModel):
    """Lens-local coverage artifact kept separate from architecture criticism."""

    id: str
    run_id: str
    lens_execution_id: str
    project_id: str
    attempt_number: int = Field(ge=1)
    addressed_discovery_item_ids: list[str] = Field(default_factory=list)
    unresolved_discovery_item_ids: list[str] = Field(default_factory=list)
    high_severity_unresolved_item_ids: list[str] = Field(default_factory=list)
    lens_adherence_score: int = Field(ge=0, le=100)
    useful_novelty_score: int = Field(ge=0, le=100)
    generic_repetition_rate: float = Field(ge=0, le=1)
    duplicate_rate: float = Field(ge=0, le=1)
    weak_attribution_rate: float = Field(ge=0, le=1)
    recommendation: LensCoverageRecommendation
    rationale: str = ""
    created_at: datetime


class AdversarialScenarioCandidate(BaseModel):
    """Scenario-specific blind spot linked into the same raw territory ledger."""

    id: str
    candidate_id: str
    run_id: str
    project_id: str
    role: str
    scenario: str
    affected_actor_id: str = ""
    insufficient_territory_ids: list[str] = Field(default_factory=list)
    concrete_failure: str
    missing_product_territory: str
    distinctness_rationale: str
    proposed_destination: TerritoryDestination
    severity: str
    source_discovery_item_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class Layer1CoverageState(BaseModel):
    """Reproducible global discovery and semantic breadth metrics."""

    id: str
    run_id: str
    project_id: str
    version: int = Field(ge=1)
    discovery_coverage: dict[str, Any] = Field(default_factory=dict)
    territory_diversity: dict[str, Any] = Field(default_factory=dict)
    lens_adherence: dict[str, Any] = Field(default_factory=dict)
    candidate_integrity: dict[str, Any] = Field(default_factory=dict)
    architecture_breadth: dict[str, Any] = Field(default_factory=dict)
    runtime_cost: dict[str, Any] = Field(default_factory=dict)
    unresolved_high_severity_item_ids: list[str] = Field(default_factory=list)
    ready_for_synthesis: bool = False
    incomplete_reasons: list[str] = Field(default_factory=list)
    created_at: datetime


class GlobalArchitectureAssessment(BaseModel):
    """Architecture-level critic kept separate from lens-local coverage."""

    id: str
    run_id: str
    project_id: str
    architecture_candidate_ids: list[str] = Field(default_factory=list)
    product_domain_coverage_score: int = Field(ge=0, le=100)
    actor_coverage_score: int = Field(ge=0, le=100)
    lifecycle_coverage_score: int = Field(ge=0, le=100)
    enterprise_obligation_coverage_score: int = Field(ge=0, le=100)
    differentiation_score: int = Field(ge=0, le=100)
    coherence_score: int = Field(ge=0, le=100)
    overbroad_pillar_ids: list[str] = Field(default_factory=list)
    fragmented_pillar_ids: list[str] = Field(default_factory=list)
    hidden_territory_candidate_ids: list[str] = Field(default_factory=list)
    unresolved_high_severity_risk_ids: list[str] = Field(default_factory=list)
    needs_additional_exploration_lens: bool = False
    recommended_lens: str = ""
    ready_for_human_review: bool = False
    rationale: str = ""
    runtime_provenance: ModelRuntimeProvenance
    created_at: datetime


class PillarTerritoryMapping(BaseModel):
    """Traceability from one synthesized pillar to accepted territory."""

    id: str
    architecture_candidate_id: str
    pillar_id: str
    territory_candidate_ids: list[str] = Field(default_factory=list)
    source_discovery_item_ids: list[str] = Field(default_factory=list)
    covered_actor_ids: list[str] = Field(default_factory=list)
    covered_domain_ids: list[str] = Field(default_factory=list)
    covered_enterprise_obligation_ids: list[str] = Field(default_factory=list)
    covered_risk_ids: list[str] = Field(default_factory=list)
    cross_cutting_concern_ids: list[str] = Field(default_factory=list)
    subordinate_feature_family_ids: list[str] = Field(default_factory=list)


class PillarArchitectureCandidate(BaseModel):
    """Immutable candidate architecture created only after exploration."""

    id: str
    run_id: str
    project_id: str
    kind: ArchitectureKind
    version: int = Field(ge=1)
    title: str
    rationale: str = ""
    pillars: list[dict[str, Any]] = Field(default_factory=list)
    mappings: list[PillarTerritoryMapping] = Field(default_factory=list)
    significant_non_pillar_territory_ids: list[str] = Field(default_factory=list)
    unresolved_risk_ids: list[str] = Field(default_factory=list)
    content_hash: str
    runtime_provenance: ModelRuntimeProvenance
    created_at: datetime


class Layer1ArchitectureApplication(BaseModel):
    """Auditable application of one selected architecture to the live Layer 1 map."""

    id: str
    project_id: str
    run_id: str
    architecture_candidate_id: str
    selection_event_id: str
    sequence_number: int = Field(ge=1)
    state: str
    applied_pillar_ids: list[str] = Field(default_factory=list)
    superseded_pillar_ids: list[str] = Field(default_factory=list)
    retained_territory_candidate_ids: list[str] = Field(default_factory=list)
    architecture_content_hash: str
    actor: str
    command_id: str
    note: str = ""
    created_at: datetime
    superseded_at: datetime | None = None


class Layer1SynthesisResult(BaseModel):
    """One synthesis invocation retaining multiple immutable options."""

    id: str
    run_id: str
    project_id: str
    source_coverage_state_id: str
    architecture_candidate_ids: list[str] = Field(default_factory=list)
    retained_non_pillar_territory_ids: list[str] = Field(default_factory=list)
    status: str = "completed"
    error_type: str = ""
    error_message: str = ""
    runtime_provenance: ModelRuntimeProvenance
    created_at: datetime


class Layer1ExpansionJobResult(BaseModel):
    """Explicitly JSON-safe result for checkpointed territory exploration."""

    run_id: str
    status: TerritoryRunStatus
    stage: TerritoryRunStage
    completed_lens_ids: list[str] = Field(default_factory=list)
    unresolved_lens_ids: list[str] = Field(default_factory=list)
    raw_candidate_count: int = 0
    classified_candidate_count: int = 0
    undispositioned_candidate_count: int = 0
    architecture_candidate_ids: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    partial_completion: bool = False
    incomplete_reasons: list[str] = Field(default_factory=list)
