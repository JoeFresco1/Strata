from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


NodeStatus = Literal["generated", "kept", "cut", "merged", "prioritized"]
NodeType = Literal["product_idea", "pillar", "subfeature", "spec"]
Layer2FeatureStatus = Literal["candidate", "kept", "cut", "merged", "renamed", "needs_review", "approved"]
Layer2RelationshipType = Literal[
    "related_to",
    "depends_on",
    "enables",
    "overlaps_with",
    "uses_shared_service",
    "duplicate_of",
    "conflicts_with",
]
Layer2ReviewActionType = Literal[
    "edit",
    "keep",
    "cut",
    "rename",
    "merge",
    "reassign_owner",
    "add_relationship",
    "remove_relationship",
    "prioritize",
    "approve_for_layer3",
    "needs_review",
    "manual_add",
]
ResearchJobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
OverlapResolutionAction = Literal["accept_merge", "link", "dismiss", "keep_separate", "needs_followup"]
ResearchJobType = Literal["layer0_competitors", "layer1_pillar_competitors", "layer2_feature_competitors"]
ResearchScope = Literal["layer0", "layer1", "layer2"]
PlatformJobStatus = Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
PlatformJobKind = Literal["research", "generation", "assistant", "replay", "audit", "diagnostics", "critic"]
CoverageStatus = Literal["supported", "partially_supported", "unclear", "not_evident"]
AdoptionLevel = Literal["common", "emerging", "rare", "unclear"]
CoverageMatrixStatus = Literal["missing", "partial", "covered", "excluded"]
SharedConcernType = Literal[
    "ingestion",
    "validation",
    "permissions",
    "notifications",
    "audit_logging",
    "templates",
    "workflow_state",
    "reporting",
]
SharedConcernStatus = Literal["flagged", "acknowledged", "promoted_to_l1", "dismissed"]
FeatureEvidenceCoverageStatus = Literal["has_feature", "partial", "not_found", "unclear"]
FeatureEvidenceSourceType = Literal["manual", "discovered"]
CompetitiveResearchMode = Literal["known_only", "expand_from_known"]
ExecutionIntent = Literal["local_first", "api_first", "blended"]
ExecutionProviderPreference = Literal["local", "api"]
Layer3ReviewState = Literal["draft", "approved", "rejected", "needs_review"]
Layer3SelectionState = Literal["include", "exclude", "undecided"]
Layer3ConfigurationKind = Literal[
    "boolean",
    "single_select",
    "multi_select",
    "numeric",
    "text",
    "rule",
    "workflow",
    "content",
    "integration",
    "other",
]
OverlapLayer = Literal["layer1", "layer2"]
OverlapVerdictRelation = Literal[
    "same_capability",
    "broader",
    "narrower",
    "merge",
    "link",
    "distinct",
    "fake_novelty",
    "needs_review",
]


class FeatureGranularity(str, Enum):
    """Layer 2 product-capability granularity classes used by the integrity critic."""

    FEATURE = "feature"
    FEATURE_VARIANT = "feature_variant"
    WORKFLOW = "workflow"
    RULE = "rule"
    CONFIGURATION = "configuration"
    SHARED_CONCERN = "shared_concern"
    TOO_BROAD = "too_broad"
    TOO_LOW_LEVEL = "too_low_level"


class Project(BaseModel):
    id: str
    name: str
    idea: str
    created_at: datetime
    updated_at: datetime | None = None
    last_opened_at: datetime | None = None
    archived_at: datetime | None = None
    lifecycle_state: Literal["active", "archived"] = "active"
    source_project_id: str | None = None


class ProjectLLMProfile(BaseModel):
    id: str
    label: str
    base_url: str = ""
    model_name: str = ""
    local_path: str = ""
    runtime_kind: Literal["auto", "managed_local", "remote_api"] = "auto"
    context_window: int = Field(ge=2048, default=32768)
    supports_reasoning: bool = True
    supports_parallel: bool = False
    max_parallel_requests: int = Field(ge=1, le=32, default=1)
    max_specialists: int = Field(ge=0, le=16, default=2)
    max_output_tokens: int = Field(ge=256, le=16000, default=1800)
    input_cost_per_million: float = Field(ge=0, default=0)
    output_cost_per_million: float = Field(ge=0, default=0)


