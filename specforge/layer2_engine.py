from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from rapidfuzz import fuzz

from specforge.llm import LLMError
from specforge.models import (
    Layer2Candidate,
    Layer2CandidateResponse,
    Layer2CoverageAssessmentResponse,
    Node,
)
from specforge.prompts import build_layer2_coverage_prompt, build_layer2_feature_prompt


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
        """Run scoped Layer 2 passes until the pillar coverage critic sees saturation."""
        product_idea = self._published_product_idea(project_id)
        prompt_catalog = self._prompt_catalog(project_id)
        for pillar in selected_pillars:
            self.db.upsert_layer1_pillar(pillar)
            scope_contract = self._layer2_scope_contract(project_id, pillar)
            coverage_families = self._layer2_coverage_family_names(scope_contract)
            previous_assessment = self._layer2_coverage_memory(project_id, pillar.id)
            stale_rounds = 0
            for round_index in range(max(1, max_rounds)):
                active_lenses = self._layer2_active_lenses(round_index, previous_assessment, coverage_families)
                round_feature_ids: list[str] = []
                for lens_name, lens_instruction in active_lenses:
                    parsed = self._call_layer2_lens(
                        project_id=project_id,
                        pillar=pillar,
                        runtime_profile=runtime_profile,
                        product_idea=product_idea,
                        prompt_catalog=prompt_catalog,
                        scope_contract=scope_contract,
                        coverage_families=coverage_families,
                        coverage_summary=self._coverage_summary(previous_assessment),
                        lens_name=lens_name,
                        lens_instruction=lens_instruction,
                        target_per_lens=target_per_lens,
                    )
                    for candidate in parsed.features:
                        feature_id = self._persist_layer2_candidate(
                            project_id=project_id,
                            run_id=run_id,
                            pillar=pillar,
                            selected_pillars=selected_pillars,
                            source_model=source_model,
                            lens_name=lens_name,
                            generation_round=round_index + 1,
                            candidate=candidate,
                            stats=stats,
                        )
                        if feature_id is not None:
                            round_feature_ids.append(feature_id)
                previous_assessment = self._assess_layer2_coverage(
                    project_id=project_id,
                    pillar=pillar,
                    runtime_profile=runtime_profile,
                    product_idea=product_idea,
                    prompt_catalog=prompt_catalog,
                    scope_contract=scope_contract,
                    coverage_families=coverage_families,
                    newest_feature_ids=round_feature_ids,
                )
                stale_rounds = stale_rounds + 1 if len(round_feature_ids) == 0 else 0
                if self._layer2_should_stop(previous_assessment, stale_rounds):
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

    @staticmethod
    def _layer2_should_stop(assessment_memory: Any, stale_rounds: int) -> bool:
        """Stop once scoped coverage is saturated or repeated rounds add nothing useful."""
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
        return bool(families) and not open_families

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

    def _find_layer2_overlap(self, project_id: str, candidate: Layer2Candidate) -> tuple[Any | None, float]:
        """Find the strongest existing Layer 2 duplicate candidate without deleting either record."""
        best_feature = None
        best_score = 0.0
        candidate_text = f"{candidate.canonical_name} {candidate.description} {' '.join(candidate.aliases)}"
        for feature in self.db.list_layer2_features(project_id):
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

