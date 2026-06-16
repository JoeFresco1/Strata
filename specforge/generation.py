from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError
from rapidfuzz import fuzz

from specforge.config import ModelProfile
from specforge.db import Database
from specforge.dedupe import detect_possible_duplicates
from specforge.embeddings import EmbeddingResult, EmbeddingService
from specforge.llm import LLMError, LlamaCppClient
from specforge.models import (
    CriticResponse,
    Node,
    PillarAssessment,
    PillarAssessmentResponse,
    PillarResponse,
    SimilarityMatch,
    SpecResponse,
    SubfeatureResponse,
)
from specforge.project_settings import embedding_profiles_by_id, llm_profiles_by_id
from specforge.prompts import (
    build_system_prompt,
    build_critic_prompt,
    build_json_repair_prompt,
    build_pillar_assessment_prompt,
    build_pillar_normalization_prompt,
    build_pillar_prompt,
    build_spec_prompt,
    build_subfeature_prompt,
    load_prompt_catalog,
)
from specforge.server_manager import LlamaServerManager, ServerManagerError
from specforge.tree import collect_approved_directions


LAYER1_LENSES: list[tuple[str, str]] = [
    (
        "Core Outcomes",
        "Explore the primary user outcomes and big problem domains the product must solve end to end.",
    ),
    (
        "Operations and Administration",
        "Look for major administrative, configuration, operational control, and internal management pillar areas.",
    ),
    (
        "Analytics and Reporting",
        "Focus on major insight, diagnostics, measurement, reporting, and decision-support pillar concepts.",
    ),
    (
        "Onboarding and Adoption",
        "Focus on major setup, adoption, education, trust-building, and long-term usage enablement pillars.",
    ),
    (
        "Risk and Exception Handling",
        "Focus on major exception management, unusual situations, safety, compliance, privacy, and failure-mode pillars.",
    ),
    (
        "Data and Integrations",
        "Focus on major data intake, normalization, interoperability, integrations, and system connectivity pillars.",
    ),
]

PILLAR_RESPONSE_SCHEMA = """{
  "pillars": [
    {
      "title": "...",
      "description": "...",
      "why_it_matters": "...",
      "risks": ["..."],
      "tags": ["..."]
    }
  ]
}"""

PILLAR_ASSESSMENT_SCHEMA = """{
  "assessments": [
    {
      "title": "...",
      "canonical_title": "...",
      "cluster_id": "...",
      "is_true_pillar": true,
      "distinctiveness_score": 0,
      "strategic_value_score": 0,
      "pillar_quality_score": 0,
      "too_narrow": false,
      "too_implementation_specific": false,
      "too_broad_generic": false,
      "merge_into": null,
      "rename_to": null,
      "sharpen_to": null,
      "rationale": "...",
      "recommended_next_lens": null
    }
  ]
}"""

CRITIC_SCHEMA = """{
  "coverage_summary": "...",
  "overlap_clusters": [["item a", "item b"]],
  "uncovered_areas": [{"title": "...", "reason": "..."}],
  "saturation_signal": "low | medium | high",
  "novelty_score": 0,
  "continue_recommendation": true,
  "reasoning": "...",
  "recommended_next_lens": "..."
}"""


@dataclass(slots=True)
class IterativeGenerationSummary:
    created_nodes: list[Node]
    total_rounds: int
    duplicate_candidates: int
    filtered_candidates: int
    unique_family_count: int
    stop_reason: str
    per_round_new_counts: list[int]
    per_round_new_family_counts: list[int]
    final_coverage_summary: str
    final_novelty_score: int | None
    lenses_used: list[str]
    models_used: list[str]
    round_summaries: list[str]
    thinking_enabled: bool


@dataclass(slots=True)
class Layer1MemoryChannels:
    user_rejected_ideas: list[str]
    user_approved_directions: list[str]
    persisted_pillars: list[dict[str, Any]]
    persisted_families: list[str]
    critic_coverage_summary: str
    critic_uncovered_areas: list[str]
    critic_recommended_lens: str | None


@dataclass(slots=True)
class Layer1RoundContext:
    siblings: list[Node]
    coverage_memory: Any
    memory_channels: Layer1MemoryChannels
    lens_name: str
    lens_instruction: str
    model_role: str
    role_instruction: str
    advisory_lens: str | None


@dataclass(slots=True)
class Layer1RoundOutcome:
    created_nodes: list[Node]
    duplicate_count: int
    filtered_count: int
    new_family_keys: set[str]