class ProjectEmbeddingProfile(BaseModel):
    id: str
    label: str
    model_name: str


class ProjectModelSettings(BaseModel):
    project_id: str
    llm_profiles: list[ProjectLLMProfile] = Field(default_factory=list)
    embedding_profiles: list[ProjectEmbeddingProfile] = Field(default_factory=list)
    execution_intent: ExecutionIntent = "local_first"
    routing_policy: dict[str, ExecutionProviderPreference] = Field(default_factory=dict)
    concurrency_policy: dict[str, int] = Field(default_factory=dict)
    assignments: dict[str, Any] = Field(default_factory=dict)
    prompt_catalog: dict[str, str] = Field(default_factory=dict)
    competitive_intelligence_enabled: bool = True
    discovery_settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ProjectWorkspaceState(BaseModel):
    """Durable per-project navigation state for the living Map/Table workspace."""

    project_id: str
    view_mode: Literal["map", "table"] = "map"
    selected_entity_type: Literal["brief", "pillar", "feature"] = "brief"
    selected_entity_id: str = "layer0-root"
    table_scope: Literal["focused", "project"] = "focused"
    map_state: dict[str, Any] = Field(default_factory=dict)
    table_state: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AssistantConversation(BaseModel):
    """One project assistant thread whose scope follows the user's working context."""

    id: str
    project_id: str
    title: str
    home_scope: str = "overall"
    compacted_summary: str = ""
    summary_state: dict[str, Any] = Field(default_factory=dict)
    archived: bool = False
    created_at: datetime
    updated_at: datetime


class AssistantMessage(BaseModel):
    """Durable user or assistant turn with retrieval and action provenance."""

    id: str
    conversation_id: str
    project_id: str
    role: Literal["user", "assistant", "system"]
    content: str = ""
    status: Literal["queued", "running", "completed", "failed"] = "completed"
    request_id: str | None = None
    active_scope: str = "overall"
    focus: dict[str, Any] = Field(default_factory=dict)
    reference_conversation_ids: list[str] = Field(default_factory=list)
    execution_intent_override: ExecutionIntent | None = None
    thinking_enabled: bool = False
    deep_mode: bool = False
    citations: list[dict[str, Any]] = Field(default_factory=list)
    proposed_actions: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_trace: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class AssistantActionProposal(BaseModel):
    """A validated mutation preview that cannot execute without confirmation."""

    id: str
    project_id: str
    conversation_id: str
    message_id: str
    action_type: str
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_state: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "applied", "rejected", "stale", "failed"] = "pending"
    result: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ProjectBrief(BaseModel):
    id: str
    project_id: str
    product_idea: str
    problem: str = ""
    known_competitors: list[str] = Field(default_factory=list)
    constraints: str = ""
    target_users: str = ""
    goals: list[str] = Field(default_factory=list)
    preferred_directions: list[str] = Field(default_factory=list)
    rejected_directions: list[str] = Field(default_factory=list)
    notes: str = ""
    status: Literal["draft", "published"] = "draft"
    current_draft_revision_id: str | None = None
    current_published_revision_id: str | None = None
    revision_number: int = 0
    content_hash: str = ""
    created_at: datetime
    updated_at: datetime


class BriefConversationTurn(BaseModel):
    id: str
    project_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    request_id: str | None = None
    extracted_updates: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class Node(BaseModel):
    id: str
    project_id: str
    parent_id: str | None = None
    layer: int
    node_type: NodeType
    title: str
    description: str | None = None
    json_payload: dict[str, Any] = Field(default_factory=dict)
    status: NodeStatus = "generated"
    priority: int | None = None
    created_at: datetime


