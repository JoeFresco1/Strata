from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from strata.layer2_constants import (
    LAYER2_GRAPH_CRITIC_SCHEMA,
    LAYER2_INTEGRITY_SCHEMA,
    LAYER2_SCOPE_DISCOVERY_SCHEMA,
)
from strata.llm import LLMError
from strata.models import (
    Layer2Candidate,
    Layer2CoverageFamilyDiscoveryResponse,
    Layer2GraphCriticResponse,
    Layer2IntegrityCriticResponse,
    PillarScopeContract,
    Node,
)
from strata.prompts import (
    build_layer2_graph_critic_prompt,
    build_layer2_integrity_critic_prompt,
    build_layer2_scope_discovery_prompt,
)
from strata.critic_policy import CriticAuthorityPolicy, CriticDisposition


class Layer2CriticMixin:
    """Scope discovery, integrity critic, graph critic, and shared-concern routing."""

    def _discover_layer2_scope_contract(
        self,
        *,
        project_id: str,
        pillar: Node,
        product_idea: str,
        prompt_catalog: dict[str, str],
        runtime_profile: dict[str, Any],
    ) -> PillarScopeContract:
        """Run the dynamic pre-pass that defines pillar boundaries and coverage families."""
        existing = self.db.get_project_memory(
            project_id=project_id,
            scope="layer2",
            scope_id=pillar.id,
            memory_type="scope_contract",
        )
        if existing:
            try:
                return PillarScopeContract.model_validate(existing.content)
            except ValidationError:
                pass
        project_pillars = [
            {"title": node.title, "description": node.description or "", "tags": [node.status], "fingerprint": node.id}
            for node in self.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
        ]
        prompt = build_layer2_scope_discovery_prompt(
            product_idea=product_idea,
            pillar_title=pillar.title,
            pillar_description=pillar.description or "",
            project_pillars=project_pillars,
            prompt_catalog=prompt_catalog,
        )
        try:
            _, discovery = self._call_structured_json_pass(
                project_id=project_id,
                node_id=pillar.id,
                prompt=prompt,
                runtime_profile=runtime_profile,
                max_tokens=1800,
                temperature=0.2,
                validator=self._validate_layer2_scope_discovery,
                schema_label="layer2_scope_discovery",
                schema_instructions=LAYER2_SCOPE_DISCOVERY_SCHEMA,
            )
            if not isinstance(discovery, Layer2CoverageFamilyDiscoveryResponse):
                raise LLMError("Scope discovery returned the wrong response schema.")
            families = [self._safe_family_name(item.name) for item in discovery.coverage_families if item.name.strip()]
            out_of_bounds = sorted(
                {
                    anti_example
                    for family in discovery.coverage_families
                    for anti_example in family.anti_examples
                    if anti_example.strip()
                }
            )
        except LLMError:
            fallback = self._layer2_family_definitions(pillar)
            families = [family_id for family_id, _ in fallback]
            out_of_bounds = []
        contract = PillarScopeContract(
            pillar_id=pillar.id,
            allowed_core_domains=families,
            explicit_out_of_bounds=out_of_bounds,
            discovered_coverage_families=families,
        )
        self.db.upsert_project_memory(
            project_id=project_id,
            scope="layer2",
            scope_id=pillar.id,
            memory_type="scope_contract",
            content=contract.model_dump(mode="json"),
        )
        return contract

    def _initialize_layer2_coverage_matrix(self, project_id: str, pillar_id: str, families: list[str]) -> None:
        """Ensure each discovered family starts with a durable missing-state matrix row."""
        for family in families:
            existing = [
                row for row in self.db.list_layer2_coverage_matrix(project_id, pillar_id=pillar_id)
                if row.family_name == family
            ]
            if existing:
                continue
            self.db.upsert_layer2_coverage_matrix_row(
                project_id=project_id,
                pillar_id=pillar_id,
                family_name=family,
                status="missing",
            )

    def _run_layer2_integrity_critic(
        self,
        *,
        project_id: str,
        pillar_id: str,
        runtime_profile: dict[str, Any],
        product_idea: str,
        prompt_catalog: dict[str, str],
        scope_contract: PillarScopeContract,
        raw_pairs: list[tuple[Any, Layer2Candidate]],
    ) -> Layer2IntegrityCriticResponse:
        """Run one batched integrity critic pass for a raw candidate batch."""
        prompt = build_layer2_integrity_critic_prompt(
            product_idea=product_idea,
            scope_contract=scope_contract.model_dump(mode="json"),
            normalized_features=[
                {
                    "candidate_id": raw.id,
                    "canonical_name": candidate.canonical_name,
                    "description": candidate.description,
                    "feature_type": candidate.feature_type,
                    "coverage_family": candidate.coverage_family,
                    "scope_classification": candidate.scope_classification,
                    "negative_cache_context": raw.payload.get("negative_cache_context", {}),
                }
                for raw, candidate in raw_pairs
            ],
            prompt_catalog=prompt_catalog,
        )
        try:
            _, response = self._call_structured_json_pass(
                project_id=project_id,
                node_id=pillar_id,
                prompt=prompt,
                runtime_profile=runtime_profile,
                max_tokens=1800,
                temperature=0.1,
                validator=self._validate_layer2_integrity,
                schema_label="layer2_integrity_critic",
                schema_instructions=LAYER2_INTEGRITY_SCHEMA,
            )
        except LLMError:
            return Layer2IntegrityCriticResponse()
        return response if isinstance(response, Layer2IntegrityCriticResponse) else Layer2IntegrityCriticResponse()

    def _run_layer2_graph_critic(
        self,
        *,
        project_id: str,
        runtime_profile: dict[str, Any],
        product_idea: str,
        prompt_catalog: dict[str, str],
        current_feature_ids: list[str],
    ) -> Layer2GraphCriticResponse:
        """Run one batched graph critic pass for the current round features."""
        current_ids = set(current_feature_ids)
        all_features = [self._layer2_feature_to_memory(feature) for feature in self.db.list_layer2_features(project_id)]
        prompt = build_layer2_graph_critic_prompt(
            product_idea=product_idea,
            current_round_features=[item for item in all_features if item["id"] in current_ids],
            existing_project_features=[item for item in all_features if item["id"] not in current_ids],
            prompt_catalog=prompt_catalog,
        )
        try:
            _, response = self._call_structured_json_pass(
                project_id=project_id,
                node_id=None,
                prompt=prompt,
                runtime_profile=runtime_profile,
                max_tokens=2200,
                temperature=0.1,
                validator=self._validate_layer2_graph_critic,
                schema_label="layer2_graph_critic",
                schema_instructions=LAYER2_GRAPH_CRITIC_SCHEMA,
            )
        except LLMError:
            return Layer2GraphCriticResponse()
        return response if isinstance(response, Layer2GraphCriticResponse) else Layer2GraphCriticResponse()

    def _apply_layer2_graph_directives(self, project_id: str, graph_critic: Layer2GraphCriticResponse, stats: dict[str, Any]) -> None:
        """Persist graph critic directives as reviewable relationships and shared concerns."""
        feature_ids = {feature.id for feature in self.db.list_layer2_features(project_id)}
        policy = CriticAuthorityPolicy(self.db)
        for merge in graph_critic.duplicate_merges:
            if merge.source_feature_id not in feature_ids or merge.target_feature_id not in feature_ids:
                continue
            stats["duplicate_recommendations"] += 1
            source_feature = self.db.get_layer2_feature(merge.source_feature_id)
            authority = policy.evaluate(
                project_id=project_id, artifact_type="layer2_feature", artifact_id=merge.source_feature_id,
                current_review_state=source_feature.status, current_actor="model", current_origin="model_critic",
                proposed_action="recommend_merge", source_freshness="unknown",
                is_new_unreviewed_candidate=source_feature.status == "candidate",
            )
            target_feature = self.db.get_layer2_feature(merge.target_feature_id)
            target_authority = policy.evaluate(
                project_id=project_id, artifact_type="layer2_feature", artifact_id=merge.target_feature_id,
                current_review_state=target_feature.status, current_actor="model", current_origin="model_critic",
                proposed_action="recommend_merge", source_freshness="unknown",
                is_new_unreviewed_candidate=target_feature.status == "candidate",
            )
            if any(result.disposition != CriticDisposition.AUTOMATIC_ROUTING for result in (authority, target_authority)):
                finding_targets = {merge.source_feature_id}
                if target_authority.disposition != CriticDisposition.AUTOMATIC_ROUTING:
                    finding_targets.add(merge.target_feature_id)
                for feature_id in finding_targets:
                    self.db.create_critic_finding(
                        project_id=project_id, artifact_type="layer2_feature", artifact_id=feature_id,
                        critic_type="layer2_graph_critic", category="duplicate_merge", severity="high",
                        explanation=merge.reason, evidence=merge.model_dump(mode="json"),
                        recommended_action="Review the proposed duplicate merge.", source_payload=merge.model_dump(mode="json"),
                    )
                continue
            self.db.insert_layer2_relationship(
                project_id=project_id,
                source_feature_id=merge.source_feature_id,
                target_feature_id=merge.target_feature_id,
                relationship_type="duplicate_of",
                strength=merge.confidence,
                rationale=merge.reason,
            )
            feature = self.db.get_layer2_feature(merge.source_feature_id)
            self.db.update_layer2_feature(feature.id, status="needs_review", metadata={**feature.metadata, "graph_critic_duplicate": True})
            self.db.record_layer2_review_action(
                project_id=project_id,
                feature_id=merge.source_feature_id,
                action_type="merge",
                payload={"source": "graph_critic", "recommended_target_feature_id": merge.target_feature_id, "reason": merge.reason, "confidence": merge.confidence},
            )
        for dependency in graph_critic.cross_pillar_dependencies:
            if dependency.source_feature_id not in feature_ids or dependency.target_feature_id not in feature_ids:
                continue
            protected_ids = []
            for feature_id in (dependency.source_feature_id, dependency.target_feature_id):
                feature = self.db.get_layer2_feature(feature_id)
                authority = policy.evaluate(
                    project_id=project_id, artifact_type="layer2_feature", artifact_id=feature_id,
                    current_review_state=feature.status, current_actor="model", current_origin="model_critic",
                    proposed_action="recommend_relationship", source_freshness="unknown",
                    is_new_unreviewed_candidate=feature.status == "candidate",
                )
                if authority.disposition != CriticDisposition.AUTOMATIC_ROUTING:
                    protected_ids.append(feature_id)
            if protected_ids:
                for feature_id in protected_ids:
                    self.db.create_critic_finding(
                        project_id=project_id, artifact_type="layer2_feature", artifact_id=feature_id,
                        critic_type="layer2_graph_critic", category="cross_pillar_dependency", severity="medium",
                        explanation=dependency.reason, evidence=dependency.model_dump(mode="json"),
                        recommended_action="Review the proposed dependency relationship.", source_payload=dependency.model_dump(mode="json"),
                    )
                continue
            self.db.insert_layer2_relationship(
                project_id=project_id,
                source_feature_id=dependency.source_feature_id,
                target_feature_id=dependency.target_feature_id,
                relationship_type=dependency.relationship_type,
                strength=dependency.confidence,
                rationale=dependency.reason,
            )
        for concern in graph_critic.detected_shared_concerns:
            connected_ids = [feature_id for feature_id in concern.connected_feature_ids if feature_id in feature_ids]
            self._route_layer2_shared_concern(
                project_id=project_id,
                name=concern.name,
                concern_type=concern.concern_type,
                connected_feature_ids=connected_ids,
            )

    def _route_layer2_shared_concern(
        self,
        *,
        project_id: str,
        name: str,
        concern_type: str,
        connected_feature_ids: list[str],
    ) -> None:
        """Store shared concerns outside the standard pillar-owned feature tree."""
        self.db.upsert_layer2_shared_concern_cluster(
            project_id=project_id,
            name=name.strip() or concern_type,
            concern_type=concern_type,
            connected_feature_ids=connected_feature_ids,
            status="flagged",
        )

    def _layer2_semantic_negative_cache_veto(self, project_id: str, candidate: Layer2Candidate) -> dict[str, Any] | None:
        """Apply semantic negative-cache veto rules before canonical feature creation."""
        candidate_text = f"{candidate.canonical_name} {candidate.description} {' '.join(candidate.aliases)}"
        embedding_model = self._embedding_model_name(project_id, "layer1_similarity_embeddings")
        embedding = self._layer2_embedding(candidate_text, embedding_model)
        return self.db.find_layer2_negative_cache_match(
            project_id=project_id,
            candidate_text=candidate_text,
            embedding_model=embedding_model,
            embedding=embedding,
        )

    def _layer2_embedding(self, text: str, embedding_model: str) -> list[float] | None:
        """Generate a Layer 2 semantic embedding when the embedding service is available."""
        if self.embedding_service is None or not self.embedding_service.enabled() or not embedding_model:
            return None
        try:
            return self.embedding_service.embed_text(text, embedding_model).embedding
        except Exception:
            return None

    @staticmethod
    def _safe_family_name(value: str) -> str:
        """Normalize model-provided coverage family names into stable ids."""
        cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_") or "general_capability"

    @staticmethod
    def _infer_shared_concern_type(candidate: Layer2Candidate) -> str:
        """Map a shared-concern candidate to the closest supported concern type."""
        text = f"{candidate.canonical_name} {candidate.description} {candidate.coverage_family}".lower()
        mapping = {
            "ingestion": ("ingest", "import", "intake", "sync"),
            "validation": ("valid", "quality", "constraint"),
            "permissions": ("permission", "role", "access", "auth"),
            "notifications": ("notification", "alert", "reminder", "message"),
            "audit_logging": ("audit", "log", "trace"),
            "templates": ("template", "reuse", "library"),
            "workflow_state": ("workflow", "state", "status", "approval"),
            "reporting": ("report", "analytics", "export", "dashboard"),
        }
        for concern_type, terms in mapping.items():
            if any(term in text for term in terms):
                return concern_type
        return "workflow_state"
