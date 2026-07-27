from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Callable
from strata.command_lifecycle import CommandLifecycleMixin
from strata.command_freshness import CommandFreshnessMixin
from strata.command_discovery import CommandDiscoveryMixin
from strata.command_layer0 import CommandLayer0Mixin
from strata.command_tokens import CommandTokenMixin
from strata.command_types import (
    AcceptLayer3Candidate,
    AddCompetitor,
    AddHumanDiscoveryLens,
    AppendBriefPlanTurn,
    ActorType,
    ApplicationCommand,
    ApproveFeature,
    ApproveCompetitorResearchRevision,
    ApproveProductDiscoveryRevision,
    ArchiveProject,
    AttachCompetitorResearchToDiscovery,
    BulkResolveFeatureReview,
    BulkSetPillarState,
    BuildLayer1DiscoveryContextProjection,
    CancelCompetitorResearch,
    CommandConflictError,
    CommandError,
    CommandNotFoundError,
    CommandResult,
    CommandValidationError,
    CreateFeature,
    CreateOrUpdateFeatureRelationship,
    CreatePillar,
    CutFeature,
    CutPillar,
    DetachCompetitorResearchFromDiscovery,
    DismissCriticFinding,
    EditFeature,
    EditLayer3ActiveRevision,
    EditPillar,
    ExcludeCompetitorFinding,
    ExcludeDiscoveryLens,
    GenerateProductDiscovery,
    GenerateLayer3Candidate,
    HumanAuthorityRequiredError,
    IdempotencyConflictError,
    ImportProjectArchive,
    InvalidTransitionError,
    KeepFeature,
    MarkFeatureNeedsReview,
    KeepPillar,
    IncludeCompetitorFinding,
    MarkCompetitorFindingStale,
    MergeFeatures,
    MergePillars,
    PartiallyAcceptLayer3Candidate,
    PrioritizePillar,
    PublishProductDiscoveryRevision,
    PublishBrief,
    ReopenCriticFinding,
    ReviewLayer3ActiveRevision,
    RejectLayer3Candidate,
    RemoveFeatureRelationship,
    RenameFeature,
    RenamePillar,
    RequestLayer1Generation,
    RequestDiscoveryRegeneration,
    RequestLayer2Generation,
    RequestLayer3Generation,
    RequestOverlapReview,
    RequestResearch,
    RebuildCompetitiveContextProjection,
    RefreshCompetitorResearch,
    RejectCompetitorResearchRevision,
    RejectProductDiscoveryRevision,
    ResolveCriticFinding,
    ResolveFeatureReview,
    ResolveOverlapVerdict,
    RestoreLayer3Revision,
    RestoreProductDiscoveryRevision,
    StaleEffect,
    StaleSourceError,
    UnarchiveProject,
    RemoveCompetitor,
    StartCompetitorResearch,
    UpdateDiscoveryHumanFields,
    UpdateProjectMetadata,
    UpdateBriefDraft,
    command_fingerprint,
    state_token,
)
from strata.dependency_db import feature_revision_token, pillar_revision_token
from strata.db import utc_now
from strata.layer3_db import Layer3RevisionConflict
from strata.layer3_service import validate_product_level_content
HUMAN_ONLY_COMMANDS = (
    UpdateBriefDraft, AppendBriefPlanTurn, PublishBrief, CreatePillar, EditPillar, KeepPillar, CutPillar,
    PrioritizePillar, RenamePillar, MergePillars, BulkSetPillarState, CreateFeature, EditFeature,
    KeepFeature, CutFeature, ApproveFeature, MarkFeatureNeedsReview, RenameFeature, MergeFeatures,
    ResolveFeatureReview, BulkResolveFeatureReview, CreateOrUpdateFeatureRelationship, RemoveFeatureRelationship,
    AcceptLayer3Candidate, PartiallyAcceptLayer3Candidate, RejectLayer3Candidate,
    RestoreLayer3Revision, EditLayer3ActiveRevision, ReviewLayer3ActiveRevision, ResolveCriticFinding, DismissCriticFinding,
    ReopenCriticFinding, ResolveOverlapVerdict, UpdateProjectMetadata, ArchiveProject, UnarchiveProject,
    ApproveProductDiscoveryRevision, PublishProductDiscoveryRevision, RejectProductDiscoveryRevision,
    RestoreProductDiscoveryRevision, UpdateDiscoveryHumanFields, AddHumanDiscoveryLens, ExcludeDiscoveryLens,
    ApproveCompetitorResearchRevision, RejectCompetitorResearchRevision, AttachCompetitorResearchToDiscovery,
    DetachCompetitorResearchFromDiscovery, ExcludeCompetitorFinding, IncludeCompetitorFinding,
    MarkCompetitorFindingStale,
    AddCompetitor, RemoveCompetitor, CancelCompetitorResearch,
)


