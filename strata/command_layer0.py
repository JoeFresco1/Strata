from __future__ import annotations

from typing import Any

from strata.command_types import AppendBriefPlanTurn, CommandResult, PublishBrief, StaleEffect, UpdateBriefDraft


class CommandLayer0Mixin:
    """Execute immutable-draft and publication commands through the shared boundary."""

    def _update_brief(self, command: UpdateBriefDraft) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            current = self.services.brief_service.ensure_brief(command.project_id)
            self._lock("project_briefs", current.id)
            self._assert_expected(command, self.brief_state_token(current), current.id)
            brief = self.services.brief_service.update_brief(
                command.project_id, command.updates, origin=command.actor.origin.value,
                actor=command.actor.actor_id, creation_command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
            )
            return {"brief": brief.model_dump(mode="json")}, self.brief_state_token(brief), StaleEffect()
        return self._execute(command, target_type="brief", target_id=command.project_id, operation=operation)

    def _append_brief_plan_turn(self, command: AppendBriefPlanTurn) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            current = self.services.brief_service.ensure_brief(command.project_id)
            self._lock("project_briefs", current.id)
            self._assert_expected(command, self.brief_state_token(current), current.id)
            reply, brief, guidance = self.services.brief_service.append_plan_turn(
                command.project_id, command.message, command.idempotency_key,
                origin=command.actor.origin.value, actor=command.actor.actor_id,
            )
            return {"reply": reply, "brief": brief.model_dump(mode="json"), "guidance": guidance}, self.brief_state_token(brief), StaleEffect()
        return self._execute(command, target_type="brief", target_id=command.project_id, operation=operation)

    def _publish_brief(self, command: PublishBrief) -> CommandResult:
        def operation() -> tuple[dict[str, Any], str, StaleEffect]:
            current = self.services.brief_service.ensure_brief(command.project_id)
            self._lock("project_briefs", current.id)
            self._assert_expected(command, self.brief_state_token(current), current.id)
            old_published = current.current_published_revision_id
            brief = self.services.brief_service.publish(
                command.project_id, origin=command.actor.origin.value,
                actor=command.actor.actor_id, creation_command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
            )
            job_ids: list[str] = []
            research_ids: list[str] = []
            if command.request_research and self.services.research_service.competitive_intelligence_enabled(command.project_id):
                research = self.services.research_service.enqueue_layer0(command.project_id, reason="publish")
                job = self.services.job_service.enqueue(
                    project_id=command.project_id, kind="research", workflow="research", scope="layer0",
                    request_payload={"research_job_id": research.id, "research_job_type": research.job_type},
                    dedupe_key=f"research:{research.id}",
                )
                research_ids.append(research.id)
                job_ids.append(job.id)
            propagation = {"directly_affected": [], "transitively_affected": [], "already_stale": [], "propagation_count": 0, "complete": True, "dependency_reason": "brief_republished"}
            if old_published and brief.current_published_revision_id != old_published:
                propagation = self.db.mark_descendants_stale(
                    project_id=command.project_id, source_artifact_type="brief", source_artifact_id=brief.id,
                    previous_source_revision_id=old_published, replacement_source_revision_id=str(brief.current_published_revision_id or ""),
                    command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
                    actor=command.actor.actor_id, origin=command.actor.origin.value, reason_code="brief_republished",
                )
            direct = tuple(item["artifact_id"] for item in propagation["directly_affected"])
            transitive = tuple(item["artifact_id"] for item in propagation["transitively_affected"])
            already = tuple(item["artifact_id"] for item in propagation["already_stale"])
            affected = direct + transitive
            stale = StaleEffect(
                "marked" if affected else "none", affected, "Published brief revision changed." if affected else "",
                direct, transitive, already, int(propagation["propagation_count"]), bool(propagation["complete"]),
            )
            data = {"brief": brief.model_dump(mode="json"), "job_ids": job_ids, "research_job_ids": research_ids, "stale_effect": propagation}
            return data, self.brief_state_token(brief), stale
        return self._execute(command, target_type="brief", target_id=command.project_id, operation=operation)
