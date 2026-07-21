from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from strata.critic_policy import CRITIC_POLICY_VERSION, stable_source_fingerprint


def utc_now() -> str:
    """Return a portable ISO timestamp without importing the composed database class."""
    return datetime.now(timezone.utc).isoformat()


class CriticDatabaseMixin:
    """Persist human authority evidence and deduplicated model review findings."""

    def record_human_artifact_action(
        self, *, project_id: str, artifact_type: str, artifact_id: str, action_type: str,
        actor: str = "user", origin: str = "api", revision_id: str = "", payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an authority event used by policy independently of current status."""
        self._validate_critic_artifact(project_id, artifact_type, artifact_id, revision_id)
        action_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"INSERT INTO artifact_authority_actions (id, project_id, artifact_type, artifact_id, revision_id, action_type, actor, origin, payload, created_at) VALUES ({', '.join([self.param] * 10)})",
            (action_id, project_id, artifact_type, artifact_id, revision_id, action_type, actor, origin, self._dump_json(payload or {}), now),
        )
        return dict(self._fetchone(f"SELECT * FROM artifact_authority_actions WHERE id = {self.param}", (action_id,)))

    def has_human_artifact_action(self, project_id: str, artifact_type: str, artifact_id: str) -> bool:
        """Return whether an explicit non-model authority event exists for an artifact."""
        row = self._fetchone(
            f"SELECT 1 AS found FROM artifact_authority_actions WHERE project_id = {self.param} AND artifact_type = {self.param} AND artifact_id = {self.param} AND actor NOT IN ('system', 'model', 'critic') LIMIT 1",
            (project_id, artifact_type, artifact_id),
        )
        return row is not None

    def create_critic_finding(
        self, *, project_id: str, artifact_type: str, artifact_id: str, critic_type: str,
        category: str, severity: str, explanation: str, evidence: dict[str, Any], recommended_action: str,
        artifact_revision_id: str = "", source_payload: Any = None, model_reference: str = "", job_reference: str = "",
        policy_version: str = CRITIC_POLICY_VERSION,
    ) -> dict[str, Any]:
        """Insert one open finding, returning the existing row when a retry dedupes."""
        self._validate_critic_artifact(project_id, artifact_type, artifact_id, artifact_revision_id)
        fingerprint = stable_source_fingerprint(source_payload if source_payload is not None else evidence)
        finding_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO critic_findings (
                id, project_id, artifact_type, artifact_id, artifact_revision_id, critic_type,
                policy_version, category, severity, explanation, evidence, recommended_action,
                source_fingerprint, model_reference, job_reference, status, created_at, updated_at,
                resolution_action, resolution_note, resolved_by, resolved_at
            ) VALUES ({', '.join([self.param] * 22)})
            ON CONFLICT (project_id, artifact_type, artifact_id, artifact_revision_id, critic_type, policy_version, category, source_fingerprint)
            DO NOTHING
            """,
            (finding_id, project_id, artifact_type, artifact_id, artifact_revision_id, critic_type,
             policy_version, category, severity, explanation, self._dump_json(evidence), recommended_action,
             fingerprint, model_reference, job_reference, "open", now, now, "", "", "", None),
        )
        row = self._fetchone(
            f"SELECT * FROM critic_findings WHERE project_id = {self.param} AND artifact_type = {self.param} AND artifact_id = {self.param} AND artifact_revision_id = {self.param} AND critic_type = {self.param} AND policy_version = {self.param} AND category = {self.param} AND source_fingerprint = {self.param}",
            (project_id, artifact_type, artifact_id, artifact_revision_id, critic_type, policy_version, category, fingerprint),
        )
        return self._critic_finding_dict(row)

    def list_critic_findings(self, project_id: str, *, artifact_id: str | None = None) -> list[dict[str, Any]]:
        """Return durable findings without mutating their review or freshness state."""
        query = f"SELECT * FROM critic_findings WHERE project_id = {self.param}"
        params: list[Any] = [project_id]
        if artifact_id is not None:
            query += f" AND artifact_id = {self.param}"
            params.append(artifact_id)
        query += " ORDER BY created_at DESC"
        return [self._critic_finding_dict(row) for row in self._fetchall(query, tuple(params))]

    def resolve_critic_finding(self, finding_id: str, *, action: str, note: str, resolved_by: str) -> dict[str, Any]:
        """Atomically resolve a finding and append its separate human authority event."""
        if action not in {"accepted", "dismissed", "superseded"}:
            raise ValueError(f"Unsupported finding resolution: {action}")
        now = utc_now()
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(f"SELECT * FROM critic_findings WHERE id = {self.param}", (finding_id,))
                row = cursor.fetchone()
                if row is None:
                    raise ValueError(f"Critic finding not found: {finding_id}")
                if str(row["status"]) != "open":
                    raise ValueError("Critic finding has already been resolved.")
                cursor.execute(
                    f"UPDATE critic_findings SET status = {self.param}, resolution_action = {self.param}, resolution_note = {self.param}, resolved_by = {self.param}, resolved_at = {self.param}, updated_at = {self.param} WHERE id = {self.param}",
                    (action, action, note, resolved_by, now, now, finding_id),
                )
                cursor.execute(
                    f"INSERT INTO artifact_authority_actions (id, project_id, artifact_type, artifact_id, revision_id, action_type, actor, origin, payload, created_at) VALUES ({', '.join([self.param] * 10)})",
                    (str(uuid.uuid4()), row["project_id"], row["artifact_type"], row["artifact_id"], row["artifact_revision_id"],
                     "resolve_finding", resolved_by, "critic_finding_resolution", self._dump_json({"finding_id": finding_id, "resolution": action}), now),
                )
            finally:
                cursor.close()
        return self._critic_finding_dict(self._fetchone(f"SELECT * FROM critic_findings WHERE id = {self.param}", (finding_id,)))

    def _validate_critic_artifact(self, project_id: str, artifact_type: str, artifact_id: str, revision_id: str = "") -> None:
        """Enforce project ownership for the supported polymorphic artifact references."""
        if artifact_type == "layer1_pillar":
            artifact = self.get_node(artifact_id)
            valid = artifact.project_id == project_id and artifact.layer == 1 and artifact.node_type == "pillar"
        elif artifact_type == "layer2_feature":
            valid = self.get_layer2_feature(artifact_id).project_id == project_id
        elif artifact_type == "layer3_expansion":
            head = self._fetchone(
                f"SELECT project_id FROM layer3_expansion_heads WHERE id = {self.param}", (artifact_id,),
            )
            valid = head is not None and str(head["project_id"]) == project_id
            if valid and revision_id:
                revision = self._fetchone(
                    f"SELECT 1 AS found FROM layer3_expansion_revisions WHERE id = {self.param} AND logical_expansion_id = {self.param} AND project_id = {self.param}",
                    (revision_id, artifact_id, project_id),
                )
                valid = revision is not None
        else:
            raise ValueError(f"Unsupported artifact type: {artifact_type}")
        if not valid:
            raise ValueError("Critic artifact does not belong to this project or logical revision.")

    def _critic_finding_dict(self, row: Any) -> dict[str, Any]:
        """Decode backend-specific JSON columns into one portable finding payload."""
        result = dict(row)
        result["evidence"] = self._load_json(result.get("evidence"))
        return result
