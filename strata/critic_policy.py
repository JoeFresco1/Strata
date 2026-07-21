from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


CRITIC_POLICY_VERSION = "human-authority-v1"

HUMAN_LAYER2_ACTIONS = {
    "keep", "cut", "prioritize", "approve_for_layer3", "rename", "merge",
    "manual_add", "reassign_owner", "add_relationship", "remove_relationship",
}
HUMAN_LAYER3_ACTIONS = {
    "accept_full_candidate", "apply_partial_candidate", "reject_candidate", "restore_revision",
    "human_edit", "approve", "reject", "needs_review",
}
HUMAN_OVERLAP_ACTIONS = {"accept_merge", "link", "dismiss", "keep_separate"}


class CriticDisposition(StrEnum):
    """Typed outcomes for every generated recommendation that could affect durable state."""

    AUTOMATIC_ROUTING = "automatic_routing"
    FINDING_ONLY = "finding_only"
    INVALID = "invalid"
    REQUIRES_HUMAN_COMMAND = "requires_human_command"


@dataclass(frozen=True)
class CriticPolicyResult:
    """Deterministic authority decision returned before any critic-driven mutation."""

    disposition: CriticDisposition
    protected: bool
    reason: str


def stable_source_fingerprint(value: Any) -> str:
    """Hash canonical JSON so retries and equivalent model output share one finding."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class CriticAuthorityPolicy:
    """Resolve whether model output may route an artifact or must remain a finding."""

    def __init__(self, db: Any):
        self.db = db

    def evaluate(
        self, *, project_id: str, artifact_type: str, artifact_id: str, revision_id: str = "",
        current_review_state: str = "", current_actor: str = "", current_origin: str = "",
        proposed_action: str = "route_for_review", source_freshness: str = "unknown",
        is_new_unreviewed_candidate: bool | None = None,
    ) -> CriticPolicyResult:
        """Classify one artifact from durable authority evidence rather than status alone."""
        if not artifact_id:
            return CriticPolicyResult(CriticDisposition.INVALID, False, "artifact_id is required")
        if source_freshness not in {"fresh", "stale", "unknown"}:
            return CriticPolicyResult(CriticDisposition.INVALID, False, "invalid source freshness")
        if proposed_action == "mark_stale" and current_origin in {"model", "critic", "model_critic"}:
            return CriticPolicyResult(CriticDisposition.INVALID, False, "model opinion cannot set dependency freshness")
        if artifact_type == "layer1_pillar":
            pillar = self.db.get_node(artifact_id)
            protected = (
                self.db.has_human_artifact_action(project_id, artifact_type, artifact_id)
                or pillar.status in {"kept", "cut", "merged", "prioritized"}
            )
        elif artifact_type == "layer2_feature":
            protected = self._layer2_has_human_authority(project_id, artifact_id)
        elif artifact_type == "layer3_expansion":
            protected = self._layer3_has_human_authority(project_id, artifact_id, revision_id)
        else:
            return CriticPolicyResult(CriticDisposition.INVALID, False, f"unsupported artifact type: {artifact_type}")
        protected = protected or current_actor not in {"", "system", "model", "critic"} or current_origin in {
            "user", "api_review", "assistant_confirmed", "api_restore", "critic_finding_resolution",
        }
        if protected:
            return CriticPolicyResult(CriticDisposition.FINDING_ONLY, True, "durable human authority exists")
        if is_new_unreviewed_candidate is False and current_review_state in {"approved", "rejected"}:
            return CriticPolicyResult(CriticDisposition.REQUIRES_HUMAN_COMMAND, False, "reviewed state lacks sufficient authority provenance")
        return CriticPolicyResult(CriticDisposition.AUTOMATIC_ROUTING, False, "generated artifact has no durable human authority")

    def require_command(self, *, operation: str) -> CriticPolicyResult:
        """Mark a high-impact operation as legal only through an explicit human command."""
        return CriticPolicyResult(CriticDisposition.REQUIRES_HUMAN_COMMAND, True, f"{operation} requires explicit human confirmation")

    def _layer2_has_human_authority(self, project_id: str, feature_id: str) -> bool:
        """Ignore legacy system recommendations while honoring every durable human decision."""
        for action in self.db.list_layer2_review_actions(project_id):
            if action.feature_id != feature_id or action.action_type not in HUMAN_LAYER2_ACTIONS:
                continue
            source = str((action.payload or {}).get("source", ""))
            legacy_graph_recommendation = (
                action.action_type == "merge"
                and "recommended_target_feature_id" in (action.payload or {})
                and "confidence" in (action.payload or {})
            )
            if source not in {"graph_critic", "coverage_critic", "system_critic"} and not legacy_graph_recommendation:
                return True
        feature = self.db.get_layer2_feature(feature_id)
        return (
            self.db.has_human_artifact_action(project_id, "layer2_feature", feature_id)
            or feature.status in {"kept", "cut", "approved", "renamed", "merged"}
        )

    def _layer3_has_human_authority(self, project_id: str, logical_id: str, revision_id: str) -> bool:
        """Treat explicit revision actions and field ownership as durable human authority."""
        query = f"SELECT action_type, actor, origin FROM layer3_revision_actions WHERE project_id = {self.db.param} AND logical_expansion_id = {self.db.param}"
        params: list[Any] = [project_id, logical_id]
        if revision_id:
            query += f" AND (revision_id = {self.db.param} OR new_active_revision_id = {self.db.param})"
            params.extend([revision_id, revision_id])
        for row in self.db._fetchall(query, tuple(params)):
            if str(row["action_type"]) in HUMAN_LAYER3_ACTIONS and str(row["actor"]) not in {"system", "model", "critic"}:
                return True
        legacy = self.db._fetchone(
            f"SELECT 1 AS found FROM layer3_expansion_actions WHERE project_id = {self.db.param} AND expansion_id = {self.db.param} AND action_type IN ('edit', 'approve', 'reject', 'restore', 'accept', 'partial_accept') LIMIT 1",
            (project_id, logical_id),
        )
        if legacy is not None:
            return True
        if revision_id:
            try:
                ownership = self.db.get_layer3_revision(revision_id).get("field_ownership", {})
            except ValueError:
                ownership = {}
            if any(str(value).startswith("human") for value in ownership.values()):
                return True
        return self.db.has_human_artifact_action(project_id, "layer3_expansion", logical_id)