class Layer1PillarRecord(BaseModel):
    id: str
    project_id: str
    node_id: str
    title: str
    description: str = ""
    status: str
    created_at: datetime
    updated_at: datetime


class Layer2GenerationRun(BaseModel):
    id: str
    project_id: str
    source_pillar_ids: list[str] = Field(default_factory=list)
    source_architecture_application_id: str | None = None
    source_territory_candidate_ids: list[str] = Field(default_factory=list)
    lenses: list[str] = Field(default_factory=list)
    source_model: str
    status: str
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    completed_at: datetime | None = None


class Layer2RawCandidate(BaseModel):
    id: str
    project_id: str
    generation_run_id: str
    source_pillar_id: str
    source_lens: str
    source_model: str
    generation_round: int
    raw_text: str
    payload: dict[str, Any] = Field(default_factory=dict)
    negative_cache_match: bool = False
    negative_cache_reason: str = ""
    created_at: datetime


class Layer2Feature(BaseModel):
    id: str
    project_id: str
    canonical_name: str
    description: str
    feature_type: str
    granularity_class: FeatureGranularity = FeatureGranularity.FEATURE
    owner_pillar_id: str
    candidate_source_ids: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    status: Layer2FeatureStatus = "candidate"
    related_pillar_ids: list[str] = Field(default_factory=list)
    used_by_feature_ids: list[str] = Field(default_factory=list)
    depends_on_feature_ids: list[str] = Field(default_factory=list)
    specificity_score: int = Field(ge=0, le=100, default=50)
    pillar_fit_score: int = Field(ge=0, le=100, default=50)
    distinctiveness_score: int = Field(ge=0, le=100, default=50)
    implementation_leakage_score: int = Field(ge=0, le=100, default=0)
    strategic_value_score: int = Field(ge=0, le=100, default=50)
    needs_human_review: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class Layer2PillarAffinity(BaseModel):
    id: str
    project_id: str
    feature_id: str
    pillar_id: str
    affinity_score: float
    recommended_owner_pillar_id: str
    created_at: datetime


class Layer2FeatureRelationship(BaseModel):
    id: str
    project_id: str
    source_feature_id: str
    target_feature_id: str
    relationship_type: Layer2RelationshipType
    strength: float
    rationale: str = ""
    created_at: datetime


class Layer2NegativeCacheEntry(BaseModel):
    id: str
    project_id: str
    rejected_name: str
    semantic_cluster: str
    rejected_aliases: list[str] = Field(default_factory=list)
    rejected_at_layer: int = 2
    rejected_from_pillar_id: str
    embedding_model: str = ""
    created_at: datetime


class PillarScopeContract(BaseModel):
    """Boundary contract for one approved Layer 1 pillar before Layer 2 descent."""

    pillar_id: str
    allowed_core_domains: list[str] = Field(default_factory=list)
    explicit_out_of_bounds: list[str] = Field(default_factory=list)
    discovered_coverage_families: list[str] = Field(default_factory=list)
    source_architecture_application_id: str | None = None
    mapped_territory: list[dict[str, Any]] = Field(default_factory=list)
    retained_non_pillar_territory: list[dict[str, Any]] = Field(default_factory=list)


class Layer2CoverageMatrixRow(BaseModel):
    """Persistent per-family exhaustion state for one pillar."""

    id: str
    project_id: str
    pillar_id: str
    family_name: str
    status: CoverageMatrixStatus = "missing"
    evidence_feature_ids: list[str] = Field(default_factory=list)
    missing_examples: list[str] = Field(default_factory=list)
    last_lens_run: str = ""
    drift_flags: bool = False
    ambiguity_flags: bool = False
    created_at: datetime
    updated_at: datetime


class Layer2SharedConcernCluster(BaseModel):
    """Cross-cutting infrastructure signal discovered while mapping Layer 2 features."""

    id: str
    project_id: str
    name: str
    concern_type: SharedConcernType
    connected_feature_ids: list[str] = Field(default_factory=list)
    status: SharedConcernStatus = "flagged"
    created_at: datetime
    updated_at: datetime


