from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from typing import Any

from strata.db import Database
from strata.embeddings import EmbeddingService
from strata.execution_policy import resolve_embedding_model_name


class AssistantIndexService:
    """Build and query a compact, content-hashed project intelligence index."""

    def __init__(self, db: Database, embedding_service: EmbeddingService):
        self.db = db
        self.embedding_service = embedding_service

    def refresh_project(self, project_id: str) -> dict[str, int]:
        """Synchronize canonical project sources into retrieval documents without re-embedding unchanged rows."""
        documents = self._source_documents(project_id)
        existing = {
            (item["source_type"], item["source_id"]): item
            for item in self.db.list_assistant_documents(project_id)
        }
        embedding_model = self._embedding_model(project_id)
        changed = 0
        active_keys: set[tuple[str, str]] = set()
        for document in documents:
            key = (document["source_type"], document["source_id"])
            active_keys.add(key)
            content_hash = self._content_hash(document["content"])
            current = existing.get(key)
            if current and current["content_hash"] == content_hash and current["embedding_model"] == embedding_model:
                continue
            embedding = self._embedding(document["content"], embedding_model)
            self.db.upsert_assistant_document(
                project_id=project_id,
                layer_scope=document["layer_scope"],
                source_type=document["source_type"],
                source_id=document["source_id"],
                title=document["title"],
                content=document["content"],
                content_hash=content_hash,
                metadata=document["metadata"],
                embedding_model=embedding_model,
                embedding=embedding,
            )
            changed += 1
        self.db.delete_stale_assistant_documents(project_id, active_keys)
        return {"total": len(documents), "changed": changed}

    def search(self, project_id: str, scope: str, query: str, *, limit: int = 16) -> list[dict[str, Any]]:
        """Retrieve semantically relevant records within the active layer or across the project."""
        embedding_model = self._embedding_model(project_id)
        return self.db.search_assistant_documents(
            project_id=project_id,
            layer_scope=scope,
            query_text=query,
            embedding_model=embedding_model,
            embedding=self._embedding(query, embedding_model),
            limit=min(max(1, limit), 24),
        )

    def project_summary(self, project_id: str, scope: str = "overall") -> dict[str, Any]:
        """Return deterministic layer counts and review state without spending model context on raw records."""
        nodes = self.db.list_all_nodes(project_id)
        features = self.db.list_layer2_features(project_id)
        relationships = self.db.list_layer2_relationships(project_id)
        coverage = self.db.list_layer2_coverage_matrix(project_id)
        concerns = self.db.list_layer2_shared_concern_clusters(project_id)
        cards = self.db.list_layer3_cards(project_id)
        node_counts = Counter(f"layer{node.layer}" for node in nodes)
        feature_statuses = Counter(feature.status for feature in features)
        return {
            "scope": scope,
            "node_counts": dict(node_counts),
            "layer1_pillars": sum(1 for node in nodes if node.layer == 1 and node.node_type == "pillar"),
            "layer2_features": len(features),
            "layer2_statuses": dict(feature_statuses),
            "layer2_relationships": len(relationships),
            "coverage_missing_or_partial": sum(1 for row in coverage if row.status in {"missing", "partial"}),
            "shared_concerns": len(concerns),
            "layer3_capability_cards": len(cards),
            "layer3_approved_cards": sum(1 for card in cards if card.review_state == "approved"),
        }

    def execute_tool(self, project_id: str, tool: dict[str, Any], active_scope: str, question: str) -> dict[str, Any]:
        """Execute one allowlisted planner directive; arbitrary SQL is never accepted."""
        name = str(tool.get("name", "search_documents"))
        arguments = tool.get("arguments", {}) if isinstance(tool.get("arguments"), dict) else {}
        scope = str(arguments.get("scope", active_scope))
        if name == "project_summary":
            return {"tool": name, "result": self.project_summary(project_id, scope)}
        if name == "search_documents":
            query = str(arguments.get("query", question))
            return {"tool": name, "result": self.search(project_id, scope, query, limit=int(arguments.get("limit", 16)))}
        if name == "filter_entities":
            return {"tool": name, "result": self._filter_entities(project_id, scope, arguments)}
        if name == "graph_neighbors":
            return {"tool": name, "result": self._graph_neighbors(project_id, arguments)}
        if name == "coverage_gaps":
            return {"tool": name, "result": self._coverage_gaps(project_id, arguments)}
        if name == "research_evidence":
            return {"tool": name, "result": self._research_evidence(project_id, scope, arguments)}
        raise ValueError(f"Assistant tool is not allowed: {name}")

    def _source_documents(self, project_id: str) -> list[dict[str, Any]]:
        """Materialize searchable documents from canonical layer records and research evidence."""
        documents: list[dict[str, Any]] = []
        project = self.db.get_project(project_id)
        brief = self.db.get_project_brief(project_id)
        documents.append(self._document("overall", "project", project.id, project.name, project.idea, {"name": project.name}))
        if brief:
            content = json.dumps(brief.model_dump(mode="json"), ensure_ascii=True, default=str)
            documents.append(self._document("layer0", "brief", brief.id, "Layer 0 Brief", content, {"status": brief.status}))
        conversations = self.db.list_brief_conversation(project_id, limit=40)
        if conversations:
            content = "\n".join(f"{turn.role}: {turn.content}" for turn in conversations)
            documents.append(self._document("layer0", "layer0_plan", project_id, "Layer 0 Plan Conversation", content, {}))
        for node in self.db.list_all_nodes(project_id):
            scope = f"layer{min(max(node.layer, 0), 3)}"
            content = json.dumps(node.model_dump(mode="json"), ensure_ascii=True, default=str)
            documents.append(self._document(scope, node.node_type, node.id, node.title, content, {"status": node.status, "parent_id": node.parent_id}))
        documents.extend(self._layer2_documents(project_id))
        for card in self.db.layer3_snapshot(project_id).get("cards", []):
            content = json.dumps(card, ensure_ascii=True, default=str)
            documents.append(self._document(
                "layer3",
                "capability_design_card",
                card["id"],
                card["feature_name"],
                content,
                {
                    "status": card["review_state"],
                    "feature_id": card["feature_id"],
                    "owner_pillar_id": card["parent_pillar_id"],
                },
            ))
        for finding in self.db.list_research_findings(project_id):
            scope = finding.scope if finding.scope.startswith("layer") else "overall"
            content = json.dumps(finding.model_dump(mode="json"), ensure_ascii=True, default=str)
            documents.append(self._document(scope, "research_finding", finding.id, finding.title, content, {"scope_id": finding.scope_id}))
        return documents

    def _layer2_documents(self, project_id: str) -> list[dict[str, Any]]:
        """Build feature documents with graph, evidence, coverage, and shared-concern context attached."""
        relationships = self.db.list_layer2_relationships(project_id)
        evidence = self.db.list_layer2_feature_evidence(project_id)
        relationship_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        evidence_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for relation in relationships:
            payload = relation.model_dump(mode="json")
            relationship_map[relation.source_feature_id].append(payload)
            relationship_map[relation.target_feature_id].append(payload)
        for item in evidence:
            evidence_map[item.feature_id].append(item.model_dump(mode="json"))
        documents: list[dict[str, Any]] = []
        for feature in self.db.list_layer2_features(project_id):
            payload = feature.model_dump(mode="json")
            payload["relationships"] = relationship_map.get(feature.id, [])
            payload["competitor_evidence"] = evidence_map.get(feature.id, [])
            content = json.dumps(payload, ensure_ascii=True, default=str)
            metadata = {"status": feature.status, "owner_pillar_id": feature.owner_pillar_id, "feature_type": feature.feature_type}
            documents.append(self._document("layer2", "layer2_feature", feature.id, feature.canonical_name, content, metadata))
        for row in self.db.list_layer2_coverage_matrix(project_id):
            content = json.dumps(row.model_dump(mode="json"), ensure_ascii=True, default=str)
            documents.append(self._document("layer2", "coverage_family", row.id, row.family_name, content, {"pillar_id": row.pillar_id, "status": row.status}))
        for concern in self.db.list_layer2_shared_concern_clusters(project_id):
            content = json.dumps(concern.model_dump(mode="json"), ensure_ascii=True, default=str)
            documents.append(self._document("layer2", "shared_concern", concern.id, concern.name, content, {"concern_type": concern.concern_type, "status": concern.status}))
        return documents

    @staticmethod
    def _document(layer_scope: str, source_type: str, source_id: str, title: str, content: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """Create the normalized document shape expected by the persistence layer."""
        return {"layer_scope": layer_scope, "source_type": source_type, "source_id": source_id, "title": title, "content": content, "metadata": metadata}

    def _filter_entities(self, project_id: str, scope: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Apply bounded metadata filters over indexed entities without dynamic SQL."""
        source_type = str(arguments.get("source_type", ""))
        source_id = str(arguments.get("source_id", ""))
        status = str(arguments.get("status", ""))
        owner = str(arguments.get("owner_pillar_id", ""))
        rows = self.db.list_assistant_documents(project_id, layer_scope=scope)
        filtered = [
            row for row in rows
            if (not source_type or row["source_type"] == source_type)
            and (not source_id or row["source_id"] == source_id)
            and (not status or row["metadata"].get("status") == status)
            and (not owner or row["metadata"].get("owner_pillar_id") == owner)
        ]
        return filtered[: min(100, int(arguments.get("limit", 50)))]

    def _graph_neighbors(self, project_id: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Return bounded Layer 2 edges touching selected feature IDs."""
        feature_ids = {str(item) for item in arguments.get("feature_ids", [])}
        rows = [item.model_dump(mode="json") for item in self.db.list_layer2_relationships(project_id)]
        if feature_ids:
            rows = [row for row in rows if row["source_feature_id"] in feature_ids or row["target_feature_id"] in feature_ids]
        return rows[:100]

    def _coverage_gaps(self, project_id: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Return missing or partial Layer 2 coverage families for decision support."""
        pillar_ids = {str(item) for item in arguments.get("pillar_ids", [])}
        rows = self.db.list_layer2_coverage_matrix(project_id)
        return [
            row.model_dump(mode="json") for row in rows
            if row.status in {"missing", "partial"} and (not pillar_ids or row.pillar_id in pillar_ids)
        ][:100]

    def _research_evidence(self, project_id: str, scope: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Return cited research findings or Layer 2 competitor evidence for the requested scope."""
        if scope == "layer2":
            feature_ids = {str(item) for item in arguments.get("feature_ids", [])}
            evidence = self.db.list_layer2_feature_evidence(project_id)
            return [item.model_dump(mode="json") for item in evidence if not feature_ids or item.feature_id in feature_ids][:100]
        findings = self.db.list_research_findings(project_id)
        return [item.model_dump(mode="json") for item in findings if scope == "overall" or item.scope == scope][:50]

    def _embedding_model(self, project_id: str) -> str:
        """Resolve the project embedding profile dedicated to assistant retrieval."""
        settings = self.db.get_project_model_settings(project_id)
        if settings is None:
            return self.embedding_service.model_name
        return resolve_embedding_model_name(
            settings.model_dump(mode="json"),
            "assistant_embeddings",
            self.embedding_service.model_name,
        )

    def _embedding(self, text: str, model_name: str) -> list[float]:
        """Generate embeddings only for PostgreSQL retrieval; SQLite tests use lexical fallback."""
        if not self.db.is_postgres:
            return []
        return self.embedding_service.embed_text(text, model_name=model_name).vector

    @staticmethod
    def _content_hash(content: str) -> str:
        """Produce a stable cache key for incremental index refresh."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
