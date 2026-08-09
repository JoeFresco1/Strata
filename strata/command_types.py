from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Literal


class ActorType(StrEnum):
    HUMAN = "human"
    SYSTEM = "system"
    IMPORT = "import"
    MIGRATION = "migration"
    MODEL = "model"


class CommandOrigin(StrEnum):
    UI = "ui"
    ASSISTANT_CONFIRMED = "assistant_confirmed"
    SYSTEM_WORKFLOW = "system_workflow"
    IMPORT = "import"
    MIGRATION = "migration"
    MODEL_GENERATION = "model_generation"
    API = "api"


@dataclass(frozen=True, kw_only=True)
class CommandActor:
    """Normalized trusted actor metadata carried by every authoritative command."""

    actor_id: str
    actor_type: ActorType
    origin: CommandOrigin

    @classmethod
    def human_ui(cls, actor_id: str = "user") -> "CommandActor":
        return cls(actor_id=actor_id, actor_type=ActorType.HUMAN, origin=CommandOrigin.UI)

    @classmethod
    def human_assistant(cls, actor_id: str = "user") -> "CommandActor":
        return cls(actor_id=actor_id, actor_type=ActorType.HUMAN, origin=CommandOrigin.ASSISTANT_CONFIRMED)

    @classmethod
    def system(cls, actor_id: str = "strata") -> "CommandActor":
        return cls(actor_id=actor_id, actor_type=ActorType.SYSTEM, origin=CommandOrigin.SYSTEM_WORKFLOW)


@dataclass(frozen=True, kw_only=True)
class ApplicationCommand:
    project_id: str
    actor: CommandActor
    idempotency_key: str = field(default_factory=lambda: str(uuid.uuid4()))
    expected_state_token: str | None = None


@dataclass(frozen=True)
class StaleEffect:
    """Explicit stale-state declaration returned by every command handler."""

    effect: Literal["none", "marked", "deferred"] = "none"
    artifact_ids: tuple[str, ...] = ()
    reason: str = ""
    directly_affected: tuple[str, ...] = ()
    transitively_affected: tuple[str, ...] = ()
    already_stale: tuple[str, ...] = ()
    propagation_count: int = 0
    complete: bool = True


@dataclass(frozen=True)
class CommandResult:
    """Portable typed success result shared by HTTP, assistant, jobs, and imports."""

    command_id: str
    command_type: str
    project_id: str
    target_type: str
    target_id: str
    state_token: str
    data: dict[str, Any]
    stale_effect: StaleEffect = StaleEffect()
    idempotent: bool = False


class CommandError(Exception):
    """Base application error containing transport-independent structured detail."""

    code = "command_error"

    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.message = message
        self.details = details


class CommandValidationError(CommandError):
    code = "validation_error"


class CommandNotFoundError(CommandError):
    code = "not_found"


class CommandConflictError(CommandError):
    code = "conflict"


class InvalidTransitionError(CommandError):
    code = "invalid_transition"


class HumanAuthorityRequiredError(CommandError):
    code = "human_authority_required"


class StaleSourceError(CommandError):
    code = "stale_source"


class IdempotencyConflictError(CommandError):
    code = "idempotency_conflict"


