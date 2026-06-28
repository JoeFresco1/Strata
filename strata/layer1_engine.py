from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from rapidfuzz import fuzz

from strata.config import ModelProfile
from strata.dedupe import detect_possible_duplicates
from strata.execution_policy import resolve_llm_profiles
from strata.generation_types import IterativeGenerationSummary
from strata.llm import LLMError
from strata.models import (
    CriticResponse,
    Node,
    PillarAssessment,
    PillarAssessmentResponse,
    PillarResponse,
    SimilarityMatch,
)
from strata.prompts import (
    build_pillar_assessment_prompt,
    build_pillar_normalization_prompt,
    build_pillar_prompt,
)
from strata.tree import collect_approved_directions
from strata.layer1_overlap import Layer1OverlapMixin


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

@dataclass(slots=True)
class Layer1MemoryChannels:
    """Source-separated memory passed into a Layer 1 generation prompt."""

    user_rejected_ideas: list[str]
    user_approved_directions: list[str]
    persisted_pillars: list[dict[str, Any]]
    persisted_families: list[str]
    critic_coverage_summary: str
    critic_uncovered_areas: list[str]
    critic_recommended_lens: str | None


@dataclass(slots=True)
class Layer1RoundContext:
    """All runtime context needed to execute one Layer 1 lens/model pass."""

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
    """Persisted result counts for a single Layer 1 generation round."""

    created_nodes: list[Node]
    duplicate_count: int
    filtered_count: int
    new_family_keys: set[str]