class Layer2FeatureEvidence(BaseModel):
    """Manual or discovered competitor evidence attached to one Layer 2 feature."""

    id: str
    project_id: str
    feature_id: str
    competitor_name: str
    coverage_status: FeatureEvidenceCoverageStatus = "unclear"
    confidence: int = Field(ge=0, le=100, default=50)
    source_url: str = ""
    evidence_snippet: str = ""
    rationale: str = ""
    notes: str = ""
    source_type: FeatureEvidenceSourceType = "manual"
    research_job_id: str | None = None
    created_at: datetime
    updated_at: datetime


class Layer2CompetitiveSettings(BaseModel):
    """Project-level settings for feature-level competitive intelligence."""

    project_id: str
    known_competitors: list[str] = Field(default_factory=list)
    research_mode: CompetitiveResearchMode = "known_only"
    created_at: datetime
    updated_at: datetime


class Layer2ReviewAction(BaseModel):
    id: str
    project_id: str
    feature_id: str | None = None
    action_type: Layer2ReviewActionType
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class FeatureExpansionOption(BaseModel):
    """One possible subfeature, setting, rule, or variant under an approved Layer 2 feature."""

    id: str = ""
    name: str
    description: str = ""
    selection_state: Layer3SelectionState = "undecided"
    configuration_kind: Layer3ConfigurationKind = "other"
    default_recommendation: str = ""
    rationale: str = ""
    dependencies: list[str] = Field(default_factory=list)
    overlaps_feature_ids: list[str] = Field(default_factory=list)


class FeatureExpansionGroup(BaseModel):
    """A named group of Layer 3 options for one feature."""

    id: str = ""
    name: str
    description: str = ""
    options: list[FeatureExpansionOption] = Field(default_factory=list)


