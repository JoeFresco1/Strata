from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field


SPECIFICATION_SCHEMA_VERSION = "strata.specification.v1"
COMPILATION_POLICY_VERSION = "specification-selection.v1"


def specification_content_hash(payload: dict[str, Any]) -> str:
    """Hash canonical specification content while excluding record identity and timestamps."""
    content = {
        key: payload.get(key)
        for key in (
            "schema_version", "compilation_policy_version", "mode", "exportable", "project",
            "root_lineage", "layer1", "layer2", "layer3", "relationships",
            "validation_summary", "memberships", "issues",
        )
    }
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class CompilationMode(StrEnum):
    """Explicit selection semantics for a compiled specification."""

    DRAFT = "draft"
    APPROVED = "approved"
    HISTORICAL = "historical"
    DIAGNOSTIC = "diagnostic"


class ManifestIssue(BaseModel):
    """Stable machine-readable compiler finding."""

    code: str
    stage: Literal["source_integrity", "state_approval", "structural", "semantic", "policy"]
    severity: Literal["info", "warning", "error"]
    message: str
    artifact_type: str = ""
    artifact_id: str = ""
    artifact_revision: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ManifestMembership(BaseModel):
    """One ordered canonical source included in an immutable manifest."""

    layer: int = Field(ge=0, le=3)
    artifact_type: str
    logical_artifact_id: str
    artifact_revision: str
    content_token: str
    inclusion_reason: str
    ordinal: int = Field(ge=0)
    dependency_metadata: dict[str, Any] = Field(default_factory=dict)
    authority_metadata: dict[str, Any] = Field(default_factory=dict)


class SpecificationManifestV1(BaseModel):
    """Durable canonical specification snapshot consumed by every renderer."""

    manifest_id: str
    project_id: str
    schema_version: Literal["strata.specification.v1"] = SPECIFICATION_SCHEMA_VERSION
    sequence_number: int = Field(ge=1)
    created_at: datetime
    actor: str
    origin: str
    command_id: str
    compilation_policy_version: str = COMPILATION_POLICY_VERSION
    mode: CompilationMode
    status: Literal["compiled", "invalid"]
    content_hash: str
    exportable: bool
    imported_historical: bool = False
    import_metadata: dict[str, Any] = Field(default_factory=dict)
    project: dict[str, Any]
    root_lineage: dict[str, Any]
    layer1: list[dict[str, Any]] = Field(default_factory=list)
    layer2: list[dict[str, Any]] = Field(default_factory=list)
    layer3: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    validation_summary: dict[str, Any]
    provenance_summary: dict[str, Any]
    memberships: list[ManifestMembership] = Field(default_factory=list)
    issues: list[ManifestIssue] = Field(default_factory=list)


class RenderedSpecificationArtifact(BaseModel):
    """Durable identity for bytes rendered from one stored manifest."""

    id: str
    manifest_id: str
    project_id: str
    format: Literal["json", "markdown"]
    renderer_version: str
    content_hash: str
    path: str
    command_id: str
    created_at: datetime
