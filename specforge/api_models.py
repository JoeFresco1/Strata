from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
