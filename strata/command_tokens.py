from __future__ import annotations

from typing import Any

from strata.command_types import state_token


class CommandTokenMixin:
    """Build optimistic-concurrency tokens for canonical command targets."""

    def brief_state_token(self, brief: Any) -> str:
        """Return the concurrency token exposed with a brief projection."""
        return state_token({
            "id": brief.id, "status": brief.status, "updated_at": brief.updated_at.isoformat(),
            "product_idea": brief.product_idea, "problem": brief.problem,
            "target_users": brief.target_users, "goals": brief.goals,
            "constraints": brief.constraints, "preferred_directions": brief.preferred_directions,
            "rejected_directions": brief.rejected_directions, "notes": brief.notes,
            "current_draft_revision_id": getattr(brief, "current_draft_revision_id", None),
            "current_published_revision_id": getattr(brief, "current_published_revision_id", None),
        })

    def project_state_token(self, project: Any) -> str:
        """Return a project token excluding read-only last-opened activity."""
        return state_token({
            "id": project.id, "name": project.name, "idea": project.idea,
            "updated_at": project.updated_at.isoformat(),
            "archived_at": project.archived_at.isoformat() if project.archived_at else None,
            "lifecycle_state": project.lifecycle_state, "source_project_id": project.source_project_id,
        })

    def specification_source_state_token(self, project_id: str) -> str:
        """Hash every canonical source coordinate used by manifest selection."""
        head = self.db.get_brief_head(project_id) or {}
        pillars = self.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
        features = self.db.list_layer2_features(project_id)
        layer3_heads = self.db._fetchall(
            f"SELECT id, feature_id, active_revision_id FROM layer3_expansion_heads WHERE project_id = {self.db.param} ORDER BY id",
            (project_id,),
        )
        return state_token({
            "project": self.project_state_token(self.db.get_project(project_id)),
            "published_brief_revision_id": head.get("current_published_revision_id"),
            "pillars": [self.pillar_state_token(item) for item in sorted(pillars, key=lambda value: value.id)],
            "features": [self.feature_state_token(item) for item in sorted(features, key=lambda value: value.id)],
            "layer3_heads": [dict(item) for item in layer3_heads],
        })

    def pillar_state_token(self, pillar: Any) -> str:
        """Return a token that changes for every authoritative Layer 1 field."""
        return state_token({
            "id": pillar.id, "title": pillar.title, "description": pillar.description,
            "status": pillar.status, "priority": pillar.priority, "json_payload": pillar.json_payload,
        })

    def feature_state_token(self, feature: Any) -> str:
        """Return the concurrency token exposed with a Layer 2 feature projection."""
        return state_token({
            "id": feature.id, "updated_at": feature.updated_at.isoformat(),
            "canonical_name": feature.canonical_name, "description": feature.description,
            "feature_type": str(feature.feature_type), "granularity_class": str(feature.granularity_class),
            "owner_pillar_id": feature.owner_pillar_id, "status": feature.status,
            "aliases": feature.aliases, "metadata": feature.metadata,
        })

    def finding_state_token(self, finding: dict[str, Any]) -> str:
        """Return the concurrency token for one durable critic finding."""
        return state_token({
            "id": finding["id"], "status": finding["status"], "updated_at": str(finding["updated_at"]),
            "resolution_action": finding.get("resolution_action", ""),
        })
