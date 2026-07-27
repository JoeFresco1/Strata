from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class DiscoveryRevisionState(StrEnum):
    """Authority states shared by discovery and competitor-research revisions."""

    CANDIDATE = "candidate"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class CompetitorResearchMode(StrEnum):
    """User-selected research depth persisted with every discovery run."""

    NONE = "no_competitor_research"
    LIGHTWEIGHT = "lightweight_competitor_scan"
    DEEP = "deep_competitor_research"


class DiscoveryItem(BaseModel):
    """Common identity and human-authority fields for nested discovery records."""

    id: str
    title: str
    description: str = ""
    source: Literal["baseline", "model_discovered", "competitor_research", "human_added"] = "model_discovered"
    downstream_state: Literal["required", "optional", "excluded"] = "optional"
    human_notes: str = ""


class DiscoveryArchetype(DiscoveryItem):
    """A product archetype inferred from the published brief."""

    confidence: float = Field(ge=0, le=1, default=0.5)
    rationale: str = ""
    brief_evidence: list[str] = Field(default_factory=list)
    product_design_implications: list[str] = Field(default_factory=list)
    related_lens_ids: list[str] = Field(default_factory=list)
    related_actor_ids: list[str] = Field(default_factory=list)
    related_obligation_ids: list[str] = Field(default_factory=list)


class DiscoveryLens(DiscoveryItem):
    """A reusable product-level perspective for downstream exploration."""

    why_it_matters: str = ""
    questions: list[str] = Field(default_factory=list)
    expected_product_territory: list[str] = Field(default_factory=list)
    relevance_score: float = Field(ge=0, le=1, default=0.5)
    recommendation: Literal["required", "recommended", "optional", "rejected"] = "optional"
    applicable_downstream_layers: list[int] = Field(default_factory=list)
    applicable_actor_ids: list[str] = Field(default_factory=list)
    related_lens_ids: list[str] = Field(default_factory=list)
    omission_risks: list[str] = Field(default_factory=list)
    supporting_competitor_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class DiscoveryActor(DiscoveryItem):
    """An actor who uses, operates, governs, buys, or is affected by the product."""

    goals: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    authority_level: str = ""
    workflows: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    information_needed: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    relevant_lens_ids: list[str] = Field(default_factory=list)
    likely_product_areas: list[str] = Field(default_factory=list)
    lifecycle_stage_ids: list[str] = Field(default_factory=list)
    competitor_expectations: list[str] = Field(default_factory=list)


class DiscoveryLifecycleStage(DiscoveryItem):
    """One stage in the product's operational lifecycle."""

    actor_ids: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    administration_needs: list[str] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)
    likely_capabilities: list[str] = Field(default_factory=list)
    competitor_maturity_signals: list[str] = Field(default_factory=list)
    unresolved_coverage_risk_ids: list[str] = Field(default_factory=list)


class EnterprisePlatformObligation(DiscoveryItem):
    """Commercially or operationally necessary enterprise product territory."""

    affected_actor_ids: list[str] = Field(default_factory=list)
    operational_rationale: str = ""
    commercial_rationale: str = ""
    omission_risk: str = ""
    likely_product_destination: str = ""
    competitor_evidence_ids: list[str] = Field(default_factory=list)
    strategic_classification: Literal[
        "table_stakes", "market_standard", "emerging", "differentiating", "optional", "out_of_scope"
    ] = "optional"


class DiscoveryDomain(DiscoveryItem):
    """A deliberately overlapping product territory, not a normalized pillar."""

    why_it_matters: str = ""
    actor_ids: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    related_lens_ids: list[str] = Field(default_factory=list)
    candidate_capabilities: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)
    brief_evidence: list[str] = Field(default_factory=list)
    competitor_evidence_ids: list[str] = Field(default_factory=list)
    downstream_classifications: list[str] = Field(default_factory=list)


class CrossDomainOpportunity(DiscoveryItem):
    """A mechanism imported from a structurally similar external domain."""

    source_domain: str = ""
    source_mechanism: str = ""
    structural_similarity: str = ""
    product_translation: str = ""
    affected_domain_ids: list[str] = Field(default_factory=list)
    potential_user_value: str = ""
    implementation_plausibility: str = ""
    differentiation_potential: str = ""
    required_data: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    evidence_or_provenance: list[str] = Field(default_factory=list)
    speculation_level: Literal[
        "concrete", "speculative", "superficial_metaphor", "unusual_but_defensible", "requires_human_review"
    ] = "requires_human_review"


