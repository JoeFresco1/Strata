from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pgvector import Vector

from strata.models import SimilarityEdge, SimilarityMatch


def utc_now() -> str:
    """Return an ISO timestamp in UTC for node embedding records."""
    return datetime.now(timezone.utc).isoformat()


class DatabaseEmbeddingMixin:
    """Node embedding and semantic-similarity persistence helpers."""

    def get_node_embedding_hash(self, node_id: str, embedding_model: str) -> str | None:
        """Return the stored content hash for a node embedding when it exists."""
        if not self.is_postgres:
            return None
        row = self._fetchone(
            f"""
            SELECT content_hash
            FROM node_embeddings
            WHERE node_id = {self.param} AND embedding_model = {self.param}
            """,
            (node_id, embedding_model),
        )
        if row is None:
            return None
        value = self._row_value(row, "content_hash")
        return str(value) if value is not None else None

    def upsert_node_embedding(
        self,
        *,
        project_id: str,
        node_id: str,
        embedding_model: str,
        embedding: list[float],
        content_hash: str,
    ) -> None:
        """Store or refresh a node embedding in pgvector-backed storage."""
        if not self.is_postgres:
            return
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO node_embeddings (
                id, project_id, node_id, embedding_model, embedding, content_hash, created_at, updated_at
            )
            VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}
            )
            ON CONFLICT (node_id, embedding_model)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                content_hash = EXCLUDED.content_hash,
                updated_at = EXCLUDED.updated_at
            """,
            (
                str(uuid.uuid4()),
                project_id,
                node_id,
                embedding_model,
                Vector(embedding),
                content_hash,
                now,
                now,
            ),
        )

    def find_similar_nodes(
        self,
        *,
        project_id: str,
        embedding_model: str,
        embedding: list[float],
        layer: int | None = None,
        node_type: str | None = None,
        exclude_node_ids: list[str] | None = None,
        min_similarity: float = 0.0,
        limit: int = 5,
    ) -> list[SimilarityMatch]:
        """Return the most cosine-similar nodes for the supplied embedding."""
        if not self.is_postgres:
            return []
        query = f"""
            SELECT
                nodes.id AS node_id,
                nodes.title,
                nodes.description,
                nodes.layer,
                nodes.node_type,
                1 - (node_embeddings.embedding <=> {self.param}) AS score
            FROM node_embeddings
            JOIN nodes ON nodes.id = node_embeddings.node_id
            WHERE node_embeddings.project_id = {self.param}
              AND node_embeddings.embedding_model = {self.param}
        """
        vector = Vector(embedding)
        params: list[Any] = [vector, project_id, embedding_model]
        if layer is not None:
            query += f" AND nodes.layer = {self.param}"
            params.append(layer)
        if node_type is not None:
            query += f" AND nodes.node_type = {self.param}"
            params.append(node_type)
        if exclude_node_ids:
            placeholders = ", ".join([self.param] * len(exclude_node_ids))
            query += f" AND nodes.id NOT IN ({placeholders})"
            params.extend(exclude_node_ids)
        query += f" AND 1 - (node_embeddings.embedding <=> {self.param}) >= {self.param}"
        params.extend([vector, min_similarity])
        query += f" ORDER BY node_embeddings.embedding <=> {self.param} ASC LIMIT {self.param}"
        params.extend([vector, limit])
        rows = self._fetchall(query, tuple(params))
        return [
            SimilarityMatch(
                node_id=str(self._row_value(row, "node_id")),
                title=str(self._row_value(row, "title")),
                description=self._row_value(row, "description"),
                layer=int(self._row_value(row, "layer")),
                node_type=str(self._row_value(row, "node_type")),
                score=float(self._row_value(row, "score")),
            )
            for row in rows
        ]

    def list_similarity_edges(
        self,
        *,
        project_id: str,
        embedding_model: str,
        layer: int,
        node_type: str,
        min_similarity: float,
    ) -> list[SimilarityEdge]:
        """Return pairwise similarity edges above the threshold using stored pgvector embeddings."""
        if not self.is_postgres:
            return []
        rows = self._fetchall(
            f"""
            SELECT
                left_nodes.id AS source_node_id,
                right_nodes.id AS target_node_id,
                left_nodes.title AS source_title,
                right_nodes.title AS target_title,
                1 - (left_embeddings.embedding <=> right_embeddings.embedding) AS score
            FROM node_embeddings AS left_embeddings
            JOIN node_embeddings AS right_embeddings
              ON left_embeddings.project_id = right_embeddings.project_id
             AND left_embeddings.embedding_model = right_embeddings.embedding_model
             AND left_embeddings.node_id < right_embeddings.node_id
            JOIN nodes AS left_nodes ON left_nodes.id = left_embeddings.node_id
            JOIN nodes AS right_nodes ON right_nodes.id = right_embeddings.node_id
            WHERE left_embeddings.project_id = {self.param}
              AND left_embeddings.embedding_model = {self.param}
              AND left_nodes.layer = {self.param}
              AND right_nodes.layer = {self.param}
              AND left_nodes.node_type = {self.param}
              AND right_nodes.node_type = {self.param}
              AND 1 - (left_embeddings.embedding <=> right_embeddings.embedding) >= {self.param}
            ORDER BY score DESC
            """,
            (project_id, embedding_model, layer, layer, node_type, node_type, min_similarity),
        )
        return [
            SimilarityEdge(
                source_node_id=str(self._row_value(row, "source_node_id")),
                target_node_id=str(self._row_value(row, "target_node_id")),
                source_title=str(self._row_value(row, "source_title")),
                target_title=str(self._row_value(row, "target_title")),
                score=float(self._row_value(row, "score")),
            )
            for row in rows
        ]

