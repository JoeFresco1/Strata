from __future__ import annotations

import uuid
import json
from datetime import datetime, timezone
from typing import Any

from strata.models import CapabilityDesignCard, Layer3OpenDecision, Layer3Relationship


def utc_now() -> str:
    """Return an ISO timestamp in UTC for Layer 3 storage records."""
    return datetime.now(timezone.utc).isoformat()


class Layer3DatabaseMixin:
    """Persist Layer 3 cards, product relationships, decisions, and review history."""

    def upsert_layer3_card(self, *, card_id: str | None = None, **values: Any) -> CapabilityDesignCard:
        """Create or replace one feature's current Capability Design Card."""
        now = utc_now()
        existing = self._fetchone(
            f"SELECT id, created_at FROM layer3_capability_cards WHERE project_id = {self.param} AND feature_id = {self.param}",
            (values["project_id"], values["feature_id"]),
        )
        resolved_id = str(self._row_value(existing, "id")) if existing is not None else card_id or str(uuid.uuid4())
        created_at = self._row_value(existing, "created_at") if existing is not None else now
        columns = [
            "parent_pillar_id", "parent_pillar_title", "feature_name", "feature_description",
            "product_purpose", "feature_archetype", "supported_variants", "configurable_options",
            "product_behaviors", "validation_constraints", "lifecycle_states", "dependencies",
            "overlaps_conflicts", "edge_cases", "product_risks", "pressure_test",
            "downstream_readiness_score", "readiness_rationale", "review_state", "provenance",
        ]
        encoded = {
            key: self._dump_json(values[key])
            if key in {
                "supported_variants", "configurable_options", "product_behaviors",
                "validation_constraints", "lifecycle_states", "dependencies",
                "overlaps_conflicts", "edge_cases", "product_risks", "pressure_test", "provenance",
            }
            else values[key]
            for key in columns
        }
        self._execute(
            f"""
            INSERT INTO layer3_capability_cards (
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
        return self.get_layer3_card(resolved_id)

    def get_layer3_card(self, card_id: str) -> CapabilityDesignCard:
        """Return one Capability Design Card by id."""
        row = self._fetchone(
            f"SELECT * FROM layer3_capability_cards WHERE id = {self.param}",
            (card_id,),
        )
        if row is None:
            raise ValueError(f"Layer 3 card not found: {card_id}")
        return self._row_to_layer3_card(row)

    def get_layer3_card_for_feature(self, project_id: str, feature_id: str) -> CapabilityDesignCard | None:
        """Return the current card for one Layer 2 feature."""
        row = self._fetchone(
            f"SELECT * FROM layer3_capability_cards WHERE project_id = {self.param} AND feature_id = {self.param}",
            (project_id, feature_id),
        )
        return self._row_to_layer3_card(row) if row is not None else None

    def list_layer3_cards(self, project_id: str) -> list[CapabilityDesignCard]:
        """List current cards in stable feature-name order."""
        rows = self._fetchall(
            f"SELECT * FROM layer3_capability_cards WHERE project_id = {self.param} ORDER BY feature_name, created_at",
            (project_id,),
        )
        return [self._row_to_layer3_card(row) for row in rows]

    def update_layer3_card(self, card_id: str, **updates: Any) -> CapabilityDesignCard:
        """Apply human edits or review-state changes to a card."""
        if not updates:
            return self.get_layer3_card(card_id)
        json_fields = {
            "supported_variants", "configurable_options", "product_behaviors",
            "validation_constraints", "lifecycle_states", "dependencies",
            "overlaps_conflicts", "edge_cases", "product_risks", "pressure_test", "provenance",
        }
        assignments = [f"{key} = {self.param}" for key in updates]
        values = [self._dump_json(value) if key in json_fields else value for key, value in updates.items()]
        assignments.append(f"updated_at = {self.param}")
        values.extend([utc_now(), card_id])
        self._execute(
            f"UPDATE layer3_capability_cards SET {', '.join(assignments)} WHERE id = {self.param}",
            tuple(values),
        )
        return self.get_layer3_card(card_id)

    def replace_layer3_relationships(
        self,
        *,
        project_id: str,
        card_id: str,
        source_feature_id: str,
        relationships: list[dict[str, Any]],
    ) -> list[Layer3Relationship]:
        """Atomically replace and deduplicate relationship edges for one card."""
        now = utc_now()
        unique_relationships = {
            (str(item["target_feature_id"]), str(item["relationship_type"])): item
            for item in relationships
        }
        with self.connect() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(f"DELETE FROM layer3_relationships WHERE card_id = {self.param}", (card_id,))
                for item in unique_relationships.values():
                    cursor.execute(
                        f"""
                        INSERT INTO layer3_relationships (
                            id, project_id, card_id, source_feature_id, target_feature_id,
                            relationship_type, rationale, created_at
                        ) VALUES ({", ".join([self.param] * 8)})
                        """,
                        (
                            str(uuid.uuid4()), project_id, card_id, source_feature_id,
                            item["target_feature_id"], item["relationship_type"],
                            item.get("rationale", ""), now,
                        ),
                    )
            finally:
                cursor.close()
        return self.list_layer3_relationships(card_id)

    def list_layer3_relationships(self, card_id: str) -> list[Layer3Relationship]:
        """List product relationship edges attached to one card."""
        rows = self._fetchall(
            f"SELECT * FROM layer3_relationships WHERE card_id = {self.param} ORDER BY created_at",
            (card_id,),
        )
        return [self._row_to_layer3_relationship(row) for row in rows]

    def replace_layer3_decisions(
        self,
        *,
        project_id: str,
        card_id: str,
        decisions: list[dict[str, Any]],
    ) -> list[Layer3OpenDecision]:
        """Atomically replace unique decisions while preserving matching resolutions."""
        existing = {item.question.strip().casefold(): item for item in self.list_layer3_decisions(card_id)}
        unique_decisions = {
            str(item["question"]).strip().casefold(): item
            for item in decisions
            if str(item.get("question", "")).strip()
        }
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(f"DELETE FROM layer3_open_decisions WHERE card_id = {self.param}", (card_id,))
                for key, item in unique_decisions.items():
                    prior = existing.get(key)
                    cursor.execute(
                        f"""
                        INSERT INTO layer3_open_decisions (
                            id, project_id, card_id, question, context, options,
                            status, resolution, created_at, updated_at
                        ) VALUES ({", ".join([self.param] * 10)})
                        """,
                        (
                            prior.id if prior else str(uuid.uuid4()),
                            project_id,
                            card_id,
                            item["question"],
                            item.get("context", ""),
                            self._dump_json(item.get("options", [])),
                            prior.status if prior else "unresolved",
                            prior.resolution if prior else "",
                            prior.created_at if prior else now,
                            now,
                        ),
                    )
            finally:
                cursor.close()
        return self.list_layer3_decisions(card_id)

    def list_layer3_decisions(self, card_id: str) -> list[Layer3OpenDecision]:
        """List explicit product decisions for one card."""
        rows = self._fetchall(
            f"SELECT * FROM layer3_open_decisions WHERE card_id = {self.param} ORDER BY created_at",
            (card_id,),
        )
        return [self._row_to_layer3_decision(row) for row in rows]

    def update_layer3_decision(
        self,
        decision_id: str,
        *,
        status: str,
        resolution: str,
    ) -> Layer3OpenDecision:
        """Resolve or reopen one product decision."""
        self._execute(
            f"""
            UPDATE layer3_open_decisions
            SET status = {self.param}, resolution = {self.param}, updated_at = {self.param}
            WHERE id = {self.param}
            """,
            (status, resolution, utc_now(), decision_id),
        )
        row = self._fetchone(
            f"SELECT * FROM layer3_open_decisions WHERE id = {self.param}",
            (decision_id,),
        )
        if row is None:
            raise ValueError(f"Layer 3 decision not found: {decision_id}")
        return self._row_to_layer3_decision(row)

    def get_layer3_decision(self, decision_id: str) -> Layer3OpenDecision:
        """Return one Layer 3 decision before applying project-scoped mutations."""
        row = self._fetchone(
            f"SELECT * FROM layer3_open_decisions WHERE id = {self.param}",
            (decision_id,),
        )
        if row is None:
            raise ValueError(f"Layer 3 decision not found: {decision_id}")
        return self._row_to_layer3_decision(row)

    def record_layer3_review_action(
        self,
        *,
        project_id: str,
        card_id: str,
        action_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Append an auditable human or generation action for one card."""
        self._execute(
            f"""
            INSERT INTO layer3_review_actions (id, project_id, card_id, action_type, payload, created_at)
            VALUES ({", ".join([self.param] * 6)})
            """,
            (str(uuid.uuid4()), project_id, card_id, action_type, self._dump_json(payload or {}), utc_now()),
        )

    def layer3_snapshot(self, project_id: str) -> dict[str, Any]:
        """Build the complete Layer 3 workspace payload from durable state."""
        cards = self.list_layer3_cards(project_id)
        card_payloads = []
        for card in cards:
            card_payloads.append({
                **card.model_dump(mode="json"),
                "relationships": [item.model_dump(mode="json") for item in self.list_layer3_relationships(card.id)],
                "open_decisions": [item.model_dump(mode="json") for item in self.list_layer3_decisions(card.id)],
            })
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
            "cards": card_payloads,
        }

    def _row_to_layer3_card(self, row: Any) -> CapabilityDesignCard:
        """Convert one database row into a typed card."""
        json_fields = {
            "supported_variants", "configurable_options", "product_behaviors",
            "validation_constraints", "lifecycle_states", "dependencies",
            "overlaps_conflicts", "edge_cases", "product_risks", "pressure_test", "provenance",
        }
        values = {
            key: self._load_layer3_json(self._row_value(row, key)) if key in json_fields else self._row_value(row, key)
            for key in CapabilityDesignCard.model_fields
        }
        for field in ("dependencies", "overlaps_conflicts", "edge_cases", "product_risks"):
            values[field] = [
                self._layer3_text_value(item)
                for item in values[field]
                if self._layer3_text_value(item)
            ]
        return CapabilityDesignCard(**values)

    def _row_to_layer3_relationship(self, row: Any) -> Layer3Relationship:
        """Convert one relationship row into its typed model."""
        return Layer3Relationship(**{key: self._row_value(row, key) for key in Layer3Relationship.model_fields})

    def _row_to_layer3_decision(self, row: Any) -> Layer3OpenDecision:
        """Convert one decision row into its typed model."""
        values = {key: self._row_value(row, key) for key in Layer3OpenDecision.model_fields}
        values["options"] = self._load_layer3_json(values["options"])
        return Layer3OpenDecision(**values)

    @staticmethod
    def _load_layer3_json(value: Any) -> Any:
        """Preserve JSON arrays and objects across SQLite text and PostgreSQL JSONB rows."""
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def _layer3_text_value(item: Any) -> str:
        """Read string-list fields written by earlier or near-valid model responses."""
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            for key in ("risk", "name", "description", "summary", "concept"):
                if str(item.get(key, "")).strip():
                    return str(item[key]).strip()
        return ""
