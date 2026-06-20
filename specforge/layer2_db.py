from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from specforge.models import (
    Layer2Feature,
    Layer2FeatureRelationship,
    Layer2GenerationRun,
    Layer2NegativeCacheEntry,
    Layer2PillarAffinity,
    Layer2RawCandidate,
    Layer2ReviewAction,
)


def utc_now() -> str:
    """Return an ISO timestamp in UTC for Layer 2 storage records."""
    return datetime.now(timezone.utc).isoformat()


class Layer2DatabaseMixin:
    """Layer 2 graph storage methods mixed into the main database adapter."""

    def create_layer2_generation_run(
        self,
        *,
        project_id: str,
        source_pillar_ids: list[str],
        lenses: list[str],
        source_model: str,
    ) -> Layer2GenerationRun:
        """Start a durable Layer 2 generation run for provenance and replay."""
        run_id = str(uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO layer2_generation_runs (
                id, project_id, source_pillar_ids, lenses, source_model, status, summary, created_at, completed_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                run_id,
                project_id,
                self._dump_json(source_pillar_ids),
                self._dump_json(lenses),
                source_model,
                "running",
                self._dump_json({}),
                utc_now(),
                None,
            ),
        )
        return self.get_layer2_generation_run(run_id)

    def complete_layer2_generation_run(self, run_id: str, *, status: str, summary: dict[str, Any]) -> Layer2GenerationRun:
        """Mark a Layer 2 run complete or failed with a compact summary."""
        self._execute(
            f"""
            UPDATE layer2_generation_runs
            SET status = {self.param}, summary = {self.param}, completed_at = {self.param}
            WHERE id = {self.param}
            """,
            (status, self._dump_json(summary), utc_now(), run_id),
        )
        return self.get_layer2_generation_run(run_id)

    def get_layer2_generation_run(self, run_id: str) -> Layer2GenerationRun:
        """Return one Layer 2 generation run."""
        row = self._fetchone(f"SELECT * FROM layer2_generation_runs WHERE id = {self.param}", (run_id,))
        if row is None:
            raise ValueError(f"Layer 2 generation run not found: {run_id}")
        return self._row_to_layer2_generation_run(row)

    def insert_layer2_raw_candidate(
        self,
        *,
        project_id: str,
        generation_run_id: str,
        source_pillar_id: str,
        source_lens: str,
        source_model: str,
        generation_round: int,
        raw_text: str,
        payload: dict[str, Any],
        negative_cache_match: bool = False,
        negative_cache_reason: str = "",
    ) -> Layer2RawCandidate:
        """Persist one raw Layer 2 candidate with source pillar, lens, model, and round provenance."""
        candidate_id = str(uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO layer2_raw_candidates (
                id, project_id, generation_run_id, source_pillar_id, source_lens, source_model,
                generation_round, raw_text, payload, negative_cache_match, negative_cache_reason, created_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                candidate_id,
                project_id,
                generation_run_id,
                source_pillar_id,
                source_lens,
                source_model,
                generation_round,
                raw_text,
                self._dump_json(payload),
                bool(negative_cache_match),
                negative_cache_reason,
                utc_now(),
            ),
        )
        return self.get_layer2_raw_candidate(candidate_id)

    def get_layer2_raw_candidate(self, candidate_id: str) -> Layer2RawCandidate:
        """Return one raw Layer 2 candidate."""
        row = self._fetchone(f"SELECT * FROM layer2_raw_candidates WHERE id = {self.param}", (candidate_id,))
        if row is None:
            raise ValueError(f"Layer 2 raw candidate not found: {candidate_id}")
        return self._row_to_layer2_raw_candidate(row)

    def create_layer2_feature(
        self,
        *,
        project_id: str,
        canonical_name: str,
        description: str,
        feature_type: str,
        owner_pillar_id: str,
        candidate_source_ids: list[str],
        aliases: list[str] | None = None,
        status: str = "candidate",
        related_pillar_ids: list[str] | None = None,
        used_by_feature_ids: list[str] | None = None,
        depends_on_feature_ids: list[str] | None = None,
        quality: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Layer2Feature:
        """Create one canonical Layer 2 feature graph node."""
        feature_id = f"feat_{uuid.uuid4().hex[:12]}"
        now = utc_now()
        quality = quality or {}
        self._execute(
            f"""
            INSERT INTO layer2_features (
                id, project_id, canonical_name, description, feature_type, owner_pillar_id,
                candidate_source_ids, aliases, status, related_pillar_ids, used_by_feature_ids,
                depends_on_feature_ids, specificity_score, pillar_fit_score, distinctiveness_score,
                implementation_leakage_score, strategic_value_score, needs_human_review, metadata,
                created_at, updated_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                feature_id,
                project_id,
                canonical_name,
                description,
                feature_type,
                owner_pillar_id,
                self._dump_json(candidate_source_ids),
                self._dump_json(aliases or []),
                status,
                self._dump_json(related_pillar_ids or []),
                self._dump_json(used_by_feature_ids or []),
                self._dump_json(depends_on_feature_ids or []),
                int(quality.get("specificity_score", 50)),
                int(quality.get("pillar_fit_score", 50)),
                int(quality.get("distinctiveness_score", 50)),
                int(quality.get("implementation_leakage_score", 0)),
                int(quality.get("strategic_value_score", 50)),
                bool(quality.get("needs_human_review", True)),
                self._dump_json(metadata or {}),
                now,
                now,
            ),
        )
        for alias in aliases or []:
            self.add_layer2_feature_alias(feature_id, alias)
        return self.get_layer2_feature(feature_id)

    def get_layer2_feature(self, feature_id: str) -> Layer2Feature:
        """Return one canonical Layer 2 feature."""
        row = self._fetchone(f"SELECT * FROM layer2_features WHERE id = {self.param}", (feature_id,))
        if row is None:
            raise ValueError(f"Layer 2 feature not found: {feature_id}")
        return self._row_to_layer2_feature(row)

    def list_layer2_features(self, project_id: str, *, statuses: list[str] | None = None) -> list[Layer2Feature]:
        """Return Layer 2 graph features, optionally limited to review/export statuses."""
        query = f"SELECT * FROM layer2_features WHERE project_id = {self.param}"
        params: list[Any] = [project_id]
        if statuses:
            placeholders = ", ".join([self.param] * len(statuses))
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY owner_pillar_id ASC, created_at ASC"
        rows = self._fetchall(query, tuple(params))
        return [self._row_to_layer2_feature(row) for row in rows]

    def update_layer2_feature(
        self,
        feature_id: str,
        *,
        canonical_name: str | None = None,
        description: str | None = None,
        owner_pillar_id: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Layer2Feature:
        """Update review-owned fields on a Layer 2 feature."""
        updates: list[str] = []
        params: list[Any] = []
        if canonical_name is not None:
            updates.append(f"canonical_name = {self.param}")
            params.append(canonical_name)
        if description is not None:
            updates.append(f"description = {self.param}")
            params.append(description)
        if owner_pillar_id is not None:
            updates.append(f"owner_pillar_id = {self.param}")
            params.append(owner_pillar_id)
        if status is not None:
            updates.append(f"status = {self.param}")
            params.append(status)
        if metadata is not None:
            updates.append(f"metadata = {self.param}")
            params.append(self._dump_json(metadata))
        if not updates:
            return self.get_layer2_feature(feature_id)
        updates.append(f"updated_at = {self.param}")
        params.extend([utc_now(), feature_id])
        self._execute(f"UPDATE layer2_features SET {', '.join(updates)} WHERE id = {self.param}", tuple(params))
        return self.get_layer2_feature(feature_id)

    def add_layer2_feature_alias(self, feature_id: str, alias: str) -> None:
        """Store a searchable alias for one canonical Layer 2 feature."""
        if not alias.strip():
            return
        self._execute(
            f"""
            INSERT INTO layer2_feature_aliases (id, feature_id, alias, created_at)
            VALUES ({self.param}, {self.param}, {self.param}, {self.param})
            ON CONFLICT (feature_id, alias) DO NOTHING
            """,
            (str(uuid.uuid4()), feature_id, alias.strip(), utc_now()),
        )

    def insert_layer2_relationship(
        self,
        *,
        project_id: str,
        source_feature_id: str,
        target_feature_id: str,
        relationship_type: str,
        strength: float,
        rationale: str = "",
    ) -> Layer2FeatureRelationship:
        """Persist a graph edge between two Layer 2 features for dedupe and dependency review."""
        relationship_id = str(uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO layer2_feature_relationships (
                id, project_id, source_feature_id, target_feature_id, relationship_type, strength, rationale, created_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                relationship_id,
                project_id,
                source_feature_id,
                target_feature_id,
                relationship_type,
                strength,
                rationale,
                utc_now(),
            ),
        )
        return self.get_layer2_relationship(relationship_id)

    def get_layer2_relationship(self, relationship_id: str) -> Layer2FeatureRelationship:
        """Return one Layer 2 feature relationship."""
        row = self._fetchone(f"SELECT * FROM layer2_feature_relationships WHERE id = {self.param}", (relationship_id,))
        if row is None:
            raise ValueError(f"Layer 2 relationship not found: {relationship_id}")
        return self._row_to_layer2_relationship(row)

    def list_layer2_relationships(self, project_id: str) -> list[Layer2FeatureRelationship]:
        """Return all Layer 2 graph edges for a project."""
        rows = self._fetchall(
            f"SELECT * FROM layer2_feature_relationships WHERE project_id = {self.param} ORDER BY created_at ASC",
            (project_id,),
        )
        return [self._row_to_layer2_relationship(row) for row in rows]

    def delete_layer2_relationship(
        self,
        *,
        project_id: str,
        source_feature_id: str,
        target_feature_id: str,
        relationship_type: str | None = None,
    ) -> int:
        """Delete matching Layer 2 graph edges and return how many records were removed."""
        query = f"""
            DELETE FROM layer2_feature_relationships
            WHERE project_id = {self.param}
              AND source_feature_id = {self.param}
              AND target_feature_id = {self.param}
        """
        params: list[Any] = [project_id, source_feature_id, target_feature_id]
        if relationship_type is not None:
            query += f" AND relationship_type = {self.param}"
            params.append(relationship_type)
        if self.is_postgres:
            query += " RETURNING id"
            rows = self._fetchall(query, tuple(params))
            return len(rows)
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, tuple(params))
                return int(cursor.rowcount or 0)
            finally:
                cursor.close()

    def insert_layer2_affinity(
        self,
        *,
        project_id: str,
        feature_id: str,
        pillar_id: str,
        affinity_score: float,
        recommended_owner_pillar_id: str,
    ) -> Layer2PillarAffinity:
        """Store one feature-to-pillar affinity score and its owner recommendation."""
        affinity_id = str(uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO layer2_pillar_affinity (
                id, project_id, feature_id, pillar_id, affinity_score, recommended_owner_pillar_id, created_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (affinity_id, project_id, feature_id, pillar_id, affinity_score, recommended_owner_pillar_id, utc_now()),
        )
        return self._row_to_layer2_affinity(
            self._fetchone(f"SELECT * FROM layer2_pillar_affinity WHERE id = {self.param}", (affinity_id,))
        )

    def list_layer2_affinities(self, project_id: str) -> list[Layer2PillarAffinity]:
        """Return all Layer 2 affinity scores for a project."""
        rows = self._fetchall(
            f"SELECT * FROM layer2_pillar_affinity WHERE project_id = {self.param} ORDER BY feature_id ASC, affinity_score DESC",
            (project_id,),
        )
        return [self._row_to_layer2_affinity(row) for row in rows]

    def create_layer2_negative_cache_entry(
        self,
        *,
        project_id: str,
        rejected_name: str,
        semantic_cluster: str,
        rejected_aliases: list[str],
        rejected_from_pillar_id: str,
    ) -> Layer2NegativeCacheEntry:
        """Persist a rejected Layer 2 concept so later generation can flag rediscovery."""
        entry_id = str(uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO layer2_negative_cache (
                id, project_id, rejected_name, semantic_cluster, rejected_aliases, rejected_at_layer,
                rejected_from_pillar_id, created_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                entry_id,
                project_id,
                rejected_name,
                semantic_cluster,
                self._dump_json(rejected_aliases),
                2,
                rejected_from_pillar_id,
                utc_now(),
            ),
        )
        return self._row_to_layer2_negative_cache(
            self._fetchone(f"SELECT * FROM layer2_negative_cache WHERE id = {self.param}", (entry_id,))
        )

    def list_layer2_negative_cache(self, project_id: str) -> list[Layer2NegativeCacheEntry]:
        """Return rejected Layer 2 semantic clusters for generation-time filtering."""
        rows = self._fetchall(
            f"SELECT * FROM layer2_negative_cache WHERE project_id = {self.param} ORDER BY created_at DESC",
            (project_id,),
        )
        return [self._row_to_layer2_negative_cache(row) for row in rows]

    def record_layer2_review_action(
        self,
        *,
        project_id: str,
        feature_id: str | None,
        action_type: str,
        payload: dict[str, Any] | None = None,
    ) -> Layer2ReviewAction:
        """Record a human or system review action before Layer 2 can be exported as final JSON."""
        action_id = str(uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO layer2_review_actions (id, project_id, feature_id, action_type, payload, created_at)
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (action_id, project_id, feature_id, action_type, self._dump_json(payload or {}), utc_now()),
        )
        return self._row_to_layer2_review_action(
            self._fetchone(f"SELECT * FROM layer2_review_actions WHERE id = {self.param}", (action_id,))
        )

    def list_layer2_review_actions(self, project_id: str) -> list[Layer2ReviewAction]:
        """Return Layer 2 review queue decisions and system recommendations."""
        rows = self._fetchall(
            f"SELECT * FROM layer2_review_actions WHERE project_id = {self.param} ORDER BY created_at DESC",
            (project_id,),
        )
        return [self._row_to_layer2_review_action(row) for row in rows]

    def layer2_graph_snapshot(self, project_id: str) -> dict[str, Any]:
        """Return the full Layer 2 graph and review queue as a serializable API payload."""
        features = self.list_layer2_features(project_id)
        affinities = self.list_layer2_affinities(project_id)
        relationships = self.list_layer2_relationships(project_id)
        review_actions = self.list_layer2_review_actions(project_id)
        negative_cache = self.list_layer2_negative_cache(project_id)
        coverage_memory = [
            item
            for item in self.list_project_memory(project_id)
            if item.scope == "layer2" and item.memory_type == "scoped_coverage"
        ]
        return {
            "features": [feature.model_dump(mode="json") for feature in features],
            "affinity": [
                {
                    "feature_id": affinity.feature_id,
                    "pillar_id": affinity.pillar_id,
                    "affinity_score": affinity.affinity_score,
                    "recommended_owner_pillar_id": affinity.recommended_owner_pillar_id,
                }
                for affinity in affinities
            ],
            "relationships": [relationship.model_dump(mode="json") for relationship in relationships],
            "review_actions": [action.model_dump(mode="json") for action in review_actions],
            "negative_cache": [entry.model_dump(mode="json") for entry in negative_cache],
            "coverage": [item.model_dump(mode="json") for item in coverage_memory],
            "review_open": any(feature.status in {"candidate", "needs_review"} for feature in features),
        }


    def _row_to_layer2_generation_run(self, row: Any) -> Layer2GenerationRun:
        """Convert a raw database row into a Layer 2 generation run."""
        completed_at = row["completed_at"]
        return Layer2GenerationRun(
            id=row["id"],
            project_id=row["project_id"],
            source_pillar_ids=self._load_json_list(row["source_pillar_ids"]),
            lenses=self._load_json_list(row["lenses"]),
            source_model=row["source_model"],
            status=row["status"],
            summary=self._load_json(row["summary"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            completed_at=datetime.fromisoformat(str(completed_at)) if completed_at else None,
        )

    def _row_to_layer2_raw_candidate(self, row: Any) -> Layer2RawCandidate:
        """Convert a raw database row into a Layer 2 raw candidate."""
        return Layer2RawCandidate(
            id=row["id"],
            project_id=row["project_id"],
            generation_run_id=row["generation_run_id"],
            source_pillar_id=row["source_pillar_id"],
            source_lens=row["source_lens"],
            source_model=row["source_model"],
            generation_round=int(row["generation_round"]),
            raw_text=row["raw_text"],
            payload=self._load_json(row["payload"]),
            negative_cache_match=bool(row["negative_cache_match"]),
            negative_cache_reason=row["negative_cache_reason"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_layer2_feature(self, row: Any) -> Layer2Feature:
        """Convert a raw database row into a canonical Layer 2 feature."""
        return Layer2Feature(
            id=row["id"],
            project_id=row["project_id"],
            canonical_name=row["canonical_name"],
            description=row["description"],
            feature_type=row["feature_type"],
            owner_pillar_id=row["owner_pillar_id"],
            candidate_source_ids=self._load_json_list(row["candidate_source_ids"]),
            aliases=self._load_json_list(row["aliases"]),
            status=row["status"],
            related_pillar_ids=self._load_json_list(row["related_pillar_ids"]),
            used_by_feature_ids=self._load_json_list(row["used_by_feature_ids"]),
            depends_on_feature_ids=self._load_json_list(row["depends_on_feature_ids"]),
            specificity_score=int(row["specificity_score"]),
            pillar_fit_score=int(row["pillar_fit_score"]),
            distinctiveness_score=int(row["distinctiveness_score"]),
            implementation_leakage_score=int(row["implementation_leakage_score"]),
            strategic_value_score=int(row["strategic_value_score"]),
            needs_human_review=bool(row["needs_human_review"]),
            metadata=self._load_json(row["metadata"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_layer2_relationship(self, row: Any) -> Layer2FeatureRelationship:
        """Convert a raw database row into a Layer 2 feature relationship."""
        return Layer2FeatureRelationship(
            id=row["id"],
            project_id=row["project_id"],
            source_feature_id=row["source_feature_id"],
            target_feature_id=row["target_feature_id"],
            relationship_type=row["relationship_type"],
            strength=float(row["strength"]),
            rationale=row["rationale"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_layer2_affinity(self, row: Any) -> Layer2PillarAffinity:
        """Convert a raw database row into a Layer 2 pillar-affinity score."""
        return Layer2PillarAffinity(
            id=row["id"],
            project_id=row["project_id"],
            feature_id=row["feature_id"],
            pillar_id=row["pillar_id"],
            affinity_score=float(row["affinity_score"]),
            recommended_owner_pillar_id=row["recommended_owner_pillar_id"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_layer2_negative_cache(self, row: Any) -> Layer2NegativeCacheEntry:
        """Convert a raw database row into a Layer 2 negative-cache entry."""
        return Layer2NegativeCacheEntry(
            id=row["id"],
            project_id=row["project_id"],
            rejected_name=row["rejected_name"],
            semantic_cluster=row["semantic_cluster"],
            rejected_aliases=self._load_json_list(row["rejected_aliases"]),
            rejected_at_layer=int(row["rejected_at_layer"]),
            rejected_from_pillar_id=row["rejected_from_pillar_id"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_layer2_review_action(self, row: Any) -> Layer2ReviewAction:
        """Convert a raw database row into a Layer 2 review action."""
        return Layer2ReviewAction(
            id=row["id"],
            project_id=row["project_id"],
            feature_id=row["feature_id"],
            action_type=row["action_type"],
            payload=self._load_json(row["payload"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

