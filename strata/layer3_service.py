from __future__ import annotations

import json
import re
import uuid
from typing import Any

from pydantic import ValidationError

from strata.llm import LLMError
from strata.models import FeatureExpansionResponse
from strata.prompts import build_layer3_feature_expansion_prompt


IMPLEMENTATION_LEAKAGE_PATTERNS = [
    r"\bapi (?:contracts?|endpoints?|requests?|responses?)\b",
    r"\bdatabase (?:schemas?|tables?|columns?|migrations?)\b",
    r"\b(?:react|vue|angular|frontend) components?\b",
    r"\bfrontend\b",
    r"\bbackend\b",
    r"\bserver-side\b",
    r"\bpayload\b",
    r"\bregex(?:p| pattern)?\b",
    r"\b(?:unit |integration )?test cases?\b",
    r"\bacceptance criteria\b",
    r"\b(?:sql|graphql)\b",
    r"\bhttp (?:methods?|statuses|status codes?)\b",
    r"\buser stor(?:y|ies)\b",
    r"\bwireframe\b",
    r"\barchitecture diagram\b",
    r"\bcoding task\b",
]


def validate_product_level_content(payload: Any) -> None:
    """Reject manual or generated Layer 3 content that crosses into implementation specs."""
    serialized = json.dumps(payload, ensure_ascii=True).casefold()
    if any(re.search(pattern, serialized) for pattern in IMPLEMENTATION_LEAKAGE_PATTERNS):
        raise ValueError("Layer 3 content must stay at product-feature level and cannot include implementation specs.")


