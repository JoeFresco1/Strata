from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from rapidfuzz import fuzz

from specforge.llm import LLMError
from specforge.models import (
    Layer2Candidate,
    Layer2CandidateResponse,
    Layer2CoverageAssessmentResponse,
    Layer2CoverageFamilyDiscoveryResponse,
    Layer2GraphCriticResponse,
    Layer2IntegrityCriticResponse,
    Node,
)


class Layer2MemoryMixin:
    """Validation, prompt-memory, overlap, and affinity helpers for Layer 2."""

    @staticmethod
    def _validate_layer2_candidates(payload: dict[str, Any]) -> Layer2CandidateResponse:
        """Validate raw Layer 2 candidate JSON from a lens pass."""
        try:
            return Layer2CandidateResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid Layer 2 feature payload: {exc}") from exc

    @staticmethod
    def _validate_layer2_coverage(payload: dict[str, Any]) -> Layer2CoverageAssessmentResponse:
        """Validate Layer 2 coverage critic JSON."""
        try:
            return Layer2CoverageAssessmentResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid Layer 2 coverage assessment payload: {exc}") from exc

    @staticmethod
    def _validate_layer2_scope_discovery(payload: dict[str, Any]) -> Layer2CoverageFamilyDiscoveryResponse:
        """Validate the dynamic Layer 2 coverage-family discovery response."""
        try:
            return Layer2CoverageFamilyDiscoveryResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid Layer 2 scope discovery payload: {exc}") from exc

    @staticmethod
    def _validate_layer2_integrity(payload: dict[str, Any]) -> Layer2IntegrityCriticResponse:
        """Validate the batched Layer 2 integrity critic response."""
        try:
            return Layer2IntegrityCriticResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid Layer 2 integrity critic payload: {exc}") from exc

    @staticmethod
    def _validate_layer2_graph_critic(payload: dict[str, Any]) -> Layer2GraphCriticResponse:
        """Validate the batched Layer 2 graph critic response."""
        try:
            return Layer2GraphCriticResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid Layer 2 graph critic payload: {exc}") from exc

    def _approved_layer1_pillar(self, project_id: str, pillar_id: str) -> Node:
        """Return a user-approved Layer 1 pillar and reject unscoped descent targets."""
        pillar = self.db.get_node(pillar_id)
        if pillar.project_id != project_id or pillar.layer != 1 or pillar.node_type != "pillar":
            raise ValueError("Layer 2 can only descend into Layer 1 pillars from the active project.")
        if pillar.status not in {"kept", "prioritized"}:
            raise ValueError(f"Layer 1 pillar '{pillar.title}' must be kept or prioritized before Layer 2 generation.")
        return pillar

    def _layer2_feature_memory(
        self,
        project_id: str,
        *,
        owner_pillar_id: str | None = None,
        exclude_owner_pillar_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return compact feature memory for duplicate-aware Layer 2 prompts."""
        packet: list[dict[str, Any]] = []
        for feature in self.db.list_layer2_features(project_id):
            if owner_pillar_id is not None and feature.owner_pillar_id != owner_pillar_id:
                continue
            if exclude_owner_pillar_id is not None and feature.owner_pillar_id == exclude_owner_pillar_id:
                continue
            packet.append(
                {
                    "title": feature.canonical_name,
                    "description": feature.description,
                    "tags": [feature.feature_type, feature.status],
                    "fingerprint": " | ".join(feature.aliases),
                }
            )
        return packet[:40]

    @staticmethod
    def _layer2_feature_to_memory(feature: Any) -> dict[str, Any]:
        """Format a Layer 2 feature for scoped coverage assessment prompts."""
        metadata = feature.metadata or {}
        return {
            "id": feature.id,
            "title": feature.canonical_name,
            "description": feature.description,
            "tags": [
                feature.feature_type,
                feature.status,
                str(metadata.get("coverage_family", "")),
                str(metadata.get("scope_classification", "")),
            ],
            "fingerprint": metadata.get("pillar_fit_rationale") or " | ".join(feature.aliases),
        }

    def _layer2_negative_cache_memory(self, project_id: str) -> list[str]:
        """Return rejected Layer 2 concepts as prompt-ready negative memory."""
        entries = self.db.list_layer2_negative_cache(project_id)
        return [
            f"{entry.rejected_name} | cluster: {entry.semantic_cluster} | aliases: {', '.join(entry.rejected_aliases)}"
            for entry in entries[:40]
        ]

    @staticmethod
    def _layer2_candidate_status(candidate: Layer2Candidate, negative_match: bool) -> str:
        """Route risky candidates into human review without dropping their provenance."""
        if (
            negative_match
            or candidate.implementation_leakage_score >= 45
            or candidate.pillar_fit_score < 60
            or candidate.scope_classification != "in_scope"
        ):
            return "needs_review"
        return "candidate"

    def _layer2_feature_metadata(
        self,
        candidate: Layer2Candidate,
        selected_pillars: list[Node],
        owner_pillar_id: str,
        lens_name: str,
        source_model: str,
        negative_match: bool,
        negative_reason: str,
    ) -> dict[str, Any]:
        """Build feature metadata that is useful in the review UI and export payload."""
        return {
            "source_lens": lens_name,
            "source_model": source_model,
            "coverage_family": candidate.coverage_family,
            "scope_classification": candidate.scope_classification,
            "pillar_fit_rationale": candidate.pillar_fit_rationale,
            "scope_drift_flag": candidate.scope_classification != "in_scope",
            "negative_cache_match": negative_match,
            "negative_cache_reason": negative_reason,
            "recommended_owner_pillar_id": self._recommended_owner_pillar_id(
                candidate,
                selected_pillars,
                fallback_id=owner_pillar_id,
            ),
        }

    def _find_layer2_overlap(
        self,
        project_id: str,
        candidate: Layer2Candidate,
        *,
        exclude_feature_ids: list[str] | None = None,
    ) -> tuple[Any | None, float]:
        """Find the strongest existing Layer 2 duplicate candidate without deleting either record."""
        best_feature = None
        best_score = 0.0
        candidate_text = f"{candidate.canonical_name} {candidate.description} {' '.join(candidate.aliases)}"
        excluded = set(exclude_feature_ids or [])
        for feature in self.db.list_layer2_features(project_id):
            if feature.id in excluded:
                continue
            feature_text = f"{feature.canonical_name} {feature.description} {' '.join(feature.aliases)}"
            score = fuzz.token_set_ratio(candidate_text.lower(), feature_text.lower()) / 100
            if score > best_score:
                best_feature = feature
                best_score = score
        if best_feature is not None and best_score >= 0.86:
            return best_feature, round(best_score, 3)
        return None, round(best_score, 3)

    @staticmethod
    def _safe_layer2_feature_type(feature_type: str) -> str:
        """Normalize model-provided feature types into a stable small vocabulary."""
        allowed = {
            "workflow",
            "automation",
            "admin_control",
            "compliance",
            "data_requirement",
            "integration",
            "reporting",
            "notification",
            "capability",
        }
        cleaned = feature_type.strip().lower().replace(" ", "_")
        return cleaned if cleaned in allowed else "capability"

    @staticmethod
    def _valid_related_pillar_ids(related_pillar_ids: list[str], allowed_pillar_ids: list[str]) -> list[str]:
        """Keep only related-pillar ids that belong to the selected Layer 2 scope."""
        allowed = set(allowed_pillar_ids)
        return [pillar_id for pillar_id in related_pillar_ids if pillar_id in allowed]

    def _recommended_owner_pillar_id(
        self,
        candidate: Layer2Candidate,
        pillars: list[Node],
        *,
        fallback_id: str,
    ) -> str:
        """Pick the pillar with the strongest lexical affinity while preserving user-overridable ownership."""
        best_id = fallback_id
        best_score = 0.0
        text = f"{candidate.canonical_name} {candidate.description}".lower()
        for pillar in pillars:
            score = fuzz.token_set_ratio(text, f"{pillar.title} {pillar.description or ''}".lower()) / 100
            if score > best_score:
                best_id = pillar.id
                best_score = score
        return best_id

    def _store_layer2_affinities(
        self,
        project_id: str,
        feature_id: str,
        candidate: Layer2Candidate,
        pillars: list[Node],
        owner_pillar_id: str,
    ) -> None:
        """Persist feature-to-pillar affinity scores for later owner reassignment review."""
        recommended_owner = self._recommended_owner_pillar_id(candidate, pillars, fallback_id=owner_pillar_id)
        text = f"{candidate.canonical_name} {candidate.description}".lower()
        for pillar in pillars:
            lexical_score = fuzz.token_set_ratio(text, f"{pillar.title} {pillar.description or ''}".lower()) / 100
            owner_bonus = 0.12 if pillar.id == owner_pillar_id else 0.0
            score = min(1.0, round(lexical_score + owner_bonus, 3))
            self.db.insert_layer2_affinity(
                project_id=project_id,
                feature_id=feature_id,
                pillar_id=pillar.id,
                affinity_score=score,
                recommended_owner_pillar_id=recommended_owner,
            )
