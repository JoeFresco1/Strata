from __future__ import annotations

from typing import Any


class FreshnessValidationService:
    """Validate selected canonical revisions before derived output is presented as current."""

    def __init__(self, db: Any):
        self.db = db

    def validate_layer3_export(self, project_id: str, expansion_ids: list[str] | None = None) -> dict[str, Any]:
        """Return coherence, stale, missing, superseded, and mixed-lineage diagnostics."""
        expansions = self.db.list_layer3_expansions(project_id)
        selected = [item for item in expansions if not expansion_ids or item.id in expansion_ids]
        stale: list[dict[str, Any]] = []
        missing: list[dict[str, str]] = []
        superseded: list[dict[str, str]] = []
        source_sets: dict[str, set[str]] = {}
        for expansion in selected:
            revision_id = str(expansion.active_revision_id or "")
            if not revision_id:
                missing.append({"artifact_type": "layer3_expansion", "artifact_id": expansion.id, "reason": "missing_active_revision"})
                continue
            freshness = self.db.freshness_for_artifact(
                project_id, "layer3_revision", expansion.id, revision_id,
            )
            if freshness["freshness_state"] != "current":
                stale.append(freshness)
            dependencies = self.db._fetchall(
                f"SELECT * FROM artifact_dependencies WHERE project_id = {self.db.param} AND dependent_artifact_type = {self.db.param} AND dependent_artifact_id = {self.db.param} AND dependent_revision_id = {self.db.param}",
                (project_id, "layer3_revision", expansion.id, revision_id),
            )
            if not dependencies:
                missing.append({"artifact_type": "layer3_revision", "artifact_id": revision_id, "reason": "missing_dependencies"})
            for dependency in dependencies:
                source_type = str(dependency["source_artifact_type"])
                source_revision = str(dependency["source_revision_id"])
                source_sets.setdefault(source_type, set()).add(source_revision)
                source_state = self.db._fetchone(
                    f"SELECT freshness_state FROM artifact_freshness_states WHERE project_id = {self.db.param} AND artifact_type = {self.db.param} AND artifact_id = {self.db.param} AND artifact_revision_id = {self.db.param}",
                    (project_id, source_type, str(dependency["source_artifact_id"]), source_revision),
                )
                if source_state and str(source_state["freshness_state"]) == "superseded":
                    superseded.append({
                        "source_artifact_type": source_type,
                        "source_artifact_id": str(dependency["source_artifact_id"]),
                        "source_revision_id": source_revision,
                    })
        mixed = {source_type: sorted(revisions) for source_type, revisions in source_sets.items() if len(revisions) > 1}
        reasons = []
        if stale:
            reasons.append("One or more selected Layer 3 revisions are stale or have unproven freshness.")
        if missing:
            reasons.append("One or more selected artifacts have missing lineage.")
        if superseded:
            reasons.append("One or more selected artifacts depend on superseded sources.")
        if mixed:
            reasons.append("The selected artifacts mix brief, pillar, or feature lineages.")
        return {
            "coherent": not reasons, "stale_artifacts": stale, "missing_dependencies": missing,
            "superseded_sources": superseded, "mixed_lineages": mixed, "actionable_reasons": reasons,
        }

