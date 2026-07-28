from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from strata.config import ModelProfile
from strata.db import Database
from strata.dedupe import detect_possible_duplicates
from strata.embeddings import EmbeddingService
from strata.execution_policy import resolve_embedding_model_name, resolve_llm_profile, resolved_runtime_request
from strata.llm import LLMError, LlamaCppClient
from strata.layer1_engine import Layer1EngineMixin, LAYER1_LENSES
from strata.layer1_territory_engine import Layer1TerritoryEngineMixin
from strata.layer2_engine import (
    LAYER2_EXHAUSTION_FAMILIES,
    LAYER2_LENSES,
    LAYER2_SURVEY_BUILDER_FAMILIES,
    Layer2EngineMixin,
)
from strata.layer3_service import Layer3ServiceMixin
from strata.models import (
    CriticResponse,
    Node,
)
from strata.prompts import (
    build_system_prompt,
    build_critic_prompt,
    build_json_repair_prompt,
    load_prompt_catalog,
)
from strata.server_manager import LlamaServerManager, ServerManagerError
from strata.tree import collect_approved_directions
from strata.telemetry import model_call_context


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





class GenerationService(
    Layer1TerritoryEngineMixin,
    Layer1EngineMixin,
    Layer2EngineMixin,
    Layer3ServiceMixin,
):
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
            telemetry_layer=layer_name.casefold().replace(" ", ""),
            telemetry_workflow=f"{scope}_coverage_critic",
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
        """Return compact published Layer 0 context, blocking Layer 1 while the brief is draft."""
        brief = self.db.get_project_brief(project_id)
        if brief is None or brief.status != "published":
            raise ValueError("Publish the Layer 0 brief before generating Layer 1.")
        return self._published_brief_context(brief)

    @staticmethod
    def _published_brief_context(brief: Any) -> str:
        """Format the published Layer 0 brief as the bounded Layer 1 source context."""
        lines = [
            f"Product idea: {brief.product_idea or 'Unspecified'}",
            f"Problem: {brief.problem or 'Unspecified'}",
            f"Target users: {brief.target_users or 'Unspecified'}",
            f"Constraints: {brief.constraints or 'Unspecified'}",
            f"Goals: {', '.join(brief.goals) if brief.goals else 'Unspecified'}",
            f"Known competitors: {', '.join(brief.known_competitors) if brief.known_competitors else 'Unspecified'}",
            f"Preferred directions: {', '.join(brief.preferred_directions) if brief.preferred_directions else 'Unspecified'}",
            f"Rejected directions: {', '.join(brief.rejected_directions) if brief.rejected_directions else 'Unspecified'}",
            f"Notes: {brief.notes or 'Unspecified'}",
        ]
        return "\n".join(lines)

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
            return resolved_runtime_request(None, llm_client=self.llm_client)
        return resolved_runtime_request(
            resolve_llm_profile(settings.model_dump(mode="json"), assignment),
            llm_client=self.llm_client,
            server_manager=self.server_manager,
        )

    def _embedding_model_name(self, project_id: str, assignment: str) -> str:
        """Resolve the embedding model configured for this project assignment."""
        if self.embedding_service is None:
            return ""
        settings = self.db.get_project_model_settings(project_id)
        if settings is None:
            return self.embedding_service.model_name
        return resolve_embedding_model_name(
            settings.model_dump(mode="json"),
            assignment,
            self.embedding_service.model_name,
        )

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
        telemetry_layer: str | None = None,
        telemetry_workflow: str | None = None,
        run_id: str | None = None,
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
                    telemetry=model_call_context(
                        project_id=project_id,
                        layer=telemetry_layer or self._telemetry_layer(schema_label),
                        workflow=telemetry_workflow or schema_label,
                        runtime_profile=runtime_profile,
                        run_id=run_id,
                        prompt_key=schema_label,
                        retry_count=attempt,
                        metadata={"node_id": node_id, "schema_label": schema_label, "repair": False},
                    ),
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
                        telemetry=model_call_context(
                            project_id=project_id,
                            layer=telemetry_layer or self._telemetry_layer(schema_label),
                            workflow=f"{telemetry_workflow or schema_label}_repair",
                            runtime_profile=runtime_profile,
                            run_id=run_id,
                            prompt_key="json_repair",
                            retry_count=attempt,
                            metadata={"node_id": node_id, "schema_label": schema_label, "repair": True},
                        ),
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

    @staticmethod
    def _telemetry_layer(schema_label: str) -> str:
        """Infer the product layer from the stable structured-response schema id."""
        if schema_label.startswith("layer2"):
            return "layer2"
        if schema_label.startswith("capability") or schema_label.startswith("layer3"):
            return "layer3"
        if schema_label.startswith("pillar"):
            return "layer1"
        return "shared"
