from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from specforge.config import ModelProfile
from specforge.db import Database
from specforge.dedupe import detect_possible_duplicates
from specforge.embeddings import EmbeddingService
from specforge.llm import LLMError, LlamaCppClient
from specforge.generation_types import IterativeGenerationSummary
from specforge.layer1_engine import Layer1EngineMixin, LAYER1_LENSES
from specforge.layer2_engine import (
    LAYER2_EXHAUSTION_FAMILIES,
    LAYER2_LENSES,
    LAYER2_SURVEY_BUILDER_FAMILIES,
    Layer2EngineMixin,
)
from specforge.models import (
    CriticResponse,
    Node,
    SpecResponse,
    SubfeatureResponse,
)
from specforge.project_settings import embedding_profiles_by_id, llm_profiles_by_id
from specforge.prompts import (
    build_system_prompt,
    build_critic_prompt,
    build_json_repair_prompt,
    build_spec_prompt,
    build_subfeature_prompt,
    load_prompt_catalog,
)
from specforge.server_manager import LlamaServerManager, ServerManagerError
from specforge.tree import collect_approved_directions


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





class GenerationService(Layer1EngineMixin, Layer2EngineMixin):
    """Coordinate LLM generation across layers while sharing runtime and database helpers."""

    def __init__(
        self,
        db: Database,
        llm_client: LlamaCppClient,
        server_manager: LlamaServerManager | None = None,
        embedding_service: EmbeddingService | None = None,
    ):
        """Wire the persistent store, active LLM client, and optional local model helpers."""
        self.db = db
        self.llm_client = llm_client
        self.server_manager = server_manager
        self.embedding_service = embedding_service

    def _prompt_catalog(self, project_id: str) -> dict[str, str]:
        """Resolve the prompt catalog snapshot stored for this project."""
        defaults = load_prompt_catalog()
        settings = self.db.get_project_model_settings(project_id)
        if settings is not None and settings.prompt_catalog:
            return {**defaults, **settings.prompt_catalog}
        return defaults

    def _system_prompt(self, project_id: str) -> str:
        """Build the system prompt from the project-scoped prompt catalog."""
        return build_system_prompt(prompt_catalog=self._prompt_catalog(project_id))

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
        """Legacy tree-mode Layer 2 descent that repeatedly asks for subfeatures under one pillar."""
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
        """Generate one tree-mode Layer 2 batch for each selected Layer 1 pillar."""
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
        """Generate Layer 3 implementation specs for approved subfeatures."""
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
    def _validate_subfeatures(payload: dict[str, Any]) -> SubfeatureResponse:
        """Validate the legacy Layer 2 tree response from the model."""
        try:
            return SubfeatureResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid subfeature payload: {exc}") from exc

    @staticmethod
    def _validate_specs(payload: dict[str, Any]) -> SpecResponse:
        """Validate the Layer 3 spec response from the model."""
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
        """Run the shared coverage critic and persist its memory packet for the next round."""
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

    @staticmethod
    def _memory_packet(nodes: list[Node]) -> list[dict[str, str]]:
        """Compress nodes into the compact memory format used in prompts."""
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
        """Read the stored critic summary or return the first-round default."""
        if not memory:
            return "No prior coverage summary yet."
        return str(memory.content.get("coverage_summary", "No prior coverage summary yet."))

    @staticmethod
    def _uncovered_titles(memory: Any) -> list[str]:
        """Extract uncovered area titles from critic memory."""
        if not memory:
            return []
        uncovered = memory.content.get("uncovered_areas", [])
        result: list[str] = []
        for item in uncovered:
            if isinstance(item, dict) and item.get("title"):
                result.append(item["title"])
        return result

    def _published_product_idea(self, project_id: str) -> str:
        """Return the published Layer 0 idea, blocking Layer 1 while the brief is draft."""
        brief = self.db.get_project_brief(project_id)
        if brief is None or brief.status != "published":
            raise ValueError("Publish the Layer 0 brief before generating Layer 1.")
        return brief.product_idea

    def _ensure_profile_loaded(self, profile: dict[str, Any], *, thinking_enabled: bool = False) -> None:
        """Load a local GGUF profile before generation when the assignment points at a file."""
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
        """Return all tree-mode Layer 2 nodes, optionally excluding one pillar's children."""
        nodes = self.db.list_nodes(project_id, parent_id="__any__", layer=2, node_type="subfeature")
        if exclude_parent_id is None:
            return nodes
        return [node for node in nodes if node.parent_id != exclude_parent_id]

    def _shared_project_subfeatures(self, project_id: str, *, exclude_parent_id: str | None = None) -> list[dict[str, str]]:
        """Expose cross-pillar subfeatures as memory for duplicate detection and shared concerns."""
        return self._memory_packet(self._project_subfeature_nodes(project_id, exclude_parent_id=exclude_parent_id))

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
        """Call the model, persist the raw generation, and repair near-valid JSON responses."""
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
