from __future__ import annotations

from typing import Any

from specforge.layer2_constants import (
    LAYER2_COVERAGE_SCHEMA,
    LAYER2_EXHAUSTION_FAMILIES,
    LAYER2_FEATURE_SCHEMA,
    LAYER2_GRAPH_CRITIC_SCHEMA,
    LAYER2_INTEGRITY_SCHEMA,
    LAYER2_LENSES,
    LAYER2_SCOPE_DISCOVERY_SCHEMA,
    LAYER2_SURVEY_BUILDER_FAMILIES,
)
from specforge.layer2_coverage import Layer2CoverageMixin
from specforge.layer2_critics import Layer2CriticMixin
from specforge.layer2_memory import Layer2MemoryMixin
from specforge.layer2_pipeline import Layer2PipelineMixin
from specforge.models import Layer2CandidateResponse, Node
from specforge.prompts import build_layer2_feature_prompt


class Layer2EngineMixin(
    Layer2PipelineMixin,
    Layer2CriticMixin,
    Layer2CoverageMixin,
    Layer2MemoryMixin,
):
    """Orchestrate graph-native Layer 2 descent from approved Layer 1 pillars."""

    def generate_layer2_feature_graph(
        self,
        project_id: str,
        pillar_ids: list[str],
        *,
        thinking_enabled: bool = False,
        max_rounds: int = 1,
        target_per_lens: int = 4,
    ) -> dict[str, Any]:
        """Generate graph-native Layer 2 features from approved Layer 1 pillars."""
        if not pillar_ids:
            raise ValueError("Select at least one approved Layer 1 pillar for Layer 2 generation.")
        runtime_profile = self._project_llm_runtime(project_id, "layer2_generation")
        self._ensure_profile_loaded(runtime_profile, thinking_enabled=thinking_enabled)
        source_model = str(runtime_profile.get("label") or runtime_profile.get("model_name") or "local-model")
        selected_pillars = [self._approved_layer1_pillar(project_id, pillar_id) for pillar_id in pillar_ids]
        run = self.db.create_layer2_generation_run(
            project_id=project_id,
            source_pillar_ids=[pillar.id for pillar in selected_pillars],
            lenses=[name for name, _ in LAYER2_LENSES],
            source_model=source_model,
        )
        stats: dict[str, Any] = {
            "created_feature_ids": [],
            "raw_candidate_count": 0,
            "negative_cache_matches": 0,
            "duplicate_recommendations": 0,
        }
        try:
            self._run_layer2_lens_passes(
                project_id=project_id,
                run_id=run.id,
                runtime_profile=runtime_profile,
                selected_pillars=selected_pillars,
                source_model=source_model,
                max_rounds=max_rounds,
                target_per_lens=target_per_lens,
                stats=stats,
            )
            summary = self._layer2_graph_summary(project_id, stats)
            self.db.complete_layer2_generation_run(run.id, status="completed", summary=summary)
            return summary
        except Exception:
            self.db.complete_layer2_generation_run(
                run.id,
                status="failed",
                summary={
                    "created_feature_ids": stats["created_feature_ids"],
                    "raw_candidate_count": stats["raw_candidate_count"],
                },
            )
            raise

    def _run_layer2_lens_passes(
        self,
        *,
        project_id: str,
        run_id: str,
        runtime_profile: dict[str, Any],
        selected_pillars: list[Node],
        source_model: str,
        max_rounds: int,
        target_per_lens: int,
        stats: dict[str, Any],
    ) -> None:
        """Run the optimized Layer 2 intelligence pipeline for each selected pillar."""
        product_idea = self._published_product_idea(project_id)
        prompt_catalog = self._prompt_catalog(project_id)
        for pillar in selected_pillars:
            self.db.upsert_layer1_pillar(pillar)
            scope_contract = self._discover_layer2_scope_contract(
                project_id=project_id,
                pillar=pillar,
                product_idea=product_idea,
                prompt_catalog=prompt_catalog,
                runtime_profile=runtime_profile,
            )
            coverage_families = scope_contract.discovered_coverage_families
            self._initialize_layer2_coverage_matrix(project_id, pillar.id, coverage_families)
            previous_assessment = self._layer2_coverage_memory(project_id, pillar.id)
            stale_rounds = 0
            for round_index in range(max(1, max_rounds)):
                active_lenses = self._layer2_active_lenses(round_index, previous_assessment, coverage_families)
                round_raw_count = 0
                round_feature_ids: list[str] = []
                for lens_name, lens_instruction in active_lenses:
                    parsed = self._call_layer2_lens(
                        project_id=project_id,
                        pillar=pillar,
                        runtime_profile=runtime_profile,
                        product_idea=product_idea,
                        prompt_catalog=prompt_catalog,
                        scope_contract=scope_contract.model_dump(mode="json"),
                        coverage_families=coverage_families,
                        coverage_summary=self._coverage_summary(previous_assessment),
                        lens_name=lens_name,
                        lens_instruction=lens_instruction,
                        target_per_lens=target_per_lens,
                    )
                    round_raw_count += len(parsed.features)
                    round_feature_ids.extend(
                        self._process_layer2_candidate_batch(
                            project_id=project_id,
                            run_id=run_id,
                            pillar=pillar,
                            selected_pillars=selected_pillars,
                            runtime_profile=runtime_profile,
                            source_model=source_model,
                            lens_name=lens_name,
                            generation_round=round_index + 1,
                            product_idea=product_idea,
                            prompt_catalog=prompt_catalog,
                            scope_contract=scope_contract,
                            candidates=parsed.features,
                            stats=stats,
                        )
                    )
                novelty_score = (len(round_feature_ids) / round_raw_count) if round_raw_count else 0.0
                previous_assessment = self._assess_layer2_coverage(
                    project_id=project_id,
                    pillar=pillar,
                    runtime_profile=runtime_profile,
                    product_idea=product_idea,
                    prompt_catalog=prompt_catalog,
                    scope_contract=scope_contract.model_dump(mode="json"),
                    coverage_families=coverage_families,
                    newest_feature_ids=round_feature_ids,
                )
                stale_rounds = stale_rounds + 1 if len(round_feature_ids) == 0 else 0
                if self._layer2_should_stop(project_id, pillar.id, previous_assessment, stale_rounds, novelty_score):
                    break

    def _call_layer2_lens(
        self,
        *,
        project_id: str,
        pillar: Node,
        runtime_profile: dict[str, Any],
        product_idea: str,
        prompt_catalog: dict[str, str],
        scope_contract: dict[str, Any],
        coverage_families: list[str],
        coverage_summary: str,
        lens_name: str,
        lens_instruction: str,
        target_per_lens: int,
    ) -> Layer2CandidateResponse:
        """Call the local model for one scoped Layer 2 lens."""
        prompt = build_layer2_feature_prompt(
            product_idea=product_idea,
            pillar_title=pillar.title,
            pillar_description=pillar.description or "",
            lens_name=lens_name,
            lens_instruction=lens_instruction,
            scope_contract=scope_contract,
            coverage_families=coverage_families,
            coverage_summary=coverage_summary,
            sibling_features=self._layer2_feature_memory(project_id, owner_pillar_id=pillar.id),
            cross_pillar_features=self._layer2_feature_memory(project_id, exclude_owner_pillar_id=pillar.id),
            negative_cache=self._layer2_negative_cache_memory(project_id),
            target_count=target_per_lens,
            prompt_catalog=prompt_catalog,
        )
        _, parsed = self._call_structured_json_pass(
            project_id=project_id,
            node_id=pillar.id,
            prompt=prompt,
            runtime_profile=runtime_profile,
            max_tokens=2800,
            validator=self._validate_layer2_candidates,
            schema_label="layer2_feature_response",
            schema_instructions=LAYER2_FEATURE_SCHEMA,
        )
        return parsed
