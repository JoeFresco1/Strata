from __future__ import annotations

from typing import Any

from strata.command_types import (
    AddCompetitor,
    AddHumanDiscoveryLens,
    ApproveCompetitorResearchRevision,
    ApproveProductDiscoveryRevision,
    AttachCompetitorResearchToDiscovery,
    BuildLayer1DiscoveryContextProjection,
    CancelCompetitorResearch,
    CommandResult,
    CommandValidationError,
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
    StaleEffect,
    StartCompetitorResearch,
    UpdateDiscoveryHumanFields,
    state_token,
)
from strata.discovery_models import CompetitorResearchMode, DiscoveryLens
from strata.project_settings import default_project_model_settings


class CommandDiscoveryMixin:
    """Execute Product Discovery authority and workflow requests through the command ledger."""

    def discovery_state_token(self, revision: Any) -> str:
        """Return the optimistic-concurrency token for one discovery revision."""
        return state_token(revision.model_dump(mode="json"))

    def competitor_research_state_token(self, revision: Any) -> str:
        """Return the optimistic-concurrency token for one competitor-research revision."""
        return state_token(revision.model_dump(mode="json"))

    def _generate_product_discovery(
        self,
        command: GenerateProductDiscovery | RequestDiscoveryRegeneration,
    ) -> CommandResult:
        """Queue explicit Product Discovery generation without starting optional research."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            brief = self.services.brief_service.ensure_brief(command.project_id)
            if brief.status != "published" or not brief.current_published_revision_id:
                raise CommandValidationError("Publish the Layer 0 brief before generating Product Discovery.")
            mode = CompetitorResearchMode(command.competitor_research_mode)
            runtime_settings = self._discovery_settings_snapshot(command.project_id)
            payload = {
                "competitor_research_mode": mode.value,
                "competitor_research_revision_id": command.competitor_research_revision_id,
                "source_brief_revision_id": brief.current_published_revision_id,
                "runtime_settings": runtime_settings,
                "prompt_key": "product_discovery_generation_v1",
                "prompt_version": "1.0.0",
            }
            job = self.services.job_service.enqueue(
                project_id=command.project_id,
                kind="generation",
                workflow="product_discovery_generation",
                scope="product_discovery",
                request_payload=payload,
                dedupe_key=f"product-discovery:{command.project_id}:{state_token(payload)}",
            )
            return {"job": job.model_dump(mode="json"), "job_ids": [job.id]}, job.id, StaleEffect()
        return self._execute(
            command,
            target_type="workflow_request",
            target_id="product_discovery_generation",
            operation=operation,
        )

    def _transition_discovery(self, command: Any, target_state: str) -> CommandResult:
        """Apply one human-controlled discovery revision transition."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            revision = self.db.get_discovery_revision(command.revision_id)
            self._assert_expected(command, self.discovery_state_token(revision), revision.id)
            updated = self.db.transition_discovery_revision(
                revision_id=revision.id,
                target_state=target_state,
                command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
                actor=command.actor.actor_id,
                origin=command.actor.origin.value,
            )
            projections: list[dict[str, Any]] = []
            if target_state == "published":
                projections.append(self.services.discovery_service.build_layer1_projection(
                    updated.id,
                    command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
                ))
                if updated.competitor_research_revision_id:
                    projections.append(self.services.discovery_service.build_competitive_projection(
                        updated.id,
                        updated.competitor_research_revision_id,
                        command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
                    ))
            data = {
                "revision": updated.model_dump(mode="json"),
                "projections": projections,
            }
            return data, self.discovery_state_token(updated), StaleEffect()
        return self._execute(
            command,
            target_type="product_discovery_revision",
            target_id=command.revision_id,
            operation=operation,
        )

    def _restore_discovery(self, command: RestoreProductDiscoveryRevision) -> CommandResult:
        """Restore historical content as a new candidate instead of mutating history."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self.db.get_discovery_revision(command.revision_id)
            brief_head = self.db.get_brief_head(source.project_id)
            current_brief_revision_id = str((brief_head or {}).get("current_published_revision_id") or "")
            if not current_brief_revision_id:
                raise CommandValidationError("Publish the Layer 0 brief before restoring Product Discovery.")
            retained_research_id = (
                source.competitor_research_revision_id
                if source.source_brief_revision_id == current_brief_revision_id
                else None
            )
            replacement = self.db.create_discovery_revision(
                project_id=source.project_id,
                source_brief_revision_id=current_brief_revision_id,
                competitor_research_mode=source.competitor_research_mode.value,
                payload=source.discovery.model_dump(mode="json"),
                model_authored_fields={
                    **source.model_authored_fields,
                    "restored_from_revision_id": source.id,
                    "restored_from_brief_revision_id": source.source_brief_revision_id,
                },
                human_owned_fields={
                    **source.human_owned_fields,
                    "restored_from_revision_id": source.id,
                },
                review_findings=[item.model_dump(mode="json") for item in source.review_findings],
                runtime_provenance=[item.model_dump(mode="json") for item in source.runtime_provenance],
                generation_job_id=source.generation_job_id,
                competitor_research_revision_id=retained_research_id,
                command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
                actor=command.actor.actor_id,
                origin=command.actor.origin.value,
            )
            return {"revision": replacement.model_dump(mode="json")}, self.discovery_state_token(replacement), StaleEffect()
        return self._execute(
            command,
            target_type="product_discovery_revision",
            target_id=command.revision_id,
            operation=operation,
        )

    def _update_discovery_human_fields(self, command: UpdateDiscoveryHumanFields) -> CommandResult:
        """Merge human-owned fields into a new candidate revision."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self.db.get_discovery_revision(command.revision_id)
            self._assert_expected(command, self.discovery_state_token(source), source.id)
            human_fields = self._deep_merge(source.human_owned_fields, command.updates)
            replacement = self.db.revise_discovery_human_fields(
                revision_id=source.id,
                human_owned_fields=human_fields,
                command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
                actor=command.actor.actor_id,
                origin=command.actor.origin.value,
            )
            return {"revision": replacement.model_dump(mode="json")}, self.discovery_state_token(replacement), StaleEffect()
        return self._execute(
            command,
            target_type="product_discovery_revision",
            target_id=command.revision_id,
            operation=operation,
        )

    def _add_human_lens(self, command: AddHumanDiscoveryLens) -> CommandResult:
        """Add a validated human-authored lens while retaining model-authored content."""
        lens = DiscoveryLens.model_validate({
            **command.lens,
            "source": "human_added",
            "downstream_state": command.lens.get("downstream_state", "optional"),
        })
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self.db.get_discovery_revision(command.revision_id)
            self._assert_expected(command, self.discovery_state_token(source), source.id)
            lenses = list(source.human_owned_fields.get("added_lenses") or [])
            lenses = [item for item in lenses if item.get("id") != lens.id]
            lenses.append(lens.model_dump(mode="json"))
            replacement = self.db.revise_discovery_human_fields(
                revision_id=source.id,
                human_owned_fields={**source.human_owned_fields, "added_lenses": lenses},
                command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
                actor=command.actor.actor_id,
                origin=command.actor.origin.value,
            )
            return {"revision": replacement.model_dump(mode="json")}, self.discovery_state_token(replacement), StaleEffect()
        return self._execute(
            command,
            target_type="product_discovery_revision",
            target_id=command.revision_id,
            operation=operation,
        )

    def _exclude_discovery_lens(self, command: ExcludeDiscoveryLens) -> CommandResult:
        """Record an authoritative lens inclusion decision in human-owned fields."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self.db.get_discovery_revision(command.revision_id)
            self._assert_expected(command, self.discovery_state_token(source), source.id)
            item_states = dict(source.human_owned_fields.get("item_states") or {})
            item_states[command.lens_id] = "excluded" if command.excluded else "optional"
            replacement = self.db.revise_discovery_human_fields(
                revision_id=source.id,
                human_owned_fields={**source.human_owned_fields, "item_states": item_states},
                command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
                actor=command.actor.actor_id,
                origin=command.actor.origin.value,
            )
            return {"revision": replacement.model_dump(mode="json")}, self.discovery_state_token(replacement), StaleEffect()
        return self._execute(
            command,
            target_type="product_discovery_revision",
            target_id=command.revision_id,
            operation=operation,
        )

    def _build_discovery_projection(
        self,
        command: BuildLayer1DiscoveryContextProjection,
    ) -> CommandResult:
        """Build or reuse the deterministic Layer 1 discovery projection."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            projection = self.services.discovery_service.build_layer1_projection(
                command.revision_id,
                command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
            )
            return {"projection": projection}, projection["content_hash"], StaleEffect()
        return self._execute(
            command,
            target_type="discovery_context_projection",
            target_id=command.revision_id,
            operation=operation,
        )

    def _start_competitor_research(self, command: StartCompetitorResearch) -> CommandResult:
        """Queue research only after an explicit enabled mode and bounded scope."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            mode = CompetitorResearchMode(str(command.scope.get("mode") or "no_competitor_research"))
            if mode == CompetitorResearchMode.NONE:
                raise CommandValidationError("Choose lightweight or deep mode to start competitor research.")
            brief = self.services.brief_service.ensure_brief(command.project_id)
            if brief.status != "published" or not brief.current_published_revision_id:
                raise CommandValidationError("Publish the Layer 0 brief before starting competitor research.")
            payload = {**command.scope, "mode": mode.value, "source_brief_revision_id": brief.current_published_revision_id}
            payload.update({
                "runtime_settings": self._discovery_settings_snapshot(command.project_id),
                "prompt_key": "competitor_evidence_extraction_v1",
                "prompt_version": "1.0.0",
            })
            job = self.services.job_service.enqueue(
                project_id=command.project_id,
                kind="research",
                workflow="competitor_research",
                scope="product_discovery",
                request_payload=payload,
                dedupe_key=f"competitor-research:{command.project_id}:{state_token(payload)}",
            )
            return {"job": job.model_dump(mode="json"), "job_ids": [job.id]}, job.id, StaleEffect()
        return self._execute(
            command,
            target_type="workflow_request",
            target_id="competitor_research",
            operation=operation,
        )

    def _cancel_competitor_research(self, command: CancelCompetitorResearch) -> CommandResult:
        """Request cancellation while preserving completed checkpoints."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            current = self.db.get_platform_job(command.job_id)
            if current.project_id != command.project_id or current.workflow != "competitor_research":
                raise CommandValidationError("Competitor research job does not belong to this project.")
            job = self.services.job_service.cancel(command.job_id)
            if job.project_id != command.project_id or job.workflow != "competitor_research":
                raise CommandValidationError("Competitor research job does not belong to this project.")
            return {"job": job.model_dump(mode="json")}, job.id, StaleEffect()
        return self._execute(
            command,
            target_type="platform_job",
            target_id=command.job_id,
            operation=operation,
        )

    def _transition_competitor_research(self, command: Any, target_state: str) -> CommandResult:
        """Apply approval or rejection to a research revision independently."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self.db.get_competitor_research_revision(command.revision_id)
            self._assert_expected(command, self.competitor_research_state_token(source), source.id)
            updated = self.db.transition_competitor_research_revision(
                revision_id=source.id,
                target_state=target_state,
                command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
                actor=command.actor.actor_id,
                origin=command.actor.origin.value,
            )
            return {"revision": updated.model_dump(mode="json")}, self.competitor_research_state_token(updated), StaleEffect()
        return self._execute(
            command,
            target_type="competitor_research_revision",
            target_id=command.revision_id,
            operation=operation,
        )

    def _attach_competitor_research(
        self,
        command: AttachCompetitorResearchToDiscovery | DetachCompetitorResearchFromDiscovery,
    ) -> CommandResult:
        """Create a discovery candidate with approved research attached or detached."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self.db.get_discovery_revision(command.discovery_revision_id)
            self._assert_expected(command, self.discovery_state_token(source), source.id)
            research_id = (
                command.competitor_research_revision_id
                if isinstance(command, AttachCompetitorResearchToDiscovery)
                else None
            )
            replacement = self.db.revise_discovery_human_fields(
                revision_id=source.id,
                human_owned_fields=source.human_owned_fields,
                command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
                actor=command.actor.actor_id,
                origin=command.actor.origin.value,
                competitor_research_revision_id=research_id,
            )
            return {"revision": replacement.model_dump(mode="json")}, self.discovery_state_token(replacement), StaleEffect()
        return self._execute(
            command,
            target_type="product_discovery_revision",
            target_id=command.discovery_revision_id,
            operation=operation,
        )

    def _set_competitor_finding_state(
        self,
        command: ExcludeCompetitorFinding | IncludeCompetitorFinding | MarkCompetitorFindingStale,
    ) -> CommandResult:
        """Create a research candidate containing an authoritative finding decision."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self.db.get_competitor_research_revision(command.revision_id)
            self._assert_expected(command, self.competitor_research_state_token(source), source.id)
            decisions = dict(source.human_decisions)
            if isinstance(command, MarkCompetitorFindingStale):
                finding_freshness = dict(decisions.get("finding_freshness") or {})
                finding_freshness[command.finding_id] = "stale"
                decisions["finding_freshness"] = finding_freshness
                replacement = self.db.revise_competitor_human_decisions(
                    revision_id=source.id,
                    human_decisions=decisions,
                    command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
                )
                return {"revision": replacement.model_dump(mode="json")}, self.competitor_research_state_token(replacement), StaleEffect()
            finding_states = dict(decisions.get("finding_states") or {})
            finding_states[command.finding_id] = (
                "excluded" if isinstance(command, ExcludeCompetitorFinding) else command.context_state
            )
            decisions["finding_states"] = finding_states
            replacement = self.db.revise_competitor_human_decisions(
                revision_id=source.id,
                human_decisions=decisions,
                command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
            )
            return {"revision": replacement.model_dump(mode="json")}, self.competitor_research_state_token(replacement), StaleEffect()
        return self._execute(
            command,
            target_type="competitor_research_revision",
            target_id=command.revision_id,
            operation=operation,
        )

    def _modify_competitor_scope(self, command: AddCompetitor | RemoveCompetitor) -> CommandResult:
        """Record an explicit competitor scope override without mutating research evidence."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self.db.get_competitor_research_revision(command.revision_id)
            self._assert_expected(command, self.competitor_research_state_token(source), source.id)
            decisions = dict(source.human_decisions)
            additions = set(str(item) for item in decisions.get("competitor_additions") or [])
            removals = set(str(item) for item in decisions.get("competitor_removals") or [])
            if isinstance(command, AddCompetitor):
                additions.add(command.competitor_name.strip())
            else:
                removals.add(command.competitor_id)
            replacement = self.db.revise_competitor_human_decisions(
                revision_id=source.id,
                human_decisions={
                    **decisions,
                    "competitor_additions": sorted(additions),
                    "competitor_removals": sorted(removals),
                },
                command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
            )
            return {"revision": replacement.model_dump(mode="json")}, self.competitor_research_state_token(replacement), StaleEffect()
        return self._execute(
            command,
            target_type="competitor_research_revision",
            target_id=command.revision_id,
            operation=operation,
        )

    def _refresh_competitor_research(self, command: RefreshCompetitorResearch) -> CommandResult:
        """Queue an explicit bounded refresh from a retained research scope."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            source = self.db.get_competitor_research_revision(command.revision_id)
            self._assert_expected(command, self.competitor_research_state_token(source), source.id)
            scope = source.scope.model_dump(mode="json")
            selected_competitor_ids = set(command.competitor_ids)
            selected_finding_ids = set(command.finding_ids)
            for item in [*source.inferred_pillars, *source.territories, *source.gaps, *source.derived_lenses]:
                if item.id not in selected_finding_ids:
                    continue
                competitor_id = getattr(item, "competitor_id", None)
                if competitor_id:
                    selected_competitor_ids.add(str(competitor_id))
                selected_competitor_ids.update(str(value) for value in getattr(item, "competitor_ids", []))
                selected_competitor_ids.update(str(value) for value in getattr(item, "supporting_competitor_ids", []))
            if selected_competitor_ids:
                scope["competitor_names"] = [
                    item.name for item in source.profiles if item.id in selected_competitor_ids
                ]
            scope.update({
                "refresh_from_revision_id": source.id,
                "refresh_competitor_ids": sorted(selected_competitor_ids),
                "refresh_finding_ids": list(command.finding_ids),
                "stale_only": command.stale_only,
                "runtime_settings": self._discovery_settings_snapshot(command.project_id),
                "prompt_key": "competitor_evidence_extraction_v1",
                "prompt_version": "1.0.0",
            })
            job = self.services.job_service.enqueue(
                project_id=command.project_id,
                kind="research",
                workflow="competitor_research",
                scope="product_discovery",
                request_payload=scope,
                dedupe_key=f"competitor-research-refresh:{source.id}:{state_token(scope)}",
            )
            return {"job": job.model_dump(mode="json"), "job_ids": [job.id]}, job.id, StaleEffect()
        return self._execute(
            command,
            target_type="workflow_request",
            target_id=f"competitor_research_refresh:{command.revision_id}",
            operation=operation,
        )

    def _rebuild_competitive_projection(
        self,
        command: RebuildCompetitiveContextProjection,
    ) -> CommandResult:
        """Build compact approved competitive context without raw research text."""
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            projection = self.services.discovery_service.build_competitive_projection(
                command.discovery_revision_id,
                command.competitor_research_revision_id,
                command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
            )
            return {"projection": projection}, projection["content_hash"], StaleEffect()
        return self._execute(
            command,
            target_type="competitive_context_projection",
            target_id=command.competitor_research_revision_id,
            operation=operation,
        )

    @staticmethod
    def _deep_merge(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        """Merge nested human-owned dictionaries while replacing scalar/list values."""
        merged = dict(current)
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = CommandDiscoveryMixin._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _discovery_settings_snapshot(self, project_id: str) -> dict[str, Any]:
        """Freeze model assignments and discovery controls into a queued job."""
        settings = self.db.get_project_model_settings(project_id)
        if settings is not None:
            return settings.model_dump(mode="json")
        return default_project_model_settings(self.services.config)