class Layer3ServiceMixin:
    """Generate product-level Layer 3 feature expansions."""

    def generate_feature_expansions(
        self,
        project_id: str,
        feature_ids: list[str],
        *,
        thinking_enabled: bool = False,
    ) -> list[Any]:
        """Generate editable subfeature/configuration expansions for approved Layer 2 features."""
        runtime_profile = self._project_llm_runtime(project_id, "layer3_generation")
        self._ensure_profile_loaded(runtime_profile, thinking_enabled=thinking_enabled)
        prompt_catalog = self._prompt_catalog(project_id)
        project = self.db.get_project(project_id)
        brief = self.db.get_project_brief(project_id)
        graph = self.db.layer2_graph_snapshot(project_id)
        all_features = {item.id: item for item in self.db.list_layer2_features(project_id)}
        graph_relationships = graph.get("relationships", [])
        created = []
        for feature_id in feature_ids:
            feature = all_features.get(feature_id)
            if feature is None or feature.project_id != project_id:
                raise ValueError(f"Layer 2 feature not found in project: {feature_id}")
            if feature.status != "approved":
                raise ValueError(f"Layer 2 feature must be approved before Layer 3 expansion: {feature_id}")
            pillar = self.db.get_node(feature.owner_pillar_id)
            siblings = [
                self._layer3_feature_context(item)
                for item in all_features.values()
                if item.id != feature.id and item.status in {"kept", "approved"} and item.owner_pillar_id == feature.owner_pillar_id
            ]
            relevant_edges = [
                edge for edge in graph_relationships
                if feature.id in {edge.get("source_feature_id"), edge.get("target_feature_id")}
            ]
            existing = self.db.get_layer3_expansion_for_feature(project_id, feature.id)
            prompt = build_layer3_feature_expansion_prompt(
                project_context={
                    "project_id": project.id,
                    "product_idea": brief.product_idea if brief else project.idea,
                    "target_users": brief.target_users if brief else "",
                    "goals": brief.goals if brief else [],
                    "constraints": brief.constraints if brief else "",
                },
                pillar_context={
                    "pillar_id": pillar.id,
                    "title": pillar.title,
                    "description": pillar.description or "",
                },
                feature_context=self._layer3_feature_context(feature),
                sibling_features=siblings,
                graph_relationships=relevant_edges,
                existing_expansion=existing.model_dump(mode="json") if existing else {},
                prompt_catalog=prompt_catalog,
            )
            response, expansion = self._call_structured_json_pass(
                project_id=project_id,
                node_id=pillar.id,
                prompt=prompt,
                runtime_profile=runtime_profile,
                max_tokens=900,
                validator=self._validate_feature_expansion,
                schema_label="layer3_feature_expansion",
                schema_instructions="Return {'expansion': {feature_intent, expansion_groups, overlap_review, open_questions}}.",
            )
            payload = self._normalize_feature_expansion(expansion.expansion.model_dump(mode="json"))
            self._validate_overlap_targets(payload, feature.id, all_features)
            validate_product_level_content(payload)
            saved = self.db.upsert_layer3_expansion(
                project_id=project_id,
                feature_id=feature.id,
                parent_pillar_id=pillar.id,
                parent_pillar_title=pillar.title,
                feature_name=feature.canonical_name,
                feature_description=feature.description,
                feature_intent=payload["feature_intent"],
                expansion_groups=payload["expansion_groups"],
                overlap_review=payload["overlap_review"],
                open_questions=payload["open_questions"],
                review_state="draft",
                provenance={
                    "source_layer0_brief_id": brief.id if brief else None,
                    "source_layer1_pillar_id": pillar.id,
                    "source_layer2_feature_id": feature.id,
                    "source_layer2_candidate_ids": feature.candidate_source_ids,
                    "source_model": getattr(response, "model_name", None) or self._runtime_model_name(runtime_profile),
                    "thinking_enabled": thinking_enabled,
                },
            )
            self.db.record_layer3_expansion_action(
                project_id=project_id,
                expansion_id=saved.id,
                action_type="generate",
                payload={"feature_id": feature.id},
            )
            created.append(saved)
        return created

    @staticmethod
    def _validate_feature_expansion(payload: dict[str, Any]) -> FeatureExpansionResponse:
        try:
            return FeatureExpansionResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid Feature Expansion payload: {exc}") from exc

    @staticmethod
    def _normalize_feature_expansion(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "feature_intent": str(payload.get("feature_intent") or "").strip(),
            "expansion_groups": [],
            "overlap_review": payload.get("overlap_review") if isinstance(payload.get("overlap_review"), list) else [],
            "open_questions": [
                str(item).strip()
                for item in payload.get("open_questions", [])
                if str(item).strip()
            ],
        }
        if not normalized["feature_intent"]:
            raise LLMError("Feature Expansion response must include feature_intent.")
        for group in payload.get("expansion_groups", []):
            if not isinstance(group, dict):
                continue
            group_name = str(group.get("name") or "").strip()
            if not group_name:
                continue
            options = []
            for option in group.get("options", []):
                if not isinstance(option, dict):
                    continue
                option_name = str(option.get("name") or "").strip()
                if not option_name:
                    continue
                selection_state = str(option.get("selection_state") or "undecided")
                if selection_state not in {"include", "exclude", "undecided"}:
                    selection_state = "undecided"
                configuration_kind = str(option.get("configuration_kind") or "other")
                if configuration_kind not in {
                    "boolean", "single_select", "multi_select", "numeric", "text",
                    "rule", "workflow", "content", "integration", "other",
                }:
                    configuration_kind = "other"
                options.append({
                    "id": str(option.get("id") or uuid.uuid4()),
                    "name": option_name,
                    "description": str(option.get("description") or "").strip(),
                    "selection_state": selection_state,
                    "configuration_kind": configuration_kind,
                    "default_recommendation": str(option.get("default_recommendation") or "").strip(),
                    "rationale": str(option.get("rationale") or "").strip(),
                    "dependencies": [
                        str(item).strip()
                        for item in option.get("dependencies", [])
                        if str(item).strip()
                    ],
                    "overlaps_feature_ids": [
                        str(item).strip()
                        for item in option.get("overlaps_feature_ids", [])
                        if str(item).strip()
                    ],
                })
            normalized["expansion_groups"].append({
                "id": str(group.get("id") or uuid.uuid4()),
                "name": group_name,
                "description": str(group.get("description") or "").strip(),
                "options": options,
            })
        if not normalized["expansion_groups"]:
            raise LLMError("Feature Expansion response must include at least one expansion group.")
        return normalized

    @staticmethod
    def _validate_overlap_targets(payload: dict[str, Any], source_feature_id: str, all_features: dict[str, Any]) -> None:
        allowed_feature_ids = {
            feature.id
            for feature in all_features.values()
            if feature.status in {"kept", "approved"} and feature.id != source_feature_id
        }
        invalid = [
            target_id
            for group in payload.get("expansion_groups", [])
            for option in group.get("options", [])
            for target_id in option.get("overlaps_feature_ids", [])
            if target_id not in allowed_feature_ids
        ]
        if invalid:
            raise ValueError("Layer 3 overlap links require active Layer 2 feature targets.")

    @staticmethod
    def _layer3_feature_context(feature: Any) -> dict[str, Any]:
        return {
            "feature_id": feature.id,
            "canonical_name": feature.canonical_name,
            "description": feature.description,
            "feature_type": feature.feature_type,
            "coverage_family": getattr(feature, "coverage_family", ""),
            "aliases": getattr(feature, "aliases", []),
            "depends_on": getattr(feature, "depends_on", []),
            "used_by": getattr(feature, "used_by", []),
            "notes": getattr(feature, "notes", ""),
        }