class DiscoveryCoverageRisk(DiscoveryItem):
    """A likely omission if Layer 1 later relies on the brief alone."""

    severity: Literal["low", "medium", "high", "critical"] = "medium"
    evidence: list[str] = Field(default_factory=list)
    affected_actor_ids: list[str] = Field(default_factory=list)
    affected_lens_ids: list[str] = Field(default_factory=list)
    competitor_evidence_ids: list[str] = Field(default_factory=list)
    recommended_layer1_attention: str = ""
    human_review_required: bool = False


class DiscoveryOpenQuestion(DiscoveryItem):
    """An ambiguity with an explicit Layer 1 blocking disposition."""

    question: str
    why_it_matters: str = ""
    affected_domain_ids: list[str] = Field(default_factory=list)
    affected_actor_ids: list[str] = Field(default_factory=list)
    affected_lens_ids: list[str] = Field(default_factory=list)
    competitor_evidence_ids: list[str] = Field(default_factory=list)
    disposition: Literal[
        "requires_human_answer_before_layer1",
        "useful_but_non_blocking",
        "safe_for_model_assumption",
        "intentionally_open",
    ] = "useful_but_non_blocking"


class DiscoveryReviewFinding(BaseModel):
    """A non-destructive practicality or evidence review disposition."""

    id: str
    item_type: str
    item_id: str
    original_output: dict[str, Any] = Field(default_factory=dict)
    outcome: Literal[
        "accepted",
        "accepted_with_revision",
        "optional",
        "duplicate",
        "needs_human_review",
        "rejected_as_superficial",
        "rejected_as_bizarre",
        "rejected_as_out_of_scope",
        "rejected_as_unsupported",
        "rejected_as_misleading_inference",
    ]
    rationale: str
    reviewer_type: Literal["deterministic", "model", "human"]
    confidence: float = Field(ge=0, le=1)
    human_review_required: bool = False
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class ModelRuntimeProvenance(BaseModel):
    """Authoritative resolved runtime facts for one model call."""

    requested_model_profile: str = ""
    resolved_model_profile: str = ""
    provider: str = ""
    endpoint: str = ""
    model_alias: str = ""
    exact_model_identifier: str = ""
    model_file_hash: str = ""
    runtime_build: str = ""
    server_process_id: str = ""
    prompt_key: str
    prompt_version: str
    effective_temperature: float
    seed: int | None = None
    context_limit: int | None = None
    output_limit: int | None = None
    request_id: str = ""
    prompt_token_count: int | None = None
    completion_token_count: int | None = None
    elapsed_time_seconds: float | None = None


class CompetitorResearchScope(BaseModel):
    """Bounded, user-approved competitor research configuration."""

    mode: CompetitorResearchMode = CompetitorResearchMode.NONE
    competitor_names: list[str] = Field(default_factory=list)
    max_competitors: int = Field(ge=0, le=50, default=0)
    source_budget: int = Field(ge=0, le=1000, default=0)
    time_budget_seconds: int = Field(ge=0, le=86400, default=0)
    per_competitor_source_limit: int = Field(ge=0, le=200, default=0)
    approved_secondary_sources: bool = False


class CompetitorEvidence(BaseModel):
    """Traceable source evidence supporting one or more competitor claims."""

    id: str
    competitor_id: str
    source_title: str
    source_type: str
    source_publisher: str = ""
    source_location: str
    publication_date: datetime | None = None
    retrieval_date: datetime
    extracted_evidence: str = ""
    claim_supported: str
    confidence: float = Field(ge=0, le=1)
    source_quality: Literal["low", "medium", "high", "authoritative"] = "medium"
    first_party: bool = False
    claim_type: Literal[
        "observed_fact",
        "competitor_claim",
        "third_party_claim",
        "architectural_inference",
        "strategic_interpretation",
        "unsupported_speculation",
    ]


class InferredCompetitorPillar(BaseModel):
    """An evidence-qualified interpretation that is never implied to be official."""

    id: str
    competitor_id: str
    title: str
    description: str = ""
    competitor_product_or_suite: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    supporting_product_areas: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    evidence_quality: Literal["low", "medium", "high", "authoritative"] = "medium"
    inference_strength: Literal["explicit", "strongly_inferred", "weakly_inferred", "speculative"]
    source_citations: list[str] = Field(default_factory=list)
    research_date: datetime
    human_review_state: Literal["pending", "approved", "rejected", "excluded"] = "pending"


