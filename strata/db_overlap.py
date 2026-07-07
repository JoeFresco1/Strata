from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pgvector import Vector

from strata.models import OverlapClusterRecord, OverlapJobItem, OverlapVerdict, OverlapVerdictResolution, SimilarityMatch


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OverlapDatabaseMixin:
    """Persistence for full-project Layer 1/Layer 2 overlap critic runs."""

    def upsert_layer2_feature_embedding(
        self,
        *,
        project_id: str,
        feature_id: str,
        embedding_model: str,
        embedding: list[float],
        content_hash: str,
    ) -> None:
        now = utc_now()
        vector_value: Any = Vector(embedding) if self.is_postgres else self._dump_json(embedding)
        self._execute(
            f"""
            INSERT INTO layer2_feature_embeddings (
                id, project_id, feature_id, embedding_model, embedding, content_hash, created_at, updated_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            ON CONFLICT (feature_id, embedding_model)
            DO UPDATE SET embedding = EXCLUDED.embedding, content_hash = EXCLUDED.content_hash, updated_at = EXCLUDED.updated_at
            """,
            (str(uuid.uuid4()), project_id, feature_id, embedding_model, vector_value, content_hash, now, now),
        )

    def get_layer2_feature_embedding_hash(self, feature_id: str, embedding_model: str) -> str | None:
        row = self._fetchone(
            f"""
            SELECT content_hash FROM layer2_feature_embeddings
            WHERE feature_id = {self.param} AND embedding_model = {self.param}
            """,
            (feature_id, embedding_model),
        )
        return str(self._row_value(row, "content_hash")) if row is not None and self._row_value(row, "content_hash") else None

    def find_similar_layer2_features(
        self,
        *,
        project_id: str,
        embedding_model: str,
        embedding: list[float],
        exclude_feature_ids: list[str] | None = None,
        min_similarity: float = 0.0,
        limit: int = 5,
    ) -> list[SimilarityMatch]:
        if not self.is_postgres:
            return []
        query = f"""
            SELECT
                layer2_features.id AS node_id,
                layer2_features.canonical_name AS title,
                layer2_features.description AS description,
                1 - (layer2_feature_embeddings.embedding <=> {self.param}) AS score
            FROM layer2_feature_embeddings
            JOIN layer2_features ON layer2_features.id = layer2_feature_embeddings.feature_id
            WHERE layer2_feature_embeddings.project_id = {self.param}
              AND layer2_feature_embeddings.embedding_model = {self.param}
              AND layer2_features.status NOT IN ('cut', 'merged')
        """
        vector = Vector(embedding)
        params: list[Any] = [vector, project_id, embedding_model]
        if exclude_feature_ids:
            placeholders = ", ".join([self.param] * len(exclude_feature_ids))
            query += f" AND layer2_features.id NOT IN ({placeholders})"
            params.extend(exclude_feature_ids)
        query += f" AND 1 - (layer2_feature_embeddings.embedding <=> {self.param}) >= {self.param}"
        params.extend([vector, min_similarity])
        query += f" ORDER BY layer2_feature_embeddings.embedding <=> {self.param} ASC LIMIT {self.param}"
        params.extend([vector, limit])
        rows = self._fetchall(query, tuple(params))
        return [
            SimilarityMatch(
                node_id=str(self._row_value(row, "node_id")),
                title=str(self._row_value(row, "title")),
                description=self._row_value(row, "description"),
                layer=2,
                node_type="feature",
                score=float(self._row_value(row, "score")),
            )
            for row in rows
        ]

    def upsert_overlap_job_item(
        self,
        *,
        project_id: str,
        job_id: str,
        layer: str,
        item_id: str,
        item_hash: str,
        status: str = "pending",
        error: str = "",
    ) -> OverlapJobItem:
        now = utc_now()
        row = self._fetchone(
            f"""
            SELECT * FROM overlap_job_items
            WHERE job_id = {self.param} AND item_id = {self.param}
            """,
            (job_id, item_id),
        )
        if row is None:
            item_row_id = str(uuid.uuid4())
            self._execute(
                f"""
                INSERT INTO overlap_job_items (
                    id, project_id, job_id, layer, item_id, item_hash, status, error, created_at, updated_at
                )
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
                """,
                (item_row_id, project_id, job_id, layer, item_id, item_hash, status, error, now, now),
            )
            return self.get_overlap_job_item(job_id, item_id)
        self._execute(
            f"""
            UPDATE overlap_job_items
            SET item_hash = {self.param}, status = {self.param}, error = {self.param}, updated_at = {self.param}
            WHERE id = {self.param}
            """,
            (item_hash, status, error, now, self._row_value(row, "id")),
        )
        return self.get_overlap_job_item(job_id, item_id)

    def get_overlap_job_item(self, job_id: str, item_id: str) -> OverlapJobItem:
        row = self._fetchone(
            f"SELECT * FROM overlap_job_items WHERE job_id = {self.param} AND item_id = {self.param}",
            (job_id, item_id),
        )
        if row is None:
            raise ValueError(f"Overlap job item not found: {job_id}/{item_id}")
        return self._row_to_overlap_job_item(row)

    def list_overlap_job_items(self, job_id: str) -> list[OverlapJobItem]:
        rows = self._fetchall(
            f"SELECT * FROM overlap_job_items WHERE job_id = {self.param} ORDER BY created_at ASC",
            (job_id,),
        )
        return [self._row_to_overlap_job_item(row) for row in rows]

    def insert_overlap_verdict(
        self,
        *,
        project_id: str,
        job_id: str,
        layer: str,
        target_id: str,
        neighbor_id: str,
        relation: str,
        confidence: float,
        rationale: str,
        critic_source: str,
        target_hash: str,
        neighbor_hash: str,
        metadata: dict[str, Any] | None = None,
    ) -> OverlapVerdict:
        verdict_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO overlap_verdicts (
                id, project_id, job_id, layer, target_id, neighbor_id, relation, confidence,
                rationale, critic_source, target_hash, neighbor_hash, metadata, created_at, updated_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                verdict_id,
                project_id,
                job_id,
                layer,
                target_id,
                neighbor_id,
                relation,
                max(0.0, min(1.0, float(confidence))),
                rationale,
                critic_source,
                target_hash,
                neighbor_hash,
                self._dump_json(metadata or {}),
                now,
                now,
            ),
        )
        return self._row_to_overlap_verdict(
            self._fetchone(f"SELECT * FROM overlap_verdicts WHERE id = {self.param}", (verdict_id,))
        )

    def insert_overlap_cluster(
        self,
        *,
        project_id: str,
        job_id: str,
        layer: str,
        cluster_id: str,
        member_ids: list[str],
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> OverlapClusterRecord:
        row_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO overlap_clusters (
                id, project_id, job_id, layer, cluster_id, member_ids, summary, metadata, created_at, updated_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (row_id, project_id, job_id, layer, cluster_id, self._dump_json(member_ids), summary, self._dump_json(metadata or {}), now, now),
        )
        return self._row_to_overlap_cluster(
            self._fetchone(f"SELECT * FROM overlap_clusters WHERE id = {self.param}", (row_id,))
        )

    def latest_completed_overlap_job_id(self, project_id: str, layer: str) -> str | None:
        workflow = f"{layer}_overlap_critic"
        row = self._fetchone(
            f"""
            SELECT id FROM platform_jobs
            WHERE project_id = {self.param}
              AND workflow = {self.param}
              AND status = 'completed'
            ORDER BY completed_at DESC, updated_at DESC
            LIMIT 1
            """,
            (project_id, workflow),
        )
        return str(self._row_value(row, "id")) if row is not None else None

    def list_overlap_verdicts_for_job(self, job_id: str) -> list[OverlapVerdict]:
        rows = self._fetchall(
            f"SELECT * FROM overlap_verdicts WHERE job_id = {self.param} ORDER BY created_at ASC",
            (job_id,),
        )
        return [self._row_to_overlap_verdict(row) for row in rows]

    def get_overlap_verdict(self, verdict_id: str) -> OverlapVerdict:
        row = self._fetchone(f"SELECT * FROM overlap_verdicts WHERE id = {self.param}", (verdict_id,))
        if row is None:
            raise ValueError(f"Overlap verdict not found: {verdict_id}")
        return self._row_to_overlap_verdict(row)

    def list_overlap_clusters_for_job(self, job_id: str) -> list[OverlapClusterRecord]:
        rows = self._fetchall(
            f"SELECT * FROM overlap_clusters WHERE job_id = {self.param} ORDER BY created_at ASC",
            (job_id,),
        )
        return [self._row_to_overlap_cluster(row) for row in rows]

    def create_overlap_verdict_resolution(
        self,
        *,
        project_id: str,
        verdict_id: str,
        layer: str,
        target_id: str,
        neighbor_id: str,
        action: str,
        note: str = "",
        resolved_by: str = "user",
        target_hash: str = "",
        neighbor_hash: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> OverlapVerdictResolution:
        resolution_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO overlap_verdict_resolutions (
                id, project_id, verdict_id, layer, target_id, neighbor_id, action, note, resolved_by,
                target_hash, neighbor_hash, metadata, created_at, updated_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                resolution_id,
                project_id,
                verdict_id,
                layer,
                target_id,
                neighbor_id,
                action,
                note,
                resolved_by,
                target_hash,
                neighbor_hash,
                self._dump_json(metadata or {}),
                now,
                now,
            ),
        )
        return self._row_to_overlap_resolution(
            self._fetchone(f"SELECT * FROM overlap_verdict_resolutions WHERE id = {self.param}", (resolution_id,))
        )

    def list_overlap_resolutions(self, project_id: str, layer: str | None = None) -> list[OverlapVerdictResolution]:
        if layer:
            rows = self._fetchall(
                f"""
                SELECT * FROM overlap_verdict_resolutions
                WHERE project_id = {self.param} AND layer = {self.param}
                ORDER BY created_at DESC
                """,
                (project_id, layer),
            )
        else:
            rows = self._fetchall(
                f"""
                SELECT * FROM overlap_verdict_resolutions
                WHERE project_id = {self.param}
                ORDER BY created_at DESC
                """,
                (project_id,),
            )
        return [self._row_to_overlap_resolution(row) for row in rows]

    def latest_active_overlap_resolution(
        self,
        project_id: str,
        layer: str,
        target_id: str,
        neighbor_id: str,
        target_hash: str,
        neighbor_hash: str,
    ) -> OverlapVerdictResolution | None:
        resolutions = self.list_overlap_resolutions(project_id, layer)
        for resolution in resolutions:
            same_order = (
                resolution.target_id == target_id
                and resolution.neighbor_id == neighbor_id
                and resolution.target_hash == target_hash
                and resolution.neighbor_hash == neighbor_hash
            )
            swapped_order = (
                resolution.target_id == neighbor_id
                and resolution.neighbor_id == target_id
                and resolution.target_hash == neighbor_hash
                and resolution.neighbor_hash == target_hash
            )
            if same_order or swapped_order:
                return resolution
        return None

    def overlap_snapshot(self, project_id: str) -> dict[str, Any]:
        return {
            "layer1": self._overlap_layer_snapshot(project_id, "layer1"),
            "layer2": self._overlap_layer_snapshot(project_id, "layer2"),
        }

    def _overlap_layer_snapshot(self, project_id: str, layer: str) -> dict[str, Any]:
        job_id = self.latest_completed_overlap_job_id(project_id, layer)
        if not job_id:
            return {"latest_completed_job_id": None, "verdicts": [], "clusters": [], "summary": {"unresolved": 0, "resolved": 0, "stale_resolution": 0}}
        current_hashes = self.current_overlap_item_hashes(project_id, layer)
        resolution_rows = self.list_overlap_resolutions(project_id, layer)
        payloads: list[dict[str, Any]] = []
        summary = {"unresolved": 0, "resolved": 0, "stale_resolution": 0}
        for verdict in self.list_overlap_verdicts_for_job(job_id):
            if current_hashes.get(verdict.target_id) != verdict.target_hash or current_hashes.get(verdict.neighbor_id) != verdict.neighbor_hash:
                continue
            active_resolution = None
            stale_resolution = None
            for resolution in resolution_rows:
                same_pair = {resolution.target_id, resolution.neighbor_id} == {verdict.target_id, verdict.neighbor_id}
                if not same_pair:
                    continue
                resolution_current = (
                    current_hashes.get(resolution.target_id) == resolution.target_hash
                    and current_hashes.get(resolution.neighbor_id) == resolution.neighbor_hash
                )
                if resolution_current:
                    active_resolution = resolution
                    break
                if stale_resolution is None:
                    stale_resolution = resolution
            if active_resolution is not None:
                state = "resolved"
                summary["resolved"] += 1
            elif stale_resolution is not None:
                state = "stale_resolution"
                summary["stale_resolution"] += 1
            else:
                state = "unresolved"
                summary["unresolved"] += 1
            payload = verdict.model_dump(mode="json")
            payload.update(
                {
                    "resolved": state == "resolved",
                    "resolution_state": state,
                    "active_resolution": active_resolution.model_dump(mode="json") if active_resolution else None,
                    "stale_resolution": stale_resolution.model_dump(mode="json") if stale_resolution and not active_resolution else None,
                }
            )
            payloads.append(payload)
        return {
            "latest_completed_job_id": job_id,
            "verdicts": payloads,
            "clusters": [cluster.model_dump(mode="json") for cluster in self.list_overlap_clusters_for_job(job_id)],
            "summary": summary,
        }

    def current_overlap_item_hashes(self, project_id: str, layer: str) -> dict[str, str]:
        if layer == "layer1":
            items = [
                (node.id, f"{node.title}\n{node.description or ''}\n{node.status}")
                for node in self.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
                if node.status not in {"cut", "merged"}
            ]
        else:
            items = [
                (feature.id, f"{feature.canonical_name}\n{feature.description}\n{feature.owner_pillar_id}\n{feature.status}")
                for feature in self.list_layer2_features(project_id)
                if feature.status not in {"cut", "merged"}
            ]
        return {item_id: self._stable_overlap_hash(text) for item_id, text in items}

    @staticmethod
    def _stable_overlap_hash(text: str) -> str:
        import hashlib

        return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()

    def _row_to_overlap_verdict(self, row: Any) -> OverlapVerdict:
        return OverlapVerdict(
            id=row["id"],
            project_id=row["project_id"],
            job_id=row["job_id"],
            layer=row["layer"],
            target_id=row["target_id"],
            neighbor_id=row["neighbor_id"],
            relation=row["relation"],
            confidence=float(row["confidence"]),
            rationale=row["rationale"],
            critic_source=row["critic_source"],
            target_hash=row["target_hash"],
            neighbor_hash=row["neighbor_hash"],
            metadata=self._load_json(row["metadata"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_overlap_cluster(self, row: Any) -> OverlapClusterRecord:
        return OverlapClusterRecord(
            id=row["id"],
            project_id=row["project_id"],
            job_id=row["job_id"],
            layer=row["layer"],
            cluster_id=row["cluster_id"],
            member_ids=self._load_json_list(row["member_ids"]),
            summary=row["summary"],
            metadata=self._load_json(row["metadata"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_overlap_resolution(self, row: Any) -> OverlapVerdictResolution:
        return OverlapVerdictResolution(
            id=row["id"],
            project_id=row["project_id"],
            verdict_id=row["verdict_id"],
            layer=row["layer"],
            target_id=row["target_id"],
            neighbor_id=row["neighbor_id"],
            action=row["action"],
            note=row["note"] or "",
            resolved_by=row["resolved_by"] or "user",
            target_hash=row["target_hash"],
            neighbor_hash=row["neighbor_hash"],
            metadata=self._load_json(row["metadata"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_overlap_job_item(self, row: Any) -> OverlapJobItem:
        return OverlapJobItem(
            id=row["id"],
            project_id=row["project_id"],
            job_id=row["job_id"],
            layer=row["layer"],
            item_id=row["item_id"],
            item_hash=row["item_hash"],
            status=row["status"],
            error=row["error"] or "",
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
