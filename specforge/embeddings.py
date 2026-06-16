from __future__ import annotations

import hashlib
from dataclasses import dataclass

import httpx
from huggingface_hub import close_session, set_client_factory
from sentence_transformers import SentenceTransformer

from specforge.config import AppConfig
from specforge.models import Node, SimilarityMatch


@dataclass(slots=True)
class EmbeddingResult:
    vector: list[float]
    content_hash: str


class EmbeddingService:
    """Generate local embeddings and query semantic overlap for saved nodes."""

    def __init__(self, config: AppConfig):
        self.config = config
        self._model: SentenceTransformer | None = None
        self._model_name = config.embeddings_model_name

    def enabled(self) -> bool:
        """Return whether embedding-backed similarity checks should run."""
        return self.config.embeddings_enabled

    @property
    def model_name(self) -> str:
        """Expose the configured embedding model name."""
        return self._model_name

    def set_model_name(self, model_name: str) -> None:
        """Switch the active embedding model and clear any cached weights."""
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("Embedding model name cannot be empty.")
        self._model_name = cleaned
        self.config.embeddings_model_name = cleaned
        self._model = None

    def ensure_model(self, model_name: str | None = None) -> SentenceTransformer:
        """Load the local embedding model lazily so startup stays fast until needed."""
        resolved_name = model_name.strip() if model_name else self._model_name
        if resolved_name == self._model_name:
            if self._model is None:
                self._model = self._load_model_with_fallback(self._model_name)
            return self._model
        return self._load_model_with_fallback(resolved_name)
        
    def embed_text(self, text: str, model_name: str | None = None) -> EmbeddingResult:
        """Embed a normalized text blob and return both vector and content hash."""
        normalized = self._normalize_text(text)
        resolved_name = model_name.strip() if model_name else self._model_name
        vector = self.ensure_model(resolved_name).encode(normalized, normalize_embeddings=True).tolist()
        return EmbeddingResult(vector=vector, content_hash=self._content_hash(normalized))

    def pillar_text(self, node_or_title: Node | str, description: str | None = None, payload: dict | None = None) -> str:
        """Build the canonical text block used for pillar embedding comparisons."""
        if isinstance(node_or_title, Node):
            title = node_or_title.title
            description = node_or_title.description
            payload = node_or_title.json_payload
        else:
            title = node_or_title
        payload = payload or {}
        tags = payload.get("tags", [])
        canonical = payload.get("canonical_title") or title
        why = payload.get("why_it_matters") or ""
        tag_blob = ", ".join(tags[:5]) if isinstance(tags, list) else ""
        return "\n".join(
            part
            for part in [
                f"title: {title}",
                f"canonical: {canonical}",
                f"description: {description or ''}",
                f"why_it_matters: {why}",
                f"tags: {tag_blob}",
            ]
            if part.strip()
        )

    def find_similar_pillars(
        self,
        *,
        db,
        project_id: str,
        embedding_model: str | None = None,
        embedding: list[float],
        exclude_node_ids: list[str] | None = None,
        min_similarity: float | None = None,
    ) -> list[SimilarityMatch]:
        """Find existing Layer 1 pillars that are cosine-similar to the supplied embedding."""
        return db.find_similar_nodes(
            project_id=project_id,
            embedding_model=embedding_model or self.model_name,
            embedding=embedding,
            layer=1,
            node_type="pillar",
            exclude_node_ids=exclude_node_ids,
            min_similarity=min_similarity if min_similarity is not None else self.config.pillar_similarity_threshold,
            limit=self.config.pillar_similarity_top_k,
        )

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Collapse whitespace so equivalent pillar payloads hash and embed consistently."""
        return " ".join(text.split())

    @staticmethod
    def _content_hash(text: str) -> str:
        """Create a stable hash for the embedded content to avoid unnecessary re-embeds."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _load_model_with_fallback(self, model_name: str) -> SentenceTransformer:
        """Load the embedding model, preconfiguring a relaxed HF client on this Windows setup when allowed."""
        if self.config.embeddings_insecure_download_fallback:
            set_client_factory(lambda: httpx.Client(verify=False, follow_redirects=True))
            close_session()
        return SentenceTransformer(model_name)
