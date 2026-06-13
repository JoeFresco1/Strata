from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


NodeStatus = Literal["generated", "kept", "cut", "merged", "prioritized"]
NodeType = Literal["product_idea", "pillar", "subfeature", "spec"]


class Project(BaseModel):
    id: str
    name: str
    idea: str
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


class PillarCandidate(BaseModel):
    title: str
    description: str
    why_it_matters: str
    risks: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class SubfeatureCandidate(BaseModel):
    title: str
    description: str
    user_value: str
    complexity: Literal["low", "medium", "high"]
    dependencies: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class UserStory(BaseModel):
    as_a: str
    i_want: str
    so_that: str


class SpecPayload(BaseModel):
    overview: str
    user_personas: list[str] = Field(default_factory=list)
    user_stories: list[UserStory] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    core_logic: list[str] = Field(default_factory=list)
    edge_cases: list[str] = Field(default_factory=list)
    ux_screens: list[str] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    implementation_notes: list[str] = Field(default_factory=list)


class PillarResponse(BaseModel):
    pillars: list[PillarCandidate]


class SubfeatureResponse(BaseModel):
    subfeatures: list[SubfeatureCandidate]


class SpecResponse(BaseModel):
    spec: SpecPayload


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
