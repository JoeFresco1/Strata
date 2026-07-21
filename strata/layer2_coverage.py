from __future__ import annotations

from typing import Any

from strata.layer2_constants import (
    LAYER2_COVERAGE_SCHEMA,
    LAYER2_EXHAUSTION_FAMILIES,
    LAYER2_LENSES,
    LAYER2_SURVEY_BUILDER_FAMILIES,
)
from strata.models import Layer2CoverageAssessmentResponse, Node
from strata.prompts import build_layer2_coverage_prompt
from strata.critic_policy import CriticAuthorityPolicy, CriticDisposition


class Layer2CoverageMixin:
    """Scope contract, coverage matrix, and exhaustion-stop helpers for Layer 2."""

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
        newest_features = [item for item in current_features if item["id"] in set(newest_feature_ids)]
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
        policy = CriticAuthorityPolicy(self.db)
        for feature_id in drifted_feature_ids:
            try:
                feature = self.db.get_layer2_feature(feature_id)
            except ValueError:
                continue
            if feature.project_id != project_id:
                continue
            authority = policy.evaluate(
                project_id=project_id, artifact_type="layer2_feature", artifact_id=feature.id,
                current_review_state=feature.status, current_actor="model", current_origin="model_critic",
                proposed_action="route_for_review", source_freshness="unknown",
                is_new_unreviewed_candidate=feature.status == "candidate",
            )
            if authority.disposition != CriticDisposition.AUTOMATIC_ROUTING:
                self.db.create_critic_finding(
                    project_id=project_id, artifact_type="layer2_feature", artifact_id=feature.id,
                    critic_type="layer2_coverage_critic", category="scope_drift", severity="medium",
                    explanation="Coverage critic identified possible scope drift.",
                    evidence={"feature_id": feature.id, "status": feature.status},
                    recommended_action="Review scope and decide whether to reroute this feature.",
                    source_payload={"feature_id": feature.id, "category": "scope_drift"},
                )
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