class CompetitorProfile(BaseModel):
    """A checkpointable competitor profile assembled from bounded evidence."""

    id: str
    name: str
    product_suite: str = ""
    research_status: Literal["pending", "in_progress", "complete", "partial", "skipped", "failed"] = "pending"
    target_customers: list[str] = Field(default_factory=list)
    target_actors: list[str] = Field(default_factory=list)
    jobs_to_be_done: list[str] = Field(default_factory=list)
    major_product_domains: list[str] = Field(default_factory=list)
    supporting_capabilities: list[str] = Field(default_factory=list)
    administration_capabilities: list[str] = Field(default_factory=list)
    data_integration_capabilities: list[str] = Field(default_factory=list)
    intelligence_analytics_capabilities: list[str] = Field(default_factory=list)
    workflow_action_capabilities: list[str] = Field(default_factory=list)
    governance_security_capabilities: list[str] = Field(default_factory=list)
    developer_ecosystem_capabilities: list[str] = Field(default_factory=list)
    commercial_signals: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    weaknesses_or_omissions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.0)
    evidence_quality: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    research_timestamp: datetime | None = None
    last_verified_timestamp: datetime | None = None
    unresolved_questions: list[str] = Field(default_factory=list)


class CompetitiveTerritory(BaseModel):
    """One evidence-scored territory in the comparative market map."""

    id: str
    title: str
    description: str = ""
    competitor_ids: list[str] = Field(default_factory=list)
    classification: Literal[
        "table_stakes",
        "market_standard",
        "emerging_pattern",
        "competitor_specific",
        "differentiation_opportunity",
        "likely_commodity",
        "avoid_copying",
        "requires_human_review",
    ]
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    advisory_only: bool = True
    human_review_state: Literal["pending", "approved", "rejected", "excluded"] = "pending"


class CompetitiveGap(BaseModel):
    """A current-product market gap or differentiation opportunity."""

    id: str
    title: str
    description: str = ""
    gap_type: Literal["behind_market", "market_absence", "differentiated", "convergence", "avoid_copying"]
    territory_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    human_review_state: Literal["pending", "approved", "rejected", "excluded"] = "pending"


class CompetitorDerivedLens(DiscoveryLens):
    """A discovery lens whose inclusion requires approved competitor evidence."""

    source: Literal["competitor_research"] = "competitor_research"


class ProductDiscovery(BaseModel):
    """The complete structured product landscape, separate from Layer 1 pillars."""

    archetypes: list[DiscoveryArchetype] = Field(default_factory=list)
    lenses: list[DiscoveryLens] = Field(default_factory=list)
    actors: list[DiscoveryActor] = Field(default_factory=list)
    lifecycle_stages: list[DiscoveryLifecycleStage] = Field(default_factory=list)
    enterprise_obligations: list[EnterprisePlatformObligation] = Field(default_factory=list)
    domains: list[DiscoveryDomain] = Field(default_factory=list)
    cross_domain_opportunities: list[CrossDomainOpportunity] = Field(default_factory=list)
    coverage_risks: list[DiscoveryCoverageRisk] = Field(default_factory=list)
    open_questions: list[DiscoveryOpenQuestion] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class ProductDiscoveryRevision(BaseModel):
    """One immutable-or-candidate revision with separate model and human fields."""

    id: str
    head_id: str
    project_id: str
    revision_number: int
    source_brief_revision_id: str
    state: DiscoveryRevisionState
    competitor_research_mode: CompetitorResearchMode
    competitor_research_revision_id: str | None = None
    generation_job_id: str | None = None
    discovery: ProductDiscovery
    model_authored_fields: dict[str, Any] = Field(default_factory=dict)
    human_owned_fields: dict[str, Any] = Field(default_factory=dict)
    review_findings: list[DiscoveryReviewFinding] = Field(default_factory=list)
    runtime_provenance: list[ModelRuntimeProvenance] = Field(default_factory=list)
    audit_history: list[dict[str, Any]] = Field(default_factory=list)
    dependency_metadata: dict[str, Any] = Field(default_factory=dict)
    freshness_state: Literal["current", "stale", "superseded", "unknown"] = "current"
    stale_reason: str = ""
    content_hash: str
    created_at: datetime
    approved_at: datetime | None = None
    published_at: datetime | None = None
    rejected_at: datetime | None = None
    superseded_at: datetime | None = None