class Layer1EngineMixin(Layer1OverlapMixin):
    """Layer 1 pillar generation, assessment, and overlap-memory behavior."""

    def generate_pillars(self, project_id: str) -> list[Node]:
        """Generate Layer 1 pillars through the exhaustive loop and return only created nodes."""
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
        total_cap: int | None = None,
        min_new_items_per_round: int = 2,
        stale_rounds_to_stop: int = 2,
    ) -> IterativeGenerationSummary:
        """Run Layer 1 model/lens passes until novelty, coverage, or critic signals are exhausted."""
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
                remaining_budget = None if total_cap is None else max(0, total_cap - len(created_nodes))
                if remaining_budget == 0:
                    stop_reason = "total_cap_reached"
                    stop_all_models = True
                    break
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
                    target_count=min(target_per_round, remaining_budget) if remaining_budget is not None else target_per_round,
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
                    max_new_items=remaining_budget,
                )

                created_nodes.extend(outcome.created_nodes)
                if outcome.created_nodes:
                    self.refresh_layer1_overlap_memory(project_id)
                duplicate_candidates += outcome.duplicate_count
                filtered_candidates += outcome.filtered_count
                per_round_new_counts.append(len(outcome.created_nodes))
                per_round_new_family_counts.append(len(outcome.new_family_keys))
                if total_cap is not None and len(created_nodes) >= total_cap:
                    stop_reason = "total_cap_reached"
                    stop_all_models = True
                    break

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
        """Assemble sibling state, overlap memory, role, and lens for one Layer 1 round."""
        siblings = self.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
        self._ensure_pillar_embeddings(project_id, siblings)
        siblings = self.refresh_layer1_overlap_memory(project_id, nodes=siblings)
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
        max_new_items: int | None = None,
    ) -> Layer1RoundOutcome:
        """Filter, dedupe, score, and persist the normalized pillars from one round."""
        round_created: list[Node] = []
        round_duplicates = 0
        round_filtered = 0
        existing_family_keys = self._existing_pillar_family_keys(siblings + created_nodes)
        round_family_keys: set[str] = set()

        for pillar in normalized_pillars:
            if max_new_items is not None and len(round_created) >= max_new_items:
                break
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
        """Return the quarantine reason for a rejected pillar assessment, if any."""
        if assessment is not None and not assessment.is_true_pillar:
            return "not_true_pillar"
        if assessment is not None and not Layer1EngineMixin._passes_pillar_quality_gate(assessment):
            return "quality_gate_failed"
        return None

    @staticmethod
    def _candidate_pillar_title(title: str, assessment: PillarAssessment | None) -> str:
        """Choose the stable saved title after model-proposed rename/sharpening."""
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
        """Attach generation provenance and assessment metadata to a Layer 1 node payload."""
        payload = dict(base_payload)
        payload["source_lens"] = source_lens
        payload["source_model"] = source_model
        if assessment is not None:
            payload["pillar_assessment"] = assessment.model_dump(mode="json")
            payload["canonical_title"] = assessment.canonical_title
            payload["cluster_id"] = assessment.cluster_id
        return payload

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
        """Translate critic and novelty counters into a loop stop decision."""
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

    @staticmethod
    def _validate_pillars(payload: dict[str, Any]) -> PillarResponse:
        """Validate generated or normalized Layer 1 pillar JSON."""
        try:
            return PillarResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid pillar payload: {exc}") from exc

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
        """Canonicalize raw pillar candidates before quality and overlap checks."""
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
        """Ask the model to score whether candidates are true Layer 1 pillars."""
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

    def _representative_pillar_memory(self, nodes: list[Node], max_families: int = 24) -> list[dict[str, str]]:
        """Collapse existing pillars to one prompt-memory item per semantic family."""
        representatives: dict[str, dict[str, str]] = {}
        for node in nodes:
            payload = node.json_payload or {}
            overlap_cluster = payload.get("overlap_cluster") if isinstance(payload.get("overlap_cluster"), dict) else {}
            canonical_title = overlap_cluster.get("representative_title") or payload.get("canonical_title") or node.title
            family_key = str(overlap_cluster.get("cluster_id") or "".join(ch.lower() for ch in str(canonical_title) if ch.isalnum()))
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
        """Validate the shared coverage critic response."""
        try:
            return CriticResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid critic payload: {exc}") from exc

    @staticmethod
    def _validate_pillar_assessment(payload: dict[str, Any]) -> PillarAssessmentResponse:
        """Validate and normalize candidate-pillar assessment scores."""
        try:
            response = PillarAssessmentResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid pillar assessment payload: {exc}") from exc
        normalized: list[PillarAssessment] = []
        for assessment in response.assessments:
            normalized.append(Layer1EngineMixin._normalized_pillar_assessment_scores(assessment))
        return PillarAssessmentResponse(assessments=normalized)

    @staticmethod
    def _normalized_pillar_assessment_scores(assessment: PillarAssessment) -> PillarAssessment:
        """Accept common 1-10 model scoring drift by scaling it into the 0-100 gate range."""
        score_fields = (
            assessment.distinctiveness_score,
            assessment.strategic_value_score,
            assessment.pillar_quality_score,
        )
        if all(0 <= score <= 10 for score in score_fields):
            return assessment.model_copy(
                update={
                    "distinctiveness_score": assessment.distinctiveness_score * 10,
                    "strategic_value_score": assessment.strategic_value_score * 10,
                    "pillar_quality_score": assessment.pillar_quality_score * 10,
                }
            )
        return assessment

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
        """Find the assessment corresponding to a normalized pillar title."""
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
        """Apply the minimum score and leakage thresholds for Layer 1 candidates."""
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
        """Build a normalized family key used for duplicate pillar prevention."""
        if assessment is not None:
            family_name = assessment.rename_to or assessment.canonical_title or title
        else:
            family_name = title
        return "".join(ch.lower() for ch in family_name if ch.isalnum())

    def _existing_pillar_family_keys(self, nodes: list[Node]) -> set[str]:
        """Collect known family keys from saved pillar payloads and overlap clusters."""
        keys: set[str] = set()
        for node in nodes:
            payload = node.json_payload or {}
            overlap_cluster = payload.get("overlap_cluster")
            if isinstance(overlap_cluster, dict):
                cluster_id = overlap_cluster.get("cluster_id")
                if isinstance(cluster_id, str) and cluster_id:
                    keys.add(cluster_id)
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
        """Return one display title per covered Layer 1 family."""
        titles: list[str] = []
        seen: set[str] = set()
        for node in nodes:
            payload = node.json_payload or {}
            overlap_cluster = payload.get("overlap_cluster") if isinstance(payload.get("overlap_cluster"), dict) else {}
            canonical_title = overlap_cluster.get("representative_title") or payload.get("canonical_title") or node.title
            if isinstance(canonical_title, str):
                family_key = str(overlap_cluster.get("cluster_id") or "".join(ch.lower() for ch in canonical_title if ch.isalnum()))
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
        """Format one round's counts for UI/debug summaries."""
        novelty_text = f", novelty {novelty_score}/100" if novelty_score is not None else ""
        saturation_text = f", saturation {saturation_signal}" if saturation_signal else ""
        return (
            f"{profile_name} | {lens_name}: created {created_count}, new families {new_family_count}, "
            f"duplicates {duplicate_count}, filtered {filtered_count}{novelty_text}{saturation_text}"
        )

    @staticmethod
    def _layer1_model_role(profile: dict[str, Any], models_used: list[str]) -> tuple[str, str]:
        """Classify the active model pass as the first explorer or a later challenger."""
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
        """Resolve configured Layer 1 model assignments with local-runtime fallbacks."""
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
            resolved = resolve_llm_profiles(settings.model_dump(mode="json"), "layer1_generation")
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
        """Remember rejected pillar candidates so later tuning can inspect why they were filtered."""
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

