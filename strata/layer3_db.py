from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from strata.models import FeatureExpansion


def utc_now() -> str:
    """Return an ISO timestamp in UTC for Layer 3 storage records."""
    return datetime.now(timezone.utc).isoformat()


class Layer3DatabaseMixin:
    """Persist Layer 3 feature expansions and their review history."""

    def upsert_layer3_expansion(self, *, expansion_id: str | None = None, **values: Any) -> FeatureExpansion:
        """Create or replace one approved Layer 2 feature's expansion."""
        now = utc_now()
        existing = self._fetchone(
            f"SELECT id, created_at FROM layer3_feature_expansions WHERE project_id = {self.param} AND feature_id = {self.param}",
            (values["project_id"], values["feature_id"]),
        )
        resolved_id = str(self._row_value(existing, "id")) if existing is not None else expansion_id or str(uuid.uuid4())
        created_at = self._row_value(existing, "created_at") if existing is not None else now
        columns = [
            "parent_pillar_id",
            "parent_pillar_title",
            "feature_name",
            "feature_description",
            "feature_intent",
            "expansion_groups",
            "overlap_review",
            "open_questions",
            "review_state",
            "provenance",
        ]
        encoded = {
            key: self._dump_json(values[key])
            if key in {"expansion_groups", "overlap_review", "open_questions", "provenance"}
            else values[key]
            for key in columns
        }
        self._execute(
            f"""
            INSERT INTO layer3_feature_expansions (
                id, project_id, feature_id, {", ".join(columns)}, created_at, updated_at
            ) VALUES (
                {", ".join([self.param] * (5 + len(columns)))}
            )
            ON CONFLICT (project_id, feature_id) DO UPDATE SET
                {", ".join(f"{column} = EXCLUDED.{column}" for column in columns)},
                updated_at = EXCLUDED.updated_at
            """,
            (
                resolved_id,
                values["project_id"],
                values["feature_id"],
                *(encoded[column] for column in columns),
                created_at,
                now,
            ),
        )
        return self.get_layer3_expansion(resolved_id)

    def get_layer3_expansion(self, expansion_id: str) -> FeatureExpansion:
        """Return one Layer 3 feature expansion by id."""
        row = self._fetchone(
            f"SELECT * FROM layer3_feature_expansions WHERE id = {self.param}",
            (expansion_id,),
        )
        if row is None:
            raise ValueError(f"Layer 3 expansion not found: {expansion_id}")
        return self._row_to_layer3_expansion(row)

    def get_layer3_expansion_for_feature(self, project_id: str, feature_id: str) -> FeatureExpansion | None:
        """Return the current expansion for one Layer 2 feature."""
        row = self._fetchone(
            f"SELECT * FROM layer3_feature_expansions WHERE project_id = {self.param} AND feature_id = {self.param}",
            (project_id, feature_id),
        )
        return self._row_to_layer3_expansion(row) if row is not None else None

    def list_layer3_expansions(self, project_id: str) -> list[FeatureExpansion]:
        """List current expansions in stable feature-name order."""
        rows = self._fetchall(
            f"SELECT * FROM layer3_feature_expansions WHERE project_id = {self.param} ORDER BY feature_name, created_at",
            (project_id,),
        )
        return [self._row_to_layer3_expansion(row) for row in rows]

    def update_layer3_expansion(self, expansion_id: str, **updates: Any) -> FeatureExpansion:
        """Apply human edits or review-state changes to a feature expansion."""
        if not updates:
            return self.get_layer3_expansion(expansion_id)
        json_fields = {"expansion_groups", "overlap_review", "open_questions", "provenance"}
        assignments = [f"{key} = {self.param}" for key in updates]
        values = [self._dump_json(value) if key in json_fields else value for key, value in updates.items()]
        assignments.append(f"updated_at = {self.param}")
        values.extend([utc_now(), expansion_id])
        self._execute(
            f"UPDATE layer3_feature_expansions SET {', '.join(assignments)} WHERE id = {self.param}",
            tuple(values),
        )
        return self.get_layer3_expansion(expansion_id)

    def record_layer3_expansion_action(
        self,
        *,
        project_id: str,
        expansion_id: str,
        action_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Append an auditable Layer 3 generation, edit, or review action."""
        self._execute(
            f"""
            INSERT INTO layer3_expansion_actions (id, project_id, expansion_id, action_type, payload, created_at)
            VALUES ({", ".join([self.param] * 6)})
            """,
            (str(uuid.uuid4()), project_id, expansion_id, action_type, self._dump_json(payload or {}), utc_now()),
        )

    def layer3_snapshot(self, project_id: str) -> dict[str, Any]:
        """Build the complete Layer 3 workspace payload from durable state."""
        expansions = [item.model_dump(mode="json") for item in self.list_layer3_expansions(project_id)]
        active_features = self.list_layer2_features(project_id, statuses=["kept", "approved"])
        eligible = [
            feature.model_dump(mode="json")
            for feature in active_features
            if feature.status == "approved"
        ]
        feature_directory = [
            {
                "id": feature.id,
                "canonical_name": feature.canonical_name,
                "status": feature.status,
                "owner_pillar_id": feature.owner_pillar_id,
            }
            for feature in active_features
        ]
        return {
            "eligible_features": eligible,
            "feature_directory": feature_directory,
            "expansions": expansions,
        }

    def _row_to_layer3_expansion(self, row: Any) -> FeatureExpansion:
        """Convert one database row into a typed FeatureExpansion."""
        json_fields = {"expansion_groups", "overlap_review", "open_questions", "provenance"}
        values = {
            key: self._load_layer3_json(self._row_value(row, key)) if key in json_fields else self._row_value(row, key)
            for key in FeatureExpansion.model_fields
        }
        return FeatureExpansion(**values)

    @staticmethod
    def _load_layer3_json(value: Any) -> Any:
        """Preserve JSON arrays and objects across SQLite text and PostgreSQL JSONB rows."""
        if isinstance(value, str):
            return json.loads(value)
        return value
