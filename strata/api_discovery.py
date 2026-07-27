from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from strata.command_types import (
    AddCompetitor,
    AddHumanDiscoveryLens,
    ApproveCompetitorResearchRevision,
    ApproveProductDiscoveryRevision,
    AttachCompetitorResearchToDiscovery,
    BuildLayer1DiscoveryContextProjection,
    CancelCompetitorResearch,
    CommandActor,
    CommandError,
    DetachCompetitorResearchFromDiscovery,
    ExcludeCompetitorFinding,
    ExcludeDiscoveryLens,
    GenerateProductDiscovery,
    IncludeCompetitorFinding,
    MarkCompetitorFindingStale,
    PublishProductDiscoveryRevision,
    RebuildCompetitiveContextProjection,
    RefreshCompetitorResearch,
    RejectCompetitorResearchRevision,
    RejectProductDiscoveryRevision,
    RemoveCompetitor,
    RequestDiscoveryRegeneration,
    RestoreProductDiscoveryRevision,
    StartCompetitorResearch,
    UpdateDiscoveryHumanFields,
)


class DiscoveryGenerateRequest(BaseModel):
    """Explicit Product Discovery job configuration."""

    competitor_research_mode: Literal[
        "no_competitor_research", "lightweight_competitor_scan", "deep_competitor_research"
    ] = "no_competitor_research"
    competitor_research_revision_id: str | None = None
    request_id: str | None = None


class RevisionActionRequest(BaseModel):
    """Shared optimistic concurrency fields for discovery authority actions."""

    expected_state_token: str | None = None
    request_id: str | None = None
    note: str = ""


class DiscoveryHumanFieldsRequest(RevisionActionRequest):
    """Human-authored annotations and downstream decisions."""

    updates: dict[str, Any] = Field(default_factory=dict)


class HumanLensRequest(RevisionActionRequest):
    """One complete human-authored discovery lens."""

    lens: dict[str, Any]


class LensDecisionRequest(RevisionActionRequest):
    """Human inclusion or exclusion state for one lens."""

    excluded: bool = True


class CompetitorResearchStartRequest(BaseModel):
    """Explicit bounded lightweight or deep research configuration."""

    mode: Literal["lightweight_competitor_scan", "deep_competitor_research"]
    competitor_names: list[str] = Field(default_factory=list)
    max_competitors: int | None = Field(default=None, ge=1, le=50)
    source_budget: int | None = Field(default=None, ge=1, le=1000)
    time_budget_seconds: int | None = Field(default=None, ge=1, le=86400)
    per_competitor_source_limit: int | None = Field(default=None, ge=1, le=200)
    approved_secondary_sources: bool = False
    request_id: str | None = None


class CompetitorAttachmentRequest(RevisionActionRequest):
    """Approved research revision selected for a discovery candidate."""

    competitor_research_revision_id: str


class CompetitorFindingDecisionRequest(RevisionActionRequest):
    """Human downstream context decision for a competitor finding."""

    context_state: Literal["required", "optional", "excluded", "stale"]


class AddCompetitorRequest(RevisionActionRequest):
    """Human-approved competitor addition."""

    competitor_name: str


class RefreshResearchRequest(RevisionActionRequest):
    """Selective or stale-only competitor research refresh."""

    competitor_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    stale_only: bool = False


