from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from rapidfuzz import fuzz

from specforge.llm import LLMError
from specforge.models import (
    FeatureGranularity,
    Layer2Candidate,
    Layer2CandidateResponse,
    Layer2CoverageAssessmentResponse,
    Layer2CoverageFamilyDiscoveryResponse,
    Layer2GraphCriticResponse,
    Layer2IntegrityCriticResponse,
    PillarScopeContract,
    Node,
)
from specforge.prompts import (
    build_layer2_coverage_prompt,
    build_layer2_feature_prompt,
    build_layer2_graph_critic_prompt,
    build_layer2_integrity_critic_prompt,
    build_layer2_scope_discovery_prompt,
)


LAYER2_LENSES: list[tuple[str, str]] = [
    ("core_workflows", "Find end-to-end capabilities users directly rely on inside this pillar."),
    ("user_actions", "Find concrete actions a user can take, without dropping to individual user-story wording."),
    ("background_automation", "Find system-driven automation, monitoring, cleanup, or scheduled capabilities."),
    ("edge_cases", "Find exception-handling capabilities for unusual, failed, or ambiguous situations."),
    ("admin_controls", "Find configuration, governance, permissioning, and operational control capabilities."),
    ("compliance", "Find auditability, privacy, risk, consent, policy, and regulatory-support capabilities."),
    ("data_requirements", "Find user-visible data capture, classification, enrichment, or validation capabilities."),
    ("integrations", "Find concrete third-party or internal interoperability capabilities."),
    ("reporting", "Find analytics, summaries, exports, and decision-support capabilities."),
    ("notifications", "Find alerts, reminders, nudges, escalation, or messaging capabilities."),
]

LAYER2_EXHAUSTION_FAMILIES: list[tuple[str, str]] = [
    ("core_capabilities", "Primary functions the module must perform."),
    ("variants_and_types", "Supported variants, modes, formats, or type inventories inside the module."),
    ("logic_and_rules", "Branching, rule, scoring, validation, and conditional behavior."),
    ("workflow_states", "Draft, review, publish, versioning, approval, and lifecycle states."),
    ("embedded_data", "Piped variables, contextual data, metadata, and reusable content inserted into the module."),
    ("templates_and_reuse", "Templates, cloning, reusable blocks, defaults, and pattern libraries."),
    ("admin_controls", "Configuration, governance, permissions, and operational controls specific to this module."),
    ("edge_cases", "Fallbacks, exceptions, error states, and uncommon but necessary module behavior."),
    ("integrations", "Inbound or outbound connections required inside this module boundary."),
    ("reporting_hooks", "Module-specific summaries, exports, audit traces, and handoffs to reporting."),
    ("accessibility_localization", "Accessibility, translation, formatting, and locale-specific support."),
]

LAYER2_SURVEY_BUILDER_FAMILIES: list[tuple[str, str]] = [
    ("question_types", "Question formats, answer inputs, matrix/ranking/open-ended variants, and media question support."),
    ("branching_logic", "Skip logic, display logic, branching rules, termination rules, and randomization."),
    ("workflow_states", "Drafting, review, approval, publishing, versioning, cloning, and rollback behavior."),
    ("embedded_data", "Piped text, respondent attributes, hidden fields, metadata, and carry-forward answer data."),
    ("scoring", "Scored questions, weighted answers, categories, thresholds, and result calculations."),
    ("templates_and_reuse", "Reusable question blocks, survey templates, themes, defaults, and question banks."),
    ("validation", "Required answers, ranges, formats, quotas, duplicate prevention, and response constraints."),
    ("distribution_setup", "Builder-owned launch configuration, availability windows, anonymous/authenticated mode, and embed setup."),
    ("accessibility_localization", "Accessible question rendering, translations, locale formats, and language variants."),
    ("collaboration_controls", "Comments, reviewer handoff, ownership, locks, and change approvals inside the builder."),
]