def state_token(payload: Any) -> str:
    """Create a stable optimistic-concurrency token from canonical state."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def command_fingerprint(command: ApplicationCommand) -> str:
    """Hash a command without its idempotency key so key reuse can be validated."""
    payload = asdict(command)
    payload.pop("idempotency_key", None)
    return state_token(payload)


# Layer 0
@dataclass(frozen=True, kw_only=True)
class UpdateBriefDraft(ApplicationCommand):
    updates: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class AppendBriefPlanTurn(ApplicationCommand):
    message: str


@dataclass(frozen=True, kw_only=True)
class PublishBrief(ApplicationCommand):
    request_research: bool = False


# Product Discovery
@dataclass(frozen=True, kw_only=True)
class GenerateProductDiscovery(ApplicationCommand):
    competitor_research_mode: Literal[
        "no_competitor_research", "lightweight_competitor_scan", "deep_competitor_research"
    ] = "no_competitor_research"
    competitor_research_revision_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class ApproveProductDiscoveryRevision(ApplicationCommand):
    revision_id: str


@dataclass(frozen=True, kw_only=True)
class PublishProductDiscoveryRevision(ApplicationCommand):
    revision_id: str


@dataclass(frozen=True, kw_only=True)
class RejectProductDiscoveryRevision(ApplicationCommand):
    revision_id: str
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class RestoreProductDiscoveryRevision(ApplicationCommand):
    revision_id: str


@dataclass(frozen=True, kw_only=True)
class UpdateDiscoveryHumanFields(ApplicationCommand):
    revision_id: str
    updates: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class AddHumanDiscoveryLens(ApplicationCommand):
    revision_id: str
    lens: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class ExcludeDiscoveryLens(ApplicationCommand):
    revision_id: str
    lens_id: str
    excluded: bool = True


@dataclass(frozen=True, kw_only=True)
class RequestDiscoveryRegeneration(GenerateProductDiscovery):
    pass


@dataclass(frozen=True, kw_only=True)
class BuildLayer1DiscoveryContextProjection(ApplicationCommand):
    revision_id: str


# Layer 1 territory exploration
@dataclass(frozen=True, kw_only=True)
class StartLayer1TerritoryExpansion(ApplicationCommand):
    config: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RunLayer1LensAttempt(ApplicationCommand):
    run_id: str
    lens_execution_id: str


@dataclass(frozen=True, kw_only=True)
class RetryLayer1LensWithTemperature(RunLayer1LensAttempt):
    temperature: float


@dataclass(frozen=True, kw_only=True)
class RetryLayer1LensWithStrongerExclusions(RunLayer1LensAttempt):
    pass


@dataclass(frozen=True, kw_only=True)
class MarkLayer1LensComplete(ApplicationCommand):
    run_id: str
    lens_execution_id: str
    state: Literal[
        "saturated",
        "covered_with_subordinate_territory",
        "intentionally_excluded",
        "requires_human_decision",
        "blocked_by_model",
        "budget_exhausted",
        "cancelled",
    ]


@dataclass(frozen=True, kw_only=True)
class ReopenLayer1Lens(ApplicationCommand):
    run_id: str
    lens_execution_id: str


@dataclass(frozen=True, kw_only=True)
class AddClosedTerritory(ApplicationCommand):
    run_id: str | None
    title: str
    description: str = ""
    semantic_examples: tuple[str, ...] = ()
    scope: Literal["run", "project"] = "run"
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class RemoveClosedTerritory(ApplicationCommand):
    logical_id: str
    run_id: str | None = None
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class AddAntiGenericPattern(ApplicationCommand):
    title: str
    description: str = ""
    semantic_examples: tuple[str, ...] = ()
    source_run_ids: tuple[str, ...] = ()
    confidence: float = 0.5
    scope: str = "project"


@dataclass(frozen=True, kw_only=True)
class DisableAntiGenericPattern(ApplicationCommand):
    logical_id: str


@dataclass(frozen=True, kw_only=True)
class ClassifyTerritoryCandidate(ApplicationCommand):
    candidate_id: str
    destination: str
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class ReclassifyTerritoryCandidate(ClassifyTerritoryCandidate):
    pass


@dataclass(frozen=True, kw_only=True)
class PromoteTerritoryToPillarCandidate(ApplicationCommand):
    candidate_id: str
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class RouteTerritoryToLayer2(ApplicationCommand):
    candidate_id: str
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class RunLayer1AdversarialPass(ApplicationCommand):
    run_id: str
    role: str = "skeptical implementation consultant"


@dataclass(frozen=True, kw_only=True)
class BuildLayer1SynthesisContext(ApplicationCommand):
    run_id: str


@dataclass(frozen=True, kw_only=True)
class GenerateLayer1ArchitectureCandidates(ApplicationCommand):
    run_id: str


@dataclass(frozen=True, kw_only=True)
class SelectLayer1ArchitectureCandidate(ApplicationCommand):
    run_id: str
    architecture_candidate_id: str
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class ApplyLayer1ArchitectureCandidate(ApplicationCommand):
    run_id: str
    architecture_candidate_id: str
    expected_current_pillar_tokens: dict[str, str] = field(default_factory=dict)
    confirm_replace: bool = False
    acknowledge_unresolved_risks: bool = False
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class CreateHybridLayer1Architecture(ApplicationCommand):
    run_id: str
    title: str
    rationale: str
    pillars: tuple[dict[str, Any], ...]
    mappings: tuple[dict[str, Any], ...]
    significant_non_pillar_territory_ids: tuple[str, ...] = ()
    unresolved_risk_ids: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class CancelLayer1ExpansionRun(ApplicationCommand):
    run_id: str


# Competitor research
@dataclass(frozen=True, kw_only=True)
class StartCompetitorResearch(ApplicationCommand):
    scope: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class CancelCompetitorResearch(ApplicationCommand):
    job_id: str


@dataclass(frozen=True, kw_only=True)
class ApproveCompetitorResearchRevision(ApplicationCommand):
    revision_id: str


@dataclass(frozen=True, kw_only=True)
class RejectCompetitorResearchRevision(ApplicationCommand):
    revision_id: str
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class AttachCompetitorResearchToDiscovery(ApplicationCommand):
    discovery_revision_id: str
    competitor_research_revision_id: str


@dataclass(frozen=True, kw_only=True)
class DetachCompetitorResearchFromDiscovery(ApplicationCommand):
    discovery_revision_id: str


@dataclass(frozen=True, kw_only=True)
class ExcludeCompetitorFinding(ApplicationCommand):
    revision_id: str
    finding_id: str


@dataclass(frozen=True, kw_only=True)
class IncludeCompetitorFinding(ApplicationCommand):
    revision_id: str
    finding_id: str
    context_state: Literal["required", "optional"] = "optional"


@dataclass(frozen=True, kw_only=True)
class MarkCompetitorFindingStale(ApplicationCommand):
    revision_id: str
    finding_id: str


@dataclass(frozen=True, kw_only=True)
class AddCompetitor(ApplicationCommand):
    revision_id: str
    competitor_name: str


@dataclass(frozen=True, kw_only=True)
class RemoveCompetitor(ApplicationCommand):
    revision_id: str
    competitor_id: str


@dataclass(frozen=True, kw_only=True)
class RefreshCompetitorResearch(ApplicationCommand):
    revision_id: str
    competitor_ids: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()
    stale_only: bool = False


@dataclass(frozen=True, kw_only=True)
class RebuildCompetitiveContextProjection(ApplicationCommand):
    discovery_revision_id: str
    competitor_research_revision_id: str


# Layer 1
@dataclass(frozen=True, kw_only=True)
class CreatePillar(ApplicationCommand):
    title: str
    description: str = ""
    status: str = "kept"
    priority: int | None = None


@dataclass(frozen=True, kw_only=True)
class EditPillar(ApplicationCommand):
    pillar_id: str
    title: str | None = None
    description: str | None = None
    priority: int | None = None
    status: str | None = None


@dataclass(frozen=True, kw_only=True)
class KeepPillar(ApplicationCommand):
    pillar_id: str


@dataclass(frozen=True, kw_only=True)
class CutPillar(ApplicationCommand):
    pillar_id: str


@dataclass(frozen=True, kw_only=True)
class PrioritizePillar(ApplicationCommand):
    pillar_id: str
    priority: int = 7


@dataclass(frozen=True, kw_only=True)
class RenamePillar(ApplicationCommand):
    pillar_id: str
    title: str


@dataclass(frozen=True, kw_only=True)
class MergePillars(ApplicationCommand):
    source_pillar_id: str
    target_pillar_id: str
    expected_target_state_token: str | None = None


@dataclass(frozen=True, kw_only=True)
class BulkSetPillarState(ApplicationCommand):
    pillar_ids: tuple[str, ...]
    status: Literal["kept", "cut", "prioritized"]
    expected_state_tokens: dict[str, str] = field(default_factory=dict)


# Layer 2
@dataclass(frozen=True, kw_only=True)
class CreateFeature(ApplicationCommand):
    canonical_name: str
    description: str
    owner_pillar_id: str
    feature_type: str = "capability"
    granularity_class: str = "feature"
    aliases: tuple[str, ...] = ()
    status: str = "candidate"
    coverage_family: str = ""
    priority: str = ""
    notes: str = ""


@dataclass(frozen=True, kw_only=True)
class EditFeature(ApplicationCommand):
    feature_id: str
    updates: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class KeepFeature(ApplicationCommand):
    feature_id: str


@dataclass(frozen=True, kw_only=True)
class CutFeature(ApplicationCommand):
    feature_id: str


@dataclass(frozen=True, kw_only=True)
class ApproveFeature(ApplicationCommand):
    feature_id: str


@dataclass(frozen=True, kw_only=True)
class MarkFeatureNeedsReview(ApplicationCommand):
    feature_id: str


@dataclass(frozen=True, kw_only=True)
class RenameFeature(ApplicationCommand):
    feature_id: str
    title: str
    description: str | None = None


@dataclass(frozen=True, kw_only=True)
class MergeFeatures(ApplicationCommand):
    source_feature_id: str
    target_feature_id: str
    expected_target_state_token: str | None = None
    rationale: str = "Reviewer merged duplicate Layer 2 features."


@dataclass(frozen=True, kw_only=True)
class ResolveFeatureReview(ApplicationCommand):
    feature_id: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    target_feature_id: str | None = None
    owner_pillar_id: str | None = None
    relationship_type: str | None = None
    title: str | None = None
    description: str | None = None


@dataclass(frozen=True, kw_only=True)
class BulkResolveFeatureReview(ApplicationCommand):
    feature_ids: tuple[str, ...]
    action: Literal["approve_for_layer3", "cut", "keep", "needs_review"]
    expected_state_tokens: dict[str, str] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class CreateOrUpdateFeatureRelationship(ApplicationCommand):
    source_feature_id: str
    target_feature_id: str
    relationship_type: str
    strength: float = 1.0
    rationale: str = ""
    expected_target_state_token: str | None = None


@dataclass(frozen=True, kw_only=True)
class RemoveFeatureRelationship(ApplicationCommand):
    source_feature_id: str
    target_feature_id: str
    relationship_type: str | None = None
    expected_target_state_token: str | None = None


# Layer 3
@dataclass(frozen=True, kw_only=True)
class GenerateLayer3Candidate(ApplicationCommand):
    feature_ids: tuple[str, ...]
    thinking_enabled: bool = False
    generation_reference: str | None = None


@dataclass(frozen=True, kw_only=True)
class AcceptLayer3Candidate(ApplicationCommand):
    expansion_id: str
    candidate_revision_id: str


@dataclass(frozen=True, kw_only=True)
class PartiallyAcceptLayer3Candidate(AcceptLayer3Candidate):
    selected_sections: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class RejectLayer3Candidate(ApplicationCommand):
    expansion_id: str
    candidate_revision_id: str
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class RestoreLayer3Revision(ApplicationCommand):
    expansion_id: str
    revision_id: str


@dataclass(frozen=True, kw_only=True)
class EditLayer3ActiveRevision(ApplicationCommand):
    expansion_id: str
    updates: dict[str, Any]


@dataclass(frozen=True, kw_only=True)
class ReviewLayer3ActiveRevision(ApplicationCommand):
    expansion_id: str
    review_state: Literal["approved", "rejected", "needs_review"]
    note: str = ""


# Findings and overlap
@dataclass(frozen=True, kw_only=True)
class ResolveCriticFinding(ApplicationCommand):
    finding_id: str
    resolution: Literal["accepted", "dismissed", "superseded"]
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class DismissCriticFinding(ApplicationCommand):
    finding_id: str
    note: str = ""
    resolution: Literal["dismissed"] = "dismissed"


@dataclass(frozen=True, kw_only=True)
class ReopenCriticFinding(ApplicationCommand):
    finding_id: str


@dataclass(frozen=True, kw_only=True)
class ResolveOverlapVerdict(ApplicationCommand):
    layer: Literal["layer1", "layer2"]
    verdict_id: str
    action: str
    note: str = ""


# Workflow requests
@dataclass(frozen=True, kw_only=True)
class RequestLayer1Generation(ApplicationCommand):
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RequestLayer2Generation(ApplicationCommand):
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class RequestLayer3Generation(ApplicationCommand):
    feature_ids: tuple[str, ...]
    thinking_enabled: bool = False


@dataclass(frozen=True, kw_only=True)
class RequestResearch(ApplicationCommand):
    layer: Literal["layer0", "layer1", "layer2"]
    artifact_ids: tuple[str, ...] = ()
    reason: str = "manual_rerun"


@dataclass(frozen=True, kw_only=True)
class RequestOverlapReview(ApplicationCommand):
    layer: Literal["layer1", "layer2"]


# Lifecycle
@dataclass(frozen=True, kw_only=True)
class UpdateProjectMetadata(ApplicationCommand):
    name: str
    idea: str


# Specification export
@dataclass(frozen=True, kw_only=True)
class CompileSpecificationManifest(ApplicationCommand):
    """Compile one immutable specification snapshot under an explicit policy mode."""

    mode: Literal["draft", "approved", "historical", "diagnostic"] = "approved"
    historical_brief_revision_id: str = ""


@dataclass(frozen=True, kw_only=True)
class RenderSpecificationManifest(ApplicationCommand):
    """Render JSON and/or Markdown from one already persisted manifest."""

    manifest_id: str
    formats: tuple[Literal["json", "markdown"], ...] = ("json", "markdown")


@dataclass(frozen=True, kw_only=True)
class ArchiveProject(ApplicationCommand):
    pass


@dataclass(frozen=True, kw_only=True)
class UnarchiveProject(ApplicationCommand):
    pass


@dataclass(frozen=True, kw_only=True)
class ImportProjectArchive(ApplicationCommand):
    archive_path: str