class CommandService(CommandLifecycleMixin, CommandFreshnessMixin, CommandLayer0Mixin, CommandDiscoveryMixin, CommandTokenMixin):
    """Execute typed authoritative mutations through one transaction and audit boundary."""

    def __init__(self, services: Any):
        self.services = services
        self.db = services.db
        self.failure_injector: Callable[[str], None] | None = None

    def handle(self, command: ApplicationCommand) -> CommandResult:
        """Dispatch a typed command without exposing transport-specific behavior."""
        handlers: dict[type[Any], Callable[[Any], CommandResult]] = {
            UpdateBriefDraft: self._update_brief,
            AppendBriefPlanTurn: self._append_brief_plan_turn,
            PublishBrief: self._publish_brief,
            GenerateProductDiscovery: self._generate_product_discovery,
            RequestDiscoveryRegeneration: self._generate_product_discovery,
            ApproveProductDiscoveryRevision: lambda item: self._transition_discovery(item, "approved"),
            PublishProductDiscoveryRevision: lambda item: self._transition_discovery(item, "published"),
            RejectProductDiscoveryRevision: lambda item: self._transition_discovery(item, "rejected"),
            RestoreProductDiscoveryRevision: self._restore_discovery,
            UpdateDiscoveryHumanFields: self._update_discovery_human_fields,
            AddHumanDiscoveryLens: self._add_human_lens,
            ExcludeDiscoveryLens: self._exclude_discovery_lens,
            BuildLayer1DiscoveryContextProjection: self._build_discovery_projection,
            StartCompetitorResearch: self._start_competitor_research,
            CancelCompetitorResearch: self._cancel_competitor_research,
            ApproveCompetitorResearchRevision: lambda item: self._transition_competitor_research(item, "approved"),
            RejectCompetitorResearchRevision: lambda item: self._transition_competitor_research(item, "rejected"),
            AttachCompetitorResearchToDiscovery: self._attach_competitor_research,
            DetachCompetitorResearchFromDiscovery: self._attach_competitor_research,
            ExcludeCompetitorFinding: self._set_competitor_finding_state,
            IncludeCompetitorFinding: self._set_competitor_finding_state,
            MarkCompetitorFindingStale: self._set_competitor_finding_state,
            AddCompetitor: self._modify_competitor_scope,
            RemoveCompetitor: self._modify_competitor_scope,
            RefreshCompetitorResearch: self._refresh_competitor_research,
            RebuildCompetitiveContextProjection: self._rebuild_competitive_projection,
            CreatePillar: self._create_pillar,
            EditPillar: self._edit_pillar,
            KeepPillar: lambda item: self._set_pillar_state(item, "kept", "keep"),
            CutPillar: lambda item: self._set_pillar_state(item, "cut", "cut"),
            PrioritizePillar: self._prioritize_pillar,
            RenamePillar: self._rename_pillar,
            MergePillars: self._merge_pillars,
            BulkSetPillarState: self._bulk_set_pillar_state,
            CreateFeature: self._create_feature,
            EditFeature: self._edit_feature,
            KeepFeature: lambda item: self._set_feature_state(item, "kept", "keep"),
            CutFeature: self._cut_feature,
            ApproveFeature: lambda item: self._set_feature_state(item, "approved", "approve_for_layer3"),
            MarkFeatureNeedsReview: lambda item: self._set_feature_state(item, "needs_review", "needs_review"),
            RenameFeature: self._rename_feature,
            MergeFeatures: self._merge_features,
            ResolveFeatureReview: self._resolve_feature_review,
            BulkResolveFeatureReview: self._bulk_resolve_feature_review,
            CreateOrUpdateFeatureRelationship: self._upsert_relationship,
            RemoveFeatureRelationship: self._remove_relationship,
            GenerateLayer3Candidate: self._generate_layer3_candidate,
            AcceptLayer3Candidate: self._accept_layer3_candidate,
            PartiallyAcceptLayer3Candidate: self._accept_layer3_candidate,
            RejectLayer3Candidate: self._reject_layer3_candidate,
            RestoreLayer3Revision: self._restore_layer3_revision,
            EditLayer3ActiveRevision: self._edit_layer3_revision,
            ReviewLayer3ActiveRevision: self._review_layer3_revision,
            ResolveCriticFinding: self._resolve_finding,
            DismissCriticFinding: self._resolve_finding,
            ReopenCriticFinding: self._reopen_finding,
            ResolveOverlapVerdict: self._resolve_overlap,
            RequestLayer1Generation: self._request_layer1_generation,
            RequestLayer2Generation: self._request_layer2_generation,
            RequestLayer3Generation: self._request_layer3_generation,
            RequestResearch: self._request_research,
            RequestOverlapReview: self._request_overlap,
            ArchiveProject: self._archive_project,
            UpdateProjectMetadata: self._update_project_metadata,
            UnarchiveProject: self._unarchive_project,
            ImportProjectArchive: self._import_archive,
        }
        handler = handlers.get(type(command))
        if handler is None:
            raise CommandValidationError(f"Unsupported command: {type(command).__name__}")
        self._validate_actor(command)
        try:
            return handler(command)
        except CommandError:
            raise
        except ValueError as exc:
            raise CommandValidationError(str(exc), command_type=type(command).__name__) from exc

    def _execute(
        self,
        command: ApplicationCommand,
        *,
        target_type: str,
        target_id: str,
        operation: Callable[[], tuple[dict[str, Any], str, StaleEffect]],
        allow_archived: bool = False,
    ) -> CommandResult:
        """Own idempotency, transaction, audit completion, and rollback for one command."""
        if not command.idempotency_key.strip():
            raise CommandValidationError("An idempotency key is required.")
        command_type = type(command).__name__
        fingerprint = command_fingerprint(command)
        with self.db.unit_of_work():
            if self.db.is_postgres:
                # The project row is the command-stream lock. Besides ordering mutations,
                # it closes the concurrent idempotency race before the unique ledger insert.
                self.db._fetchone(
                    f"SELECT id FROM projects WHERE id = {self.db.param} FOR UPDATE",
                    (command.project_id,),
                )
            try:
                project = self.db.get_project(command.project_id)
            except ValueError as exc:
                raise CommandNotFoundError(str(exc), project_id=command.project_id) from exc
            if project.lifecycle_state == "archived" and not allow_archived:
                raise InvalidTransitionError("Archived projects are read-only.", artifact_id=project.id)
            existing = self.db._fetchone(
                f"SELECT * FROM command_executions WHERE project_id = {self.db.param} AND idempotency_key = {self.db.param}",
                (command.project_id, command.idempotency_key),
            )
            if existing is not None:
                if str(existing["command_type"]) != command_type or str(existing["request_fingerprint"]) != fingerprint:
                    raise IdempotencyConflictError(
                        "The idempotency key was already used for a different command.",
                        idempotency_key=command.idempotency_key,
                        existing_command=str(existing["command_type"]),
                        requested_command=command_type,
                    )
                return self._stored_result(existing)
            command_id = str(uuid.uuid4())
            self.db._transaction_state.command_id = command_id
            now = utc_now()
            payload = asdict(command)
            self.db._execute(
                f"INSERT INTO command_executions (id, project_id, command_type, target_type, target_id, actor_id, actor_type, origin, idempotency_key, request_fingerprint, status, input_payload, result_payload, stale_effects, created_at, completed_at) VALUES ({', '.join([self.db.param] * 16)})",
                (command_id, command.project_id, command_type, target_type, target_id,
                 command.actor.actor_id, command.actor.actor_type.value, command.actor.origin.value,
                 command.idempotency_key, fingerprint, "running", self.db._dump_json(payload),
                 self.db._dump_json({}), self.db._dump_json(asdict(StaleEffect())), now, None),
            )
            self._fail("after_command_started")
            data, next_token, stale = operation()
            self._fail("after_canonical_write")
            resolved_target_id = target_id
            if target_id == "new":
                created = data.get("pillar") or data.get("feature") or data.get("project")
                if isinstance(created, dict) and created.get("id"):
                    resolved_target_id = str(created["id"])
            result_payload = {
                "command_id": command_id, "command_type": command_type, "project_id": command.project_id,
                "target_type": target_type, "target_id": resolved_target_id, "state_token": next_token,
                "data": data, "stale_effect": asdict(stale), "idempotent": False,
            }
            completed_at = utc_now()
            self.db._execute(
                f"UPDATE command_executions SET status = {self.db.param}, target_id = {self.db.param}, result_payload = {self.db.param}, stale_effects = {self.db.param}, completed_at = {self.db.param} WHERE id = {self.db.param}",
                ("completed", resolved_target_id, self.db._dump_json(result_payload), self.db._dump_json(asdict(stale)), completed_at, command_id),
            )
            self._fail("after_audit_write")
            result = CommandResult(
                command_id=command_id, command_type=command_type, project_id=command.project_id,
                target_type=target_type, target_id=resolved_target_id, state_token=next_token,
                data=data, stale_effect=stale, idempotent=False,
            )
            self.db._transaction_state.command_id = None
            return result

    def _stored_result(self, row: Any) -> CommandResult:
        """Rehydrate a completed idempotent command result from the audit ledger."""
        payload = self.db._load_json(row["result_payload"])
        stale_payload = payload.get("stale_effect", {})
        return CommandResult(
            command_id=str(payload["command_id"]), command_type=str(payload["command_type"]),
            project_id=str(payload["project_id"]), target_type=str(payload["target_type"]),
            target_id=str(payload["target_id"]), state_token=str(payload.get("state_token", "")),
            data=dict(payload.get("data", {})), stale_effect=StaleEffect(
                effect=stale_payload.get("effect", "none"),
                artifact_ids=tuple(stale_payload.get("artifact_ids", [])),
                reason=stale_payload.get("reason", ""),
                directly_affected=tuple(stale_payload.get("directly_affected", [])),
                transitively_affected=tuple(stale_payload.get("transitively_affected", [])),
                already_stale=tuple(stale_payload.get("already_stale", [])),
                propagation_count=int(stale_payload.get("propagation_count", 0)),
                complete=bool(stale_payload.get("complete", True)),
            ), idempotent=True,
        )

    def _validate_actor(self, command: ApplicationCommand) -> None:
        """Reject autonomous model/system attempts to invoke human-only transitions."""
        if isinstance(command, HUMAN_ONLY_COMMANDS) and command.actor.actor_type is not ActorType.HUMAN:
            raise HumanAuthorityRequiredError(
                f"{type(command).__name__} requires a confirmed human actor.",
                actor_type=command.actor.actor_type.value,
                origin=command.actor.origin.value,
            )
        if command.actor.origin.value == "assistant_confirmed" and command.actor.actor_type is not ActorType.HUMAN:
            raise HumanAuthorityRequiredError("Confirmed assistant commands must carry a human actor.")

    def _assert_expected(self, command: ApplicationCommand, actual: str, artifact_id: str) -> None:
        """Reject stale authoritative writes without silently rebasing them."""
        expected = command.expected_state_token
        if not expected:
            raise CommandValidationError(
                "An expected state token is required for this mutation.", artifact_id=artifact_id,
            )
        if expected != actual:
            raise CommandConflictError(
                "The artifact changed after it was loaded. Reload before retrying.",
                expected_revision=expected, actual_revision=actual, artifact_id=artifact_id,
                recovery="reload",
            )

    def _lock(self, table: str, artifact_id: str) -> Any | None:
        """Lock one authoritative row on PostgreSQL; SQLite uses BEGIN IMMEDIATE."""
        suffix = " FOR UPDATE" if self.db.is_postgres else ""
        return self.db._fetchone(
            f"SELECT * FROM {table} WHERE id = {self.db.param}{suffix}", (artifact_id,),
        )

    def _fail(self, step: str) -> None:
        """Invoke the test-only failure hook inside the active unit of work."""
        if self.failure_injector is not None:
            self.failure_injector(step)

    # Layer 1 handlers
    def _create_pillar(self, command: CreatePillar) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            brief = self.services.brief_service.ensure_brief(command.project_id)
            if brief.status != "published":
                raise InvalidTransitionError("Publish Layer 0 before adding Layer 1 pillars.")
            if not command.title.strip():
                raise CommandValidationError("Pillar title is required.")
            if command.status not in {"generated", "kept", "cut", "prioritized"}:
                raise CommandValidationError("Unsupported initial pillar state.", status=command.status)
            node = self.db.create_node(
                project_id=command.project_id, parent_id=None, layer=1, node_type="pillar",
                title=command.title.strip(), description=command.description.strip(), status=command.status,
                priority=command.priority, json_payload={"source": "manual", "creation_mode": "manual_layer1"},
            )
            node = self.services.generation_service.refresh_pillar_semantic_metadata(node.id)
            self._register_pillar_lineage(node, pillar_revision_token(node))
            self._authority(command, "layer1_pillar", node.id, "manual_add")
            return {"pillar": node.model_dump(mode="json")}, self.pillar_state_token(node), StaleEffect()
        return self._execute(command, target_type="layer1_pillar", target_id="new", operation=operation)

    def _pillar(self, command: ApplicationCommand, pillar_id: str) -> Any:
        self._lock("nodes", pillar_id)
        try:
            pillar = self.db.get_node(pillar_id)
        except ValueError as exc:
            raise CommandNotFoundError(str(exc), artifact_id=pillar_id) from exc
        if pillar.project_id != command.project_id or pillar.layer != 1 or pillar.node_type != "pillar":
            raise CommandNotFoundError("Layer 1 pillar was not found in this project.", artifact_id=pillar_id)
        self._assert_expected(command, self.pillar_state_token(pillar), pillar.id)
        return pillar

    def _edit_pillar(self, command: EditPillar) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            before = self._pillar(command, command.pillar_id)
            if before.status == "merged":
                raise InvalidTransitionError("Merged pillars cannot be edited.", artifact_id=before.id)
            if command.status is not None and command.status not in {"generated", "kept", "cut", "prioritized"}:
                raise InvalidTransitionError("Unsupported pillar transition.", artifact_id=before.id, requested_state=command.status)
            if command.title is not None and not command.title.strip():
                raise CommandValidationError("Pillar title cannot be blank.", artifact_id=before.id)
            node = self.db.update_node(
                before.id, title=command.title.strip() if command.title is not None else None,
                description=command.description.strip() if command.description is not None else None,
                priority=command.priority, status=command.status,
            )
            node = self.services.generation_service.refresh_pillar_semantic_metadata(node.id)
            changed_content = before.title != node.title or (before.description or "") != (node.description or "")
            if changed_content:
                payload = dict(node.json_payload or {})
                payload["research_stale"] = {"scope": "layer1", "reason": "pillar_content_changed"}
                node = self.db.update_node(node.id, json_payload=payload)
            self._authority(command, "layer1_pillar", node.id, "edit", asdict(command))
            stale = StaleEffect()
            if changed_content:
                old_revision = pillar_revision_token(before)
                new_revision = pillar_revision_token(node)
                self._register_pillar_lineage(node, new_revision)
                stale = self._propagate_content_change(
                    command, artifact_type="layer1_pillar", artifact_id=node.id,
                    previous_revision_id=old_revision, replacement_revision_id=new_revision,
                    reason_code="pillar_content_changed",
                )
            return {"pillar": node.model_dump(mode="json")}, self.pillar_state_token(node), stale
        return self._execute(command, target_type="layer1_pillar", target_id=command.pillar_id, operation=operation)

    def _set_pillar_state(self, command: Any, status: str, action: str) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            pillar = self._pillar(command, command.pillar_id)
            if pillar.status == "merged":
                raise InvalidTransitionError("Merged pillars cannot change review state.", artifact_id=pillar.id)
            node = self.db.update_node(pillar.id, status=status)
            self._authority(command, "layer1_pillar", node.id, action, {"status": status})
            return {"pillar": node.model_dump(mode="json")}, self.pillar_state_token(node), StaleEffect()
        return self._execute(command, target_type="layer1_pillar", target_id=command.pillar_id, operation=operation)

    def _prioritize_pillar(self, command: PrioritizePillar) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            pillar = self._pillar(command, command.pillar_id)
            if pillar.status == "merged":
                raise InvalidTransitionError("Merged pillars cannot be prioritized.", artifact_id=pillar.id)
            node = self.db.update_node(pillar.id, status="prioritized", priority=command.priority)
            self._authority(command, "layer1_pillar", node.id, "prioritize", {"priority": command.priority})
            return {"pillar": node.model_dump(mode="json")}, self.pillar_state_token(node), StaleEffect()
        return self._execute(command, target_type="layer1_pillar", target_id=command.pillar_id, operation=operation)

    def _rename_pillar(self, command: RenamePillar) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            pillar = self._pillar(command, command.pillar_id)
            if pillar.status == "merged":
                raise InvalidTransitionError("Merged pillars cannot be renamed.", artifact_id=pillar.id)
            if not command.title.strip():
                raise CommandValidationError("Pillar title cannot be blank.", artifact_id=pillar.id)
            node = self.db.update_node(pillar.id, title=command.title.strip())
            node = self.services.generation_service.refresh_pillar_semantic_metadata(node.id)
            payload = dict(node.json_payload or {})
            payload["research_stale"] = {"scope": "layer1", "reason": "pillar_content_changed"}
            node = self.db.update_node(node.id, json_payload=payload)
            self._authority(command, "layer1_pillar", node.id, "rename", {"title": node.title})
            old_revision = pillar_revision_token(pillar)
            new_revision = pillar_revision_token(node)
            self._register_pillar_lineage(node, new_revision)
            stale = self._propagate_content_change(
                command, artifact_type="layer1_pillar", artifact_id=node.id,
                previous_revision_id=old_revision, replacement_revision_id=new_revision,
                reason_code="pillar_renamed",
            )
            return {"pillar": node.model_dump(mode="json")}, self.pillar_state_token(node), stale
        return self._execute(command, target_type="layer1_pillar", target_id=command.pillar_id, operation=operation)

    def _merge_pillars(self, command: MergePillars) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self._pillar(command, command.source_pillar_id)
            if source.id == command.target_pillar_id:
                raise CommandValidationError("A pillar cannot be merged into itself.")
            if source.status == "merged":
                raise InvalidTransitionError("The source pillar is already merged.", artifact_id=source.id)
            self._lock("nodes", command.target_pillar_id)
            target = self.db.get_node(command.target_pillar_id)
            if target.project_id != command.project_id or target.layer != 1:
                raise CommandNotFoundError("Merge target pillar was not found in this project.")
            if target.status in {"cut", "merged"}:
                raise InvalidTransitionError("The merge target must be an active pillar.", artifact_id=target.id)
            if not command.expected_target_state_token:
                raise CommandValidationError("An expected target state token is required for a merge.")
            if command.expected_target_state_token != self.pillar_state_token(target):
                raise CommandConflictError("The merge target changed. Reload before retrying.", expected_revision=command.expected_target_state_token, actual_revision=self.pillar_state_token(target), artifact_id=target.id, recovery="reload")
            payload = dict(source.json_payload or {})
            payload["merged_into_pillar_id"] = target.id
            merged = self.db.update_node(source.id, status="merged", json_payload=payload)
            self._authority(command, "layer1_pillar", source.id, "merge", {"target_pillar_id": target.id})
            self._authority(command, "layer1_pillar", target.id, "merge_target", {"source_pillar_id": source.id})
            stale = self._propagate_content_change(
                command, artifact_type="layer1_pillar", artifact_id=source.id,
                previous_revision_id=pillar_revision_token(source), replacement_revision_id=pillar_revision_token(merged),
                reason_code="pillar_merged",
            )
            return {"source": merged.model_dump(mode="json"), "target": target.model_dump(mode="json")}, self.pillar_state_token(merged), stale
        return self._execute(command, target_type="layer1_pillar", target_id=command.source_pillar_id, operation=operation)

    def _bulk_set_pillar_state(self, command: BulkSetPillarState) -> CommandResult:
        """Atomically apply one state to a reviewer-selected pillar set."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            if not command.pillar_ids:
                raise CommandValidationError("Select at least one pillar for a bulk action.")
            updated = []
            for pillar_id in command.pillar_ids:
                self._lock("nodes", pillar_id)
                pillar = self.db.get_node(pillar_id)
                actual = self.pillar_state_token(pillar)
                expected = command.expected_state_tokens.get(pillar_id)
                if pillar.project_id != command.project_id or pillar.layer != 1 or pillar.node_type != "pillar":
                    raise CommandNotFoundError("Layer 1 pillar was not found in this project.", artifact_id=pillar_id)
                if not expected:
                    raise CommandValidationError("Every bulk item requires an expected state token.", artifact_id=pillar_id)
                if expected != actual:
                    raise CommandConflictError("A bulk item changed. No items were updated.", expected_revision=expected, actual_revision=actual, artifact_id=pillar_id, recovery="reload")
                if pillar.status == "merged":
                    raise InvalidTransitionError("Merged pillars cannot change review state.", artifact_id=pillar_id)
                node = self.db.update_node(pillar_id, status=command.status)
                self._authority(command, "layer1_pillar", pillar_id, command.status, {"status": command.status})
                updated.append(node.model_dump(mode="json"))
            return {"pillars": updated}, state_token({item["id"]: item["status"] for item in updated}), StaleEffect()
        return self._execute(command, target_type="layer1_pillar_set", target_id=",".join(command.pillar_ids), operation=operation)

    # Layer 2 handlers
    def _create_feature(self, command: CreateFeature) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            if not command.canonical_name.strip() or not command.description.strip():
                raise CommandValidationError("Feature name and description are required.")
            owner = self.db.get_node(command.owner_pillar_id)
            if owner.project_id != command.project_id or owner.layer != 1:
                raise CommandValidationError("Feature owner must be a Layer 1 pillar in this project.")
            if command.status not in {"candidate", "kept", "needs_review", "approved"}:
                raise CommandValidationError("Unsupported initial feature state.", status=command.status)
            feature = self.db.create_layer2_feature(
                project_id=command.project_id, canonical_name=command.canonical_name.strip(),
                description=command.description.strip(), feature_type=command.feature_type,
                granularity_class=command.granularity_class, owner_pillar_id=command.owner_pillar_id,
                candidate_source_ids=[], aliases=list(command.aliases), status=command.status,
                metadata={"source": "manual", "coverage_family": command.coverage_family, "priority": command.priority, "notes": command.notes},
            )
            self.db.record_layer2_review_action(project_id=command.project_id, feature_id=feature.id, action_type="manual_add", payload={"source": "command"})
            self._authority(command, "layer2_feature", feature.id, "manual_add")
            self._register_feature_lineage(feature, feature_revision_token(feature))
            return {"feature": feature.model_dump(mode="json")}, self.feature_state_token(feature), StaleEffect()
        return self._execute(command, target_type="layer2_feature", target_id="new", operation=operation)

    def _feature(self, command: ApplicationCommand, feature_id: str) -> Any:
        self._lock("layer2_features", feature_id)
        try:
            feature = self.db.get_layer2_feature(feature_id)
        except ValueError as exc:
            raise CommandNotFoundError(str(exc), artifact_id=feature_id) from exc
        if feature.project_id != command.project_id:
            raise CommandNotFoundError("Layer 2 feature was not found in this project.", artifact_id=feature_id)
        self._assert_expected(command, self.feature_state_token(feature), feature.id)
        return feature

    def _edit_feature(self, command: EditFeature) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            feature = self._feature(command, command.feature_id)
            if feature.status == "merged":
                raise InvalidTransitionError("Merged features cannot be edited.", artifact_id=feature.id)
            allowed = {"canonical_name", "description", "feature_type", "granularity_class", "owner_pillar_id", "status", "coverage_family", "priority", "notes"}
            updates = {key: value for key, value in command.updates.items() if key in allowed}
            if not updates:
                raise CommandValidationError("Provide at least one editable feature field.")
            if "canonical_name" in updates and not str(updates["canonical_name"]).strip():
                raise CommandValidationError("Feature name cannot be blank.", artifact_id=feature.id)
            if "description" in updates and not str(updates["description"]).strip():
                raise CommandValidationError("Feature description cannot be blank.", artifact_id=feature.id)
            if "status" in updates and updates["status"] not in {"candidate", "kept", "cut", "renamed", "needs_review", "approved"}:
                raise InvalidTransitionError("Unsupported feature transition.", artifact_id=feature.id, requested_state=updates["status"])
            if updates.get("owner_pillar_id"):
                owner = self.db.get_node(str(updates["owner_pillar_id"]))
                if owner.project_id != command.project_id or owner.layer != 1:
                    raise CommandValidationError("Feature owner must be a Layer 1 pillar in this project.")
            updated = self.db.update_layer2_feature(feature.id, **updates)
            self.db.record_layer2_review_action(project_id=command.project_id, feature_id=feature.id, action_type="edit", payload={"source": "command", "fields": sorted(updates)})
            self._authority(command, "layer2_feature", feature.id, "edit", updates)
            changed_source = feature_revision_token(feature) != feature_revision_token(updated)
            stale = StaleEffect()
            if changed_source:
                self._register_feature_lineage(updated, feature_revision_token(updated))
                stale = self._propagate_content_change(
                    command, artifact_type="layer2_feature", artifact_id=feature.id,
                    previous_revision_id=feature_revision_token(feature), replacement_revision_id=feature_revision_token(updated),
                    reason_code="feature_content_changed",
                )
            return {"feature": updated.model_dump(mode="json")}, self.feature_state_token(updated), stale
        return self._execute(command, target_type="layer2_feature", target_id=command.feature_id, operation=operation)

    def _set_feature_state(self, command: Any, status: str, action: str) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            feature = self._feature(command, command.feature_id)
            if feature.status == "merged":
                raise InvalidTransitionError("Merged features cannot change review state.", artifact_id=feature.id)
            updated = self._apply_feature_review_state(command, feature, action, {})
            return {"feature": updated.model_dump(mode="json")}, self.feature_state_token(updated), StaleEffect()
        return self._execute(command, target_type="layer2_feature", target_id=command.feature_id, operation=operation)

    def _cut_feature(self, command: CutFeature) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            feature = self._feature(command, command.feature_id)
            if feature.status == "merged":
                raise InvalidTransitionError("Merged features cannot be cut again.", artifact_id=feature.id)
            updated = self._apply_feature_review_state(command, feature, "cut", {})
            stale = self._propagate_content_change(
                command, artifact_type="layer2_feature", artifact_id=feature.id,
                previous_revision_id=feature_revision_token(feature), replacement_revision_id=feature_revision_token(updated),
                reason_code="feature_replaced_or_cut",
            )
            return {"feature": updated.model_dump(mode="json")}, self.feature_state_token(updated), stale
        return self._execute(command, target_type="layer2_feature", target_id=command.feature_id, operation=operation)

    def _apply_feature_review_state(self, command: ApplicationCommand, feature: Any, action: str, payload: dict[str, Any]) -> Any:
        """Apply one normalized feature review decision inside the caller's transaction."""
        statuses = {"keep": "kept", "cut": "cut", "approve_for_layer3": "approved", "needs_review": "needs_review"}
        status = statuses.get(action)
        if status is None:
            raise CommandValidationError(f"Unsupported feature review action: {action}")
        updated = self.db.update_layer2_feature(feature.id, status=status)
        if action == "cut":
            embedding_model = self.services.generation_service._embedding_model_name(command.project_id, "layer1_similarity_embeddings")
            embedding = self.services.generation_service._layer2_embedding(f"{feature.canonical_name} {feature.description} {' '.join(feature.aliases)}", embedding_model)
            self.db.create_layer2_negative_cache_entry(
                project_id=command.project_id, rejected_name=feature.canonical_name,
                semantic_cluster=str(payload.get("semantic_cluster") or feature.canonical_name.lower()), rejected_aliases=feature.aliases,
                rejected_from_pillar_id=feature.owner_pillar_id, embedding_model=embedding_model, embedding=embedding,
            )
        self.db.record_layer2_review_action(project_id=command.project_id, feature_id=feature.id, action_type=action, payload={**payload, "source": "command"})
        self._authority(command, "layer2_feature", feature.id, action, {**payload, "status": status})
        return updated

    def _rename_feature(self, command: RenameFeature) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            feature = self._feature(command, command.feature_id)
            if feature.status == "merged":
                raise InvalidTransitionError("Merged features cannot be renamed.", artifact_id=feature.id)
            if not command.title.strip():
                raise CommandValidationError("Feature name cannot be blank.", artifact_id=feature.id)
            updates: dict[str, Any] = {"canonical_name": command.title.strip(), "status": "renamed"}
            if command.description is not None:
                if not command.description.strip():
                    raise CommandValidationError("Feature description cannot be blank.", artifact_id=feature.id)
                updates["description"] = command.description.strip()
            updated = self.db.update_layer2_feature(feature.id, **updates)
            self.db.record_layer2_review_action(project_id=command.project_id, feature_id=feature.id, action_type="rename", payload={"source": "command", "fields": sorted(updates)})
            self._authority(command, "layer2_feature", feature.id, "rename", updates)
            self._register_feature_lineage(updated, feature_revision_token(updated))
            stale = self._propagate_content_change(
                command, artifact_type="layer2_feature", artifact_id=feature.id,
                previous_revision_id=feature_revision_token(feature), replacement_revision_id=feature_revision_token(updated),
                reason_code="feature_renamed",
            )
            return {"feature": updated.model_dump(mode="json")}, self.feature_state_token(updated), stale
        return self._execute(command, target_type="layer2_feature", target_id=command.feature_id, operation=operation)

    def _merge_features(self, command: MergeFeatures) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self._feature(command, command.source_feature_id)
            if source.id == command.target_feature_id:
                raise CommandValidationError("A feature cannot be merged into itself.")
            if source.status == "merged":
                raise InvalidTransitionError("The source feature is already merged.", artifact_id=source.id)
            self._lock("layer2_features", command.target_feature_id)
            target = self.db.get_layer2_feature(command.target_feature_id)
            if target.project_id != command.project_id:
                raise CommandNotFoundError("Merge target feature was not found in this project.")
            if target.status in {"cut", "merged"}:
                raise InvalidTransitionError("The merge target must be an active feature.", artifact_id=target.id)
            actual_target = self.feature_state_token(target)
            if not command.expected_target_state_token:
                raise CommandValidationError("An expected target state token is required for a merge.")
            if command.expected_target_state_token != actual_target:
                raise CommandConflictError("The merge target changed. Reload before retrying.", expected_revision=command.expected_target_state_token, actual_revision=actual_target, artifact_id=target.id, recovery="reload")
            relationship = self.db.insert_layer2_relationship(
                project_id=command.project_id, source_feature_id=source.id, target_feature_id=target.id,
                relationship_type="duplicate_of", strength=1.0, rationale=command.rationale,
            )
            merged = self.db.update_layer2_feature(source.id, status="merged")
            self.db.record_layer2_review_action(project_id=command.project_id, feature_id=source.id, action_type="merge", payload={"source": "command", "target_feature_id": target.id, "relationship_id": relationship.id})
            self._authority(command, "layer2_feature", source.id, "merge", {"target_feature_id": target.id})
            self._authority(command, "layer2_feature", target.id, "merge_target", {"source_feature_id": source.id})
            stale = self._propagate_content_change(
                command, artifact_type="layer2_feature", artifact_id=source.id,
                previous_revision_id=feature_revision_token(source), replacement_revision_id=feature_revision_token(merged),
                reason_code="feature_merged",
            )
            return {"source": merged.model_dump(mode="json"), "target": target.model_dump(mode="json"), "relationship": relationship.model_dump(mode="json")}, self.feature_state_token(merged), stale
        return self._execute(command, target_type="layer2_feature", target_id=command.source_feature_id, operation=operation)

    def _resolve_feature_review(self, command: ResolveFeatureReview) -> CommandResult:
        mapping: dict[str, ApplicationCommand] = {
            "keep": KeepFeature(project_id=command.project_id, actor=command.actor, idempotency_key=command.idempotency_key, expected_state_token=command.expected_state_token, feature_id=command.feature_id),
            "cut": CutFeature(project_id=command.project_id, actor=command.actor, idempotency_key=command.idempotency_key, expected_state_token=command.expected_state_token, feature_id=command.feature_id),
            "approve_for_layer3": ApproveFeature(project_id=command.project_id, actor=command.actor, idempotency_key=command.idempotency_key, expected_state_token=command.expected_state_token, feature_id=command.feature_id),
            "needs_review": MarkFeatureNeedsReview(project_id=command.project_id, actor=command.actor, idempotency_key=command.idempotency_key, expected_state_token=command.expected_state_token, feature_id=command.feature_id),
        }
        if command.action == "rename":
            mapping["rename"] = RenameFeature(project_id=command.project_id, actor=command.actor, idempotency_key=command.idempotency_key, expected_state_token=command.expected_state_token, feature_id=command.feature_id, title=command.title or "", description=command.description)
        if command.action == "merge" and command.target_feature_id:
            mapping["merge"] = MergeFeatures(project_id=command.project_id, actor=command.actor, idempotency_key=command.idempotency_key, expected_state_token=command.expected_state_token, source_feature_id=command.feature_id, target_feature_id=command.target_feature_id, expected_target_state_token=str(command.payload.get("expected_target_state_token") or ""), rationale=str(command.payload.get("rationale") or "Reviewer merged duplicate Layer 2 features."))
        if command.action == "prioritize":
            mapping["prioritize"] = EditFeature(project_id=command.project_id, actor=command.actor, idempotency_key=command.idempotency_key, expected_state_token=command.expected_state_token, feature_id=command.feature_id, updates={"priority": command.payload.get("priority", "high")})
        if command.action == "reassign_owner" and command.owner_pillar_id:
            mapping["reassign_owner"] = EditFeature(project_id=command.project_id, actor=command.actor, idempotency_key=command.idempotency_key, expected_state_token=command.expected_state_token, feature_id=command.feature_id, updates={"owner_pillar_id": command.owner_pillar_id, "status": "kept"})
        if command.action == "add_relationship" and command.target_feature_id and command.relationship_type:
            mapping["add_relationship"] = CreateOrUpdateFeatureRelationship(
                project_id=command.project_id, actor=command.actor, idempotency_key=command.idempotency_key,
                expected_state_token=command.expected_state_token, source_feature_id=command.feature_id,
                target_feature_id=command.target_feature_id, relationship_type=command.relationship_type,
                expected_target_state_token=str(command.payload.get("expected_target_state_token") or ""),
                strength=float(command.payload.get("strength", 1.0)), rationale=str(command.payload.get("rationale", "")),
            )
        if command.action == "remove_relationship" and command.target_feature_id:
            mapping["remove_relationship"] = RemoveFeatureRelationship(
                project_id=command.project_id, actor=command.actor, idempotency_key=command.idempotency_key,
                expected_state_token=command.expected_state_token, source_feature_id=command.feature_id,
                target_feature_id=command.target_feature_id, relationship_type=command.relationship_type,
                expected_target_state_token=str(command.payload.get("expected_target_state_token") or ""),
            )
        selected = mapping.get(command.action)
        if selected is None:
            raise CommandValidationError(f"Unsupported Layer 2 review action: {command.action}")
        return self.handle(selected)

    def _bulk_resolve_feature_review(self, command: BulkResolveFeatureReview) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            if not command.feature_ids:
                raise CommandValidationError("Select at least one feature for a bulk action.")
            updated = []
            for feature_id in command.feature_ids:
                self._lock("layer2_features", feature_id)
                feature = self.db.get_layer2_feature(feature_id)
                if feature.project_id != command.project_id:
                    raise CommandNotFoundError("Layer 2 feature was not found in this project.", artifact_id=feature_id)
                expected = command.expected_state_tokens.get(feature_id)
                actual = self.feature_state_token(feature)
                if not expected:
                    raise CommandValidationError("Every bulk item requires an expected state token.", artifact_id=feature_id)
                if expected != actual:
                    raise CommandConflictError("A bulk item changed. No items were updated.", expected_revision=expected, actual_revision=actual, artifact_id=feature_id, recovery="reload")
                if feature.status == "merged":
                    raise InvalidTransitionError("Merged features cannot change review state.", artifact_id=feature.id)
                item = self._apply_feature_review_state(command, feature, command.action, command.payload)
                updated.append(item.model_dump(mode="json"))
            tokens = {item["id"]: self.feature_state_token(self.db.get_layer2_feature(item["id"])) for item in updated}
            stale = StaleEffect("deferred", tuple(command.feature_ids), "Layer 3 source reconciliation is deferred.")
            return {"features": updated}, state_token(tokens), stale
        return self._execute(command, target_type="layer2_feature_set", target_id=",".join(command.feature_ids), operation=operation)

    def _upsert_relationship(self, command: CreateOrUpdateFeatureRelationship) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self._feature(command, command.source_feature_id)
            self._lock("layer2_features", command.target_feature_id)
            target = self.db.get_layer2_feature(command.target_feature_id)
            if target.project_id != command.project_id:
                raise CommandNotFoundError("Relationship target was not found in this project.")
            if source.id == target.id or source.status in {"cut", "merged"} or target.status in {"cut", "merged"}:
                raise InvalidTransitionError("Relationships require two distinct active features.")
            actual_target = self.feature_state_token(target)
            if not command.expected_target_state_token or command.expected_target_state_token != actual_target:
                raise CommandConflictError("Relationship target changed or lacks an expected token.", expected_revision=command.expected_target_state_token, actual_revision=actual_target, artifact_id=target.id, recovery="reload")
            existing = self.db._fetchone(
                f"SELECT id FROM layer2_feature_relationships WHERE project_id = {self.db.param} AND source_feature_id = {self.db.param} AND target_feature_id = {self.db.param} AND relationship_type = {self.db.param} LIMIT 1",
                (command.project_id, source.id, target.id, command.relationship_type),
            )
            if existing is None:
                relationship = self.db.insert_layer2_relationship(project_id=command.project_id, source_feature_id=source.id, target_feature_id=target.id, relationship_type=command.relationship_type, strength=command.strength, rationale=command.rationale)
            else:
                self.db._execute(
                    f"UPDATE layer2_feature_relationships SET strength = {self.db.param}, rationale = {self.db.param} WHERE id = {self.db.param}",
                    (command.strength, command.rationale, existing["id"]),
                )
                relationship = self.db.get_layer2_relationship(str(existing["id"]))
            self.db.record_layer2_review_action(project_id=command.project_id, feature_id=source.id, action_type="add_relationship", payload={"source": "command", "relationship_id": relationship.id})
            self._authority(command, "layer2_feature", source.id, "add_relationship", {"target_feature_id": target.id, "relationship_type": command.relationship_type})
            return {"relationship": relationship.model_dump(mode="json")}, self.feature_state_token(source), StaleEffect("deferred", (source.id, target.id), "Layer 3 graph reconciliation is deferred.")
        return self._execute(command, target_type="layer2_relationship", target_id=command.source_feature_id, operation=operation)

    def _remove_relationship(self, command: RemoveFeatureRelationship) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self._feature(command, command.source_feature_id)
            self._lock("layer2_features", command.target_feature_id)
            target = self.db.get_layer2_feature(command.target_feature_id)
            actual_target = self.feature_state_token(target)
            if target.project_id != command.project_id or not command.expected_target_state_token or command.expected_target_state_token != actual_target:
                raise CommandConflictError("Relationship target changed or is invalid.", expected_revision=command.expected_target_state_token, actual_revision=actual_target, artifact_id=target.id, recovery="reload")
            removed = self.db.delete_layer2_relationship(project_id=command.project_id, source_feature_id=source.id, target_feature_id=target.id, relationship_type=command.relationship_type)
            if not removed:
                raise CommandNotFoundError("Layer 2 relationship was not found.")
            self.db.record_layer2_review_action(project_id=command.project_id, feature_id=source.id, action_type="remove_relationship", payload={"source": "command", "target_feature_id": target.id})
            self._authority(command, "layer2_feature", source.id, "remove_relationship", {"target_feature_id": target.id})
            return {"removed": removed}, self.feature_state_token(source), StaleEffect("deferred", (source.id, target.id), "Layer 3 graph reconciliation is deferred.")
        return self._execute(command, target_type="layer2_relationship", target_id=command.source_feature_id, operation=operation)

    # Layer 3 handlers preserve Ticket 1 semantics.
    def _generate_layer3_candidate(self, command: GenerateLayer3Candidate) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            created = self.services.generation_service.generate_feature_expansions(
                command.project_id, list(command.feature_ids), thinking_enabled=command.thinking_enabled,
                generation_reference=command.generation_reference or command.idempotency_key,
                actor=command.actor.actor_id,
            )
            ids = [str(item["id"] if isinstance(item, dict) else item.id) for item in created]
            return {"candidates": [item if isinstance(item, dict) else item.model_dump(mode="json") for item in created]}, state_token(ids), StaleEffect()
        return self._execute(command, target_type="layer3_candidate", target_id=",".join(command.feature_ids), operation=operation)

    def _accept_layer3_candidate(self, command: Any) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            if not command.expected_state_token:
                raise CommandValidationError("An expected active Layer 3 revision is required.", artifact_id=command.expansion_id)
            sections = list(command.selected_sections) if isinstance(command, PartiallyAcceptLayer3Candidate) else []
            previous_active_id = str(self.db.get_layer3_expansion(command.expansion_id).active_revision_id or "")
            try:
                result = self.db.apply_layer3_candidate(
                    project_id=command.project_id, logical_expansion_id=command.expansion_id,
                    candidate_revision_id=command.candidate_revision_id,
                    expected_active_revision_id=command.expected_state_token,
                    request_id=command.idempotency_key, selected_sections=sections,
                    actor=command.actor.actor_id, origin=command.actor.origin.value,
                )
            except Layer3RevisionConflict as exc:
                actual = self.db.get_layer3_expansion(command.expansion_id).active_revision_id
                raise CommandConflictError(str(exc), expected_revision=command.expected_state_token, actual_revision=actual, artifact_id=command.expansion_id, recovery="reload_or_compare") from exc
            active_id = str(result["active_revision"]["id"])
            if active_id != command.candidate_revision_id:
                self.db.carry_forward_dependencies(
                    project_id=command.project_id, artifact_type="layer3_revision",
                    artifact_id=command.expansion_id, previous_revision_id=command.candidate_revision_id,
                    replacement_revision_id=active_id,
                )
            freshness = self.db.evaluate_artifact_freshness(
                project_id=command.project_id, artifact_type="layer3_revision",
                artifact_id=command.expansion_id, artifact_revision_id=active_id,
            )
            self.db._execute(
                f"UPDATE layer3_expansion_revision_states SET freshness_state = {self.db.param}, updated_at = {self.db.param} WHERE revision_id = {self.db.param}",
                ("fresh" if freshness["freshness_state"] == "current" else freshness["freshness_state"], utc_now(), active_id),
            )
            if previous_active_id and previous_active_id != active_id:
                previous = self.db.freshness_for_artifact(command.project_id, "layer3_revision", command.expansion_id, previous_active_id)
                self.db.set_artifact_freshness(
                    project_id=command.project_id, artifact_type="layer3_revision", artifact_id=command.expansion_id,
                    artifact_revision_id=previous_active_id, freshness_state="superseded",
                    lineage_quality=str(previous.get("lineage_quality", "unknown")),
                )
            result["freshness"] = freshness
            return result, active_id, StaleEffect()
        return self._execute(command, target_type="layer3_expansion", target_id=command.expansion_id, operation=operation)

    def _reject_layer3_candidate(self, command: RejectLayer3Candidate) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            expansion = self.db.get_layer3_expansion(command.expansion_id)
            self._assert_expected(command, str(expansion.active_revision_id or ""), command.expansion_id)
            candidate = self.db.get_layer3_revision(command.candidate_revision_id)
            if candidate["logical_expansion_id"] != command.expansion_id:
                raise CommandValidationError("Candidate does not belong to this expansion.")
            try:
                result = self.db.reject_layer3_candidate(project_id=command.project_id, candidate_revision_id=command.candidate_revision_id, request_id=command.idempotency_key, actor=command.actor.actor_id, note=command.note)
            except Layer3RevisionConflict as exc:
                raise InvalidTransitionError(str(exc), artifact_id=command.candidate_revision_id) from exc
            return result, str(expansion.active_revision_id or ""), StaleEffect()
        return self._execute(command, target_type="layer3_expansion", target_id=command.expansion_id, operation=operation)

    def _restore_layer3_revision(self, command: RestoreLayer3Revision) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            try:
                result = self.db.restore_layer3_revision(
                    project_id=command.project_id, logical_expansion_id=command.expansion_id,
                    source_revision_id=command.revision_id, expected_active_revision_id=str(command.expected_state_token or ""),
                    request_id=command.idempotency_key, actor=command.actor.actor_id,
                )
            except Layer3RevisionConflict as exc:
                actual = self.db.get_layer3_expansion(command.expansion_id).active_revision_id
                raise CommandConflictError(str(exc), expected_revision=command.expected_state_token, actual_revision=actual, artifact_id=command.expansion_id, recovery="reload") from exc
            active_id = str(result["active_revision"]["id"])
            self.db.carry_forward_dependencies(
                project_id=command.project_id, artifact_type="layer3_revision",
                artifact_id=command.expansion_id, previous_revision_id=command.revision_id,
                replacement_revision_id=active_id,
            )
            freshness = self.db.evaluate_artifact_freshness(
                project_id=command.project_id, artifact_type="layer3_revision",
                artifact_id=command.expansion_id, artifact_revision_id=active_id,
            )
            self.db._execute(
                f"UPDATE layer3_expansion_revision_states SET freshness_state = {self.db.param}, updated_at = {self.db.param} WHERE revision_id = {self.db.param}",
                ("fresh" if freshness["freshness_state"] == "current" else freshness["freshness_state"], utc_now(), active_id),
            )
            result["freshness"] = freshness
            return result, active_id, StaleEffect()
        return self._execute(command, target_type="layer3_expansion", target_id=command.expansion_id, operation=operation)

    def _edit_layer3_revision(self, command: EditLayer3ActiveRevision) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            expansion = self.db.get_layer3_expansion(command.expansion_id)
            self._assert_expected(command, str(expansion.active_revision_id or ""), command.expansion_id)
            validate_product_level_content(command.updates)
            updated = self.db.revise_active_expansion(command.expansion_id, command.updates, actor=command.actor.actor_id, origin=command.actor.origin.value)
            if expansion.active_revision_id and updated.active_revision_id:
                self.db.carry_forward_dependencies(
                    project_id=command.project_id, artifact_type="layer3_revision", artifact_id=command.expansion_id,
                    previous_revision_id=str(expansion.active_revision_id), replacement_revision_id=str(updated.active_revision_id),
                )
                self.db.evaluate_artifact_freshness(
                    project_id=command.project_id, artifact_type="layer3_revision", artifact_id=command.expansion_id,
                    artifact_revision_id=str(updated.active_revision_id),
                )
            return {"expansion": updated.model_dump(mode="json")}, str(updated.active_revision_id or ""), StaleEffect()
        return self._execute(command, target_type="layer3_expansion", target_id=command.expansion_id, operation=operation)

    def _review_layer3_revision(self, command: ReviewLayer3ActiveRevision) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            expansion = self.db.get_layer3_expansion(command.expansion_id)
            self._assert_expected(command, str(expansion.active_revision_id or ""), command.expansion_id)
            if expansion.project_id != command.project_id:
                raise CommandNotFoundError("Layer 3 expansion was not found in this project.")
            if command.review_state == "approved":
                feature = self.db.get_layer2_feature(expansion.feature_id)
                if feature.project_id != command.project_id or feature.status != "approved":
                    raise StaleSourceError("The source Layer 2 feature must still be approved.", artifact_id=feature.id)
                validate_product_level_content(expansion.model_dump(mode="json"))
            updated = self.db.set_active_layer3_review_state(expansion.id, command.review_state, actor=command.actor.actor_id, note=command.note)
            self._authority(command, "layer3_expansion", expansion.id, f"review_{command.review_state}", {"note": command.note}, revision_id=str(expansion.active_revision_id or ""))
            return {"expansion": updated.model_dump(mode="json")}, str(updated.active_revision_id or ""), StaleEffect()
        return self._execute(command, target_type="layer3_expansion", target_id=command.expansion_id, operation=operation)

    # Finding and overlap handlers
    def _resolve_finding(self, command: ResolveCriticFinding) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            rows = self.db.list_critic_findings(command.project_id)
            finding = next((item for item in rows if item["id"] == command.finding_id), None)
            if finding is None:
                raise CommandNotFoundError("Critic finding was not found in this project.")
            self._lock("critic_findings", command.finding_id)
            self._assert_expected(command, self.finding_state_token(finding), command.finding_id)
            updated = self.db.resolve_critic_finding(command.finding_id, action=command.resolution, note=command.note, resolved_by=command.actor.actor_id)
            return {"finding": updated}, self.finding_state_token(updated), StaleEffect()
        return self._execute(command, target_type="critic_finding", target_id=command.finding_id, operation=operation)

    def _reopen_finding(self, command: ReopenCriticFinding) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            finding = next((item for item in self.db.list_critic_findings(command.project_id) if item["id"] == command.finding_id), None)
            if finding is None:
                raise CommandNotFoundError("Critic finding was not found in this project.")
            self._lock("critic_findings", command.finding_id)
            self._assert_expected(command, self.finding_state_token(finding), command.finding_id)
            if finding["status"] == "open":
                raise InvalidTransitionError("Critic finding is already open.")
            now = utc_now()
            self.db._execute(
                f"UPDATE critic_findings SET status = {self.db.param}, resolution_action = '', resolution_note = '', resolved_by = '', resolved_at = NULL, updated_at = {self.db.param} WHERE id = {self.db.param}",
                ("open", now, command.finding_id),
            )
            updated = next(item for item in self.db.list_critic_findings(command.project_id) if item["id"] == command.finding_id)
            self._authority(command, updated["artifact_type"], updated["artifact_id"], "reopen_finding", {"finding_id": command.finding_id}, updated["artifact_revision_id"])
            return {"finding": updated}, self.finding_state_token(updated), StaleEffect()
        return self._execute(command, target_type="critic_finding", target_id=command.finding_id, operation=operation)

    def _resolve_overlap(self, command: ResolveOverlapVerdict) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            try:
                verdict = self.db.get_overlap_verdict(command.verdict_id)
            except ValueError as exc:
                raise CommandNotFoundError(str(exc)) from exc
            if verdict.project_id != command.project_id or verdict.layer != command.layer:
                raise CommandNotFoundError("Overlap verdict does not belong to this project/layer.")
            current_hashes = self.db.current_overlap_item_hashes(command.project_id, command.layer)
            target_hash = current_hashes.get(verdict.target_id)
            neighbor_hash = current_hashes.get(verdict.neighbor_id)
            actual = state_token({"target": target_hash, "neighbor": neighbor_hash, "verdict": verdict.id})
            self._assert_expected(command, actual, verdict.id)
            if not target_hash or not neighbor_hash:
                raise StaleSourceError("Overlap verdict is stale because one or both items are no longer active.", artifact_id=verdict.id)
            resolution = self.db.create_overlap_verdict_resolution(
                project_id=command.project_id, verdict_id=verdict.id, layer=command.layer,
                target_id=verdict.target_id, neighbor_id=verdict.neighbor_id, action=command.action,
                note=command.note, resolved_by=command.actor.actor_id,
                target_hash=target_hash, neighbor_hash=neighbor_hash,
                metadata={"critic_relation": verdict.relation, "critic_confidence": verdict.confidence, "origin": command.actor.origin.value},
            )
            stale = StaleEffect()
            if command.layer == "layer2" and command.action in {"accept_merge", "link"}:
                target = self.db.get_layer2_feature(verdict.target_id)
                neighbor = self.db.get_layer2_feature(verdict.neighbor_id)
                relationship_type = "duplicate_of" if command.action == "accept_merge" else "overlaps_with"
                relationship = self.db.insert_layer2_relationship(project_id=command.project_id, source_feature_id=target.id, target_feature_id=neighbor.id, relationship_type=relationship_type, strength=verdict.confidence, rationale=f"Overlap critic {verdict.relation}: {verdict.rationale}")
                if command.action == "accept_merge":
                    self.db.update_layer2_feature(target.id, status="merged")
                self.db.record_layer2_review_action(project_id=command.project_id, feature_id=target.id, action_type="merge" if command.action == "accept_merge" else "add_relationship", payload={"source": "overlap_resolution", "verdict_id": verdict.id, "neighbor_id": neighbor.id, "relationship_type": relationship_type, "relationship_id": relationship.id})
                self._authority(command, "layer2_feature", target.id, "merge" if command.action == "accept_merge" else "add_relationship", {"verdict_id": verdict.id, "neighbor_id": neighbor.id})
                stale = StaleEffect("deferred", (target.id, neighbor.id), "Layer 3 graph reconciliation is deferred.")
            return {"resolution": resolution.model_dump(mode="json")}, actual, stale
        return self._execute(command, target_type="overlap_verdict", target_id=command.verdict_id, operation=operation)

    # Durable workflow request handlers
    def _request_job(self, command: ApplicationCommand, *, kind: str, workflow: str, scope: str, scope_id: str | None, payload: dict[str, Any], dedupe_key: str) -> tuple[dict[str, Any], str, StaleEffect]:
        job = self.services.job_service.enqueue(project_id=command.project_id, kind=kind, workflow=workflow, scope=scope, scope_id=scope_id, request_payload=payload, dedupe_key=dedupe_key)
        return {"job": job.model_dump(mode="json"), "job_ids": [job.id]}, job.id, StaleEffect()

    def _request_layer1_generation(self, command: RequestLayer1Generation) -> CommandResult:
        def operation():
            brief = self.services.brief_service.ensure_brief(command.project_id)
            if brief.status != "published":
                raise InvalidTransitionError("Publish the Layer 0 brief before generating Layer 1.")
            aliases = [str(item) for item in command.payload.get("model_aliases", [])]
            try:
                self.services.job_service._resolve_layer1_profiles(aliases)
            except ValueError as exc:
                raise CommandValidationError(str(exc)) from exc
            return self._request_job(command, kind="generation", workflow="layer1_generation", scope="layer1", scope_id=None, payload=command.payload, dedupe_key=f"generation:layer1:{command.project_id}:{state_token(command.payload)}")
        return self._execute(command, target_type="workflow_request", target_id="layer1_generation", operation=operation)

    def _request_layer2_generation(self, command: RequestLayer2Generation) -> CommandResult:
        def operation():
            pillar_ids = [str(item) for item in command.payload.get("pillar_ids", [])]
            if not pillar_ids:
                raise CommandValidationError("Select at least one approved Layer 1 pillar for Layer 2 generation.")
            for pillar_id in pillar_ids:
                pillar = self.db.get_node(pillar_id)
                if pillar.project_id != command.project_id or pillar.status not in {"kept", "prioritized"}:
                    raise StaleSourceError("Layer 2 generation requires kept or prioritized Layer 1 pillars.", artifact_id=pillar_id)
            return self._request_job(command, kind="generation", workflow="layer2_generation", scope="layer2", scope_id=None, payload=command.payload, dedupe_key=f"generation:layer2:{command.project_id}:{state_token(command.payload)}")
        return self._execute(command, target_type="workflow_request", target_id="layer2_generation", operation=operation)

    def _request_layer3_generation(self, command: RequestLayer3Generation) -> CommandResult:
        def operation():
            if not command.feature_ids:
                raise CommandValidationError("Select at least one approved Layer 2 feature.")
            for feature_id in command.feature_ids:
                feature = self.db.get_layer2_feature(feature_id)
                if feature.project_id != command.project_id or feature.status != "approved":
                    raise StaleSourceError("Layer 3 generation requires approved Layer 2 features.", artifact_id=feature_id)
            payload = {"feature_ids": list(command.feature_ids), "thinking_enabled": command.thinking_enabled}
            return self._request_job(command, kind="generation", workflow="layer3_generation", scope="layer3", scope_id=None, payload=payload, dedupe_key=f"generation:layer3:{command.project_id}:{state_token(payload)}")
        return self._execute(command, target_type="workflow_request", target_id="layer3_generation", operation=operation)

    def _request_research(self, command: RequestResearch) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            research_jobs = []
            platform_jobs = []
            if command.layer == "layer0":
                research_jobs = [self.services.research_service.enqueue_layer0(command.project_id, reason=command.reason)]
            elif command.layer == "layer1":
                ids = list(command.artifact_ids) or [node.id for node in self.db.list_nodes(command.project_id, parent_id=None, layer=1, node_type="pillar")]
                research_jobs = [self.services.research_service.enqueue_layer1(command.project_id, item, reason=command.reason) for item in ids]
            else:
                research_jobs = [self.services.research_service.enqueue_layer2(command.project_id, feature_ids=list(command.artifact_ids) or None, reason=command.reason)]
            for research in research_jobs:
                platform = self.services.job_service.enqueue(
                    project_id=command.project_id, kind="research", workflow="research", scope=command.layer,
                    scope_id=research.scope_id,
                    request_payload={"research_job_id": research.id, "research_job_type": research.job_type},
                    dedupe_key=f"research:{research.id}",
                )
                platform_jobs.append(platform)
            ids = [job.id for job in platform_jobs]
            return {"research_jobs": [job.model_dump(mode="json") for job in research_jobs], "jobs": [job.model_dump(mode="json") for job in platform_jobs], "job_ids": ids}, state_token(ids), StaleEffect()
        return self._execute(command, target_type="workflow_request", target_id=f"research:{command.layer}", operation=operation)

    def _request_overlap(self, command: RequestOverlapReview) -> CommandResult:
        def operation():
            workflow = f"{command.layer}_overlap_critic"
            return self._request_job(command, kind="critic", workflow=workflow, scope=command.layer, scope_id=None, payload={"layer": command.layer}, dedupe_key=f"critic:overlap:{command.project_id}:{command.layer}")
        return self._execute(command, target_type="workflow_request", target_id=f"overlap:{command.layer}", operation=operation)