LAYER2_FEATURE_SCHEMA = """{
  "features": [
    {
      "canonical_name": "...",
      "description": "...",
      "feature_type": "workflow | automation | admin_control | compliance | data_requirement | integration | reporting | notification | capability",
      "coverage_family": "...",
      "scope_classification": "in_scope | adjacent_owned_elsewhere | new_layer1_pillar | too_low_level | implementation_detail",
      "pillar_fit_rationale": "...",
      "aliases": ["..."],
      "related_pillar_ids": ["..."],
      "depends_on": ["..."],
      "used_by": ["..."],
      "specificity_score": 0,
      "pillar_fit_score": 0,
      "distinctiveness_score": 0,
      "implementation_leakage_score": 0,
      "strategic_value_score": 0,
      "needs_human_review": true
    }
  ]
}"""

LAYER2_COVERAGE_SCHEMA = """{
  "coverage_summary": "...",
  "family_assessments": [
    {
      "family": "...",
      "status": "covered | partial | missing | excluded",
      "evidence_feature_ids": ["..."],
      "missing_examples": ["..."],
      "next_lens": "...",
      "rationale": "..."
    }
  ],
  "drifted_feature_ids": ["..."],
  "adjacent_module_suggestions": ["..."],
  "saturation_signal": "low | medium | high",
  "novelty_score": 0,
  "continue_recommendation": true,
  "recommended_next_lenses": ["..."],
  "reasoning": "..."
}"""

LAYER2_SCOPE_DISCOVERY_SCHEMA = """{
  "coverage_families": [
    {
      "name": "...",
      "description": "...",
      "exhaustion_goal": "...",
      "example_features": ["..."],
      "anti_examples": ["..."]
    }
  ],
  "reasoning": "..."
}"""

LAYER2_INTEGRITY_SCHEMA = """{
  "assessments": [
    {
      "candidate_id": "...",
      "granularity_class": "feature | feature_variant | workflow | rule | configuration | shared_concern | too_broad | too_low_level",
      "is_out_of_bounds": false,
      "ambiguity_score": 0.0,
      "reason": "..."
    }
  ]
}"""

LAYER2_GRAPH_CRITIC_SCHEMA = """{
  "duplicate_merges": [
    {"source_feature_id": "...", "target_feature_id": "...", "confidence": 0.0, "reason": "..."}
  ],
  "cross_pillar_dependencies": [
    {"source_feature_id": "...", "target_feature_id": "...", "relationship_type": "depends_on", "confidence": 0.0, "reason": "..."}
  ],
  "detected_shared_concerns": [
    {"name": "...", "concern_type": "ingestion", "connected_feature_ids": ["..."], "planning_implication": "...", "confidence": 0.0}
  ]
}"""


