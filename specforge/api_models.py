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
    min_new_items_per_round: int = 2
    stale_rounds_to_stop: int = 2


class Layer2GenerateRequest(BaseModel):
    pillar_ids: list[str] = Field(default_factory=list)
    thinking_enabled: bool = False
    max_rounds: int = 5
    target_per_round: int = 10
    min_new_items_per_round: int = 2
    stale_rounds_to_stop: int = 2


class Layer3GenerateRequest(BaseModel):
    subfeature_ids: list[str] = Field(default_factory=list)
    thinking_enabled: bool = False


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


class EmbeddingSettingsUpdateRequest(BaseModel):
    embeddings_model_name: str


class RuntimeModelSettingsUpdateRequest(BaseModel):
    llama_base_url: str
    llm_model_name: str
    preferred_model_path: str = ""
    embeddings_model_name: str
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


class ProjectEmbeddingProfileRequest(BaseModel):
    id: str
    label: str
    model_name: str


class ProjectModelSettingsUpdateRequest(BaseModel):
    llm_profiles: list[ProjectLLMProfileRequest] = Field(default_factory=list)
    embedding_profiles: list[ProjectEmbeddingProfileRequest] = Field(default_factory=list)
    assignments: dict[str, Any] = Field(default_factory=dict)
    prompt_catalog: dict[str, str] = Field(default_factory=dict)


class AppSnapshotResponse(BaseModel):
    project: dict[str, Any]
    brief: dict[str, Any] | None = None
    project_model_settings: dict[str, Any] | None = None
    brief_conversation: list[dict[str, Any]] = Field(default_factory=list)
    nodes: list[dict[str, Any]]
    tree: list[dict[str, Any]]
    memory: list[dict[str, Any]]
    research_jobs: list[dict[str, Any]] = Field(default_factory=list)
    research_findings: list[dict[str, Any]] = Field(default_factory=list)
    layer2_graph: dict[str, Any] = Field(default_factory=dict)


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
    embedding_model_presets: list[str] = Field(default_factory=list)
    model_profiles: list[ModelProfileResponse]
    llm_profiles: list[ProjectLLMProfileRequest] = Field(default_factory=list)
    embedding_profiles: list[ProjectEmbeddingProfileRequest] = Field(default_factory=list)
    assignments: dict[str, Any] = Field(default_factory=dict)
    prompt_catalog: dict[str, str] = Field(default_factory=dict)
