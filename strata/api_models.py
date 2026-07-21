from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ProjectCreateRequest(BaseModel):
    name: str
    idea: str
    known_competitors: list[str] = Field(default_factory=list)
    constraints: str = ""
    target_users: str = ""
    goals: list[str] = Field(default_factory=list)
    preferred_directions: list[str] = Field(default_factory=list)
    rejected_directions: list[str] = Field(default_factory=list)
    notes: str = ""


class ProjectUpdateRequest(BaseModel):
    name: str
    idea: str
    expected_state_token: str | None = None
    request_id: str | None = None

    @field_validator("name", "idea")
    @classmethod
    def required_project_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Project name and summary cannot be blank.")
        return cleaned


class ProjectCloneRequest(BaseModel):
    name: str | None = None


class ProjectArchiveExportResponse(BaseModel):
    archive_path: str
    manifest: dict[str, Any] = Field(default_factory=dict)


class ProjectArchiveImportRequest(BaseModel):
    archive_path: str
    request_id: str | None = None


class ProjectArchiveImportResponse(BaseModel):
    project: dict[str, Any]
    lifecycle_warnings: list[str] = Field(default_factory=list)


class ProjectBriefUpdateRequest(BaseModel):
    product_idea: str
    problem: str = ""
    known_competitors: list[str] = Field(default_factory=list)
    constraints: str = ""
    target_users: str = ""
    goals: list[str] = Field(default_factory=list)
    preferred_directions: list[str] = Field(default_factory=list)
    rejected_directions: list[str] = Field(default_factory=list)
    notes: str = ""
    expected_state_token: str | None = None
    request_id: str | None = None


class Layer0ChatRequest(BaseModel):
    message: str
    request_id: str | None = None
    expected_state_token: str | None = None


class Layer0PlanGuidanceResponse(BaseModel):
    assistant_message: str
    focus_area: str
    recap: str
    next_questions: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: str


class Layer0ChatResponse(BaseModel):
    reply: str
    brief: dict[str, Any]
    conversation: list[dict[str, Any]]
    plan_guidance: Layer0PlanGuidanceResponse


class PublishBriefResponse(BaseModel):
    brief: dict[str, Any]
    snapshot: dict[str, Any]


class NodeUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: int | None = None
    expected_state_token: str | None = None
    request_id: str | None = None


class Layer1GenerateRequest(BaseModel):
    model_aliases: list[str] = Field(default_factory=list)
    thinking_enabled: bool = False
    max_rounds: int = 6
    target_per_round: int = 12
    total_cap: int | None = Field(default=None, ge=1)
    min_new_items_per_round: int = 2
    stale_rounds_to_stop: int = 2
    request_id: str | None = None


class Layer1PillarCreateRequest(BaseModel):
    title: str
    description: str = ""
    status: Literal["generated", "kept", "cut", "merged", "prioritized"] = "kept"
    priority: int = Field(default=0, ge=0, le=10)
    request_id: str | None = None

    @field_validator("title")
    @classmethod
    def require_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Manual Layer 1 pillars require a title.")
        return cleaned


class Layer1BulkActionRequest(BaseModel):
    pillar_ids: list[str] = Field(default_factory=list)
    status: Literal["kept", "cut", "prioritized"]
    expected_state_tokens: dict[str, str] = Field(default_factory=dict)
    request_id: str | None = None


class Layer2GenerateRequest(BaseModel):
    pillar_ids: list[str] = Field(default_factory=list)
    thinking_enabled: bool = False
    max_rounds: int = 5
    target_per_round: int = 10
    total_cap: int | None = Field(default=None, ge=1)
    min_new_items_per_round: int = 2
    stale_rounds_to_stop: int = 2
    request_id: str | None = None


class Layer3GenerateRequest(BaseModel):
    feature_ids: list[str] = Field(default_factory=list)
    thinking_enabled: bool = False
    request_id: str | None = None


class Layer3ExpansionOptionRequest(BaseModel):
    id: str = ""
    name: str
    description: str = ""
    selection_state: Literal["include", "exclude", "undecided"] = "undecided"
    configuration_kind: Literal[
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
    ] = "other"
    default_recommendation: str = ""
    rationale: str = ""
    dependencies: list[str] = Field(default_factory=list)
    overlaps_feature_ids: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def require_option_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Layer 3 expansion options require a name.")
        return cleaned