class CompetitorResearchRevision(BaseModel):
    """An independently versioned, partially completable competitor research artifact."""

    id: str
    head_id: str
    project_id: str
    revision_number: int
    source_brief_revision_id: str
    state: DiscoveryRevisionState
    scope: CompetitorResearchScope
    profiles: list[CompetitorProfile] = Field(default_factory=list)
    evidence: list[CompetitorEvidence] = Field(default_factory=list)
    inferred_pillars: list[InferredCompetitorPillar] = Field(default_factory=list)
    territories: list[CompetitiveTerritory] = Field(default_factory=list)
    gaps: list[CompetitiveGap] = Field(default_factory=list)
    derived_lenses: list[CompetitorDerivedLens] = Field(default_factory=list)
    human_decisions: dict[str, Any] = Field(default_factory=dict)
    runtime_provenance: list[ModelRuntimeProvenance] = Field(default_factory=list)
    checkpoint_state: dict[str, Any] = Field(default_factory=dict)
    partial_completion: bool = False
    freshness_state: Literal["current", "stale", "superseded", "unknown"] = "current"
    stale_reason: str = ""
    content_hash: str
    created_at: datetime
    research_date: datetime | None = None
    last_verified_at: datetime | None = None
    approved_at: datetime | None = None
    published_at: datetime | None = None
    rejected_at: datetime | None = None
    superseded_at: datetime | None = None


class DiscoveryContextProjectionBase(BaseModel):
    """Deterministic compact context with auditable inclusion decisions."""

    id: str
    project_id: str
    source_discovery_revision_id: str
    source_competitor_research_revision_id: str | None = None
    compiler_version: str
    included_item_ids: list[str] = Field(default_factory=list)
    excluded_item_ids: list[str] = Field(default_factory=list)
    inclusion_rationale: dict[str, str] = Field(default_factory=dict)
    exclusion_rationale: dict[str, str] = Field(default_factory=dict)
    unresolved_risks: list[dict[str, Any]] = Field(default_factory=list)
    token_estimate: int = 0
    content_hash: str
    created_at: datetime


class Layer1DiscoveryContextProjection(DiscoveryContextProjectionBase):
    """Approved compact product-discovery context for future Layer 1 consumption."""

    required_lenses: list[dict[str, Any]] = Field(default_factory=list)
    optional_lenses: list[dict[str, Any]] = Field(default_factory=list)
    actors: list[dict[str, Any]] = Field(default_factory=list)
    domains: list[dict[str, Any]] = Field(default_factory=list)
    enterprise_obligations: list[dict[str, Any]] = Field(default_factory=list)
    cross_domain_opportunities: list[dict[str, Any]] = Field(default_factory=list)
    open_questions: list[dict[str, Any]] = Field(default_factory=list)


class CompetitiveContextProjection(DiscoveryContextProjectionBase):
    """Approved competitive context without raw research corpora."""

    inferred_competitor_pillars: list[dict[str, Any]] = Field(default_factory=list)
    table_stakes_territories: list[dict[str, Any]] = Field(default_factory=list)
    emerging_patterns: list[dict[str, Any]] = Field(default_factory=list)
    differentiation_opportunities: list[dict[str, Any]] = Field(default_factory=list)
    market_gaps: list[dict[str, Any]] = Field(default_factory=list)
    concise_evidence_references: list[dict[str, Any]] = Field(default_factory=list)


class ProductDiscoveryJobResult(BaseModel):
    """JSON-safe terminal result for a Product Discovery platform job."""

    discovery_revision_id: str
    competitor_research_revision_id: str | None = None
    projection_ids: list[str] = Field(default_factory=list)
    raw_response_preserved: bool = False
    schema_valid: bool = False
    repair_attempts: int = 0
    final_candidate_counts: dict[str, int] = Field(default_factory=dict)
    stop_reason: str = ""


class CompetitorResearchJobResult(BaseModel):
    """JSON-safe terminal result for a checkpointed competitor-research job."""

    competitor_research_revision_id: str
    completed_competitor_ids: list[str] = Field(default_factory=list)
    unresolved_competitor_ids: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    inferred_pillar_count: int = 0
    partial_completion: bool = False
    checkpoint_state: dict[str, Any] = Field(default_factory=dict)
    stop_reason: str = ""