class FeatureExpansion(BaseModel):
    """Persistent Layer 3 feature-expansion artifact for one approved Layer 2 feature."""

    id: str
    project_id: str
    feature_id: str
    parent_pillar_id: str
    parent_pillar_title: str
    feature_name: str
    feature_description: str = ""
    feature_intent: str = ""
    expansion_groups: list[FeatureExpansionGroup] = Field(default_factory=list)
    overlap_review: list[dict[str, Any] | str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    review_state: Layer3ReviewState = "draft"
    provenance: dict[str, Any] = Field(default_factory=dict)
    active_revision_id: str = ""
    revision_number: int = 0
    created_at: datetime
    updated_at: datetime


class GenerationLog(BaseModel):
    id: str
    project_id: str
    node_id: str | None = None
    prompt: str
    raw_response: str
    parsed_json: dict[str, Any] | None = None
    model_name: str | None = None
    created_at: datetime


class ProjectMemory(BaseModel):
    id: str
    project_id: str
    scope: str
    scope_id: str | None = None
    memory_type: str
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class SimilarityEdge(BaseModel):
    source_node_id: str
    target_node_id: str
    source_title: str
    target_title: str
    score: float


class ResearchJob(BaseModel):
    id: str
    project_id: str
    scope: ResearchScope
    scope_id: str | None = None
    job_type: ResearchJobType
    status: ResearchJobStatus
    progress: int = Field(ge=0, le=100)
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class PlatformJob(BaseModel):
    id: str
    project_id: str
    kind: PlatformJobKind
    workflow: str
    scope: str
    scope_id: str | None = None
    status: PlatformJobStatus
    progress: int = Field(ge=0, le=100)
    current_step: str = ""
    request_payload: dict[str, Any] = Field(default_factory=dict)
    result_payload: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    dedupe_key: str | None = None
    cancel_requested: bool = False
    attempt: int = 1
    created_at: datetime
    started_at: datetime | None = None
    updated_at: datetime
    completed_at: datetime | None = None


class OverlapVerdict(BaseModel):
    id: str
    project_id: str
    job_id: str
    layer: OverlapLayer
    target_id: str
    neighbor_id: str
    relation: OverlapVerdictRelation
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    rationale: str = ""
    critic_source: str = "overlap_critic"
    target_hash: str = ""
    neighbor_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class OverlapVerdictResolution(BaseModel):
    id: str
    project_id: str
    verdict_id: str
    layer: OverlapLayer
    target_id: str
    neighbor_id: str
    action: OverlapResolutionAction
    note: str = ""
    resolved_by: str = "user"
    target_hash: str = ""
    neighbor_hash: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class OverlapClusterRecord(BaseModel):
    id: str
    project_id: str
    job_id: str
    layer: OverlapLayer
    cluster_id: str
    member_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class OverlapJobItem(BaseModel):
    id: str
    project_id: str
    job_id: str
    layer: OverlapLayer
    item_id: str
    item_hash: str = ""
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    error: str = ""
    created_at: datetime
    updated_at: datetime


class ResearchSource(BaseModel):
    id: str
    project_id: str
    scope: ResearchScope
    scope_id: str | None = None
    competitor_name: str
    domain: str
    url: str
    page_type: str
    title: str | None = None
    status_code: int | None = None
    fetched_at: datetime
    content_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchChunk(BaseModel):
    id: str
    project_id: str
    scope: ResearchScope
    scope_id: str | None = None
    source_id: str
    competitor_name: str
    domain: str
    url: str
    title: str | None = None
    chunk_index: int
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class EvidenceSnippet(BaseModel):
    url: str
    title: str | None = None
    snippet: str
    competitor_name: str


class CompetitorCoverage(BaseModel):
    competitor_name: str
    domain: str | None = None
    coverage_status: CoverageStatus
    adoption_level: AdoptionLevel
    summary: str
    evidence: list[EvidenceSnippet] = Field(default_factory=list)
    confidence: int = Field(ge=0, le=100)


class ResearchFinding(BaseModel):
    id: str
    project_id: str
    scope: ResearchScope
    scope_id: str | None = None
    finding_type: str
    title: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class SimilarityMatch(BaseModel):
    node_id: str
    title: str
    layer: int
    node_type: str
    score: float
    description: str | None = None


class PillarCandidate(BaseModel):
    title: str
    description: str
    why_it_matters: str
    risks: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class PillarResearchRating(BaseModel):
    name: str
    label: str
    rating: int = Field(ge=1, le=10)
    rationale: str


class PillarResearchAssessment(BaseModel):
    summary: str
    confidence: int = Field(ge=0, le=100)
    indexed_score: int = Field(ge=0, le=100, default=0)
    ratings: list[PillarResearchRating] = Field(default_factory=list)
    implications: list[str] = Field(default_factory=list)


class Layer2Candidate(BaseModel):
    canonical_name: str
    description: str
    feature_type: str = "capability"
    coverage_family: str = "general_capability"
    scope_classification: Literal[
        "in_scope",
        "adjacent_owned_elsewhere",
        "new_layer1_pillar",
        "too_low_level",
        "implementation_detail",
    ] = "in_scope"
    pillar_fit_rationale: str = ""
    aliases: list[str] = Field(default_factory=list)
    related_pillar_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    used_by: list[str] = Field(default_factory=list)
    specificity_score: int = Field(ge=0, le=100, default=60)
    pillar_fit_score: int = Field(ge=0, le=100, default=60)
    distinctiveness_score: int = Field(ge=0, le=100, default=60)
    implementation_leakage_score: int = Field(ge=0, le=100, default=0)
    strategic_value_score: int = Field(ge=0, le=100, default=60)
    needs_human_review: bool = True


class Layer2IntegrityAssessment(BaseModel):
    candidate_id: str
    granularity_class: FeatureGranularity = FeatureGranularity.FEATURE
    is_out_of_bounds: bool = False
    ambiguity_score: float = Field(ge=0.0, le=1.0, default=0.0)
    reason: str = ""


class Layer2IntegrityCriticResponse(BaseModel):
    assessments: list[Layer2IntegrityAssessment] = Field(default_factory=list)


class Layer2DuplicateMergeDirective(BaseModel):
    source_feature_id: str
    target_feature_id: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    reason: str = ""


class Layer2DependencyDirective(BaseModel):
    source_feature_id: str
    target_feature_id: str
    relationship_type: Layer2RelationshipType = "depends_on"
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    reason: str = ""


class Layer2SharedConcernDirective(BaseModel):
    name: str
    concern_type: SharedConcernType
    connected_feature_ids: list[str] = Field(default_factory=list)
    planning_implication: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class Layer2GraphCriticResponse(BaseModel):
    duplicate_merges: list[Layer2DuplicateMergeDirective] = Field(default_factory=list)
    cross_pillar_dependencies: list[Layer2DependencyDirective] = Field(default_factory=list)
    detected_shared_concerns: list[Layer2SharedConcernDirective] = Field(default_factory=list)


class Layer2CandidateResponse(BaseModel):
    features: list[Layer2Candidate]


class Layer2CoverageFamilyDiscoveryItem(BaseModel):
    name: str
    description: str = ""
    exhaustion_goal: str = ""
    example_features: list[str] = Field(default_factory=list)
    anti_examples: list[str] = Field(default_factory=list)


class Layer2CoverageFamilyDiscoveryResponse(BaseModel):
    coverage_families: list[Layer2CoverageFamilyDiscoveryItem] = Field(default_factory=list)
    reasoning: str = ""


class Layer2CoverageFamilyAssessment(BaseModel):
    family: str
    status: Literal["covered", "partial", "missing", "excluded"] = "missing"
    evidence_feature_ids: list[str] = Field(default_factory=list)
    missing_examples: list[str] = Field(default_factory=list)
    next_lens: str | None = None
    rationale: str = ""


class Layer2CoverageAssessmentResponse(BaseModel):
    coverage_summary: str
    family_assessments: list[Layer2CoverageFamilyAssessment] = Field(default_factory=list)
    drifted_feature_ids: list[str] = Field(default_factory=list)
    adjacent_module_suggestions: list[str] = Field(default_factory=list)
    saturation_signal: Literal["low", "medium", "high"]
    novelty_score: int = Field(ge=0, le=100)
    continue_recommendation: bool
    recommended_next_lenses: list[str] = Field(default_factory=list)
    reasoning: str


class PillarResponse(BaseModel):
    pillars: list[PillarCandidate]


class FeatureExpansionPayload(BaseModel):
    feature_intent: str
    expansion_groups: list[FeatureExpansionGroup] = Field(default_factory=list)
    overlap_review: list[dict[str, Any] | str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class FeatureExpansionResponse(BaseModel):
    expansion: FeatureExpansionPayload


class CoverageGap(BaseModel):
    title: str
    reason: str


class CriticResponse(BaseModel):
    coverage_summary: str
    overlap_clusters: list[list[str]] = Field(default_factory=list)
    uncovered_areas: list[CoverageGap] = Field(default_factory=list)
    saturation_signal: Literal["low", "medium", "high"]
    novelty_score: int = Field(ge=0, le=100)
    continue_recommendation: bool
    reasoning: str
    recommended_next_lens: str | None = None


class PillarAssessment(BaseModel):
    title: str
    canonical_title: str
    cluster_id: str
    is_true_pillar: bool
    distinctiveness_score: int = Field(ge=0, le=100)
    strategic_value_score: int = Field(ge=0, le=100)
    pillar_quality_score: int = Field(ge=0, le=100)
    too_narrow: bool = False
    too_implementation_specific: bool = False
    too_broad_generic: bool = False
    merge_into: str | None = None
    rename_to: str | None = None
    sharpen_to: str | None = None
    rationale: str


class PillarAssessmentResponse(BaseModel):
    assessments: list[PillarAssessment]