class Layer3ExpansionGroupRequest(BaseModel):
    id: str = ""
    name: str
    description: str = ""
    options: list[Layer3ExpansionOptionRequest] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def require_group_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Layer 3 expansion groups require a name.")
        return cleaned


class Layer3ExpansionUpdateRequest(BaseModel):
    feature_intent: str | None = None
    expansion_groups: list[Layer3ExpansionGroupRequest] | None = None
    overlap_review: list[dict[str, Any] | str] | None = None
    open_questions: list[str] | None = None
    expected_state_token: str | None = None
    request_id: str | None = None

    @field_validator("feature_intent")
    @classmethod
    def non_blank_intent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Layer 3 feature intent cannot be blank.")
        return cleaned


class Layer3ReviewRequest(BaseModel):
    action: Literal["approve", "reject", "needs_review"]
    note: str = ""
    expected_state_token: str | None = None
    request_id: str | None = None


class Layer3CandidateApplyRequest(BaseModel):
    expected_active_revision_id: str | None = None
    request_id: str = Field(min_length=1)
    selected_sections: list[Literal["feature_intent", "expansion_groups", "overlap_review", "open_questions"]] = Field(default_factory=list)
    actor: str = "user"


class Layer3CandidateRejectRequest(BaseModel):
    request_id: str = Field(min_length=1)
    note: str = ""
    actor: str = "user"
    expected_active_revision_id: str | None = None


class Layer3RevisionRestoreRequest(BaseModel):
    expected_active_revision_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    actor: str = "user"


class Layer2ReviewActionRequest(BaseModel):
    action_type: Literal[
        "keep",
        "cut",
        "rename",
        "merge",
        "reassign_owner",
        "add_relationship",
        "remove_relationship",
        "prioritize",
        "approve_for_layer3",
    ]
    feature_id: str | None = None
    target_feature_id: str | None = None
    title: str | None = None
    description: str | None = None
    owner_pillar_id: str | None = None
    relationship_type: Literal[
        "related_to",
        "depends_on",
        "enables",
        "overlaps_with",
        "uses_shared_service",
        "duplicate_of",
        "conflicts_with",
    ] | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_state_token: str | None = None
    expected_target_state_token: str | None = None
    request_id: str | None = None


class Layer2FeatureCreateRequest(BaseModel):
    canonical_name: str
    description: str
    owner_pillar_id: str
    feature_type: str = "capability"
    granularity_class: str = "feature"
    coverage_family: str = ""
    aliases: list[str] = Field(default_factory=list)
    status: str = "candidate"
    priority: str = ""
    notes: str = ""
    request_id: str | None = None

    @field_validator("canonical_name", "description", "owner_pillar_id")
    @classmethod
    def required_text(cls, value: str) -> str:
        """Reject blank identifiers/text before the database layer sees them."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Required Layer 2 feature fields cannot be blank.")
        return cleaned

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, value: list[str]) -> list[str]:
        """Normalize alias payloads from the workbench textarea."""
        return [item.strip() for item in value if item.strip()]


class Layer2FeatureUpdateRequest(BaseModel):
    canonical_name: str | None = None
    description: str | None = None
    feature_type: str | None = None
    granularity_class: str | None = None
    owner_pillar_id: str | None = None
    status: str | None = None
    coverage_family: str | None = None
    priority: str | None = None
    notes: str | None = None
    expected_state_token: str | None = None
    request_id: str | None = None

    @field_validator("canonical_name", "description", "feature_type", "granularity_class", "owner_pillar_id", "status")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        """Trim optional text fields while preserving omitted values."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Provided Layer 2 update fields cannot be blank.")
        return cleaned


class Layer2BulkActionRequest(BaseModel):
    feature_ids: list[str] = Field(default_factory=list)
    action_type: Literal["approve_for_layer3", "cut", "keep", "needs_review"] = "keep"
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_state_tokens: dict[str, str] = Field(default_factory=dict)
    request_id: str | None = None