class GenerationService:
    def __init__(
        self,
        db: Database,
        llm_client: LlamaCppClient,
        server_manager: LlamaServerManager | None = None,
        embedding_service: EmbeddingService | None = None,
    ):
        self.db = db
        self.llm_client = llm_client
        self.server_manager = server_manager
        self.embedding_service = embedding_service

    def _prompt_catalog(self, project_id: str) -> dict[str, str]:
        """Resolve the prompt catalog snapshot stored for this project."""
        settings = self.db.get_project_model_settings(project_id)
        if settings is not None and settings.prompt_catalog:
            return settings.prompt_catalog
        return load_prompt_catalog()

    def _system_prompt(self, project_id: str) -> str:
        """Build the system prompt from the project-scoped prompt catalog."""
        return build_system_prompt(prompt_catalog=self._prompt_catalog(project_id))

    def generate_pillars(self, project_id: str) -> list[Node]:
        summary = self.generate_pillars_until_exhausted(project_id)
        return summary.created_nodes

    def generate_pillars_until_exhausted(
        self,
        project_id: str,
        *,
        model_profiles: list[ModelProfile] | None = None,
        thinking_enabled: bool = False,
        max_rounds: int = 6,
        target_per_round: int = 12,
        min_new_items_per_round: int = 2,
        stale_rounds_to_stop: int = 2,
    ) -> IterativeGenerationSummary:
        product_idea = self._published_product_idea(project_id)
        created_nodes: list[Node] = []
        duplicate_candidates = 0
        filtered_candidates = 0
        per_round_new_counts: list[int] = []
        per_round_new_family_counts: list[int] = []
        stale_rounds = 0
        stale_family_rounds = 0
        stop_reason = "max_rounds_reached"
        final_coverage_summary = ""
        final_novelty_score: int | None = None
        lenses_used: list[str] = []
        models_used: list[str] = []
        round_summaries: list[str] = []
        active_profiles = self._resolve_layer1_profiles(project_id, model_profiles)
        prompt_catalog = self._prompt_catalog(project_id)

        round_index = 0
        stop_all_models = False
        for profile in active_profiles:
            if stop_all_models:
                break
            models_used.append(str(profile["label"]))
            self._ensure_profile_loaded(profile, thinking_enabled=thinking_enabled)
            stale_rounds = 0
            for _ in range(max_rounds):
                # Layer 1 deliberately runs as a multi-pass agentic loop:
                # 1) generate broadly, 2) normalize to stable pillar concepts,
                # 3) assess and prune before anything reaches the tree.
                context = self._build_layer1_round_context(
                    project_id=project_id,
                    profile=profile,
                    created_nodes=created_nodes,
                    models_used=models_used,
                    round_index=round_index,
                )
                round_index += 1
                lenses_used.append(f"{profile['label']}: {context.lens_name}")
                prompt = build_pillar_prompt(
                    product_idea,
                    context.memory_channels.user_rejected_ideas,
                    context.memory_channels.user_approved_directions,
                    context.memory_channels.persisted_pillars,
                    context.memory_channels.persisted_families,
                    context.memory_channels.critic_coverage_summary,
                    context.memory_channels.critic_uncovered_areas,
                    context.advisory_lens,
                    context.lens_name,
                    context.lens_instruction,
                    context.model_role,
                    context.role_instruction,
                    target_count=target_per_round,
                    prompt_catalog=prompt_catalog,
                )
                _, raw_parsed = self._call_structured_json_pass(
                    project_id=project_id,
                    node_id=None,
                    prompt=prompt,
                    runtime_profile=profile,
                    max_tokens=2200,
                    validator=self._validate_pillars,
                    schema_label="pillar_response",
                    schema_instructions=PILLAR_RESPONSE_SCHEMA,
                )
                normalized = self._normalize_pillars(
                    project_id=project_id,
                    product_idea=product_idea,
                    lens_name=context.lens_name,
                    existing_pillars=context.memory_channels.persisted_pillars,
                    raw_pillars=raw_parsed.pillars,
                    runtime_profile=profile,
                )
                assessments = self._assess_pillars(
                    project_id=project_id,
                    product_idea=product_idea,
                    existing_pillars=context.memory_channels.persisted_pillars,
                    candidate_pillars=normalized.pillars,
                    runtime_profile=profile,
                )
                outcome = self._persist_layer1_round(
                    project_id=project_id,
                    siblings=context.siblings,
                    created_nodes=created_nodes,
                    normalized_pillars=normalized.pillars,
                    assessments=assessments.assessments,
                    source_model=str(profile["label"]),
                    source_lens=context.lens_name,
                )

                created_nodes.extend(outcome.created_nodes)
                duplicate_candidates += outcome.duplicate_count
                filtered_candidates += outcome.filtered_count
                per_round_new_counts.append(len(outcome.created_nodes))
                per_round_new_family_counts.append(len(outcome.new_family_keys))

                critic = self._run_critic(
                    project_id=project_id,
                    scope="layer1",
                    scope_id=None,
                    layer_name="Layer 1 Feature Pillars",
                    product_idea=product_idea,
                    parent_context=f"Top-level product decomposition | model phase: {profile['label']}",
                    existing_nodes=context.siblings,
                    new_nodes=outcome.created_nodes,
                    runtime_profile=profile,
                )
                final_coverage_summary = critic.coverage_summary
                final_novelty_score = critic.novelty_score
                round_summaries.append(
                    self._format_layer1_round_summary(
                        profile_name=str(profile["label"]),
                        lens_name=context.lens_name,
                        created_count=len(outcome.created_nodes),
                        new_family_count=len(outcome.new_family_keys),
                        duplicate_count=outcome.duplicate_count,
                        filtered_count=outcome.filtered_count,
                        novelty_score=critic.novelty_score,
                        saturation_signal=critic.saturation_signal,
                    )
                )

                if len(outcome.created_nodes) < min_new_items_per_round:
                    stale_rounds += 1
                else:
                    stale_rounds = 0
                if len(outcome.new_family_keys) == 0:
                    stale_family_rounds += 1
                else:
                    stale_family_rounds = 0

                stop_reason, stop_all_models = self._layer1_stop_decision(
                    critic=critic,
                    profile=profile,
                    normalized_count=len(normalized.pillars),
                    created_count=len(outcome.created_nodes),
                    duplicate_count=outcome.duplicate_count,
                    stale_rounds=stale_rounds,
                    stale_family_rounds=stale_family_rounds,
                    stale_rounds_to_stop=stale_rounds_to_stop,
                )
                if stop_reason != "continue":
                    break

        return IterativeGenerationSummary(
            created_nodes=created_nodes,
            total_rounds=len(per_round_new_counts),
            duplicate_candidates=duplicate_candidates,
            filtered_candidates=filtered_candidates,
            unique_family_count=len(self._existing_pillar_family_keys(self.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar"))),
            stop_reason=stop_reason,
            per_round_new_counts=per_round_new_counts,
            per_round_new_family_counts=per_round_new_family_counts,
            final_coverage_summary=final_coverage_summary,
            final_novelty_score=final_novelty_score,
            lenses_used=lenses_used,
            models_used=models_used,
            round_summaries=round_summaries,
            thinking_enabled=thinking_enabled,
        )

    def _build_layer1_round_context(
        self,
        *,
        project_id: str,
        profile: dict[str, Any],
        created_nodes: list[Node],
        models_used: list[str],
        round_index: int,
    ) -> Layer1RoundContext:
        siblings = self.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
        self._ensure_pillar_embeddings(project_id, siblings)
        coverage_memory = self.db.get_project_memory(
            project_id=project_id,
            scope="layer1",
            scope_id=None,
            memory_type="coverage",
        )
        model_role, role_instruction = self._layer1_model_role(profile, models_used)
        lens_name, lens_instruction = self._layer1_lens_for_round(round_index, model_role=model_role)
        advisory_lens = self._critic_advisory_lens(coverage_memory)
        return Layer1RoundContext(
            siblings=siblings,
            coverage_memory=coverage_memory,
            memory_channels=self._layer1_memory_channels(
                project_id=project_id,
                siblings=siblings,
                created_nodes=created_nodes,
                coverage_memory=coverage_memory,
                model_role=model_role,
            ),
            lens_name=lens_name,
            lens_instruction=lens_instruction,
            model_role=model_role,
            role_instruction=role_instruction,
            advisory_lens=advisory_lens,
        )

    def _persist_layer1_round(
        self,
        *,
        project_id: str,
        siblings: list[Node],
        created_nodes: list[Node],
        normalized_pillars: list[Any],
        assessments: list[PillarAssessment],
        source_model: str,
        source_lens: str,
    ) -> Layer1RoundOutcome:
        round_created: list[Node] = []
        round_duplicates = 0
        round_filtered = 0
        existing_family_keys = self._existing_pillar_family_keys(siblings + created_nodes)
        round_family_keys: set[str] = set()

        for pillar in normalized_pillars:
            assessment = self._assessment_for_pillar(pillar.title, assessments)
            filter_reason = self._layer1_filter_reason(assessment)
            if filter_reason is not None:
                round_filtered += 1
                self._record_layer1_quarantine(
                    project_id=project_id,
                    pillar=pillar.model_dump(),
                    reason=filter_reason,
                    assessment=assessment.model_dump(mode="json") if assessment is not None else None,
                    source_model=source_model,
                    source_lens=source_lens,
                )
                continue

            candidate_title = self._candidate_pillar_title(pillar.title, assessment)
            family_key = self._pillar_family_key(candidate_title, assessment)
            if family_key in existing_family_keys:
                round_duplicates += 1
                continue

            payload = self._layer1_payload(pillar.model_dump(), assessment, source_model, source_lens)
            lexical_duplicate = detect_possible_duplicates(
                existing_nodes=siblings + created_nodes + round_created,
                title=candidate_title,
                description=pillar.description,
            )
            if lexical_duplicate:
                payload["lexical_similarity"] = lexical_duplicate

            embedding_result, similarity_matches = self._pillar_similarity_result(
                project_id=project_id,
                title=candidate_title,
                description=pillar.description,
                payload=payload,
            )
            if self._should_block_on_semantic_overlap(similarity_matches):
                round_duplicates += 1
                self._record_layer1_quarantine(
                    project_id=project_id,
                    pillar=pillar.model_dump(),
                    reason="semantic_overlap_blocked",
                    assessment=assessment.model_dump(mode="json") if assessment is not None else None,
                    source_model=source_model,
                    source_lens=source_lens,
                )
                continue

            if similarity_matches:
                payload["semantic_similarity"] = self._semantic_similarity_payload(similarity_matches)
            existing_family_keys.add(family_key)
            round_family_keys.add(family_key)
            created_node = self.db.create_node(
                project_id=project_id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title=candidate_title,
                description=pillar.description,
                json_payload=payload,
            )
            self._store_pillar_embedding(project_id, created_node, embedding_result)
            round_created.append(created_node)

        return Layer1RoundOutcome(
            created_nodes=round_created,
            duplicate_count=round_duplicates,
            filtered_count=round_filtered,
            new_family_keys=round_family_keys,
        )

    def _should_block_on_semantic_overlap(self, matches: list[SimilarityMatch]) -> bool:
        """Use embeddings as the primary Layer 1 overlap gate once canonical-family checks have already run."""
        if not matches:
            return False
        return matches[0].score >= self.embedding_service.config.pillar_similarity_block_threshold if self.embedding_service is not None else False

    def _layer1_memory_channels(
        self,
        *,
        project_id: str,
        siblings: list[Node],
        created_nodes: list[Node],
        coverage_memory: Any,
        model_role: str,
    ) -> Layer1MemoryChannels:
        """Build source-typed Layer 1 memory so later models can distinguish hard constraints from advisory inferences."""
        all_nodes = self.db.list_all_nodes(project_id)
        persisted_nodes = siblings if model_role == "Explorer" else self._challenger_visible_pillars(siblings)
        return Layer1MemoryChannels(
            user_rejected_ideas=self.db.get_rejected_ideas(project_id),
            user_approved_directions=collect_approved_directions(all_nodes),
            persisted_pillars=self._representative_pillar_memory(persisted_nodes),
            persisted_families=self._covered_family_titles(siblings + created_nodes),
            critic_coverage_summary=self._coverage_summary(coverage_memory),
            critic_uncovered_areas=self._uncovered_titles(coverage_memory),
            critic_recommended_lens=self._critic_advisory_lens(coverage_memory),
        )

    @staticmethod
    def _challenger_visible_pillars(nodes: list[Node]) -> list[Node]:
        """Show challenger rounds a thinner slice of saved pillar state so they are less anchored to the current frame."""
        if len(nodes) <= 12:
            return nodes
        return [node for index, node in enumerate(nodes) if index % 2 == 0][:12]

    @staticmethod
    def _layer1_filter_reason(assessment: PillarAssessment | None) -> str | None:
        if assessment is not None and not assessment.is_true_pillar:
            return "not_true_pillar"
        if assessment is not None and not GenerationService._passes_pillar_quality_gate(assessment):
            return "quality_gate_failed"
        return None

    @staticmethod
    def _candidate_pillar_title(title: str, assessment: PillarAssessment | None) -> str:
        if assessment is None:
            return title
        return assessment.sharpen_to or assessment.rename_to or assessment.canonical_title or title

    @staticmethod
    def _layer1_payload(
        base_payload: dict[str, Any],
        assessment: PillarAssessment | None,
        source_model: str,
        source_lens: str,
    ) -> dict[str, Any]:
        payload = dict(base_payload)
        payload["source_lens"] = source_lens
        payload["source_model"] = source_model
        if assessment is not None:
            payload["pillar_assessment"] = assessment.model_dump(mode="json")
            payload["canonical_title"] = assessment.canonical_title
            payload["cluster_id"] = assessment.cluster_id
        return payload

    def refresh_pillar_semantic_metadata(self, node_id: str) -> Node:
        """Recompute semantic-overlap metadata and embeddings for an existing Layer 1 pillar."""
        node = self.db.get_node(node_id)
        if node.node_type != "pillar" or node.layer != 1:
            return node
        payload = dict(node.json_payload or {})
        embedding_result, similarity_matches = self._pillar_similarity_result(
            project_id=node.project_id,
            title=node.title,
            description=node.description or "",
            payload=payload,
            exclude_node_ids=[node.id],
        )
        if similarity_matches:
            payload["semantic_similarity"] = self._semantic_similarity_payload(similarity_matches)
        else:
            payload.pop("semantic_similarity", None)
        updated = self.db.update_node(node.id, json_payload=payload)
        self._store_pillar_embedding(node.project_id, updated, embedding_result)
        return updated

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

    @staticmethod
    def _layer1_stop_decision(
        *,
        critic: CriticResponse,
        profile: dict[str, Any],
        normalized_count: int,
        created_count: int,
        duplicate_count: int,
        stale_rounds: int,
        stale_family_rounds: int,
        stale_rounds_to_stop: int,
    ) -> tuple[str, bool]:
        if not critic.continue_recommendation:
            return f"critic_stopped_{critic.saturation_signal}", True
        if critic.saturation_signal == "high" and critic.novelty_score <= 25:
            return "critic_detected_saturation", True
        if created_count == 0 and duplicate_count > 0:
            return f"model_repeated_existing_pillars_{profile['id']}", False
        if stale_rounds >= stale_rounds_to_stop:
            return "novelty_exhausted", False
        if stale_family_rounds >= stale_rounds_to_stop:
            return "family_spread_exhausted", False
        if normalized_count == 0:
            return f"model_returned_no_additional_pillars_{profile['id']}", False
        return "continue", False

    def generate_subfeatures_until_exhausted(
        self,
        project_id: str,
        pillar_id: str,
        *,
        thinking_enabled: bool = False,
        max_rounds: int = 5,
        target_per_round: int = 10,
        min_new_items_per_round: int = 2,
        stale_rounds_to_stop: int = 2,
    ) -> IterativeGenerationSummary:
        project = self.db.get_project(project_id)
        pillar = self.db.get_node(pillar_id)
        rejected = self.db.get_rejected_ideas(project_id)
        created_nodes: list[Node] = []
        duplicate_candidates = 0
        filtered_candidates = 0
        per_round_new_counts: list[int] = []
        per_round_new_family_counts: list[int] = []
        stale_rounds = 0
        stop_reason = "max_rounds_reached"
        final_coverage_summary = ""
        final_novelty_score: int | None = None
        round_summaries: list[str] = []
        runtime_profile = self._project_llm_runtime(project_id, "layer2_generation")
        self._ensure_profile_loaded(runtime_profile, thinking_enabled=thinking_enabled)
        prompt_catalog = self._prompt_catalog(project_id)

        for _ in range(max_rounds):
            approved = collect_approved_directions(self.db.list_all_nodes(project_id))
            siblings = self.db.list_nodes(project_id, parent_id=pillar_id, layer=2, node_type="subfeature")
            shared_project_features = self._shared_project_subfeatures(project_id, exclude_parent_id=pillar_id)
            memory = self.db.get_project_memory(
                project_id=project_id,
                scope="layer2",
                scope_id=pillar_id,
                memory_type="coverage",
            )
            prompt = build_subfeature_prompt(
                project.idea,
                pillar.title,
                pillar.description or "",
                self._memory_packet(siblings),
                shared_project_features,
                rejected,
                approved,
                self._coverage_summary(memory),
                self._uncovered_titles(memory),
                prompt_catalog=prompt_catalog,
            )
            _, parsed = self._call_structured_json_pass(
                project_id=project_id,
                node_id=pillar_id,
                prompt=prompt,
                runtime_profile=runtime_profile,
                max_tokens=2600,
                validator=self._validate_subfeatures,
                schema_label="subfeature_response",
                schema_instructions="Return {'subfeatures': [{title, description, user_value, complexity, dependencies, tags}]}.",
            )
            round_created: list[Node] = []
            round_duplicates = 0
            global_existing = self._project_subfeature_nodes(project_id, exclude_parent_id=pillar_id)
            for feature in parsed.subfeatures:
                duplicate = detect_possible_duplicates(
                    existing_nodes=siblings + created_nodes + round_created + global_existing,
                    title=feature.title,
                    description=feature.description,
                )
                if duplicate:
                    round_duplicates += 1
                    continue
                round_created.append(
                    self.db.create_node(
                        project_id=project_id,
                        parent_id=pillar_id,
                        layer=2,
                        node_type="subfeature",
                        title=feature.title,
                        description=feature.description,
                        json_payload=feature.model_dump(),
                    )
                )
            created_nodes.extend(round_created)
            duplicate_candidates += round_duplicates
            per_round_new_counts.append(len(round_created))
            per_round_new_family_counts.append(len(round_created))

            critic = self._run_critic(
                project_id=project_id,
                scope="layer2",
                scope_id=pillar_id,
                layer_name="Layer 2 Subfeatures",
                product_idea=project.idea,
                parent_context=f"{pillar.title}: {pillar.description or ''}",
                existing_nodes=siblings,
                new_nodes=round_created,
                runtime_profile=runtime_profile,
            )
            final_coverage_summary = critic.coverage_summary
            final_novelty_score = critic.novelty_score
            round_summaries.append(
                self._format_layer1_round_summary(
                    profile_name="current model",
                    lens_name=pillar.title,
                    created_count=len(round_created),
                    new_family_count=len(round_created),
                    duplicate_count=round_duplicates,
                    filtered_count=0,
                    novelty_score=critic.novelty_score,
                    saturation_signal=critic.saturation_signal,
                )
            )

            if len(round_created) < min_new_items_per_round:
                stale_rounds += 1
            else:
                stale_rounds = 0

            if not critic.continue_recommendation:
                stop_reason = f"critic_stopped_{critic.saturation_signal}"
                break
            if critic.saturation_signal == "high" and critic.novelty_score <= 25:
                stop_reason = "critic_detected_saturation"
                break
            if len(round_created) == 0 and round_duplicates > 0:
                stop_reason = "model_repeated_existing_subfeatures"
                break
            if stale_rounds >= stale_rounds_to_stop:
                stop_reason = "novelty_exhausted"
                break
            if not parsed.subfeatures:
                stop_reason = "model_returned_no_additional_subfeatures"
                break

        return IterativeGenerationSummary(
            created_nodes=created_nodes,
            total_rounds=len(per_round_new_counts),
            duplicate_candidates=duplicate_candidates,
            filtered_candidates=filtered_candidates,
            unique_family_count=0,
            stop_reason=stop_reason,
            per_round_new_counts=per_round_new_counts,
            per_round_new_family_counts=per_round_new_family_counts,
            final_coverage_summary=final_coverage_summary,
            final_novelty_score=final_novelty_score,
            lenses_used=[],
            models_used=[],
            round_summaries=round_summaries,
            thinking_enabled=thinking_enabled,
        )

    def generate_subfeatures(self, project_id: str, pillar_ids: list[str]) -> list[Node]:
        runtime_profile = self._project_llm_runtime(project_id, "layer2_generation")
        self._ensure_profile_loaded(runtime_profile, thinking_enabled=False)
        prompt_catalog = self._prompt_catalog(project_id)
        project = self.db.get_project(project_id)
        rejected = self.db.get_rejected_ideas(project_id)
        approved = collect_approved_directions(self.db.list_all_nodes(project_id))
        created: list[Node] = []
        for pillar_id in pillar_ids:
            pillar = self.db.get_node(pillar_id)
            siblings = self.db.list_nodes(project_id, parent_id=pillar_id, layer=2, node_type="subfeature")
            shared_project_features = self._shared_project_subfeatures(project_id, exclude_parent_id=pillar_id)
            memory = self.db.get_project_memory(
                project_id=project_id,
                scope="layer2",
                scope_id=pillar_id,
                memory_type="coverage",
            )
            prompt = build_subfeature_prompt(
                project.idea,
                pillar.title,
                pillar.description or "",
                self._memory_packet(siblings),
                shared_project_features,
                rejected,
                approved,
                self._coverage_summary(memory),
                self._uncovered_titles(memory),
                prompt_catalog=prompt_catalog,
            )
            _, parsed = self._call_structured_json_pass(
                project_id=project_id,
                node_id=pillar_id,
                prompt=prompt,
                runtime_profile=runtime_profile,
                max_tokens=2600,
                validator=self._validate_subfeatures,
                schema_label="subfeature_response",
                schema_instructions="Return {'subfeatures': [{title, description, user_value, complexity, dependencies, tags}]}.",
            )
            batch_nodes: list[Node] = []
            global_existing = self._project_subfeature_nodes(project_id, exclude_parent_id=pillar_id)
            for feature in parsed.subfeatures:
                duplicate = detect_possible_duplicates(
                    existing_nodes=siblings + batch_nodes + global_existing,
                    title=feature.title,
                    description=feature.description,
                )
                payload = feature.model_dump()
                if duplicate:
                    payload["possible_duplicate"] = duplicate
                batch_nodes.append(
                    self.db.create_node(
                        project_id=project_id,
                        parent_id=pillar_id,
                        layer=2,
                        node_type="subfeature",
                        title=feature.title,
                        description=feature.description,
                        json_payload=payload,
                    )
                )
            created.extend(batch_nodes)
        return created

    def generate_specs(self, project_id: str, subfeature_ids: list[str], *, thinking_enabled: bool = False) -> list[Node]:
        runtime_profile = self._project_llm_runtime(project_id, "layer3_generation")
        self._ensure_profile_loaded(runtime_profile, thinking_enabled=thinking_enabled)
        prompt_catalog = self._prompt_catalog(project_id)
        project = self.db.get_project(project_id)
        rejected = self.db.get_rejected_ideas(project_id)
        approved = collect_approved_directions(self.db.list_all_nodes(project_id))
        created: list[Node] = []
        for subfeature_id in subfeature_ids:
            subfeature = self.db.get_node(subfeature_id)
            if subfeature.parent_id is None:
                raise ValueError("Subfeature must have a parent pillar.")
            pillar = self.db.get_node(subfeature.parent_id)
            siblings = self.db.list_nodes(project_id, parent_id=subfeature_id, layer=3, node_type="spec")
            prompt = build_spec_prompt(
                project.idea,
                pillar.title,
                subfeature.title,
                subfeature.description or "",
                self._shared_project_subfeatures(project_id, exclude_parent_id=subfeature.parent_id),
                rejected,
                approved,
                prompt_catalog=prompt_catalog,
            )
            _, parsed = self._call_structured_json_pass(
                project_id=project_id,
                node_id=subfeature_id,
                prompt=prompt,
                runtime_profile=runtime_profile,
                max_tokens=3200,
                validator=self._validate_specs,
                schema_label="spec_response",
                schema_instructions="Return {'spec': {overview, user_personas, user_stories, inputs, outputs, core_logic, edge_cases, ux_screens, data_requirements, acceptance_criteria, open_questions, risks, implementation_notes}}.",
            )
            spec_title = f"{subfeature.title} Spec"
            duplicate = detect_possible_duplicates(
                existing_nodes=siblings,
                title=spec_title,
                description=parsed.spec.overview,
            )
            payload = parsed.spec.model_dump(mode="json")
            if duplicate:
                payload["possible_duplicate"] = duplicate
            created.append(
                self.db.create_node(
                    project_id=project_id,
                    parent_id=subfeature_id,
                    layer=3,
                    node_type="spec",
                    title=spec_title,
                    description=parsed.spec.overview,
                    json_payload=payload,
                )
            )
        return created

    @staticmethod
    def _validate_pillars(payload: dict[str, Any]) -> PillarResponse:
        try:
            return PillarResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid pillar payload: {exc}") from exc

    @staticmethod
    def _validate_subfeatures(payload: dict[str, Any]) -> SubfeatureResponse:
        try:
            return SubfeatureResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid subfeature payload: {exc}") from exc

    @staticmethod
    def _validate_specs(payload: dict[str, Any]) -> SpecResponse:
        try:
            return SpecResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid spec payload: {exc}") from exc

    def _run_critic(
        self,
        *,
        project_id: str,
        scope: str,
        scope_id: str | None,
        layer_name: str,
        product_idea: str,
        parent_context: str,
        existing_nodes: list[Node],
        new_nodes: list[Node],
        runtime_profile: dict[str, Any] | None = None,
    ) -> CriticResponse:
        previous_memory = self.db.get_project_memory(
            project_id=project_id,
            scope=scope,
            scope_id=scope_id,
            memory_type="coverage",
        )
        prompt = build_critic_prompt(
            layer_name=layer_name,
            product_idea=product_idea,
            parent_context=parent_context,
            existing_items=self._memory_packet(existing_nodes),
            new_items=self._memory_packet(new_nodes),
            previous_summary=self._coverage_summary(previous_memory),
            available_lenses=[name for name, _ in LAYER1_LENSES] if scope == "layer1" else [],
            prompt_catalog=self._prompt_catalog(project_id),
        )
        _, critic = self._call_structured_json_pass(
            project_id=project_id,
            node_id=scope_id,
            prompt=prompt,
            runtime_profile=runtime_profile,
            max_tokens=1800,
            temperature=0.2,
            validator=self._validate_critic,
            schema_label="critic_response",
            schema_instructions=CRITIC_SCHEMA,
        )
        self.db.upsert_project_memory(
            project_id=project_id,
            scope=scope,
            scope_id=scope_id,
            memory_type="coverage",
            content=critic.model_dump(mode="json"),
        )
        return critic

    def _normalize_pillars(
        self,
        *,
        project_id: str,
        product_idea: str,
        lens_name: str,
        existing_pillars: list[dict[str, str]],
        raw_pillars: list[Any],
        runtime_profile: dict[str, Any] | None = None,
    ) -> PillarResponse:
        raw_candidates = [
            {
                "title": pillar.title,
                "description": pillar.description,
                "tags": pillar.tags,
                "fingerprint": pillar.why_it_matters,
            }
            for pillar in raw_pillars
        ]
        prompt = build_pillar_normalization_prompt(
            product_idea=product_idea,
            lens_name=lens_name,
            existing_pillars=existing_pillars,
            raw_candidates=raw_candidates,
            prompt_catalog=self._prompt_catalog(project_id),
        )
        _, normalized = self._call_structured_json_pass(
            project_id=project_id,
            node_id=None,
            prompt=prompt,
            runtime_profile=runtime_profile,
            max_tokens=2200,
            temperature=0.2,
            validator=self._validate_pillars,
            schema_label="pillar_response",
            schema_instructions=PILLAR_RESPONSE_SCHEMA,
        )
        return normalized

    def _assess_pillars(
        self,
        *,
        project_id: str,
        product_idea: str,
        existing_pillars: list[dict[str, str]],
        candidate_pillars: list[Any],
        runtime_profile: dict[str, Any] | None = None,
    ) -> PillarAssessmentResponse:
        candidate_packet = [
            {
                "title": pillar.title,
                "description": pillar.description,
                "tags": pillar.tags,
                "fingerprint": pillar.why_it_matters,
            }
            for pillar in candidate_pillars
        ]
        prompt = build_pillar_assessment_prompt(
            product_idea=product_idea,
            existing_pillars=existing_pillars,
            candidate_pillars=candidate_packet,
            prompt_catalog=self._prompt_catalog(project_id),
        )
        _, assessments = self._call_structured_json_pass(
            project_id=project_id,
            node_id=None,
            prompt=prompt,
            runtime_profile=runtime_profile,
            max_tokens=2200,
            temperature=0.2,
            validator=self._validate_pillar_assessment,
            schema_label="pillar_assessment_response",
            schema_instructions=PILLAR_ASSESSMENT_SCHEMA,
        )
        return assessments

    @staticmethod
    def _memory_packet(nodes: list[Node]) -> list[dict[str, str]]:
        packet: list[dict[str, str]] = []
        for node in nodes:
            payload = node.json_payload or {}
            tags = payload.get("tags", [])
            why = payload.get("why_it_matters") or payload.get("user_value") or node.description or ""
            packet.append(
                {
                    "title": node.title,
                    "description": (node.description or "")[:180],
                    "tags": tags[:5] if isinstance(tags, list) else [],
                    "fingerprint": why[:180],
                }
            )
        return packet

    @staticmethod
    def _coverage_summary(memory: Any) -> str:
        if not memory:
            return "No prior coverage summary yet."
        return str(memory.content.get("coverage_summary", "No prior coverage summary yet."))

    @staticmethod
    def _uncovered_titles(memory: Any) -> list[str]:
        if not memory:
            return []
        uncovered = memory.content.get("uncovered_areas", [])
        result: list[str] = []
        for item in uncovered:
            if isinstance(item, dict) and item.get("title"):
                result.append(item["title"])
        return result

    def _representative_pillar_memory(self, nodes: list[Node], max_families: int = 24) -> list[dict[str, str]]:
        representatives: dict[str, dict[str, str]] = {}
        for node in nodes:
            payload = node.json_payload or {}
            canonical_title = payload.get("canonical_title") or node.title
            family_key = "".join(ch.lower() for ch in str(canonical_title) if ch.isalnum())
            if not family_key or family_key in representatives:
                continue
            # One representative per family keeps Layer 1 prompts compact without
            # losing the semantic shape of what has already been explored.
            representatives[family_key] = {
                "title": str(canonical_title),
                "description": (node.description or "")[:180],
                "tags": payload.get("tags", [])[:5] if isinstance(payload.get("tags"), list) else [],
                "fingerprint": str(payload.get("why_it_matters") or node.description or "")[:180],
            }
            if len(representatives) >= max_families:
                break
        return list(representatives.values())

    @staticmethod
    def _validate_critic(payload: dict[str, Any]) -> CriticResponse:
        try:
            return CriticResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid critic payload: {exc}") from exc

    @staticmethod
    def _validate_pillar_assessment(payload: dict[str, Any]) -> PillarAssessmentResponse:
        try:
            return PillarAssessmentResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid pillar assessment payload: {exc}") from exc

    @staticmethod
    def _layer1_lens_for_round(round_index: int, *, model_role: str) -> tuple[str, str]:
        """Choose the active lens without letting critic recommendations directly control the sequence."""
        if model_role == "Challenger":
            return LAYER1_LENSES[(round_index + 2) % len(LAYER1_LENSES)]
        return LAYER1_LENSES[round_index % len(LAYER1_LENSES)]

    @staticmethod
    def _critic_advisory_lens(memory: Any) -> str | None:
        """Expose the critic-suggested lens as a soft advisory signal rather than a routing directive."""
        if memory and isinstance(memory.content.get("recommended_next_lens"), str):
            return memory.content["recommended_next_lens"]
        return None

    @staticmethod
    def _assessment_for_pillar(title: str, assessments: list[PillarAssessment]) -> PillarAssessment | None:
        exact_matches = [item for item in assessments if item.title == title]
        if exact_matches:
            return exact_matches[0]
        best_match: PillarAssessment | None = None
        best_score = 0.0
        for item in assessments:
            score = max(
                fuzz.ratio(title, item.title),
                fuzz.ratio(title, item.canonical_title),
                fuzz.ratio(title, item.rename_to or ""),
            )
            if score > best_score:
                best_score = score
                best_match = item
        return best_match if best_score >= 82 else None

    @staticmethod
    def _passes_pillar_quality_gate(assessment: PillarAssessment) -> bool:
        return (
            assessment.pillar_quality_score >= 55
            and assessment.distinctiveness_score >= 40
            and assessment.strategic_value_score >= 45
            and not assessment.too_narrow
            and not assessment.too_implementation_specific
            and not assessment.too_broad_generic
        )

    @staticmethod
    def _pillar_family_key(title: str, assessment: PillarAssessment | None) -> str:
        if assessment is not None:
            family_name = assessment.rename_to or assessment.canonical_title or title
        else:
            family_name = title
        return "".join(ch.lower() for ch in family_name if ch.isalnum())

    def _existing_pillar_family_keys(self, nodes: list[Node]) -> set[str]:
        keys: set[str] = set()
        for node in nodes:
            payload = node.json_payload or {}
            assessment_payload = payload.get("pillar_assessment")
            assessment = None
            if isinstance(assessment_payload, dict):
                try:
                    assessment = PillarAssessment.model_validate(assessment_payload)
                except ValidationError:
                    assessment = None
            keys.add(self._pillar_family_key(node.title, assessment))
            canonical_title = payload.get("canonical_title")
            if isinstance(canonical_title, str) and canonical_title:
                keys.add("".join(ch.lower() for ch in canonical_title if ch.isalnum()))
        return keys

    def _covered_family_titles(self, nodes: list[Node]) -> list[str]:
        titles: list[str] = []
        seen: set[str] = set()
        for node in nodes:
            payload = node.json_payload or {}
            canonical_title = payload.get("canonical_title") or node.title
            if isinstance(canonical_title, str):
                family_key = "".join(ch.lower() for ch in canonical_title if ch.isalnum())
                if family_key and family_key not in seen:
                    seen.add(family_key)
                    titles.append(canonical_title)
        return titles

    @staticmethod
    def _format_layer1_round_summary(
        *,
        profile_name: str,
        lens_name: str,
        created_count: int,
        new_family_count: int,
        duplicate_count: int,
        filtered_count: int,
        novelty_score: int | None,
        saturation_signal: str | None,
    ) -> str:
        novelty_text = f", novelty {novelty_score}/100" if novelty_score is not None else ""
        saturation_text = f", saturation {saturation_signal}" if saturation_signal else ""
        return (
            f"{profile_name} | {lens_name}: created {created_count}, new families {new_family_count}, "
            f"duplicates {duplicate_count}, filtered {filtered_count}{novelty_text}{saturation_text}"
        )

    @staticmethod
    def _layer1_model_role(profile: dict[str, Any], models_used: list[str]) -> tuple[str, str]:
        if len(models_used) <= 1:
            return (
                "Explorer",
                "Map the broadest plausible pillar landscape and establish strong top-level families."
            )
        return (
            "Challenger",
            "Do not re-cover established territory. Treat critic guidance as hypothesis, not law, and hunt for missing pillar families, blind spots, and alternate top-level framings."
        )

    def _resolve_layer1_profiles(
        self,
        project_id: str | None = None,
        model_profiles: list[ModelProfile] | None = None,
    ) -> list[dict[str, Any]]:
        if model_profiles:
            return [
                {
                    "id": profile.alias,
                    "label": profile.display_name,
                    "base_url": "",
                    "model_name": profile.alias,
                    "local_path": str(profile.path) if profile.path else "",
                }
                for profile in model_profiles
            ]
        settings = self.db.get_project_model_settings(project_id) if project_id is not None else None
        if settings is not None:
            payload = settings.model_dump(mode="json")
            profiles = llm_profiles_by_id(payload)
            assignment = payload.get("assignments", {}).get("layer1_generation", [])
            if isinstance(assignment, list):
                resolved = [profiles[item] for item in assignment if item in profiles]
                if resolved:
                    return resolved
        if self.server_manager is not None:
            current_alias = self.server_manager.get_loaded_model_alias()
            if current_alias:
                managed_profile = self.server_manager.get_managed_profile(current_alias)
                if managed_profile is not None:
                    return [
                        {
                            "id": managed_profile.alias,
                            "label": managed_profile.display_name,
                            "base_url": "",
                            "model_name": managed_profile.alias,
                            "local_path": str(managed_profile.path) if managed_profile.path else "",
                        }
                    ]
                return [{"id": current_alias, "label": current_alias, "base_url": "", "model_name": current_alias, "local_path": ""}]
        fallback_alias = self.llm_client.model_name or "default"
        return [{"id": fallback_alias, "label": fallback_alias, "base_url": "", "model_name": fallback_alias, "local_path": ""}]

    def _published_product_idea(self, project_id: str) -> str:
        """Return the published Layer 0 idea, blocking Layer 1 while the brief is draft."""
        brief = self.db.get_project_brief(project_id)
        if brief is None or brief.status != "published":
            raise ValueError("Publish the Layer 0 brief before generating Layer 1.")
        return brief.product_idea

    def _ensure_profile_loaded(self, profile: dict[str, Any], *, thinking_enabled: bool = False) -> None:
        local_path = str(profile.get("local_path", "")).strip()
        if not local_path:
            return
        if self.server_manager is None:
            raise LLMError("Model sequencing requires a server manager, but none is configured.")
        try:
            self.server_manager.ensure_model_loaded(
                ModelProfile(
                    alias=str(profile["id"]),
                    display_name=str(profile.get("label", profile["id"])),
                    path=Path(local_path),
                ),
                thinking_enabled=thinking_enabled,
            )
        except ServerManagerError as exc:
            raise LLMError(str(exc)) from exc

    def _project_subfeature_nodes(self, project_id: str, *, exclude_parent_id: str | None = None) -> list[Node]:
        nodes = self.db.list_nodes(project_id, parent_id="__any__", layer=2, node_type="subfeature")
        if exclude_parent_id is None:
            return nodes
        return [node for node in nodes if node.parent_id != exclude_parent_id]

    def _shared_project_subfeatures(self, project_id: str, *, exclude_parent_id: str | None = None) -> list[dict[str, str]]:
        return self._memory_packet(self._project_subfeature_nodes(project_id, exclude_parent_id=exclude_parent_id))

    def _record_layer1_quarantine(
        self,
        *,
        project_id: str,
        pillar: dict[str, Any],
        reason: str,
        assessment: dict[str, Any] | None,
        source_model: str,
        source_lens: str,
    ) -> None:
        existing = self.db.get_project_memory(
            project_id=project_id,
            scope="layer1",
            scope_id=None,
            memory_type="quarantine",
        )
        items = list(existing.content.get("items", [])) if existing else []
        item = {
            "title": pillar.get("title", ""),
            "description": pillar.get("description", ""),
            "reason": reason,
            "assessment": assessment or {},
            "source_model": source_model,
            "source_lens": source_lens,
        }
        dedupe_key = f"{item['title']}|{reason}"
        existing_keys = {f"{entry.get('title','')}|{entry.get('reason','')}" for entry in items if isinstance(entry, dict)}
        if dedupe_key not in existing_keys:
            items.append(item)
        self.db.upsert_project_memory(
            project_id=project_id,
            scope="layer1",
            scope_id=None,
            memory_type="quarantine",
            content={"items": items[-100:]},
        )

    def _project_llm_runtime(self, project_id: str, assignment: str) -> dict[str, Any]:
        """Resolve a project-scoped LLM profile for the requested assignment."""
        settings = self.db.get_project_model_settings(project_id)
        if settings is None:
            fallback_alias = self.llm_client.model_name or "default"
            return {"id": fallback_alias, "label": fallback_alias, "base_url": "", "model_name": fallback_alias, "local_path": ""}
        payload = settings.model_dump(mode="json")
        assignment_id = str(payload.get("assignments", {}).get(assignment, "")).strip()
        profile = llm_profiles_by_id(payload).get(assignment_id)
        if profile is not None:
            return profile
        fallback_alias = self.llm_client.model_name or "default"
        return {"id": fallback_alias, "label": fallback_alias, "base_url": "", "model_name": fallback_alias, "local_path": ""}

    def _embedding_model_name(self, project_id: str, assignment: str) -> str:
        """Resolve the embedding model configured for this project assignment."""
        if self.embedding_service is None:
            return ""
        settings = self.db.get_project_model_settings(project_id)
        if settings is None:
            return self.embedding_service.model_name
        payload = settings.model_dump(mode="json")
        assignment_id = str(payload.get("assignments", {}).get(assignment, "")).strip()
        profile = embedding_profiles_by_id(payload).get(assignment_id)
        if profile is None:
            return self.embedding_service.model_name
        return str(profile.get("model_name", "")).strip() or self.embedding_service.model_name

    @staticmethod
    def _runtime_model_name(runtime_profile: dict[str, Any] | None) -> str | None:
        """Choose the model identifier sent to the target chat endpoint."""
        if runtime_profile is None:
            return None
        local_path = str(runtime_profile.get("local_path", "")).strip()
        if local_path:
            return str(runtime_profile.get("id", "")).strip() or None
        return str(runtime_profile.get("model_name", "")).strip() or None

    @staticmethod
    def _runtime_base_url(runtime_profile: dict[str, Any] | None) -> str | None:
        """Choose the endpoint URL used for a scoped chat request."""
        if runtime_profile is None:
            return None
        return str(runtime_profile.get("base_url", "")).strip() or None

    def _call_structured_json_pass(
        self,
        *,
        project_id: str,
        node_id: str | None,
        prompt: str,
        runtime_profile: dict[str, Any] | None,
        max_tokens: int,
        validator: Callable[[dict[str, Any]], Any],
        schema_label: str,
        schema_instructions: str,
        temperature: float | None = None,
        max_attempts: int = 2,
    ) -> tuple[Any, Any]:
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                response = self.llm_client.generate_json(
                    system_prompt=self._system_prompt(project_id),
                    user_prompt=prompt,
                    model_name=self._runtime_model_name(runtime_profile),
                    base_url=self._runtime_base_url(runtime_profile),
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                self.db.save_generation(
                    project_id=project_id,
                    node_id=node_id,
                    prompt=prompt,
                    raw_response=response.content,
                    parsed_json=response.parsed_json,
                    model_name=response.model_name,
                )
                try:
                    return response, validator(response.parsed_json)
                except LLMError:
                    # Generation often fails because the structure is "close but
                    # not valid". Repairing the JSON is much cheaper than rerunning
                    # the full reasoning pass from scratch.
                    repair_prompt = build_json_repair_prompt(
                        schema_label=schema_label,
                        schema_instructions=schema_instructions,
                        candidate_content=json.dumps(response.parsed_json, ensure_ascii=True),
                    )
                    repair_response = self.llm_client.generate_json(
                        system_prompt=self._system_prompt(project_id),
                        user_prompt=repair_prompt,
                        model_name=self._runtime_model_name(runtime_profile),
                        base_url=self._runtime_base_url(runtime_profile),
                        max_tokens=max_tokens,
                        temperature=0.1,
                    )
                    self.db.save_generation(
                        project_id=project_id,
                        node_id=node_id,
                        prompt=repair_prompt,
                        raw_response=repair_response.content,
                        parsed_json=repair_response.parsed_json,
                        model_name=repair_response.model_name,
                    )
                    return repair_response, validator(repair_response.parsed_json)
            except LLMError as exc:
                last_error = exc
                continue
        raise LLMError(f"Structured pass failed after {max_attempts} attempts for {schema_label}: {last_error}")
