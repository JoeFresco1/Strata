from __future__ import annotations

from typing import Any

from strata.command_types import ApplicationCommand, StaleEffect
from strata.dependency_db import pillar_revision_token


class CommandFreshnessMixin:
    """Keep command-layer lineage registration and typed propagation rules centralized."""

    def _authority(self, command: ApplicationCommand, artifact_type: str, artifact_id: str, action: str, payload: dict[str, Any] | None = None, revision_id: str = "") -> None:
        """Append the human authority record inside the command transaction."""
        self.db.record_human_artifact_action(
            project_id=command.project_id, artifact_type=artifact_type, artifact_id=artifact_id,
            revision_id=revision_id, action_type=action, actor=command.actor.actor_id,
            origin=command.actor.origin.value, payload=payload or {},
        )
        self._fail("after_authority_write")

    def _register_pillar_lineage(self, pillar: Any, revision_id: str, *, quality: str = "exact") -> None:
        """Bind one pillar version to the exact active published brief revision."""
        brief = self.services.brief_service.ensure_brief(pillar.project_id)
        source_revision = str(brief.current_published_revision_id or "")
        self.db.set_artifact_freshness(
            project_id=pillar.project_id, artifact_type="layer1_pillar", artifact_id=pillar.id,
            artifact_revision_id=revision_id, freshness_state="current", lineage_quality=quality,
        )
        if source_revision:
            self.db.add_artifact_dependency(
                project_id=pillar.project_id, dependent_artifact_type="layer1_pillar",
                dependent_artifact_id=pillar.id, dependent_revision_id=revision_id,
                source_artifact_type="brief", source_artifact_id=brief.id,
                source_revision_id=source_revision, lineage_quality=quality,
            )

    def _register_feature_lineage(self, feature: Any, revision_id: str, *, quality: str = "exact") -> None:
        """Bind one feature version to its current brief and owner-pillar versions."""
        brief = self.services.brief_service.ensure_brief(feature.project_id)
        pillar = self.db.get_node(feature.owner_pillar_id)
        self.db.set_artifact_freshness(
            project_id=feature.project_id, artifact_type="layer2_feature", artifact_id=feature.id,
            artifact_revision_id=revision_id, freshness_state="current", lineage_quality=quality,
        )
        if brief.current_published_revision_id:
            self.db.add_artifact_dependency(
                project_id=feature.project_id, dependent_artifact_type="layer2_feature",
                dependent_artifact_id=feature.id, dependent_revision_id=revision_id,
                source_artifact_type="brief", source_artifact_id=brief.id,
                source_revision_id=str(brief.current_published_revision_id), lineage_quality=quality,
            )
        self.db.add_artifact_dependency(
            project_id=feature.project_id, dependent_artifact_type="layer2_feature",
            dependent_artifact_id=feature.id, dependent_revision_id=revision_id,
            source_artifact_type="layer1_pillar", source_artifact_id=pillar.id,
            source_revision_id=pillar_revision_token(pillar), lineage_quality=quality,
        )

    def _propagate_content_change(
        self, command: ApplicationCommand, *, artifact_type: str, artifact_id: str,
        previous_revision_id: str, replacement_revision_id: str, reason_code: str,
    ) -> StaleEffect:
        """Run deterministic dependency propagation and return its typed command report."""
        report = self.db.mark_descendants_stale(
            project_id=command.project_id, source_artifact_type=artifact_type,
            source_artifact_id=artifact_id, previous_source_revision_id=previous_revision_id,
            replacement_source_revision_id=replacement_revision_id,
            command_id=str(getattr(self.db._transaction_state, "command_id", "") or command.idempotency_key),
            actor=command.actor.actor_id, origin=command.actor.origin.value, reason_code=reason_code,
        )
        direct = tuple(item["artifact_id"] for item in report["directly_affected"])
        transitive = tuple(item["artifact_id"] for item in report["transitively_affected"])
        already = tuple(item["artifact_id"] for item in report["already_stale"])
        affected = direct + transitive
        return StaleEffect(
            "marked" if affected else "none", affected, reason_code,
            direct, transitive, already, int(report["propagation_count"]), bool(report["complete"]),
        )
