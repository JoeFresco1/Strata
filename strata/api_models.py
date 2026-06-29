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


class ProjectArchiveImportResponse(BaseModel):
    project: dict[str, Any]
    lifecycle_warnings: list[str] = Field(default_factory=list)


class ProjectBriefUpdateRequest(BaseModel):
    product_idea: str
    known_competitors: list[str] = Field(default_factory=list)
    constraints: str = ""
    target_users: str = ""
    goals: list[str] = Field(default_factory=list)
    preferred_directions: list[str] = Field(default_factory=list)
    rejected_directions: list[str] = Field(default_factory=list)
    notes: str = ""


class Layer0ChatRequest(BaseModel):
    message: str
    request_id: str | None = None


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


class Layer1GenerateRequest(BaseModel):
    model_aliases: list[str] = Field(default_factory=list)
    thinking_enabled: bool = False
    max_rounds: int = 6
    target_per_round: int = 12
    total_cap: int | None = Field(default=None, ge=1)
    min_new_items_per_round: int = 2
    stale_rounds_to_stop: int = 2


class Layer1PillarCreateRequest(BaseModel):
    title: str
    description: str = ""
    status: Literal["generated", "kept", "cut", "merged", "prioritized"] = "kept"
    priority: int = Field(default=0, ge=0, le=10)

    @field_validator("title")
    @classmethod
    def require_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Manual Layer 1 pillars require a title.")
        return cleaned


class Layer2GenerateRequest(BaseModel):
    pillar_ids: list[str] = Field(default_factory=list)
    thinking_enabled: bool = False
    max_rounds: int = 5
    target_per_round: int = 10
    total_cap: int | None = Field(default=None, ge=1)
    min_new_items_per_round: int = 2
    stale_rounds_to_stop: int = 2


class Layer3GenerateRequest(BaseModel):
    feature_ids: list[str] = Field(default_factory=list)
    thinking_enabled: bool = False
    selected_sections: list[str] = Field(default_factory=list)


class Layer3RelationshipUpdateRequest(BaseModel):
    target_feature_id: str
    relationship_type: Literal[
        "depends_on",
        "feeds",
        "overlaps_with",
        "conflicts_with",
        "optionally_uses",
        "shared_concern",
    ]
    rationale: str = ""

    @field_validator("target_feature_id")
    @classmethod
    def required_relationship_target(cls, value: str) -> str:
        """Require every edited relationship to identify a concrete Layer 2 feature."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Layer 3 relationships require a target feature.")
        return cleaned


class Layer3DecisionDraftRequest(BaseModel):
    question: str
    context: str = ""
    options: list[str] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def required_question(cls, value: str) -> str:
        """Keep edited decisions reviewable and safe to persist."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Layer 3 decisions require a question.")
        return cleaned

    @field_validator("options")
    @classmethod
    def clean_decision_options(cls, value: list[str]) -> list[str]:
        """Remove blank decision options before persistence."""
        return [item.strip() for item in value if item.strip()]


class Layer3CardUpdateRequest(BaseModel):
    product_purpose: str | None = None
    feature_archetype: str | None = None
    supported_variants: list[dict[str, Any]] | None = None
    configurable_options: list[dict[str, Any]] | None = None
    product_behaviors: list[dict[str, Any]] | None = None
    validation_constraints: list[dict[str, Any]] | None = None
    lifecycle_states: list[dict[str, Any]] | None = None
    dependencies: list[str] | None = None
    overlaps_conflicts: list[str] | None = None
    edge_cases: list[str] | None = None
    product_risks: list[str] | None = None
    relationships: list[Layer3RelationshipUpdateRequest] | None = None
    open_decisions: list[Layer3DecisionDraftRequest] | None = None

    @field_validator("product_purpose", "feature_archetype")
    @classmethod
    def non_blank_card_text(cls, value: str | None) -> str | None:
        """Reject blank identity fields while allowing omitted partial updates."""
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Layer 3 purpose and archetype cannot be blank.")
        return cleaned


class Layer3ReviewRequest(BaseModel):
    action: Literal["approve", "reject", "needs_review"]
    note: str = ""


class Layer3PressureTestRequest(BaseModel):
    thinking_enabled: bool = False


class Layer3DecisionUpdateRequest(BaseModel):
    status: Literal["resolved", "unresolved"]
    resolution: str = ""


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


class Layer2ResearchStartRequest(BaseModel):
    feature_ids: list[str] = Field(default_factory=list)


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
    research_findings: list[dict[str, Any]] = Field(default_factory=list)
    layer2_graph: dict[str, Any] = Field(default_factory=dict)
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
