from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from specforge.embeddings import EmbeddingResult
from specforge.models import Node, SimilarityEdge, SimilarityMatch


@dataclass(slots=True)
class OverlapCluster:
    """Connected group of semantically similar Layer 1 pillars."""

    cluster_id: str
    representative_node_id: str
    representative_title: str
    member_node_ids: list[str]
    member_titles: list[str]
    average_score: float


@dataclass(slots=True)
class Layer1OverlapIndex:
    """In-memory lookup tables produced from persisted Layer 1 similarity edges."""

    matches_by_node: dict[str, list[SimilarityMatch]]
    clusters_by_node: dict[str, OverlapCluster]
    relationships_by_node: dict[str, list[dict[str, Any]]]
    memory_payload: dict[str, Any]


class Layer1OverlapMixin:
    """Semantic overlap clustering and embedding refresh helpers for Layer 1 pillars."""

    def refresh_pillar_semantic_metadata(self, node_id: str) -> Node:
        """Recompute semantic-overlap metadata, clusters, and relationships for an existing Layer 1 pillar."""
        node = self.db.get_node(node_id)
        if node.node_type != "pillar" or node.layer != 1:
            return node
        self._ensure_pillar_embeddings(node.project_id, [node])
        refreshed_nodes = self.refresh_layer1_overlap_memory(node.project_id)
        for refreshed in refreshed_nodes:
            if refreshed.id == node.id:
                return refreshed
        return node

    def refresh_layer1_overlap_memory(self, project_id: str, nodes: list[Node] | None = None) -> list[Node]:
        """Persist cluster-backed Layer 1 overlap memory so review and future rounds can reuse it."""
        if nodes is None:
            nodes = self.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
        if self.embedding_service is None or not self.embedding_service.enabled() or not self.db.is_postgres:
            return nodes
        if not nodes:
            self.db.upsert_project_memory(
                project_id=project_id,
                scope="layer1",
                scope_id=None,
                memory_type="overlap_graph",
                content={"clusters": [], "edges": [], "node_clusters": {}, "threshold": None},
            )
            return nodes
        overlap_index = self._build_layer1_overlap_index(project_id, nodes)
        refreshed_nodes: list[Node] = []
        for node in nodes:
            refreshed_nodes.append(self._apply_overlap_index_to_node(node, overlap_index))
        self.db.upsert_project_memory(
            project_id=project_id,
            scope="layer1",
            scope_id=None,
            memory_type="overlap_graph",
            content=overlap_index.memory_payload,
        )
        return refreshed_nodes

    def _build_layer1_overlap_index(self, project_id: str, nodes: list[Node]) -> Layer1OverlapIndex:
        """Convert stored pairwise similarities into connected-cluster review memory."""
        if self.embedding_service is None:
            return Layer1OverlapIndex(matches_by_node={}, clusters_by_node={}, relationships_by_node={}, memory_payload={})
        threshold = self.embedding_service.config.pillar_similarity_threshold
        block_threshold = self.embedding_service.config.pillar_similarity_block_threshold
        embedding_model_name = self._embedding_model_name(project_id, "layer1_similarity_embeddings")
        edges = self.db.list_similarity_edges(
            project_id=project_id,
            embedding_model=embedding_model_name,
            layer=1,
            node_type="pillar",
            min_similarity=threshold,
        )
        node_by_id = {node.id: node for node in nodes}
        matches_by_node: dict[str, list[SimilarityMatch]] = {node.id: [] for node in nodes}
        adjacency: dict[str, set[str]] = {node.id: set() for node in nodes}
        edge_scores: dict[tuple[str, str], float] = {}

        for edge in edges:
            left = node_by_id.get(edge.source_node_id)
            right = node_by_id.get(edge.target_node_id)
            if left is None or right is None:
                continue
            similarity = round(edge.score, 4)
            pair_key = tuple(sorted((left.id, right.id)))
            edge_scores[pair_key] = similarity
            adjacency[left.id].add(right.id)
            adjacency[right.id].add(left.id)
            matches_by_node[left.id].append(
                SimilarityMatch(
                    node_id=right.id,
                    title=right.title,
                    description=right.description,
                    layer=right.layer,
                    node_type=right.node_type,
                    score=similarity,
                )
            )
            matches_by_node[right.id].append(
                SimilarityMatch(
                    node_id=left.id,
                    title=left.title,
                    description=left.description,
                    layer=left.layer,
                    node_type=left.node_type,
                    score=similarity,
                )
            )

        for node_id, matches in matches_by_node.items():
            matches_by_node[node_id] = sorted(matches, key=lambda item: item.score, reverse=True)[: self.embedding_service.config.pillar_similarity_top_k]

        clusters = self._connected_similarity_clusters(nodes, adjacency, edge_scores)
        clusters_by_node: dict[str, OverlapCluster] = {}
        relationships_by_node: dict[str, list[dict[str, Any]]] = {node.id: [] for node in nodes}

        for cluster in clusters:
            for member_node_id in cluster.member_node_ids:
                clusters_by_node[member_node_id] = cluster

        for edge in edges:
            left_cluster = clusters_by_node.get(edge.source_node_id)
            right_cluster = clusters_by_node.get(edge.target_node_id)
            relationship_type = self._overlap_relationship_type(edge.score, block_threshold)
            relationship_detail = (
                f"Near-duplicate signal {edge.score:.4f}"
                if relationship_type == "near_duplicate"
                else f"Cluster overlap {edge.score:.4f}"
            )
            if left_cluster is not None and right_cluster is not None and left_cluster.cluster_id == right_cluster.cluster_id:
                relationships_by_node[edge.source_node_id].append(
                    {
                        "target_node_id": edge.target_node_id,
                        "target_title": edge.target_title,
                        "relationship_type": relationship_type,
                        "score": round(edge.score, 4),
                        "cluster_id": left_cluster.cluster_id,
                        "detail": relationship_detail,
                    }
                )
                relationships_by_node[edge.target_node_id].append(
                    {
                        "target_node_id": edge.source_node_id,
                        "target_title": edge.source_title,
                        "relationship_type": relationship_type,
                        "score": round(edge.score, 4),
                        "cluster_id": left_cluster.cluster_id,
                        "detail": relationship_detail,
                    }
                )

        memory_payload = {
            "threshold": threshold,
            "near_duplicate_threshold": block_threshold,
            "clusters": [
                {
                    "cluster_id": cluster.cluster_id,
                    "representative_node_id": cluster.representative_node_id,
                    "representative_title": cluster.representative_title,
                    "member_count": len(cluster.member_node_ids),
                    "member_node_ids": cluster.member_node_ids,
                    "member_titles": cluster.member_titles,
                    "average_score": cluster.average_score,
                }
                for cluster in clusters
            ],
            "edges": [
                {
                    "source_node_id": edge.source_node_id,
                    "target_node_id": edge.target_node_id,
                    "source_title": edge.source_title,
                    "target_title": edge.target_title,
                    "relationship_type": self._overlap_relationship_type(edge.score, block_threshold),
                    "score": round(edge.score, 4),
                }
                for edge in edges
            ],
            "node_clusters": {
                node_id: {
                    "cluster_id": cluster.cluster_id,
                    "representative_node_id": cluster.representative_node_id,
                    "representative_title": cluster.representative_title,
                    "member_count": len(cluster.member_node_ids),
                }
                for node_id, cluster in clusters_by_node.items()
            },
        }
        return Layer1OverlapIndex(
            matches_by_node=matches_by_node,
            clusters_by_node=clusters_by_node,
            relationships_by_node=relationships_by_node,
            memory_payload=memory_payload,
        )

    def _apply_overlap_index_to_node(self, node: Node, overlap_index: Layer1OverlapIndex) -> Node:
        """Write cluster-backed overlap metadata back onto one pillar payload."""
        payload = dict(node.json_payload or {})
        matches = overlap_index.matches_by_node.get(node.id, [])
        cluster = overlap_index.clusters_by_node.get(node.id)
        relationships = overlap_index.relationships_by_node.get(node.id, [])
        changed = False

        if matches:
            next_similarity = self._semantic_similarity_payload(matches)
            if payload.get("semantic_similarity") != next_similarity:
                payload["semantic_similarity"] = next_similarity
                changed = True
        elif "semantic_similarity" in payload:
            payload.pop("semantic_similarity", None)
            changed = True

        if cluster is not None:
            next_cluster = {
                "cluster_id": cluster.cluster_id,
                "representative_node_id": cluster.representative_node_id,
                "representative_title": cluster.representative_title,
                "member_count": len(cluster.member_node_ids),
                "member_node_ids": cluster.member_node_ids,
                "member_titles": cluster.member_titles,
                "average_score": cluster.average_score,
            }
            if payload.get("overlap_cluster") != next_cluster:
                payload["overlap_cluster"] = next_cluster
                changed = True
        elif "overlap_cluster" in payload:
            payload.pop("overlap_cluster", None)
            changed = True

        if relationships:
            if payload.get("overlap_relationships") != relationships:
                payload["overlap_relationships"] = relationships
                changed = True
        elif "overlap_relationships" in payload:
            payload.pop("overlap_relationships", None)
            changed = True

        if not changed:
            return node
        return self.db.update_node(node.id, json_payload=payload)

    @staticmethod
    def _connected_similarity_clusters(
        nodes: list[Node],
        adjacency: dict[str, set[str]],
        edge_scores: dict[tuple[str, str], float],
    ) -> list[OverlapCluster]:
        """Collapse pairwise similarity edges into connected concept neighborhoods."""
        node_by_id = {node.id: node for node in nodes}
        seen: set[str] = set()
        clusters: list[OverlapCluster] = []
        for node in nodes:
            if node.id in seen or not adjacency.get(node.id):
                continue
            stack = [node.id]
            member_ids: list[str] = []
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                member_ids.append(current)
                stack.extend(sorted(adjacency.get(current, set()) - seen))

            member_ids = sorted(member_ids)
            representative_node_id = Layer1OverlapMixin._cluster_representative_node_id(member_ids, adjacency, node_by_id)
            representative_title = Layer1OverlapMixin._overlap_reference_title(node_by_id[representative_node_id])
            member_titles = [node_by_id[item].title for item in member_ids]
            average_score = Layer1OverlapMixin._cluster_average_score(member_ids, edge_scores)
            cluster_slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in representative_title).strip("-") or representative_node_id[:8]
            clusters.append(
                OverlapCluster(
                    cluster_id=f"semantic-{cluster_slug}",
                    representative_node_id=representative_node_id,
                    representative_title=representative_title,
                    member_node_ids=member_ids,
                    member_titles=member_titles,
                    average_score=average_score,
                )
            )
        return clusters

    @staticmethod
    def _cluster_representative_node_id(
        member_ids: list[str],
        adjacency: dict[str, set[str]],
        node_by_id: dict[str, Node],
    ) -> str:
        """Choose a stable representative title for a similarity cluster."""
        ranked = sorted(
            member_ids,
            key=lambda node_id: (
                -len(adjacency.get(node_id, set())),
                Layer1OverlapMixin._overlap_reference_title(node_by_id[node_id]).lower(),
                node_id,
            ),
        )
        return ranked[0]

    @staticmethod
    def _cluster_average_score(member_ids: list[str], edge_scores: dict[tuple[str, str], float]) -> float:
        """Summarize cluster density with an average internal edge score."""
        scores = [
            score
            for pair, score in edge_scores.items()
            if pair[0] in member_ids and pair[1] in member_ids
        ]
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 4)

    @staticmethod
    def _overlap_reference_title(node: Node) -> str:
        """Prefer canonical or representative labels when naming overlap clusters."""
        payload = node.json_payload or {}
        overlap_cluster = payload.get("overlap_cluster")
        if isinstance(overlap_cluster, dict):
            title = overlap_cluster.get("representative_title")
            if isinstance(title, str) and title.strip():
                return title.strip()
        canonical_title = payload.get("canonical_title")
        if isinstance(canonical_title, str) and canonical_title.strip():
            return canonical_title.strip()
        return node.title

    @staticmethod
    def _overlap_relationship_type(score: float, block_threshold: float) -> str:
        """Differentiate very strong duplicate pressure from broader cluster membership."""
        return "near_duplicate" if score >= block_threshold else "cluster_neighbor"

    @staticmethod
    def _semantic_similarity_payload(matches: list[SimilarityMatch]) -> dict[str, Any]:
        """Convert similarity matches into compact JSON the review UI can render easily."""
        return {
            "matches": [match.model_dump(mode="json") for match in matches],
            "top_score": round(matches[0].score, 4) if matches else None,
        }

    def _pillar_similarity_result(
        self,
        *,
        project_id: str,
        title: str,
        description: str,
        payload: dict[str, Any],
        exclude_node_ids: list[str] | None = None,
    ) -> tuple[EmbeddingResult | None, list[SimilarityMatch]]:
        """Embed a pillar and return cosine-similar saved Layer 1 pillars from the same project."""
        if self.embedding_service is None or not self.embedding_service.enabled() or not self.db.is_postgres:
            return None, []
        embedding_model_name = self._embedding_model_name(project_id, "layer1_similarity_embeddings")
        text = self.embedding_service.pillar_text(title, description, payload)
        embedding_result = self.embedding_service.embed_text(text, model_name=embedding_model_name)
        matches = self.embedding_service.find_similar_pillars(
            db=self.db,
            project_id=project_id,
            embedding_model=embedding_model_name,
            embedding=embedding_result.vector,
            exclude_node_ids=exclude_node_ids,
        )
        return embedding_result, matches

    def _ensure_pillar_embeddings(self, project_id: str, nodes: list[Node]) -> None:
        """Backfill embeddings for existing pillars so similarity checks have real context."""
        if self.embedding_service is None or not self.embedding_service.enabled() or not self.db.is_postgres:
            return
        embedding_model_name = self._embedding_model_name(project_id, "layer1_similarity_embeddings")
        for node in nodes:
            text = self.embedding_service.pillar_text(node)
            embedding_result = self.embedding_service.embed_text(text, model_name=embedding_model_name)
            existing_hash = self.db.get_node_embedding_hash(node.id, embedding_model_name)
            if existing_hash == embedding_result.content_hash:
                continue
            self.db.upsert_node_embedding(
                project_id=project_id,
                node_id=node.id,
                embedding_model=embedding_model_name,
                embedding=embedding_result.vector,
                content_hash=embedding_result.content_hash,
            )

    def _store_pillar_embedding(
        self,
        project_id: str,
        node: Node,
        embedding_result: EmbeddingResult | None,
    ) -> None:
        """Persist the embedding for a pillar after create or refresh operations."""
        if self.embedding_service is None or not self.embedding_service.enabled() or not self.db.is_postgres:
            return
        embedding_model_name = self._embedding_model_name(project_id, "layer1_similarity_embeddings")
        if embedding_result is None:
            text = self.embedding_service.pillar_text(node)
            embedding_result = self.embedding_service.embed_text(text, model_name=embedding_model_name)
        self.db.upsert_node_embedding(
            project_id=project_id,
            node_id=node.id,
            embedding_model=embedding_model_name,
            embedding=embedding_result.vector,
            content_hash=embedding_result.content_hash,
        )

