from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable

from pydantic import ValidationError
from rapidfuzz import fuzz

from specforge.config import ModelProfile
from specforge.db import Database
from specforge.dedupe import detect_possible_duplicates
from specforge.llm import LLMError, LlamaCppClient
from specforge.models import (
    CriticResponse,
    Node,
    PillarAssessment,
    PillarAssessmentResponse,
    PillarResponse,
    SpecResponse,
    SubfeatureResponse,
)
from specforge.prompts import (
    build_system_prompt,
    build_critic_prompt,
    build_json_repair_prompt,
    build_pillar_assessment_prompt,
    build_pillar_normalization_prompt,
    build_pillar_prompt,
    build_spec_prompt,
    build_subfeature_prompt,
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


class GenerationService:
    def __init__(self, db: Database, llm_client: LlamaCppClient, server_manager: LlamaServerManager | None = None):
        self.db = db
        self.llm_client = llm_client
        self.server_manager = server_manager
        self.system_prompt = build_system_prompt()

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
        project = self.db.get_project(project_id)
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
        active_profiles = self._resolve_layer1_profiles(model_profiles)

        round_index = 0
        stop_all_models = False
        for profile in active_profiles:
            if stop_all_models:
                break
            models_used.append(profile.display_name)
            self._ensure_profile_loaded(profile, thinking_enabled=thinking_enabled)
            stale_rounds = 0
            for _ in range(max_rounds):
                all_nodes = self.db.list_all_nodes(project_id)
                rejected = self.db.get_rejected_ideas(project_id)
                approved = collect_approved_directions(all_nodes)
                siblings = self.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
                memory_packet = self._representative_pillar_memory(siblings)
                memory = self.db.get_project_memory(
                    project_id=project_id,
                    scope="layer1",
                    scope_id=None,
                    memory_type="coverage",
                )
                lens_name, lens_instruction = self._layer1_lens_for_round(round_index, memory)
                round_index += 1
                lenses_used.append(f"{profile.display_name}: {lens_name}")
                model_role, role_instruction = self._layer1_model_role(profile, models_used)
                covered_families = self._covered_family_titles(siblings + created_nodes)
                prompt = build_pillar_prompt(
                    project.idea,
                    rejected,
                    approved,
                    memory_packet,
                    covered_families,
                    self._coverage_summary(memory),
                    self._uncovered_titles(memory),
                    lens_name,
                    lens_instruction,
                    model_role,
                    role_instruction,
                    target_count=target_per_round,
                )
                response, raw_parsed = self._call_structured_json_pass(
                    project_id=project_id,
                    node_id=None,
                    prompt=prompt,
                    model_alias=profile.alias,
                    max_tokens=2200,
                    validator=self._validate_pillars,
                    schema_label="pillar_response",
                    schema_instructions=PILLAR_RESPONSE_SCHEMA,
                )
                normalized = self._normalize_pillars(
                    project_id=project_id,
                    product_idea=project.idea,
                    lens_name=lens_name,
                    existing_pillars=memory_packet,
                    raw_pillars=raw_parsed.pillars,
                    model_alias=profile.alias,
                )
                assessments = self._assess_pillars(
                    project_id=project_id,
                    product_idea=project.idea,
                    existing_pillars=memory_packet,
                    candidate_pillars=normalized.pillars,
                    model_alias=profile.alias,
                )

                round_created: list[Node] = []
                round_duplicates = 0
                round_filtered = 0
                existing_family_keys = self._existing_pillar_family_keys(siblings + created_nodes)
                round_family_keys: set[str] = set()
                for pillar in normalized.pillars:
                    assessment = self._assessment_for_pillar(pillar.title, assessments.assessments)
                    if assessment is not None and not assessment.is_true_pillar:
                        round_filtered += 1
                        self._record_layer1_quarantine(
                            project_id=project_id,
                            pillar=pillar.model_dump(),
                            reason="not_true_pillar",
                            assessment=assessment.model_dump(mode="json"),
                            source_model=profile.display_name,
                            source_lens=lens_name,
                        )
                        continue
                    if assessment is not None and not self._passes_pillar_quality_gate(assessment):
                        round_filtered += 1
                        self._record_layer1_quarantine(
                            project_id=project_id,
                            pillar=pillar.model_dump(),
                            reason="quality_gate_failed",
                            assessment=assessment.model_dump(mode="json"),
                            source_model=profile.display_name,
                            source_lens=lens_name,
                        )
                        continue
                    family_key = self._pillar_family_key(pillar.title, assessment)
                    if family_key in existing_family_keys:
                        round_duplicates += 1
                        continue
                    duplicate = detect_possible_duplicates(
                        existing_nodes=siblings + created_nodes + round_created,
                        title=(assessment.rename_to or assessment.canonical_title or pillar.title) if assessment else pillar.title,
                        description=pillar.description,
                    )
                    if duplicate:
                        round_duplicates += 1
                        continue
                    payload = pillar.model_dump()
                    payload["source_lens"] = lens_name
                    payload["source_model"] = profile.display_name
                    if assessment is not None:
                        payload["pillar_assessment"] = assessment.model_dump(mode="json")
                        payload["canonical_title"] = assessment.canonical_title
                        payload["cluster_id"] = assessment.cluster_id
                    save_title = pillar.title
                    if assessment is not None:
                        save_title = assessment.sharpen_to or assessment.rename_to or assessment.canonical_title or pillar.title
                    family_key = self._pillar_family_key(save_title, assessment)
                    existing_family_keys.add(family_key)
                    round_family_keys.add(family_key)
                    round_created.append(
                        self.db.create_node(
                            project_id=project_id,
                            parent_id=None,
                            layer=1,
                            node_type="pillar",
                            title=save_title,
                            description=pillar.description,
                            json_payload=payload,
                        )
                    )

                created_nodes.extend(round_created)
                duplicate_candidates += round_duplicates
                filtered_candidates += round_filtered
                per_round_new_counts.append(len(round_created))
                per_round_new_family_counts.append(len(round_family_keys))

                critic = self._run_critic(
                    project_id=project_id,
                    scope="layer1",
                    scope_id=None,
                    layer_name="Layer 1 Feature Pillars",
                    product_idea=project.idea,
                    parent_context=f"Top-level product decomposition | model phase: {profile.display_name}",
                    existing_nodes=siblings,
                    new_nodes=round_created,
                    model_alias=profile.alias,
                )
                final_coverage_summary = critic.coverage_summary
                final_novelty_score = critic.novelty_score
                round_summaries.append(
                    self._format_layer1_round_summary(
                        profile_name=profile.display_name,
                        lens_name=lens_name,
                        created_count=len(round_created),
                        new_family_count=len(round_family_keys),
                        duplicate_count=round_duplicates,
                        filtered_count=round_filtered,
                        novelty_score=critic.novelty_score,
                        saturation_signal=critic.saturation_signal,
                    )
                )

                if len(round_created) < min_new_items_per_round:
                    stale_rounds += 1
                else:
                    stale_rounds = 0
                if len(round_family_keys) == 0:
                    stale_family_rounds += 1
                else:
                    stale_family_rounds = 0

                if not critic.continue_recommendation:
                    stop_reason = f"critic_stopped_{critic.saturation_signal}"
                    stop_all_models = True
                    break
                if critic.saturation_signal == "high" and critic.novelty_score <= 25:
                    stop_reason = "critic_detected_saturation"
                    stop_all_models = True
                    break
                if len(round_created) == 0 and round_duplicates > 0:
                    stop_reason = f"model_repeated_existing_pillars_{profile.alias}"
                    break
                if stale_rounds >= stale_rounds_to_stop:
                    stop_reason = "novelty_exhausted"
                    break
                if stale_family_rounds >= stale_rounds_to_stop:
                    stop_reason = "family_spread_exhausted"
                    break
                if not normalized.pillars:
                    stop_reason = f"model_returned_no_additional_pillars_{profile.alias}"
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
        self._ensure_current_server_mode(thinking_enabled=thinking_enabled)

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
            )
            _, parsed = self._call_structured_json_pass(
                project_id=project_id,
                node_id=pillar_id,
                prompt=prompt,
                model_alias=None,
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
        self._ensure_current_server_mode(thinking_enabled=False)
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
            )
            _, parsed = self._call_structured_json_pass(
                project_id=project_id,
                node_id=pillar_id,
                prompt=prompt,
                model_alias=None,
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
        self._ensure_current_server_mode(thinking_enabled=thinking_enabled)
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
            )
            _, parsed = self._call_structured_json_pass(
                project_id=project_id,
                node_id=subfeature_id,
                prompt=prompt,
                model_alias=None,
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
        model_alias: str | None = None,
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
        )
        _, critic = self._call_structured_json_pass(
            project_id=project_id,
            node_id=scope_id,
            prompt=prompt,
            model_alias=model_alias,
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
        model_alias: str | None = None,
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
        )
        _, normalized = self._call_structured_json_pass(
            project_id=project_id,
            node_id=None,
            prompt=prompt,
            model_alias=model_alias,
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
        model_alias: str | None = None,
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
        )
        _, assessments = self._call_structured_json_pass(
            project_id=project_id,
            node_id=None,
            prompt=prompt,
            model_alias=model_alias,
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
    def _layer1_lens_for_round(round_index: int, memory: Any) -> tuple[str, str]:
        if memory and isinstance(memory.content.get("recommended_next_lens"), str):
            recommended = memory.content["recommended_next_lens"]
            for lens_name, lens_instruction in LAYER1_LENSES:
                if lens_name == recommended:
                    return lens_name, lens_instruction
        uncovered_titles = GenerationService._uncovered_titles(memory)
        if uncovered_titles:
            title_blob = " ".join(uncovered_titles).lower()
            for lens_name, lens_instruction in LAYER1_LENSES:
                lens_blob = f"{lens_name} {lens_instruction}".lower()
                if any(word in lens_blob for word in title_blob.split()):
                    return lens_name, lens_instruction
        return LAYER1_LENSES[round_index % len(LAYER1_LENSES)]

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
    def _layer1_model_role(profile: ModelProfile, models_used: list[str]) -> tuple[str, str]:
        if len(models_used) <= 1:
            return (
                "Explorer",
                "Map the broadest plausible pillar landscape and establish strong top-level families."
            )
        return (
            "Challenger",
            "Do not re-cover established territory. Hunt for missing pillar families, blind spots, and underexplored strategic areas."
        )

    def _resolve_layer1_profiles(self, model_profiles: list[ModelProfile] | None) -> list[ModelProfile]:
        if model_profiles:
            return model_profiles
        if self.server_manager is not None:
            current_alias = self.server_manager.get_loaded_model_alias()
            if current_alias:
                managed_profile = self.server_manager.get_managed_profile(current_alias)
                if managed_profile is not None:
                    return [managed_profile]
                return [ModelProfile(alias=current_alias, display_name=current_alias, path=None)]
        fallback_alias = self.llm_client.model_name or "default"
        return [ModelProfile(alias=fallback_alias, display_name=fallback_alias, path=None)]

    def _ensure_profile_loaded(self, profile: ModelProfile, *, thinking_enabled: bool = False) -> None:
        if profile.path is None:
            return
        if self.server_manager is None:
            raise LLMError("Model sequencing requires a server manager, but none is configured.")
        try:
            self.server_manager.ensure_model_loaded(profile, thinking_enabled=thinking_enabled)
        except ServerManagerError as exc:
            raise LLMError(str(exc)) from exc

    def _ensure_current_server_mode(self, *, thinking_enabled: bool) -> None:
        if self.server_manager is None:
            return
        current_alias = self.server_manager.get_loaded_model_alias()
        if current_alias is None:
            return
        managed_profile = self.server_manager.get_managed_profile(current_alias)
        if managed_profile is None:
            return
        self._ensure_profile_loaded(managed_profile, thinking_enabled=thinking_enabled)

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

    def _call_structured_json_pass(
        self,
        *,
        project_id: str,
        node_id: str | None,
        prompt: str,
        model_alias: str | None,
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
                    system_prompt=self.system_prompt,
                    user_prompt=prompt,
                    model_name=model_alias,
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
                    repair_prompt = build_json_repair_prompt(
                        schema_label=schema_label,
                        schema_instructions=schema_instructions,
                        candidate_content=json.dumps(response.parsed_json, ensure_ascii=True),
                    )
                    repair_response = self.llm_client.generate_json(
                        system_prompt=self.system_prompt,
                        user_prompt=repair_prompt,
                        model_name=model_alias,
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