class Layer2EngineMixin:
    """Layer 2 graph generation helpers mixed into GenerationService.

    The mixin keeps the graph-native Layer 2 descent code separate from the broader
    Layer 1 and Layer 3 orchestration code while still using the service's database,
    model runtime, and structured JSON repair helpers.
    """

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

    def _process_layer2_candidate_batch(
        self,
        *,
        project_id: str,
        run_id: str,
        pillar: Node,
        selected_pillars: list[Node],
        runtime_profile: dict[str, Any],
        source_model: str,
        lens_name: str,
        generation_round: int,
        product_idea: str,
        prompt_catalog: dict[str, str],
        scope_contract: PillarScopeContract,
        candidates: list[Layer2Candidate],
        stats: dict[str, Any],
    ) -> list[str]:
        """Persist raw candidates, apply semantic veto, run critics, and create graph features."""
        raw_pairs: list[tuple[Any, Layer2Candidate]] = []
        for candidate in candidates:
            stats["raw_candidate_count"] += 1
            veto = self._layer2_semantic_negative_cache_veto(project_id, candidate)
            if veto and veto["action"] == "auto_reject":
                stats["negative_cache_matches"] += 1
                self.db.insert_layer2_raw_candidate(
                    project_id=project_id,
                    generation_run_id=run_id,
                    source_pillar_id=pillar.id,
                    source_lens=lens_name,
                    source_model=source_model,
                    generation_round=generation_round,
                    raw_text=candidate.model_dump_json(),
                    payload={**candidate.model_dump(mode="json"), "negative_cache_veto": veto},
                    negative_cache_match=True,
                    negative_cache_reason=f"Auto-rejected repeat of '{veto['rejected_name']}' at similarity {veto['similarity']}.",
                )
                continue
            raw = self.db.insert_layer2_raw_candidate(
                project_id=project_id,
                generation_run_id=run_id,
                source_pillar_id=pillar.id,
                source_lens=lens_name,
                source_model=source_model,
                generation_round=generation_round,
                raw_text=candidate.model_dump_json(),
                payload={
                    **candidate.model_dump(mode="json"),
                    "is_potential_negative_cache_repeat": bool(veto),
                    "negative_cache_context": veto or {},
                },
                negative_cache_match=bool(veto),
                negative_cache_reason=(
                    f"Potential repeat of '{veto['rejected_name']}' at similarity {veto['similarity']}."
                    if veto else ""
                ),
            )
            if veto:
                stats["negative_cache_matches"] += 1
            raw_pairs.append((raw, candidate))

        if not raw_pairs:
            return []

        integrity = self._run_layer2_integrity_critic(
            project_id=project_id,
            pillar_id=pillar.id,
            runtime_profile=runtime_profile,
            product_idea=product_idea,
            prompt_catalog=prompt_catalog,
            scope_contract=scope_contract,
            raw_pairs=raw_pairs,
        )
        integrity_by_id = {item.candidate_id: item for item in integrity.assessments}
        created_feature_ids: list[str] = []
        selected_pillar_ids = [item.id for item in selected_pillars]
        for raw, candidate in raw_pairs:
            assessment = integrity_by_id.get(raw.id)
            granularity = assessment.granularity_class if assessment else FeatureGranularity.FEATURE
            ambiguity_score = assessment.ambiguity_score if assessment else 0.0
            drift_flag = bool(
                (assessment and assessment.is_out_of_bounds)
                or granularity in {FeatureGranularity.TOO_BROAD, FeatureGranularity.TOO_LOW_LEVEL}
                or candidate.scope_classification != "in_scope"
            )
            metadata = self._layer2_feature_metadata(
                candidate,
                selected_pillars,
                pillar.id,
                lens_name,
                source_model,
                raw.negative_cache_match,
                raw.negative_cache_reason,
            )
            metadata.update(
                {
                    "raw_candidate_id": raw.id,
                    "granularity_class": granularity.value,
                    "integrity_reason": assessment.reason if assessment else "",
                    "ambiguity_score": ambiguity_score,
                    "ambiguity_flag": ambiguity_score >= 0.55,
                    "scope_drift_flag": drift_flag,
                }
            )
            if granularity == FeatureGranularity.SHARED_CONCERN:
                self._route_layer2_shared_concern(
                    project_id=project_id,
                    name=candidate.canonical_name,
                    concern_type=self._infer_shared_concern_type(candidate),
                    connected_feature_ids=[],
                )
                continue
            status = self._layer2_candidate_status(candidate, raw.negative_cache_match)
            if drift_flag or ambiguity_score >= 0.55:
                status = "needs_review"
            feature = self.db.create_layer2_feature(
                project_id=project_id,
                canonical_name=candidate.canonical_name.strip(),
                description=candidate.description.strip(),
                feature_type=self._safe_layer2_feature_type(candidate.feature_type),
                granularity_class=granularity.value,
                owner_pillar_id=pillar.id,
                candidate_source_ids=[raw.id],
                aliases=candidate.aliases,
                status=status,
                related_pillar_ids=self._valid_related_pillar_ids(candidate.related_pillar_ids, selected_pillar_ids),
                used_by_feature_ids=[],
                depends_on_feature_ids=[],
                quality={**candidate.model_dump(mode="json"), "needs_human_review": status == "needs_review" or candidate.needs_human_review},
                metadata=metadata,
            )
            stats["created_feature_ids"].append(feature.id)
            created_feature_ids.append(feature.id)
            self._store_layer2_affinities(project_id, feature.id, candidate, selected_pillars, pillar.id)
            existing, overlap_score = self._find_layer2_overlap(project_id, candidate, exclude_feature_ids=[feature.id])
            if existing is not None:
                stats["duplicate_recommendations"] += 1
                self._record_layer2_duplicate_recommendation(project_id, feature.id, existing.id, existing.canonical_name, overlap_score)

        if created_feature_ids:
            graph_critic = self._run_layer2_graph_critic(
                project_id=project_id,
                runtime_profile=runtime_profile,
                product_idea=product_idea,
                prompt_catalog=prompt_catalog,
                current_feature_ids=created_feature_ids,
            )
            self._apply_layer2_graph_directives(project_id, graph_critic, stats)
        return created_feature_ids

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
        for merge in graph_critic.duplicate_merges:
            if merge.source_feature_id not in feature_ids or merge.target_feature_id not in feature_ids:
                continue
            stats["duplicate_recommendations"] += 1
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
                payload={"recommended_target_feature_id": merge.target_feature_id, "reason": merge.reason, "confidence": merge.confidence},
            )
        for dependency in graph_critic.cross_pillar_dependencies:
            if dependency.source_feature_id not in feature_ids or dependency.target_feature_id not in feature_ids:
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

    def _persist_layer2_candidate(
        self,
        *,
        project_id: str,
        run_id: str,
        pillar: Node,
        selected_pillars: list[Node],
        source_model: str,
        lens_name: str,
        generation_round: int,
        candidate: Layer2Candidate,
        stats: dict[str, Any],
    ) -> str | None:
        """Store one raw candidate, canonical feature, affinities, and duplicate review recommendation."""
        stats["raw_candidate_count"] += 1
        selected_pillar_ids = [pillar.id for pillar in selected_pillars]
        negative_match, negative_reason = self._match_layer2_negative_cache(project_id, candidate)
        if negative_match:
            stats["negative_cache_matches"] += 1
        raw = self.db.insert_layer2_raw_candidate(
            project_id=project_id,
            generation_run_id=run_id,
            source_pillar_id=pillar.id,
            source_lens=lens_name,
            source_model=source_model,
            generation_round=generation_round,
            raw_text=candidate.model_dump_json(),
            payload=candidate.model_dump(mode="json"),
            negative_cache_match=negative_match,
            negative_cache_reason=negative_reason,
        )
        existing, overlap_score = self._find_layer2_overlap(project_id, candidate)
        feature = self.db.create_layer2_feature(
            project_id=project_id,
            canonical_name=candidate.canonical_name.strip(),
            description=candidate.description.strip(),
            feature_type=self._safe_layer2_feature_type(candidate.feature_type),
            owner_pillar_id=pillar.id,
            candidate_source_ids=[raw.id],
            aliases=candidate.aliases,
            status=self._layer2_candidate_status(candidate, negative_match),
            related_pillar_ids=self._valid_related_pillar_ids(candidate.related_pillar_ids, selected_pillar_ids),
            used_by_feature_ids=[],
            depends_on_feature_ids=[],
            quality=candidate.model_dump(mode="json"),
            metadata=self._layer2_feature_metadata(candidate, selected_pillars, pillar.id, lens_name, source_model, negative_match, negative_reason),
        )
        stats["created_feature_ids"].append(feature.id)
        self._store_layer2_affinities(project_id, feature.id, candidate, selected_pillars, pillar.id)
        if existing is not None:
            stats["duplicate_recommendations"] += 1
            self._record_layer2_duplicate_recommendation(project_id, feature.id, existing.id, existing.canonical_name, overlap_score)
        return feature.id

    def _record_layer2_duplicate_recommendation(
        self,
        project_id: str,
        feature_id: str,
        existing_feature_id: str,
        existing_feature_name: str,
        overlap_score: float,
    ) -> None:
        """Create the review artifacts for a possible Layer 2 duplicate."""
        self.db.insert_layer2_relationship(
            project_id=project_id,
            source_feature_id=feature_id,
            target_feature_id=existing_feature_id,
            relationship_type="duplicate_of",
            strength=overlap_score,
            rationale=f"Generated candidate resembles existing Layer 2 feature '{existing_feature_name}'.",
        )
        self.db.record_layer2_review_action(
            project_id=project_id,
            feature_id=feature_id,
            action_type="merge",
            payload={
                "recommended_target_feature_id": existing_feature_id,
                "recommended_target_name": existing_feature_name,
                "reason": "Possible duplicate found during Layer 2 graph normalization.",
                "overlap_score": overlap_score,
            },
        )

    def _layer2_graph_summary(self, project_id: str, stats: dict[str, Any]) -> dict[str, Any]:
        """Build the API summary for a completed Layer 2 graph run."""
        review_queue_count = len(
            [feature for feature in self.db.list_layer2_features(project_id) if feature.status in {"candidate", "needs_review"}]
        )
        return {
            "created_feature_ids": stats["created_feature_ids"],
            "raw_candidate_count": stats["raw_candidate_count"],
            "negative_cache_matches": stats["negative_cache_matches"],
            "duplicate_recommendations": stats["duplicate_recommendations"],
            "review_queue_count": review_queue_count,
        }

    def _layer2_scope_contract(self, project_id: str, pillar: Node) -> dict[str, Any]:
        """Build the locked parent-pillar scope contract used to prevent lateral drift."""
        sibling_pillars = [
            {"id": node.id, "title": node.title, "description": node.description or ""}
            for node in self.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
            if node.id != pillar.id
        ]
        families = self._layer2_family_definitions(pillar)
        return {
            "pillar_id": pillar.id,
            "pillar_name": pillar.title,
            "pillar_description": pillar.description or "",
            "allowed_capability_families": [
                {"id": family_id, "description": description}
                for family_id, description in families
            ],
            "excluded_adjacent_modules": sibling_pillars,
            "scope_rule": (
                "Exhaust concrete capabilities inside this parent pillar only. "
                "Adjacent modules can be related, but they cannot become owned Layer 2 features here."
            ),
        }

    @staticmethod
    def _layer2_family_definitions(pillar: Node) -> list[tuple[str, str]]:
        """Pick default or domain-specific coverage families for exhaustive descent."""
        text = f"{pillar.title} {pillar.description or ''}".lower()
        if "survey" in text and any(term in text for term in ("builder", "build", "question", "form")):
            return LAYER2_SURVEY_BUILDER_FAMILIES
        return LAYER2_EXHAUSTION_FAMILIES

    @staticmethod
    def _layer2_coverage_family_names(scope_contract: dict[str, Any]) -> list[str]:
        """Return family ids from a scope contract."""
        return [
            str(item.get("id"))
            for item in scope_contract.get("allowed_capability_families", [])
            if item.get("id")
        ]

    def _layer2_coverage_memory(self, project_id: str, pillar_id: str) -> Any:
        """Read the latest scoped Layer 2 coverage assessment for one pillar."""
        return self.db.get_project_memory(
            project_id=project_id,
            scope="layer2",
            scope_id=pillar_id,
            memory_type="scoped_coverage",
        )

    @staticmethod
    def _layer2_active_lenses(round_index: int, assessment_memory: Any, coverage_families: list[str]) -> list[tuple[str, str]]:
        """Choose broad first-pass lenses, then focus on missing or partial coverage families."""
        if round_index == 0 or not assessment_memory:
            return [*LAYER2_LENSES, *[(family, f"Exhaust the {family} coverage family inside this pillar.") for family in coverage_families]]
        content = assessment_memory.content or {}
        recommended = content.get("recommended_next_lenses", [])
        if not recommended:
            recommended = [
                item.get("family")
                for item in content.get("family_assessments", [])
                if item.get("status") in {"missing", "partial"} and item.get("family")
            ]
        lenses = [
            (str(lens), f"Fill remaining scoped Layer 2 coverage for {lens}.")
            for lens in recommended
            if str(lens).strip()
        ]
        return lenses[:8] or [("scoped_gap_fill", "Find concrete missing capabilities inside the parent pillar scope only.")]

    def _assess_layer2_coverage(
        self,
        *,
        project_id: str,
        pillar: Node,
        runtime_profile: dict[str, Any],
        product_idea: str,
        prompt_catalog: dict[str, str],
        scope_contract: dict[str, Any],
        coverage_families: list[str],
        newest_feature_ids: list[str],
    ) -> Any:
        """Assess scoped Layer 2 coverage and persist the critic output as project memory."""
        current_features = [
            self._layer2_feature_to_memory(feature)
            for feature in self.db.list_layer2_features(project_id)
            if feature.owner_pillar_id == pillar.id
        ]
        newest_features = [
            item for item in current_features if item["id"] in set(newest_feature_ids)
        ]
        previous = self._layer2_coverage_memory(project_id, pillar.id)
        prompt = build_layer2_coverage_prompt(
            product_idea=product_idea,
            scope_contract=scope_contract,
            coverage_families=coverage_families,
            current_features=current_features,
            newest_features=newest_features,
            previous_summary=self._coverage_summary(previous),
            prompt_catalog=prompt_catalog,
        )
        _, assessment = self._call_structured_json_pass(
            project_id=project_id,
            node_id=pillar.id,
            prompt=prompt,
            runtime_profile=runtime_profile,
            max_tokens=2600,
            temperature=0.2,
            validator=self._validate_layer2_coverage,
            schema_label="layer2_coverage_assessment",
            schema_instructions=LAYER2_COVERAGE_SCHEMA,
        )
        self._apply_layer2_drift_flags(project_id, assessment.drifted_feature_ids)
        self._update_layer2_coverage_matrix_from_assessment(
            project_id=project_id,
            pillar_id=pillar.id,
            assessment=assessment,
        )
        return self.db.upsert_project_memory(
            project_id=project_id,
            scope="layer2",
            scope_id=pillar.id,
            memory_type="scoped_coverage",
            content={
                **assessment.model_dump(mode="json"),
                "scope_contract": scope_contract,
                "coverage_families": coverage_families,
            },
        )

    def _apply_layer2_drift_flags(self, project_id: str, drifted_feature_ids: list[str]) -> None:
        """Mark critic-identified drift as needs_review without deleting provenance."""
        for feature_id in drifted_feature_ids:
            try:
                feature = self.db.get_layer2_feature(feature_id)
            except ValueError:
                continue
            if feature.project_id != project_id:
                continue
            self.db.update_layer2_feature(
                feature.id,
                status="needs_review",
                metadata={**feature.metadata, "scope_drift_flag": True},
            )

    def _update_layer2_coverage_matrix_from_assessment(
        self,
        *,
        project_id: str,
        pillar_id: str,
        assessment: Layer2CoverageAssessmentResponse,
    ) -> None:
        """Persist the latest critic assessment into the inspectable coverage matrix."""
        drifted = set(assessment.drifted_feature_ids)
        for family in assessment.family_assessments:
            self.db.upsert_layer2_coverage_matrix_row(
                project_id=project_id,
                pillar_id=pillar_id,
                family_name=family.family,
                status=family.status,
                evidence_feature_ids=family.evidence_feature_ids,
                missing_examples=family.missing_examples,
                last_lens_run=family.next_lens or "",
                drift_flags=bool(drifted),
                ambiguity_flags=False,
            )

    def _layer2_should_stop(self, project_id: str, pillar_id: str, assessment_memory: Any, stale_rounds: int, novelty_score: float) -> bool:
        """Stop once novelty is exhausted and all coverage families are resolved."""
        if stale_rounds >= 2:
            return True
        if not assessment_memory:
            return False
        content = assessment_memory.content or {}
        if not content.get("continue_recommendation", False):
            return True
        if content.get("saturation_signal") == "high" and int(content.get("novelty_score", 0)) <= 25:
            return True
        families = content.get("family_assessments", [])
        open_families = [item for item in families if item.get("status") in {"missing", "partial"}]
        matrix_rows = self.db.list_layer2_coverage_matrix(project_id, pillar_id=pillar_id)
        matrix_resolved = bool(matrix_rows) and all(row.status in {"covered", "excluded"} for row in matrix_rows)
        return (bool(families) and not open_families) or (novelty_score < 0.15 and matrix_resolved)

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

    def _match_layer2_negative_cache(self, project_id: str, candidate: Layer2Candidate) -> tuple[bool, str]:
        """Flag candidates that semantically resemble previously cut Layer 2 concepts."""
        candidate_text = f"{candidate.canonical_name} {candidate.description} {' '.join(candidate.aliases)}".lower()
        for entry in self.db.list_layer2_negative_cache(project_id):
            rejected_terms = [entry.rejected_name, entry.semantic_cluster, *entry.rejected_aliases]
            scores = [fuzz.token_set_ratio(candidate_text, term.lower()) for term in rejected_terms if term]
            if scores and max(scores) >= 82:
                return True, f"Matches rejected Layer 2 cluster '{entry.semantic_cluster}' ({max(scores):.0f})."
        return False, ""

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