def register_discovery_routes(app: FastAPI, services: Any) -> None:
    """Register Product Discovery and competitor-research API surfaces."""

    @app.get("/api/projects/{project_id}/discovery")
    def get_discovery(project_id: str) -> dict[str, Any]:
        """Return the canonical discovery snapshot including revision history."""
        services.db.get_project(project_id)
        return services.db.discovery_snapshot(project_id)

    @app.get("/api/projects/{project_id}/discovery/revisions")
    def list_discovery_revisions(project_id: str) -> list[dict[str, Any]]:
        """List immutable and candidate discovery revisions."""
        return [
            item.model_dump(mode="json")
            for item in services.db.list_discovery_revisions(project_id)
        ]

    @app.get("/api/projects/{project_id}/discovery/candidate")
    def get_discovery_candidate(project_id: str) -> dict[str, Any] | None:
        """Return the current candidate without conflating it with publication."""
        return services.db.discovery_snapshot(project_id)["current_candidate"]

    @app.get("/api/projects/{project_id}/discovery/published")
    def get_published_discovery(project_id: str) -> dict[str, Any] | None:
        """Return only the discovery revision selected for downstream use."""
        return services.db.discovery_snapshot(project_id)["published"]

    @app.get("/api/projects/{project_id}/discovery/revisions/{revision_id}/raw")
    def get_discovery_raw_response(project_id: str, revision_id: str) -> dict[str, Any]:
        """Expose retained raw generation output for audit."""
        revision = _project_discovery_revision(services, project_id, revision_id)
        return {
            "revision_id": revision.id,
            "raw_response": revision.model_authored_fields.get("raw_response", ""),
            "parsed_response": revision.model_authored_fields.get("parsed_response", {}),
        }

    @app.get("/api/projects/{project_id}/discovery/revisions/{revision_id}/review")
    def get_discovery_review(project_id: str, revision_id: str) -> list[dict[str, Any]]:
        """Return non-destructive practicality and evidence findings."""
        revision = _project_discovery_revision(services, project_id, revision_id)
        return [item.model_dump(mode="json") for item in revision.review_findings]

    @app.get("/api/projects/{project_id}/discovery/revisions/{left_id}/compare/{right_id}")
    def compare_discovery_revisions(project_id: str, left_id: str, right_id: str) -> dict[str, Any]:
        """Compare nested stable IDs without forcing domain normalization."""
        left = _project_discovery_revision(services, project_id, left_id)
        right = _project_discovery_revision(services, project_id, right_id)
        return _compare_discovery(left.discovery.model_dump(mode="json"), right.discovery.model_dump(mode="json"))

    @app.get("/api/projects/{project_id}/discovery/context")
    def get_discovery_context(project_id: str) -> dict[str, Any]:
        """Return the latest deterministic Layer 1 and competitive projections."""
        services.db.get_project(project_id)
        projections = services.db.list_discovery_context_projections(project_id)
        return {
            "layer1_discovery": next(
                (item for item in reversed(projections) if item["projection_type"] == "layer1_discovery"),
                None,
            ),
            "competitive": next(
                (item for item in reversed(projections) if item["projection_type"] == "competitive"),
                None,
            ),
            "history": projections,
        }

    @app.get("/api/projects/{project_id}/discovery/competitor-research")
    def get_competitor_research(project_id: str) -> dict[str, Any]:
        """Return current research, immutable history, evidence, and freshness."""
        services.db.get_project(project_id)
        return services.db.discovery_snapshot(project_id)["competitor_research"]

    @app.get("/api/projects/{project_id}/discovery/competitor-research/{revision_id}")
    def get_competitor_research_revision(project_id: str, revision_id: str) -> dict[str, Any]:
        """Return one research revision including sources and checkpoint state."""
        revision = _project_competitor_revision(services, project_id, revision_id)
        return {
            **revision.model_dump(mode="json"),
            "state_token": services.command_service.competitor_research_state_token(revision),
        }

    @app.get("/api/projects/{project_id}/discovery/competitor-research/{revision_id}/sources")
    def get_competitor_sources(project_id: str, revision_id: str) -> dict[str, Any]:
        """Expose retained source metadata and evidence without inference ambiguity."""
        revision = _project_competitor_revision(services, project_id, revision_id)
        return {
            "revision_id": revision.id,
            "mode": revision.scope.mode.value,
            "research_date": revision.research_date,
            "last_verified_at": revision.last_verified_at,
            "freshness_state": revision.freshness_state,
            "stale_reason": revision.stale_reason,
            "evidence": [item.model_dump(mode="json") for item in revision.evidence],
        }

    @app.get("/api/projects/{project_id}/discovery/competitor-research/{left_id}/compare/{right_id}")
    def compare_competitor_research(project_id: str, left_id: str, right_id: str) -> dict[str, Any]:
        """Compare competitive findings by stable identity and retained decisions."""
        left = _project_competitor_revision(services, project_id, left_id)
        right = _project_competitor_revision(services, project_id, right_id)
        return {
            "profiles": _compare_items(left.profiles, right.profiles),
            "evidence": _compare_items(left.evidence, right.evidence),
            "inferred_pillars": _compare_items(left.inferred_pillars, right.inferred_pillars),
            "territories": _compare_items(left.territories, right.territories),
            "gaps": _compare_items(left.gaps, right.gaps),
            "derived_lenses": _compare_items(left.derived_lenses, right.derived_lenses),
            "human_decisions_changed": left.human_decisions != right.human_decisions,
        }

    @app.post("/api/projects/{project_id}/discovery/generate")
    def generate_discovery(
        project_id: str,
        request: DiscoveryGenerateRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """Queue user-triggered Product Discovery generation."""
        command = GenerateProductDiscovery(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            idempotency_key=request.request_id or str(uuid.uuid4()),
            competitor_research_mode=request.competitor_research_mode,
            competitor_research_revision_id=request.competitor_research_revision_id,
        )
        result = _handle(services, command)
        for job_id in result.data.get("job_ids", []):
            background_tasks.add_task(services.job_service.run_job, job_id)
        return result.data

    @app.post("/api/projects/{project_id}/discovery/revisions/{revision_id}/regenerate")
    def regenerate_discovery(
        project_id: str,
        revision_id: str,
        request: DiscoveryGenerateRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """Queue regeneration while preserving prior and human-owned revisions."""
        source = _project_discovery_revision(services, project_id, revision_id)
        result = _handle(services, RequestDiscoveryRegeneration(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            idempotency_key=request.request_id or str(uuid.uuid4()),
            competitor_research_mode=request.competitor_research_mode or source.competitor_research_mode.value,
            competitor_research_revision_id=request.competitor_research_revision_id,
        ))
        for job_id in result.data.get("job_ids", []):
            background_tasks.add_task(services.job_service.run_job, job_id)
        return result.data

    @app.post("/api/projects/{project_id}/discovery/revisions/{revision_id}/approve")
    def approve_discovery(project_id: str, revision_id: str, request: RevisionActionRequest) -> dict[str, Any]:
        """Approve a candidate while leaving publication as a separate action."""
        return _handle(services, ApproveProductDiscoveryRevision(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/revisions/{revision_id}/publish")
    def publish_discovery(project_id: str, revision_id: str, request: RevisionActionRequest) -> dict[str, Any]:
        """Publish approved discovery and compile compact projections without starting Layer 1."""
        return _handle(services, PublishProductDiscoveryRevision(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/revisions/{revision_id}/reject")
    def reject_discovery(project_id: str, revision_id: str, request: RevisionActionRequest) -> dict[str, Any]:
        """Reject a discovery candidate without deleting its evidence."""
        return _handle(services, RejectProductDiscoveryRevision(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            note=request.note,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/revisions/{revision_id}/restore")
    def restore_discovery(project_id: str, revision_id: str, request: RevisionActionRequest) -> dict[str, Any]:
        """Restore historical discovery as a new candidate."""
        return _handle(services, RestoreProductDiscoveryRevision(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.patch("/api/projects/{project_id}/discovery/revisions/{revision_id}/human-fields")
    def update_human_fields(
        project_id: str,
        revision_id: str,
        request: DiscoveryHumanFieldsRequest,
    ) -> dict[str, Any]:
        """Create a candidate containing separate human-owned edits."""
        return _handle(services, UpdateDiscoveryHumanFields(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            updates=request.updates,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/revisions/{revision_id}/lenses")
    def add_human_lens(project_id: str, revision_id: str, request: HumanLensRequest) -> dict[str, Any]:
        """Add a human-authored product lens with stable identity."""
        return _handle(services, AddHumanDiscoveryLens(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            lens=request.lens,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/revisions/{revision_id}/lenses/{lens_id}/exclude")
    def exclude_lens(
        project_id: str,
        revision_id: str,
        lens_id: str,
        request: LensDecisionRequest,
    ) -> dict[str, Any]:
        """Persist a lens inclusion decision that regeneration cannot override."""
        return _handle(services, ExcludeDiscoveryLens(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            lens_id=lens_id,
            excluded=request.excluded,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/revisions/{revision_id}/projection")
    def build_discovery_projection(
        project_id: str,
        revision_id: str,
        request: RevisionActionRequest,
    ) -> dict[str, Any]:
        """Compile approved downstream-ready discovery context."""
        return _handle(services, BuildLayer1DiscoveryContextProjection(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/competitor-research")
    def start_competitor_research(
        project_id: str,
        request: CompetitorResearchStartRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """Start only explicitly enabled competitor research."""
        scope = request.model_dump(mode="json", exclude={"request_id"}, exclude_none=True)
        result = _handle(services, StartCompetitorResearch(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            scope=scope,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        ))
        for job_id in result.data.get("job_ids", []):
            background_tasks.add_task(services.job_service.run_job, job_id)
        return result.data

    @app.post("/api/projects/{project_id}/discovery/competitor-research/jobs/{job_id}/cancel")
    def cancel_competitor_research(project_id: str, job_id: str, request: RevisionActionRequest) -> dict[str, Any]:
        """Cancel research while retaining persisted partial checkpoints."""
        return _handle(services, CancelCompetitorResearch(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            job_id=job_id,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/competitor-research/{revision_id}/approve")
    def approve_competitor_research(
        project_id: str,
        revision_id: str,
        request: RevisionActionRequest,
    ) -> dict[str, Any]:
        """Approve evidence and inference independently from Product Discovery."""
        return _handle(services, ApproveCompetitorResearchRevision(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/competitor-research/{revision_id}/reject")
    def reject_competitor_research(
        project_id: str,
        revision_id: str,
        request: RevisionActionRequest,
    ) -> dict[str, Any]:
        """Reject research without deleting its sources or partial evidence."""
        return _handle(services, RejectCompetitorResearchRevision(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            note=request.note,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/revisions/{revision_id}/competitor-research/attach")
    def attach_research(
        project_id: str,
        revision_id: str,
        request: CompetitorAttachmentRequest,
    ) -> dict[str, Any]:
        """Attach only approved research to a new discovery candidate."""
        return _handle(services, AttachCompetitorResearchToDiscovery(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            discovery_revision_id=revision_id,
            competitor_research_revision_id=request.competitor_research_revision_id,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/revisions/{revision_id}/competitor-research/detach")
    def detach_research(project_id: str, revision_id: str, request: RevisionActionRequest) -> dict[str, Any]:
        """Detach research by creating a new discovery candidate."""
        return _handle(services, DetachCompetitorResearchFromDiscovery(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            discovery_revision_id=revision_id,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/competitor-research/{revision_id}/findings/{finding_id}")
    def decide_competitor_finding(
        project_id: str,
        revision_id: str,
        finding_id: str,
        request: CompetitorFindingDecisionRequest,
    ) -> dict[str, Any]:
        """Approve, optionally include, or exclude one competitive finding."""
        command_type = (
            ExcludeCompetitorFinding
            if request.context_state == "excluded"
            else MarkCompetitorFindingStale
            if request.context_state == "stale"
            else IncludeCompetitorFinding
        )
        kwargs = {
            "project_id": project_id,
            "actor": CommandActor.human_ui(),
            "revision_id": revision_id,
            "finding_id": finding_id,
            "expected_state_token": request.expected_state_token,
            "idempotency_key": request.request_id or str(uuid.uuid4()),
        }
        if command_type is IncludeCompetitorFinding:
            kwargs["context_state"] = request.context_state
        return _handle(services, command_type(**kwargs)).data

    @app.post("/api/projects/{project_id}/discovery/competitor-research/{revision_id}/competitors")
    def add_competitor(
        project_id: str,
        revision_id: str,
        request: AddCompetitorRequest,
    ) -> dict[str, Any]:
        """Record a human-approved competitor addition."""
        return _handle(services, AddCompetitor(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            competitor_name=request.competitor_name,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data

    @app.delete("/api/projects/{project_id}/discovery/competitor-research/{revision_id}/competitors/{competitor_id}")
    def remove_competitor(
        project_id: str,
        revision_id: str,
        competitor_id: str,
        expected_state_token: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Exclude one competitor from future refreshes without deleting evidence."""
        return _handle(services, RemoveCompetitor(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            competitor_id=competitor_id,
            expected_state_token=expected_state_token,
            idempotency_key=request_id or str(uuid.uuid4()),
        )).data

    @app.post("/api/projects/{project_id}/discovery/competitor-research/{revision_id}/refresh")
    def refresh_research(
        project_id: str,
        revision_id: str,
        request: RefreshResearchRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        """Refresh selected competitors, findings, or stale sources explicitly."""
        result = _handle(services, RefreshCompetitorResearch(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            revision_id=revision_id,
            competitor_ids=tuple(request.competitor_ids),
            finding_ids=tuple(request.finding_ids),
            stale_only=request.stale_only,
            expected_state_token=request.expected_state_token,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        ))
        for job_id in result.data.get("job_ids", []):
            background_tasks.add_task(services.job_service.run_job, job_id)
        return result.data

    @app.post("/api/projects/{project_id}/discovery/revisions/{discovery_revision_id}/competitive-projection/{research_revision_id}")
    def rebuild_competitive_projection(
        project_id: str,
        discovery_revision_id: str,
        research_revision_id: str,
        request: RevisionActionRequest,
    ) -> dict[str, Any]:
        """Rebuild approved compact competitive context deterministically."""
        return _handle(services, RebuildCompetitiveContextProjection(
            project_id=project_id,
            actor=CommandActor.human_ui(),
            discovery_revision_id=discovery_revision_id,
            competitor_research_revision_id=research_revision_id,
            idempotency_key=request.request_id or str(uuid.uuid4()),
        )).data


def _handle(services: Any, command: Any) -> Any:
    """Translate command errors at the focused discovery API boundary."""
    try:
        return services.command_service.handle(command)
    except CommandError as exc:
        status = {
            "not_found": 404,
            "conflict": 409,
            "idempotency_conflict": 409,
            "stale_source": 409,
            "invalid_transition": 422,
            "human_authority_required": 403,
            "validation_error": 422,
        }.get(exc.code, 400)
        raise HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": exc.message, **exc.details},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _project_discovery_revision(services: Any, project_id: str, revision_id: str) -> Any:
    """Enforce project ownership for read-only discovery routes."""
    revision = services.db.get_discovery_revision(revision_id)
    if revision.project_id != project_id:
        raise HTTPException(status_code=404, detail="Product Discovery revision not found for this project.")
    return revision


def _project_competitor_revision(services: Any, project_id: str, revision_id: str) -> Any:
    """Load one research revision and enforce project ownership."""
    revision = services.db.get_competitor_research_revision(revision_id)
    if revision.project_id != project_id:
        raise HTTPException(status_code=404, detail="Competitor research revision not found for this project.")
    return revision


def _compare_items(left: list[Any], right: list[Any]) -> dict[str, list[str]]:
    """Compare model lists using their stable nested IDs."""
    left_ids = {str(item.id) for item in left}
    right_ids = {str(item.id) for item in right}
    return {
        "added_ids": sorted(right_ids - left_ids),
        "removed_ids": sorted(left_ids - right_ids),
        "retained_ids": sorted(left_ids & right_ids),
    }


def _compare_discovery(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Compare stable nested IDs section by section without normalizing domains."""
    sections = (
        "archetypes", "lenses", "actors", "lifecycle_stages", "enterprise_obligations",
        "domains", "cross_domain_opportunities", "coverage_risks", "open_questions",
    )
    comparison: dict[str, Any] = {}
    for section in sections:
        left_items = {item["id"]: item for item in left.get(section, [])}
        right_items = {item["id"]: item for item in right.get(section, [])}
        comparison[section] = {
            "added_ids": sorted(set(right_items) - set(left_items)),
            "removed_ids": sorted(set(left_items) - set(right_items)),
            "changed_ids": sorted(
                item_id
                for item_id in set(left_items) & set(right_items)
                if left_items[item_id] != right_items[item_id]
            ),
        }
    return comparison
