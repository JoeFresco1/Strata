from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from strata.layer3_revision import (
    TOP_LEVEL_SECTIONS,
    build_structured_diff,
    mark_human_owned_changes,
    merge_selected_sections,
    normalize_human_groups,
)
from strata.models import FeatureExpansion


def utc_now() -> str:
    """Return an ISO timestamp in UTC for Layer 3 storage records."""
    return datetime.now(timezone.utc).isoformat()


class Layer3RevisionConflict(ValueError):
    """Signal an optimistic-concurrency or stale-candidate conflict."""


class Layer3DatabaseMixin:
    """Persist Layer 3 active projections, immutable revisions, state, and audit history."""

    _REVISION_JSON_FIELDS = {"payload", "structured_diff", "field_ownership"}
    _ACTION_JSON_FIELDS = {"selected_sections", "before_snapshot", "after_snapshot", "payload"}

    def migrate_layer3_revisions(self) -> int:
        """Backfill every legacy active expansion as revision 1 without changing its projection."""
        migrated = 0
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT * FROM layer3_feature_expansions WHERE active_revision_id = '' OR active_revision_id IS NULL")
                for row in cursor.fetchall():
                    values = self._projection_values(row)
                    logical_id = str(values["id"])
                    revision_id = str(uuid.uuid4())
                    payload = self._artifact_payload(values)
                    ownership = self._legacy_field_ownership(cursor, logical_id, payload)
                    now = utc_now()
                    self._insert_head(cursor, logical_id, values["project_id"], values["feature_id"], revision_id, 2, now)
                    self._insert_revision(
                        cursor,
                        revision_id=revision_id,
                        logical_expansion_id=logical_id,
                        project_id=values["project_id"],
                        revision_number=1,
                        source_layer2_feature_revision=str(payload.get("provenance", {}).get("source_layer2_feature_revision") or "legacy"),
                        source_brief_revision=str(payload.get("provenance", {}).get("source_brief_revision") or "legacy"),
                        source_pillar_revision=str(payload.get("provenance", {}).get("source_pillar_revision") or "legacy"),
                        generation_reference=str(payload.get("provenance", {}).get("generation_reference") or "legacy-backfill"),
                        origin="legacy_backfill",
                        actor="system",
                        payload=payload,
                        structured_diff=build_structured_diff({}, payload),
                        field_ownership=ownership,
                        created_at=str(values["created_at"]),
                    )
                    self._insert_revision_state(cursor, revision_id, "active", values["review_state"], "unknown", now)
                    cursor.execute(
                        f"UPDATE layer3_feature_expansions SET active_revision_id = {self.param}, revision_number = 1 WHERE id = {self.param}",
                        (revision_id, logical_id),
                    )
                    migrated += 1
            finally:
                cursor.close()
        return migrated

    def upsert_layer3_expansion(self, *, expansion_id: str | None = None, **values: Any) -> FeatureExpansion:
        """Create an initial active expansion; retained as a compatibility entrypoint for fixtures/imports."""
        existing = self.get_layer3_expansion_for_feature(values["project_id"], values["feature_id"])
        if existing is not None:
            updates = {section: values[section] for section in TOP_LEVEL_SECTIONS if section in values}
            return self.revise_active_expansion(existing.id, updates, actor="system", origin="compatibility_upsert")
        now = utc_now()
        logical_id = expansion_id or str(uuid.uuid4())
        revision_id = str(uuid.uuid4())
        payload = self._artifact_payload({**values, "id": logical_id})
        ownership = self._selection_ownership(payload)
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                self._insert_head(cursor, logical_id, values["project_id"], values["feature_id"], revision_id, 2, now)
                self._insert_revision(
                    cursor,
                    revision_id=revision_id,
                    logical_expansion_id=logical_id,
                    project_id=values["project_id"],
                    revision_number=1,
                    source_layer2_feature_revision=str(payload.get("provenance", {}).get("source_layer2_feature_revision") or ""),
                    source_brief_revision=str(payload.get("provenance", {}).get("source_brief_revision") or ""),
                    source_pillar_revision=str(payload.get("provenance", {}).get("source_pillar_revision") or ""),
                    generation_reference=str(payload.get("provenance", {}).get("generation_reference") or "initial"),
                    origin="initial",
                    actor="system",
                    payload=payload,
                    structured_diff=build_structured_diff({}, payload),
                    field_ownership=ownership,
                    created_at=now,
                )
                self._insert_revision_state(cursor, revision_id, "active", values.get("review_state", "draft"), "fresh", now)
                self._write_projection(cursor, logical_id, revision_id, 1, payload, values.get("review_state", "draft"), now, now)
            finally:
                cursor.close()
        return self.get_layer3_expansion(logical_id)

    def create_layer3_candidate(
        self,
        *,
        project_id: str,
        feature_id: str,
        artifact_payload: dict[str, Any],
        structured_diff: dict[str, Any],
        field_ownership: dict[str, Any],
        source_layer2_feature_revision: str,
        source_brief_revision: str,
        source_pillar_revision: str,
        generation_reference: str,
        origin: str,
        actor: str,
    ) -> dict[str, Any]:
        """Persist an immutable candidate without advancing the active head or projection."""
        self.migrate_layer3_revisions()
        now = utc_now()
        revision_id = str(uuid.uuid4())
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                head = self._select_head(cursor, project_id, feature_id, lock=True)
                if head is None:
                    logical_id = str(uuid.uuid4())
                    revision_number = 1
                    self._insert_head(cursor, logical_id, project_id, feature_id, None, 2, now)
                else:
                    logical_id = str(self._row_value(head, "id"))
                    revision_number = int(self._row_value(head, "next_revision_number"))
                    cursor.execute(
                        f"UPDATE layer3_expansion_heads SET next_revision_number = {self.param}, updated_at = {self.param} WHERE id = {self.param}",
                        (revision_number + 1, now, logical_id),
                    )
                self._insert_revision(
                    cursor,
                    revision_id=revision_id,
                    logical_expansion_id=logical_id,
                    project_id=project_id,
                    revision_number=revision_number,
                    source_layer2_feature_revision=source_layer2_feature_revision,
                    source_brief_revision=source_brief_revision,
                    source_pillar_revision=source_pillar_revision,
                    generation_reference=generation_reference,
                    origin=origin,
                    actor=actor,
                    payload=artifact_payload,
                    structured_diff=structured_diff,
                    field_ownership=field_ownership,
                    created_at=now,
                )
                self._insert_revision_state(cursor, revision_id, "candidate", "needs_review", "fresh", now)
                before = self._revision_snapshot(cursor, self._row_value(head, "active_revision_id")) if head and self._row_value(head, "active_revision_id") else {}
                after = self._revision_snapshot(cursor, revision_id)
                self._insert_revision_action(
                    cursor,
                    request_id=f"candidate:{revision_id}",
                    project_id=project_id,
                    logical_expansion_id=logical_id,
                    revision_id=revision_id,
                    action_type="generate_candidate",
                    expected_active_revision_id=self._row_value(head, "active_revision_id") if head else None,
                    previous_active_revision_id=self._row_value(head, "active_revision_id") if head else None,
                    new_active_revision_id=self._row_value(head, "active_revision_id") if head else None,
                    selected_sections=[],
                    before_snapshot=before,
                    after_snapshot=after,
                    actor=actor,
                    origin=origin,
                    payload={"feature_id": feature_id, "generation_reference": generation_reference},
                )
            finally:
                cursor.close()
        return self.get_layer3_revision(revision_id)

    def apply_layer3_candidate(
        self,
        *,
        project_id: str,
        logical_expansion_id: str,
        candidate_revision_id: str,
        expected_active_revision_id: str | None,
        request_id: str,
        selected_sections: list[str] | None = None,
        actor: str = "user",
        origin: str = "api",
        fail_after_step: str | None = None,
    ) -> dict[str, Any]:
        """Atomically accept all or selected candidate sections with optimistic concurrency."""
        sections = list(selected_sections or [])
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                prior_action = self._select_action(cursor, request_id)
                if prior_action is not None:
                    return {"idempotent": True, **self._load_action_result(prior_action)}
                head = self._select_head_by_id(cursor, logical_expansion_id, lock=True)
                if head is None or str(self._row_value(head, "project_id")) != project_id:
                    raise ValueError("Layer 3 logical expansion was not found in this project.")
                active_revision_id = self._row_value(head, "active_revision_id")
                if (active_revision_id or None) != (expected_active_revision_id or None):
                    raise Layer3RevisionConflict("The active Layer 3 revision changed. Refresh and compare again before applying.")
                candidate = self._select_revision(cursor, candidate_revision_id)
                if candidate is None or str(self._row_value(candidate, "logical_expansion_id")) != logical_expansion_id:
                    raise ValueError("Layer 3 candidate revision was not found for this expansion.")
                candidate_state = self._select_revision_state(cursor, candidate_revision_id)
                if self._row_value(candidate_state, "workflow_state") != "candidate":
                    raise Layer3RevisionConflict("Only a pending Layer 3 candidate can be applied.")
                self._raise_failpoint(fail_after_step, "verify")
                before = self._revision_snapshot(cursor, active_revision_id) if active_revision_id else {}
                candidate_payload = self._load_json_value(self._row_value(candidate, "payload"), {})
                if sections:
                    if not active_revision_id:
                        raise ValueError("Partial application requires an existing active expansion.")
                    active_payload = self._load_json_value(self._row_value(self._select_revision(cursor, active_revision_id), "payload"), {})
                    applied_payload = merge_selected_sections(active_payload, candidate_payload, sections)
                    new_revision_id, new_revision_number = self._insert_derived_revision(
                        cursor,
                        head=head,
                        project_id=project_id,
                        logical_expansion_id=logical_expansion_id,
                        source_revision=candidate,
                        payload=applied_payload,
                        diff=build_structured_diff(active_payload, applied_payload),
                        origin="partial_apply",
                        actor=actor,
                    )
                    cursor.execute(
                        f"UPDATE layer3_expansion_revision_states SET workflow_state = {self.param}, review_state = {self.param}, updated_at = {self.param} WHERE revision_id = {self.param}",
                        ("applied_partial", "approved", utc_now(), candidate_revision_id),
                    )
                else:
                    new_revision_id = candidate_revision_id
                    new_revision_number = int(self._row_value(candidate, "revision_number"))
                    applied_payload = candidate_payload
                    cursor.execute(
                        f"UPDATE layer3_expansion_revision_states SET workflow_state = {self.param}, review_state = {self.param}, updated_at = {self.param} WHERE revision_id = {self.param}",
                        ("active", "approved", utc_now(), candidate_revision_id),
                    )
                self._raise_failpoint(fail_after_step, "accept")
                if active_revision_id:
                    cursor.execute(
                        f"UPDATE layer3_expansion_revision_states SET workflow_state = {self.param}, updated_at = {self.param} WHERE revision_id = {self.param}",
                        ("superseded", utc_now(), active_revision_id),
                    )
                self._raise_failpoint(fail_after_step, "supersede")
                now = utc_now()
                cursor.execute(
                    f"UPDATE layer3_expansion_heads SET active_revision_id = {self.param}, updated_at = {self.param} WHERE id = {self.param}",
                    (new_revision_id, now, logical_expansion_id),
                )
                self._write_projection(cursor, logical_expansion_id, new_revision_id, new_revision_number, applied_payload, "approved", before.get("created_at", now), now)
                self._raise_failpoint(fail_after_step, "projection")
                after = self._revision_snapshot(cursor, new_revision_id)
                result = {"active_revision": after, "candidate_revision_id": candidate_revision_id, "selected_sections": sections}
                self._insert_revision_action(
                    cursor,
                    request_id=request_id,
                    project_id=project_id,
                    logical_expansion_id=logical_expansion_id,
                    revision_id=candidate_revision_id,
                    action_type="apply_partial_candidate" if sections else "accept_full_candidate",
                    expected_active_revision_id=expected_active_revision_id,
                    previous_active_revision_id=active_revision_id,
                    new_active_revision_id=new_revision_id,
                    selected_sections=sections,
                    before_snapshot=before,
                    after_snapshot=after,
                    actor=actor,
                    origin=origin,
                    payload={"result": result},
                )
                self._raise_failpoint(fail_after_step, "audit")
                return {"idempotent": False, **result}
            finally:
                cursor.close()

    def reject_layer3_candidate(
        self, *, project_id: str, candidate_revision_id: str, request_id: str, actor: str = "user", note: str = ""
    ) -> dict[str, Any]:
        """Reject a pending candidate idempotently without touching the active revision."""
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                prior_action = self._select_action(cursor, request_id)
                if prior_action is not None:
                    return {"idempotent": True, **self._load_action_result(prior_action)}
                revision = self._select_revision(cursor, candidate_revision_id)
                if revision is None or str(self._row_value(revision, "project_id")) != project_id:
                    raise ValueError("Layer 3 candidate revision was not found in this project.")
                state = self._select_revision_state(cursor, candidate_revision_id)
                if self._row_value(state, "workflow_state") != "candidate":
                    raise Layer3RevisionConflict("Only a pending Layer 3 candidate can be rejected.")
                logical_id = str(self._row_value(revision, "logical_expansion_id"))
                head = self._select_head_by_id(cursor, logical_id, lock=True)
                active_id = self._row_value(head, "active_revision_id")
                before = self._revision_snapshot(cursor, active_id) if active_id else {}
                cursor.execute(
                    f"UPDATE layer3_expansion_revision_states SET workflow_state = {self.param}, review_state = {self.param}, updated_at = {self.param} WHERE revision_id = {self.param}",
                    ("rejected", "rejected", utc_now(), candidate_revision_id),
                )
                after = self._revision_snapshot(cursor, candidate_revision_id)
                result = {"candidate_revision": after, "active_revision_id": active_id}
                self._insert_revision_action(
                    cursor, request_id=request_id, project_id=project_id, logical_expansion_id=logical_id,
                    revision_id=candidate_revision_id, action_type="reject_candidate", expected_active_revision_id=active_id,
                    previous_active_revision_id=active_id, new_active_revision_id=active_id, selected_sections=[],
                    before_snapshot=before, after_snapshot=after, actor=actor, origin="api", payload={"note": note, "result": result},
                )
                return {"idempotent": False, **result}
            finally:
                cursor.close()

    def restore_layer3_revision(
        self,
        *,
        project_id: str,
        logical_expansion_id: str,
        source_revision_id: str,
        expected_active_revision_id: str,
        request_id: str,
        actor: str = "user",
    ) -> dict[str, Any]:
        """Atomically restore an earlier accepted payload as a new active revision."""
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                prior_action = self._select_action(cursor, request_id)
                if prior_action is not None:
                    return {"idempotent": True, **self._load_action_result(prior_action)}
                head = self._select_head_by_id(cursor, logical_expansion_id, lock=True)
                if head is None or str(self._row_value(head, "project_id")) != project_id:
                    raise ValueError("Layer 3 logical expansion was not found in this project.")
                active_id = str(self._row_value(head, "active_revision_id") or "")
                if active_id != expected_active_revision_id:
                    raise Layer3RevisionConflict("The active Layer 3 revision changed. Refresh before restoring.")
                source = self._select_revision(cursor, source_revision_id)
                source_state = self._select_revision_state(cursor, source_revision_id)
                if source is None or str(self._row_value(source, "logical_expansion_id")) != logical_expansion_id:
                    raise ValueError("The requested Layer 3 revision does not belong to this expansion.")
                if self._row_value(source_state, "workflow_state") not in {"active", "superseded"}:
                    raise ValueError("Only an earlier accepted Layer 3 revision can be restored.")
                active_revision = self._select_revision(cursor, active_id)
                active_payload = self._load_json_value(self._row_value(active_revision, "payload"), {})
                restored_payload = self._load_json_value(self._row_value(source, "payload"), {})
                new_id, number = self._insert_derived_revision(
                    cursor, head=head, project_id=project_id, logical_expansion_id=logical_expansion_id,
                    source_revision=source, payload=restored_payload, diff=build_structured_diff(active_payload, restored_payload),
                    origin="restore", actor=actor,
                )
                before = self._revision_snapshot(cursor, active_id)
                cursor.execute(
                    f"UPDATE layer3_expansion_revision_states SET workflow_state = {self.param}, updated_at = {self.param} WHERE revision_id = {self.param}",
                    ("superseded", utc_now(), active_id),
                )
                now = utc_now()
                cursor.execute(
                    f"UPDATE layer3_expansion_heads SET active_revision_id = {self.param}, updated_at = {self.param} WHERE id = {self.param}",
                    (new_id, now, logical_expansion_id),
                )
                self._write_projection(cursor, logical_expansion_id, new_id, number, restored_payload, "approved", before.get("created_at", now), now)
                after = self._revision_snapshot(cursor, new_id)
                result = {"active_revision": after, "restored_from_revision_id": source_revision_id}
                self._insert_revision_action(
                    cursor, request_id=request_id, project_id=project_id, logical_expansion_id=logical_expansion_id,
                    revision_id=source_revision_id, action_type="restore_revision", expected_active_revision_id=expected_active_revision_id,
                    previous_active_revision_id=active_id, new_active_revision_id=new_id, selected_sections=list(TOP_LEVEL_SECTIONS),
                    before_snapshot=before, after_snapshot=after, actor=actor, origin="api", payload={"result": result},
                )
                return {"idempotent": False, **result}
            finally:
                cursor.close()

    def get_layer3_expansion(self, expansion_id: str) -> FeatureExpansion:
        """Return the current Layer 3 read projection by logical expansion id."""
        row = self._fetchone(f"SELECT * FROM layer3_feature_expansions WHERE id = {self.param}", (expansion_id,))
        if row is None:
            raise ValueError(f"Layer 3 expansion not found: {expansion_id}")
        return self._row_to_layer3_expansion(row)

    def get_layer3_expansion_for_feature(self, project_id: str, feature_id: str) -> FeatureExpansion | None:
        """Return the active expansion projection for one Layer 2 feature."""
        row = self._fetchone(
            f"SELECT * FROM layer3_feature_expansions WHERE project_id = {self.param} AND feature_id = {self.param}",
            (project_id, feature_id),
        )
        return self._row_to_layer3_expansion(row) if row is not None else None

    def list_layer3_expansions(self, project_id: str) -> list[FeatureExpansion]:
        """List current active projections in stable feature-name order."""
        rows = self._fetchall(
            f"SELECT * FROM layer3_feature_expansions WHERE project_id = {self.param} ORDER BY feature_name, created_at",
            (project_id,),
        )
        return [self._row_to_layer3_expansion(row) for row in rows]

    def get_layer3_revision(self, revision_id: str) -> dict[str, Any]:
        """Return one revision with immutable metadata and its current workflow state."""
        row = self._fetchone(
            f"""
            SELECT revisions.*, states.workflow_state, states.review_state, states.freshness_state, states.updated_at AS state_updated_at
            FROM layer3_expansion_revisions revisions
            JOIN layer3_expansion_revision_states states ON states.revision_id = revisions.id
            WHERE revisions.id = {self.param}
            """,
            (revision_id,),
        )
        if row is None:
            raise ValueError(f"Layer 3 revision not found: {revision_id}")
        return self._revision_values(row)

    def list_layer3_revisions(self, logical_expansion_id: str) -> list[dict[str, Any]]:
        """List all immutable revisions and current states for one logical expansion."""
        rows = self._fetchall(
            f"""
            SELECT revisions.*, states.workflow_state, states.review_state, states.freshness_state, states.updated_at AS state_updated_at
            FROM layer3_expansion_revisions revisions
            JOIN layer3_expansion_revision_states states ON states.revision_id = revisions.id
            WHERE revisions.logical_expansion_id = {self.param}
            ORDER BY revisions.revision_number
            """,
            (logical_expansion_id,),
        )
        return [self._revision_values(row) for row in rows]

    def update_layer3_expansion(self, expansion_id: str, **updates: Any) -> FeatureExpansion:
        """Create a new active revision for explicit human content edits or change review state only."""
        content_updates = {key: value for key, value in updates.items() if key in TOP_LEVEL_SECTIONS}
        if content_updates:
            return self.revise_active_expansion(expansion_id, content_updates, actor="user", origin="api_edit")
        if "review_state" in updates:
            return self.set_active_layer3_review_state(expansion_id, str(updates["review_state"]), actor="user")
        return self.get_layer3_expansion(expansion_id)

    def revise_active_expansion(self, expansion_id: str, updates: dict[str, Any], *, actor: str, origin: str) -> FeatureExpansion:
        """Atomically turn human edits into a new active immutable revision."""
        self.migrate_layer3_revisions()
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                head = self._select_head_by_id(cursor, expansion_id, lock=True)
                if head is None or not self._row_value(head, "active_revision_id"):
                    raise ValueError("Layer 3 active revision was not found.")
                active_id = str(self._row_value(head, "active_revision_id"))
                active = self._select_revision(cursor, active_id)
                payload = self._load_json_value(self._row_value(active, "payload"), {})
                updated = copy.deepcopy(payload)
                ownership = self._load_json_value(self._row_value(active, "field_ownership"), {})
                if "expansion_groups" in updates:
                    groups, ownership = normalize_human_groups(payload.get("expansion_groups", []), updates["expansion_groups"], ownership)
                    updated["expansion_groups"] = groups
                for section in ("feature_intent", "overlap_review", "open_questions"):
                    if section in updates:
                        updated[section] = copy.deepcopy(updates[section])
                if updated == payload:
                    return self.get_layer3_expansion(expansion_id)
                ownership = mark_human_owned_changes(payload, updated, ownership)
                new_id, number = self._insert_derived_revision(
                    cursor, head=head, project_id=str(self._row_value(head, "project_id")), logical_expansion_id=expansion_id,
                    source_revision=active, payload=updated, diff=build_structured_diff(payload, updated), origin=origin, actor=actor,
                    field_ownership=ownership, review_state="needs_review",
                )
                before = self._revision_snapshot(cursor, active_id)
                cursor.execute(
                    f"UPDATE layer3_expansion_revision_states SET workflow_state = {self.param}, updated_at = {self.param} WHERE revision_id = {self.param}",
                    ("superseded", utc_now(), active_id),
                )
                now = utc_now()
                cursor.execute(
                    f"UPDATE layer3_expansion_heads SET active_revision_id = {self.param}, updated_at = {self.param} WHERE id = {self.param}",
                    (new_id, now, expansion_id),
                )
                self._write_projection(cursor, expansion_id, new_id, number, updated, "needs_review", before.get("created_at", now), now)
                after = self._revision_snapshot(cursor, new_id)
                self._insert_revision_action(
                    cursor, request_id=f"edit:{new_id}", project_id=str(self._row_value(head, "project_id")), logical_expansion_id=expansion_id,
                    revision_id=new_id, action_type="human_edit", expected_active_revision_id=active_id,
                    previous_active_revision_id=active_id, new_active_revision_id=new_id,
                    selected_sections=sorted(updates), before_snapshot=before, after_snapshot=after,
                    actor=actor, origin=origin, payload={"fields": sorted(updates)},
                )
            finally:
                cursor.close()
        return self.get_layer3_expansion(expansion_id)

    def set_active_layer3_review_state(self, expansion_id: str, state: str, *, actor: str, note: str = "") -> FeatureExpansion:
        """Update review workflow state without mutating immutable revision content."""
        self.migrate_layer3_revisions()
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                head = self._select_head_by_id(cursor, expansion_id, lock=True)
                if head is None or not self._row_value(head, "active_revision_id"):
                    raise ValueError("Layer 3 active revision was not found.")
                revision_id = str(self._row_value(head, "active_revision_id"))
                before = self._revision_snapshot(cursor, revision_id)
                cursor.execute(
                    f"UPDATE layer3_expansion_revision_states SET review_state = {self.param}, updated_at = {self.param} WHERE revision_id = {self.param}",
                    (state, utc_now(), revision_id),
                )
                cursor.execute(
                    f"UPDATE layer3_feature_expansions SET review_state = {self.param}, updated_at = {self.param} WHERE id = {self.param}",
                    (state, utc_now(), expansion_id),
                )
                after = self._revision_snapshot(cursor, revision_id)
                self._insert_revision_action(
                    cursor, request_id=f"review:{uuid.uuid4()}", project_id=str(self._row_value(head, "project_id")),
                    logical_expansion_id=expansion_id, revision_id=revision_id, action_type=state,
                    expected_active_revision_id=revision_id, previous_active_revision_id=revision_id, new_active_revision_id=revision_id,
                    selected_sections=[], before_snapshot=before, after_snapshot=after, actor=actor, origin="api_review", payload={"note": note},
                )
            finally:
                cursor.close()
        return self.get_layer3_expansion(expansion_id)

    def record_layer3_expansion_action(
        self, *, project_id: str, expansion_id: str, action_type: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Append a legacy-compatible action record used by older import/export tooling and tests."""
        self._execute(
            f"INSERT INTO layer3_expansion_actions (id, project_id, expansion_id, action_type, payload, created_at) VALUES ({', '.join([self.param] * 6)})",
            (str(uuid.uuid4()), project_id, expansion_id, action_type, self._dump_json(payload or {}), utc_now()),
        )

    def layer3_snapshot(self, project_id: str) -> dict[str, Any]:
        """Build the Layer 3 workspace payload with active projections and reviewable revisions."""
        self.migrate_layer3_revisions()
        expansions = []
        for item in self.list_layer3_expansions(project_id):
            value = item.model_dump(mode="json")
            if item.active_revision_id:
                value["freshness"] = self.freshness_for_artifact(
                    project_id, "layer3_revision", item.id, item.active_revision_id,
                )
                value["freshness_state"] = value["freshness"]["freshness_state"]
            else:
                value["freshness_state"] = "unknown"
            expansions.append(value)
        active_features = self.list_layer2_features(project_id, statuses=["kept", "approved"])
        eligible = [feature.model_dump(mode="json") for feature in active_features if feature.status == "approved"]
        feature_directory = [
            {"id": feature.id, "canonical_name": feature.canonical_name, "status": feature.status, "owner_pillar_id": feature.owner_pillar_id}
            for feature in active_features
        ]
        revisions = self._fetchall(
            f"""
            SELECT revisions.*, states.workflow_state, states.review_state, states.freshness_state, states.updated_at AS state_updated_at
            FROM layer3_expansion_revisions revisions
            JOIN layer3_expansion_revision_states states ON states.revision_id = revisions.id
            WHERE revisions.project_id = {self.param}
            ORDER BY revisions.created_at DESC
            """,
            (project_id,),
        )
        revision_values = [self._revision_values(row) for row in revisions]
        from strata.dependency_db import feature_revision_token, pillar_revision_token
        feature_revisions = {feature.id: feature_revision_token(feature) for feature in active_features}
        brief = self.get_project_brief(project_id)
        brief_revision = str(brief.current_published_revision_id or "") if brief else ""
        pillar_revisions = {
            feature.owner_pillar_id: pillar_revision_token(self.get_node(feature.owner_pillar_id))
            for feature in active_features
        }
        for revision in revision_values:
            feature_id = str(revision["payload"].get("feature_id", ""))
            pillar_id = str(revision["payload"].get("parent_pillar_id", ""))
            source_matches = (
                feature_revisions.get(feature_id) == revision["source_layer2_feature_revision"]
                and brief_revision == revision["source_brief_revision"]
                and pillar_revisions.get(pillar_id, "") == revision["source_pillar_revision"]
            )
            freshness = self.freshness_for_artifact(
                project_id, "layer3_revision", str(revision["logical_expansion_id"]), str(revision["id"]),
            )
            revision["freshness"] = freshness
            revision["freshness_state"] = freshness["freshness_state"]
            revision["source_matches_current"] = source_matches
        return {
            "eligible_features": eligible,
            "feature_directory": feature_directory,
            "expansions": expansions,
            "candidates": [item for item in revision_values if item["workflow_state"] == "candidate"],
            "revision_history": revision_values,
        }

    def _insert_derived_revision(
        self, cursor: Any, *, head: Any, project_id: str, logical_expansion_id: str, source_revision: Any,
        payload: dict[str, Any], diff: dict[str, Any], origin: str, actor: str,
        field_ownership: dict[str, Any] | None = None, review_state: str = "approved",
    ) -> tuple[str, int]:
        """Insert a new immutable accepted revision while holding the logical head lock."""
        revision_id = str(uuid.uuid4())
        number = int(self._row_value(head, "next_revision_number"))
        now = utc_now()
        ownership = field_ownership if field_ownership is not None else self._load_json_value(self._row_value(source_revision, "field_ownership"), {})
        self._insert_revision(
            cursor, revision_id=revision_id, logical_expansion_id=logical_expansion_id, project_id=project_id,
            revision_number=number,
            source_layer2_feature_revision=str(self._row_value(source_revision, "source_layer2_feature_revision")),
            source_brief_revision=str(self._row_value(source_revision, "source_brief_revision")),
            source_pillar_revision=str(self._row_value(source_revision, "source_pillar_revision")),
            generation_reference=str(self._row_value(source_revision, "generation_reference")),
            origin=origin, actor=actor, payload=payload, structured_diff=diff, field_ownership=ownership, created_at=now,
        )
        self._insert_revision_state(cursor, revision_id, "active", review_state, "fresh", now)
        cursor.execute(
            f"UPDATE layer3_expansion_heads SET next_revision_number = {self.param}, updated_at = {self.param} WHERE id = {self.param}",
            (number + 1, now, logical_expansion_id),
        )
        return revision_id, number

    def _write_projection(
        self, cursor: Any, logical_id: str, revision_id: str, revision_number: int,
        payload: dict[str, Any], review_state: str, created_at: str, updated_at: str,
    ) -> None:
        """Update the compatibility read projection inside its caller's transaction."""
        columns = (
            "project_id", "feature_id", "parent_pillar_id", "parent_pillar_title", "feature_name",
            "feature_description", "feature_intent", "expansion_groups", "overlap_review", "open_questions",
            "review_state", "provenance", "active_revision_id", "revision_number", "created_at", "updated_at",
        )
        values = {
            **payload,
            "review_state": review_state,
            "active_revision_id": revision_id,
            "revision_number": revision_number,
            "created_at": created_at,
            "updated_at": updated_at,
        }
        encoded = [self._dump_json(values[key]) if key in {"expansion_groups", "overlap_review", "open_questions", "provenance"} else values[key] for key in columns]
        cursor.execute(
            f"""
            INSERT INTO layer3_feature_expansions (id, {', '.join(columns)})
            VALUES ({', '.join([self.param] * (len(columns) + 1))})
            ON CONFLICT (project_id, feature_id) DO UPDATE SET
                {', '.join(f'{column} = EXCLUDED.{column}' for column in columns)}
            """,
            (logical_id, *encoded),
        )

    def _insert_head(
        self, cursor: Any, logical_id: str, project_id: str, feature_id: str,
        active_revision_id: str | None, next_revision_number: int, now: str,
    ) -> None:
        """Insert one logical expansion head inside an existing transaction."""
        cursor.execute(
            f"INSERT INTO layer3_expansion_heads (id, project_id, feature_id, active_revision_id, next_revision_number, created_at, updated_at) VALUES ({', '.join([self.param] * 7)})",
            (logical_id, project_id, feature_id, active_revision_id, next_revision_number, now, now),
        )

    def _insert_revision(self, cursor: Any, **values: Any) -> None:
        """Insert immutable revision content and lineage inside an existing transaction."""
        values = {**values, "id": values["revision_id"]}
        columns = (
            "id", "logical_expansion_id", "project_id", "revision_number", "source_layer2_feature_revision",
            "source_brief_revision", "source_pillar_revision", "generation_reference", "origin", "actor",
            "payload", "structured_diff", "field_ownership", "created_at",
        )
        encoded = [self._dump_json(values[key]) if key in self._REVISION_JSON_FIELDS else values[key] for key in columns]
        cursor.execute(
            f"INSERT INTO layer3_expansion_revisions ({', '.join(columns)}) VALUES ({', '.join([self.param] * len(columns))})",
            tuple(encoded),
        )

    def _insert_revision_state(
        self, cursor: Any, revision_id: str, workflow_state: str, review_state: str, freshness_state: str, now: str
    ) -> None:
        """Insert mutable workflow state separately from immutable revision content."""
        cursor.execute(
            f"SELECT logical_expansion_id FROM layer3_expansion_revisions WHERE id = {self.param}",
            (revision_id,),
        )
        revision = cursor.fetchone()
        if revision is None:
            raise ValueError("Layer 3 revision state requires an existing revision.")
        logical_expansion_id = str(self._row_value(revision, "logical_expansion_id"))
        cursor.execute(
            f"INSERT INTO layer3_expansion_revision_states (revision_id, logical_expansion_id, workflow_state, review_state, freshness_state, updated_at) VALUES ({', '.join([self.param] * 6)})",
            (revision_id, logical_expansion_id, workflow_state, review_state, freshness_state, now),
        )

    def _insert_revision_action(self, cursor: Any, **values: Any) -> None:
        """Write a complete before/after audit record inside the caller's transaction."""
        columns = (
            "id", "request_id", "project_id", "logical_expansion_id", "revision_id", "action_type",
            "expected_active_revision_id", "previous_active_revision_id", "new_active_revision_id",
            "selected_sections", "before_snapshot", "after_snapshot", "actor", "origin", "payload", "created_at",
        )
        row = {"id": str(uuid.uuid4()), "created_at": utc_now(), **values}
        encoded = [
            self._dump_json(self._json_compatible(row[key])) if key in self._ACTION_JSON_FIELDS else row.get(key)
            for key in columns
        ]
        cursor.execute(
            f"INSERT INTO layer3_revision_actions ({', '.join(columns)}) VALUES ({', '.join([self.param] * len(columns))})",
            tuple(encoded),
        )

    def _select_head(self, cursor: Any, project_id: str, feature_id: str, *, lock: bool = False) -> Any | None:
        """Read one logical head and lock it on PostgreSQL mutation paths."""
        suffix = " FOR UPDATE" if lock and self.is_postgres else ""
        cursor.execute(
            f"SELECT * FROM layer3_expansion_heads WHERE project_id = {self.param} AND feature_id = {self.param}{suffix}",
            (project_id, feature_id),
        )
        return cursor.fetchone()

    def _select_head_by_id(self, cursor: Any, logical_id: str, *, lock: bool = False) -> Any | None:
        """Read one logical head by id and lock it on PostgreSQL mutation paths."""
        suffix = " FOR UPDATE" if lock and self.is_postgres else ""
        cursor.execute(f"SELECT * FROM layer3_expansion_heads WHERE id = {self.param}{suffix}", (logical_id,))
        return cursor.fetchone()

    def _select_revision(self, cursor: Any, revision_id: str | None) -> Any | None:
        """Read immutable revision content using an existing transaction cursor."""
        if not revision_id:
            return None
        cursor.execute(f"SELECT * FROM layer3_expansion_revisions WHERE id = {self.param}", (revision_id,))
        return cursor.fetchone()

    def _select_revision_state(self, cursor: Any, revision_id: str) -> Any | None:
        """Read current workflow state using an existing transaction cursor."""
        cursor.execute(f"SELECT * FROM layer3_expansion_revision_states WHERE revision_id = {self.param}", (revision_id,))
        return cursor.fetchone()

    def _select_action(self, cursor: Any, request_id: str) -> Any | None:
        """Look up a prior command result for idempotent replay."""
        cursor.execute(f"SELECT * FROM layer3_revision_actions WHERE request_id = {self.param}", (request_id,))
        return cursor.fetchone()

    def _revision_snapshot(self, cursor: Any, revision_id: str | None) -> dict[str, Any]:
        """Return complete revision content plus state inside the current transaction."""
        if not revision_id:
            return {}
        cursor.execute(
            f"""
            SELECT revisions.*, states.workflow_state, states.review_state, states.freshness_state, states.updated_at AS state_updated_at
            FROM layer3_expansion_revisions revisions
            JOIN layer3_expansion_revision_states states ON states.revision_id = revisions.id
            WHERE revisions.id = {self.param}
            """,
            (revision_id,),
        )
        row = cursor.fetchone()
        return self._revision_values(row) if row is not None else {}

    def _load_action_result(self, action: Any) -> dict[str, Any]:
        """Recover the original command result from a durable audit action."""
        payload = self._load_json_value(self._row_value(action, "payload"), {})
        return payload.get("result", payload)

    def _row_to_layer3_expansion(self, row: Any) -> FeatureExpansion:
        """Convert one current-projection row into a typed FeatureExpansion."""
        json_fields = {"expansion_groups", "overlap_review", "open_questions", "provenance"}
        values = {
            key: self._load_json_value(self._row_value(row, key), [] if key != "provenance" else {}) if key in json_fields else self._row_value(row, key)
            for key in FeatureExpansion.model_fields
        }
        return FeatureExpansion(**values)

    def _projection_values(self, row: Any) -> dict[str, Any]:
        """Normalize a legacy projection row into a serializable dictionary."""
        keys = (
            "id", "project_id", "feature_id", "parent_pillar_id", "parent_pillar_title", "feature_name",
            "feature_description", "feature_intent", "expansion_groups", "overlap_review", "open_questions",
            "review_state", "provenance", "created_at", "updated_at",
        )
        return {
            key: self._load_json_value(self._row_value(row, key), {} if key == "provenance" else [])
            if key in {"expansion_groups", "overlap_review", "open_questions", "provenance"}
            else self._row_value(row, key)
            for key in keys
        }

    @staticmethod
    def _artifact_payload(values: dict[str, Any]) -> dict[str, Any]:
        """Extract the immutable artifact fields stored in every revision payload."""
        return {
            key: copy.deepcopy(values.get(key, [] if key in {"expansion_groups", "overlap_review", "open_questions"} else {} if key == "provenance" else ""))
            for key in (
                "project_id", "feature_id", "parent_pillar_id", "parent_pillar_title", "feature_name",
                "feature_description", "feature_intent", "expansion_groups", "overlap_review", "open_questions", "provenance",
            )
        }

    @staticmethod
    def _selection_ownership(payload: dict[str, Any]) -> dict[str, Any]:
        """Mark every option selection as human-owned regardless of generation origin."""
        return {
            f"option:{option.get('id')}.selection_state": "human"
            for group in payload.get("expansion_groups", [])
            for option in group.get("options", [])
            if option.get("id")
        }

    def _legacy_field_ownership(self, cursor: Any, logical_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Conservatively recover ownership from legacy edit actions during backfill."""
        ownership = self._selection_ownership(payload)
        cursor.execute(
            f"SELECT payload FROM layer3_expansion_actions WHERE expansion_id = {self.param} AND action_type = {self.param}",
            (logical_id, "edit"),
        )
        edited_fields: set[str] = set()
        for row in cursor.fetchall():
            edited_fields.update(self._load_json_value(self._row_value(row, "payload"), {}).get("fields", []))
        for field in edited_fields:
            if field in {"feature_intent", "overlap_review", "open_questions"}:
                ownership[field] = "human"
        if "expansion_groups" in edited_fields:
            for group in payload.get("expansion_groups", []):
                group_id = str(group.get("id", ""))
                ownership[f"group:{group_id}.__entity__"] = "human"
                for field in ("name", "description"):
                    ownership[f"group:{group_id}.{field}"] = "human"
                for option in group.get("options", []):
                    option_id = str(option.get("id", ""))
                    ownership[f"option:{option_id}.__entity__"] = "human"
                    for field in ("name", "description", "selection_state", "configuration_kind", "default_recommendation", "rationale", "dependencies", "overlaps_feature_ids"):
                        ownership[f"option:{option_id}.{field}"] = "human"
        return ownership

    def _revision_values(self, row: Any) -> dict[str, Any]:
        """Normalize a joined revision/state row from SQLite or PostgreSQL."""
        keys = (
            "id", "logical_expansion_id", "project_id", "revision_number", "source_layer2_feature_revision",
            "source_brief_revision", "source_pillar_revision", "generation_reference", "origin", "actor",
            "payload", "structured_diff", "field_ownership", "created_at", "workflow_state", "review_state",
            "freshness_state", "state_updated_at",
        )
        return {
            key: self._load_json_value(self._row_value(row, key), {}) if key in self._REVISION_JSON_FIELDS else self._row_value(row, key)
            for key in keys
        }

    @staticmethod
    def _load_json_value(value: Any, default: Any) -> Any:
        """Load SQLite JSON text while preserving native PostgreSQL JSON values."""
        if value is None:
            return copy.deepcopy(default)
        if isinstance(value, str):
            return json.loads(value)
        return copy.deepcopy(value)

    @staticmethod
    def _json_compatible(value: Any) -> Any:
        """Recursively normalize native PostgreSQL timestamps for JSONB audit snapshots."""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: Layer3DatabaseMixin._json_compatible(item) for key, item in value.items()}
        if isinstance(value, list):
            return [Layer3DatabaseMixin._json_compatible(item) for item in value]
        return value

    @staticmethod
    def _raise_failpoint(requested: str | None, step: str) -> None:
        """Inject a deterministic pre-commit failure for transaction rollback tests."""
        if requested == step:
            raise RuntimeError(f"Injected Layer 3 application failure after {step}")