class Layer2FeatureEvidenceRequest(BaseModel):
    feature_id: str
    competitor_name: str
    coverage_status: Literal["has_feature", "partial", "not_found", "unclear"] = "unclear"
    confidence: int = Field(ge=0, le=100, default=50)
    source_url: str = ""
    evidence_snippet: str = ""
    notes: str = ""
    source_type: Literal["manual", "discovered"] = "manual"

    @field_validator("feature_id", "competitor_name")
    @classmethod
    def required_evidence_text(cls, value: str) -> str:
        """Keep evidence rows tied to an actual feature and named competitor."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Feature evidence requires a feature and competitor.")
        return cleaned


class Layer2CompetitiveSettingsRequest(BaseModel):
    known_competitors: list[str] = Field(default_factory=list)
    research_mode: Literal["known_only", "expand_from_known"] = "known_only"


class ExportResponse(BaseModel):
    markdown_path: str
    json_path: str


class ResearchStartRequest(BaseModel):
    pillar_ids: list[str] = Field(default_factory=list)
    request_id: str | None = None


class Layer2ResearchStartRequest(BaseModel):
    feature_ids: list[str] = Field(default_factory=list)
    request_id: str | None = None


class EmbeddingSettingsUpdateRequest(BaseModel):
    embeddings_model_name: str


class RuntimeModelSettingsUpdateRequest(BaseModel):
    llama_base_url: str
    llm_model_name: str
    preferred_model_path: str = ""
    embeddings_model_name: str
    bearer_token: str = ""
    clear_bearer_token: bool = False
    context_window: int = Field(ge=2048, default=32768)
    max_output_tokens: int = Field(ge=256, le=16000, default=1800)
    runtime_preset: str = ""
    execution_intent: Literal["local_first", "api_first", "blended"] = "local_first"
    routing_policy: dict[str, Literal["local", "api"]] = Field(default_factory=dict)
    concurrency_policy: dict[str, int] = Field(default_factory=dict)
    llm_profiles: list[ProjectLLMProfileRequest] = Field(default_factory=list)
    embedding_profiles: list[ProjectEmbeddingProfileRequest] = Field(default_factory=list)
    assignments: dict[str, Any] = Field(default_factory=dict)
    prompt_catalog: dict[str, str] = Field(default_factory=dict)


class ProjectLLMProfileRequest(BaseModel):
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


class ProjectEmbeddingProfileRequest(BaseModel):
    id: str
    label: str
    model_name: str


class ProjectModelSettingsUpdateRequest(BaseModel):
    llm_profiles: list[ProjectLLMProfileRequest] = Field(default_factory=list)
    embedding_profiles: list[ProjectEmbeddingProfileRequest] = Field(default_factory=list)
    execution_intent: Literal["local_first", "api_first", "blended"] = "local_first"
    routing_policy: dict[str, Literal["local", "api"]] = Field(default_factory=dict)
    concurrency_policy: dict[str, int] = Field(default_factory=dict)
    assignments: dict[str, Any] = Field(default_factory=dict)
    prompt_catalog: dict[str, str] = Field(default_factory=dict)
    competitive_intelligence_enabled: bool = True


class ProjectWorkspaceStateUpdateRequest(BaseModel):
    view_mode: Literal["map", "table"] = "map"
    selected_entity_type: Literal["brief", "pillar", "feature"] = "brief"
    selected_entity_id: str = "layer0-root"
    table_scope: Literal["focused", "project"] = "focused"
    map_state: dict[str, Any] = Field(default_factory=dict)
    table_state: dict[str, Any] = Field(default_factory=dict)


class TelemetrySettingsUpdateRequest(BaseModel):
    enabled: bool = True
    capture_prompt_bodies: bool = True
    capture_response_bodies: bool = True
    capture_parsed_results: bool = True


class DataOwnershipSettingsUpdateRequest(BaseModel):
    telemetry_retention_days: int | None = Field(default=None, ge=1)
    telemetry_body_retention_days: int | None = Field(default=None, ge=1)
    research_retention_days: int | None = Field(default=None, ge=1)
    assistant_retention_days: int | None = Field(default=None, ge=1)
    exports_retention_days: int | None = Field(default=None, ge=1)


class DiagnosticsExportRequest(BaseModel):
    include_logs: bool = True
    include_recent_errors: bool = True
    include_traces: bool = True
    log_line_limit: int = Field(ge=1, le=1000, default=400)
    redaction_profile: str = "standard"


class SetupCompleteRequest(BaseModel):
    llama_base_url: str = "http://127.0.0.1:8080"
    model_name: str = "local-model"
    embeddings_enabled: bool = True
    embeddings_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    bearer_token: str = ""
    clear_bearer_token: bool = False
    context_window: int = Field(ge=2048, default=32768)
    max_output_tokens: int = Field(ge=256, le=16000, default=1800)
    runtime_preset: str = ""


class AssistantConversationCreateRequest(BaseModel):
    title: str = "New conversation"
    home_scope: Literal["overall", "layer0", "layer1", "layer2", "layer3"] = "overall"


class AssistantConversationUpdateRequest(BaseModel):
    title: str | None = None
    archived: bool | None = None


class AssistantMessageCreateRequest(BaseModel):
    content: str
    request_id: str
    active_scope: Literal["overall", "layer0", "layer1", "layer2", "layer3"] = "overall"
    focus: dict[str, Any] = Field(default_factory=dict)
    reference_conversation_ids: list[str] = Field(default_factory=list)
    execution_intent_override: Literal["local_first", "api_first", "blended"] | None = None
    thinking_enabled: bool = False
    deep_mode: bool = False


class AssistantActionDecisionRequest(BaseModel):
    decision: Literal["apply", "reject"]


class OverlapVerdictResolutionRequest(BaseModel):
    action: Literal["accept_merge", "link", "dismiss", "keep_separate", "needs_followup"]
    note: str = ""
    resolved_by: str = "user"
    expected_state_token: str | None = None
    request_id: str | None = None


class CriticFindingResolutionRequest(BaseModel):
    action: Literal["accepted", "dismissed", "superseded"]
    note: str = ""
    resolved_by: str = "user"
    expected_state_token: str | None = None
    request_id: str | None = None


class AppSnapshotResponse(BaseModel):
    project: dict[str, Any]
    brief: dict[str, Any] | None = None
    project_model_settings: dict[str, Any] | None = None
    workspace_state: dict[str, Any] | None = None
    brief_conversation: list[dict[str, Any]] = Field(default_factory=list)
    nodes: list[dict[str, Any]]
    tree: list[dict[str, Any]]
    memory: list[dict[str, Any]]
    research_jobs: list[dict[str, Any]] = Field(default_factory=list)
    platform_jobs: list[dict[str, Any]] = Field(default_factory=list)
    research_findings: list[dict[str, Any]] = Field(default_factory=list)
    critic_findings: list[dict[str, Any]] = Field(default_factory=list)
    layer2_graph: dict[str, Any] = Field(default_factory=dict)
    overlap: dict[str, Any] = Field(default_factory=dict)
    layer3: dict[str, Any] = Field(default_factory=dict)


class ModelProfileResponse(BaseModel):
    alias: str
    display_name: str
    path: str | None


class AppConfigResponse(BaseModel):
    database_backend: str
    database_target: str
    llama_base_url: str
    llm_model_name: str
    preferred_model_path: str | None
    exports_dir: str
    default_model_alias: str | None
    embeddings_model_name: str
    has_bearer_token: bool = False
    context_window: int = Field(ge=2048, default=32768)
    max_output_tokens: int = Field(ge=256, le=16000, default=1800)
    embedding_model_presets: list[str] = Field(default_factory=list)
    provider_readiness: dict[str, Any] = Field(default_factory=dict)
    runtime_presets: list[dict[str, Any]] = Field(default_factory=list)
    model_profiles: list[ModelProfileResponse]
    execution_intent: Literal["local_first", "api_first", "blended"] = "local_first"
    routing_policy: dict[str, Literal["local", "api"]] = Field(default_factory=dict)
    concurrency_policy: dict[str, int] = Field(default_factory=dict)
    llm_profiles: list[ProjectLLMProfileRequest] = Field(default_factory=list)
    embedding_profiles: list[ProjectEmbeddingProfileRequest] = Field(default_factory=list)
    assignments: dict[str, Any] = Field(default_factory=dict)
    prompt_catalog: dict[str, str] = Field(default_factory=dict)
