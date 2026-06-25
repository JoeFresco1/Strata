from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from strata.llm import LLMError
from strata.models import (
    CapabilityDesignResponse,
    CapabilityPressureTestResponse,
)
from strata.prompts import build_layer3_capability_prompt, build_layer3_pressure_test_prompt


LAYER3_CARD_SECTIONS = [
    "product_purpose",
    "feature_archetype",
    "supported_variants",
    "configurable_options",
    "product_behaviors",
    "validation_constraints",
    "lifecycle_states",
    "relationships",
    "dependencies",
    "overlaps_conflicts",
    "edge_cases",
    "product_risks",
    "open_decisions",
]

IMPLEMENTATION_LEAKAGE_PATTERNS = [
    r"\bapi (?:contracts?|endpoints?|requests?|responses?)\b",
    r"\bdatabase (?:schemas?|tables?|columns?|migrations?)\b",
    r"\b(?:react|vue|angular|frontend) components?\b",
    r"\bfrontend\b",
    r"\bbackend\b",
    r"\bserver-side\b",
    r"\basynchronous processing\b",
    r"\bpayload\b",
    r"\bbuffer limits?\b",
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
        raise ValueError("Layer 3 content must stay at product-definition level and cannot include implementation specs.")


class Layer3ServiceMixin:
    """Generate and pressure-test product-level Layer 3 Capability Design Cards."""

    def generate_capability_cards(
        self,
        project_id: str,
        feature_ids: list[str],
        *,
        thinking_enabled: bool = False,
        selected_sections: list[str] | None = None,
    ) -> list[Any]:
        """Generate or selectively refresh cards for approved Layer 2 features."""
        requested_sections = self._valid_layer3_sections(selected_sections)
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
                raise ValueError(f"Layer 2 feature must be approved before Layer 3 generation: {feature_id}")
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
            existing = self.db.get_layer3_card_for_feature(project_id, feature.id)
            existing_payload = self._layer3_existing_payload(existing)
            if existing is not None:
                existing_payload["relationships"] = [
                    item.model_dump(mode="json") for item in self.db.list_layer3_relationships(existing.id)
                ]
                existing_payload["open_decisions"] = [
                    item.model_dump(mode="json") for item in self.db.list_layer3_decisions(existing.id)
                ]
            merged = self._empty_layer3_payload(existing_payload)
            response = None
            for section_batch in self._layer3_generation_batches(requested_sections):
                prompt = build_layer3_capability_prompt(
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
                    existing_card=merged,
                    selected_sections=section_batch,
                    prompt_catalog=prompt_catalog,
                )
                response, generated_payload = self._call_structured_json_pass(
                    project_id=project_id,
                    node_id=pillar.id,
                    prompt=prompt,
                    runtime_profile=runtime_profile,
                    max_tokens=380,
                    validator=lambda payload, sections=section_batch: self._validate_capability_section(payload, sections),
                    schema_label="capability_design_sections",
                    schema_instructions=f"Return {{'card': {{only these fields: {', '.join(section_batch)}}}}} with product-level content only.",
                )
                generated_payload = self._normalize_layer3_collections(generated_payload)
                merged = self._merge_layer3_sections(merged, generated_payload, section_batch)
            known_feature_ids = {
                item.id for item in all_features.values()
                if item.status in {"kept", "approved"}
            }
            allowed_relationships = {
                "depends_on", "feeds", "overlaps_with", "conflicts_with", "optionally_uses", "shared_concern",
            }
            merged["relationships"] = [
                item for item in merged["relationships"]
                if isinstance(item, dict)
                and item.get("relationship_type") in allowed_relationships
                and item.get("target_feature_id") in known_feature_ids
                and item.get("target_feature_id") != feature.id
            ]
            merged["open_decisions"] = [
                item for item in merged["open_decisions"]
                if isinstance(item, dict) and str(item.get("question", "")).strip()
            ]
            pressure_prompt = build_layer3_pressure_test_prompt(
                card={key: value for key, value in merged.items() if key not in {"relationships", "open_decisions"}},
                relationships=merged["relationships"],
                open_decisions=merged["open_decisions"],
                prompt_catalog=prompt_catalog,
            )
            _, pressure = self._call_structured_json_pass(
                project_id=project_id,
                node_id=pillar.id,
                prompt=pressure_prompt,
                runtime_profile=runtime_profile,
                max_tokens=250,
                temperature=0.1,
                validator=self._validate_capability_pressure_test,
                schema_label="capability_pressure_test",
                schema_instructions="Return {'pressure_test': {ambiguity, product_risk, overreach, missing_decisions, downstream_blockers, implementation_leakage, downstream_readiness_score, readiness_rationale}}.",
            )
            pressure_payload = pressure.pressure_test.model_dump(mode="json")
            pressure_payload = self._sanitize_pressure_test(pressure_payload)
            readiness = self._bounded_layer3_readiness(pressure_payload, merged["open_decisions"])
            card = self.db.upsert_layer3_card(
                project_id=project_id,
                feature_id=feature.id,
                parent_pillar_id=pillar.id,
                parent_pillar_title=pillar.title,
                feature_name=feature.canonical_name,
                feature_description=feature.description,
                product_purpose=merged["product_purpose"],
                feature_archetype=merged["feature_archetype"],
                supported_variants=merged["supported_variants"],
                configurable_options=merged["configurable_options"],
                product_behaviors=merged["product_behaviors"],
                validation_constraints=merged["validation_constraints"],
                lifecycle_states=merged["lifecycle_states"],
                dependencies=merged["dependencies"],
                overlaps_conflicts=merged["overlaps_conflicts"],
                edge_cases=merged["edge_cases"],
                product_risks=merged["product_risks"],
                pressure_test=pressure_payload,
                downstream_readiness_score=readiness,
                readiness_rationale=pressure_payload["readiness_rationale"],
                review_state="draft",
                provenance={
                    "source_layer0_brief_id": brief.id if brief else None,
                    "source_layer1_pillar_id": pillar.id,
                    "source_layer2_feature_id": feature.id,
                    "source_layer2_candidate_ids": feature.candidate_source_ids,
                    "source_model": getattr(response, "model_name", None) or self._runtime_model_name(runtime_profile),
                    "thinking_enabled": thinking_enabled,
                    "selected_sections": requested_sections,
                },
            )
            self.db.replace_layer3_relationships(
                project_id=project_id,
                card_id=card.id,
                source_feature_id=feature.id,
                relationships=merged["relationships"],
            )
            self.db.replace_layer3_decisions(
                project_id=project_id,
                card_id=card.id,
                decisions=merged["open_decisions"],
            )
            self.db.record_layer3_review_action(
                project_id=project_id,
                card_id=card.id,
                action_type="regenerate_sections" if selected_sections else "generate",
                payload={"sections": requested_sections},
            )
            created.append(card)
        return created

    def pressure_test_capability_card(
        self,
        project_id: str,
        card_id: str,
        *,
        thinking_enabled: bool = False,
    ) -> Any:
        """Recalculate pressure findings and readiness after human card edits."""
        card = self.db.get_layer3_card(card_id)
        if card.project_id != project_id:
            raise ValueError("Layer 3 card belongs to another project.")
        feature = self.db.get_layer2_feature(card.feature_id)
        if feature.project_id != project_id or feature.status != "approved":
            raise ValueError("The source Layer 2 feature must be approved before pressure testing.")
        runtime_profile = self._project_llm_runtime(project_id, "layer3_generation")
        self._ensure_profile_loaded(runtime_profile, thinking_enabled=thinking_enabled)
        relationships = [
            item.model_dump(mode="json") for item in self.db.list_layer3_relationships(card.id)
        ]
        decisions = [
            item.model_dump(mode="json") for item in self.db.list_layer3_decisions(card.id)
        ]
        prompt = build_layer3_pressure_test_prompt(
            card=card.model_dump(mode="json"),
            relationships=relationships,
            open_decisions=decisions,
            prompt_catalog=self._prompt_catalog(project_id),
        )
        _, pressure = self._call_structured_json_pass(
            project_id=project_id,
            node_id=card.parent_pillar_id,
            prompt=prompt,
            runtime_profile=runtime_profile,
            max_tokens=250,
            temperature=0.1,
            validator=self._validate_capability_pressure_test,
            schema_label="capability_pressure_test",
            schema_instructions="Return the Layer 3 pressure-test fields and readiness score.",
        )
        pressure_payload = self._sanitize_pressure_test(pressure.pressure_test.model_dump(mode="json"))
        unresolved = [item for item in decisions if item["status"] == "unresolved"]
        updated = self.db.update_layer3_card(
            card.id,
            pressure_test=pressure_payload,
            downstream_readiness_score=self._bounded_layer3_readiness(pressure_payload, unresolved),
            readiness_rationale=pressure_payload["readiness_rationale"],
            review_state="needs_review",
        )
        self.db.record_layer3_review_action(
            project_id=project_id,
            card_id=card.id,
            action_type="pressure_test",
            payload={"thinking_enabled": thinking_enabled},
        )
        return updated

    @staticmethod
    def _valid_layer3_sections(selected_sections: list[str] | None) -> list[str]:
        """Normalize selective rerun fields against the public Layer 3 section vocabulary."""
        if not selected_sections:
            return list(LAYER3_CARD_SECTIONS)
        invalid = sorted(set(selected_sections) - set(LAYER3_CARD_SECTIONS))
        if invalid:
            raise ValueError(f"Unsupported Layer 3 sections: {', '.join(invalid)}")
        return list(dict.fromkeys(selected_sections))

    @staticmethod
    def _layer3_feature_context(feature: Any) -> dict[str, Any]:
        """Compress one Layer 2 feature into bounded Layer 3 prompt context."""
        return {
            "feature_id": feature.id,
            "canonical_name": feature.canonical_name,
            "description": feature.description,
            "feature_type": feature.feature_type,
            "granularity_class": str(feature.granularity_class.value if hasattr(feature.granularity_class, "value") else feature.granularity_class),
            "owner_pillar_id": feature.owner_pillar_id,
            "depends_on_feature_ids": feature.depends_on_feature_ids,
            "used_by_feature_ids": feature.used_by_feature_ids,
            "metadata": {
                key: feature.metadata.get(key)
                for key in ("coverage_family", "priority", "notes")
                if feature.metadata.get(key)
            },
        }

    @staticmethod
    def _layer3_existing_payload(card: Any | None) -> dict[str, Any]:
        """Return only editable/generated sections from an existing card."""
        if card is None:
            return {}
        payload = card.model_dump(mode="json")
        return {key: payload.get(key) for key in LAYER3_CARD_SECTIONS if key not in {"relationships", "open_decisions"}}

    @staticmethod
    def _merge_layer3_sections(existing: dict[str, Any], generated: dict[str, Any], sections: list[str]) -> dict[str, Any]:
        """Preserve untouched sections during a selective rerun."""
        merged = {**generated}
        for section in LAYER3_CARD_SECTIONS:
            if section not in sections and section in existing:
                merged[section] = existing[section]
        merged.setdefault("relationships", [])
        merged.setdefault("open_decisions", [])
        return merged

    @staticmethod
    def _empty_layer3_payload(existing: dict[str, Any]) -> dict[str, Any]:
        """Seed multi-pass generation with a complete compact card shape."""
        seeded = {
            "product_purpose": "",
            "feature_archetype": "other",
            **{key: [] for key in LAYER3_CARD_SECTIONS if key not in {"product_purpose", "feature_archetype"}},
        }
        return {**seeded, **existing}

    @staticmethod
    def _layer3_generation_batches(sections: list[str]) -> list[list[str]]:
        """Split full-card generation so slower local models finish valid JSON inside request limits."""
        if len(sections) <= 7:
            return [sections]
        first = {"product_purpose", "feature_archetype", "supported_variants", "configurable_options"}
        second = {"product_behaviors", "validation_constraints", "lifecycle_states", "edge_cases"}
        return [batch for batch in [
            [section for section in sections if section in first],
            [section for section in sections if section in second],
            [section for section in sections if section not in first | second],
        ] if batch]

    @staticmethod
    def _normalize_layer3_collections(payload: dict[str, Any]) -> dict[str, Any]:
        """Expand compact local-model strings into the persisted structured section shape."""
        field_keys = {
            "supported_variants": "name",
            "configurable_options": "name",
            "product_behaviors": "behavior",
            "validation_constraints": "concept",
            "lifecycle_states": "state",
        }
        normalized = {**payload}
        for field, key in field_keys.items():
            normalized[field] = [
                item if isinstance(item, dict) else {key: str(item)}
                for item in payload.get(field, [])
            ]
        for field in ("dependencies", "overlaps_conflicts", "edge_cases", "product_risks"):
            normalized[field] = [
                Layer3ServiceMixin._layer3_list_text(item)
                for item in payload.get(field, [])
                if Layer3ServiceMixin._layer3_list_text(item)
            ]
        return normalized

    @staticmethod
    def _layer3_list_text(item: Any) -> str:
        """Collapse unexpected object-shaped list items back to product-level summary text."""
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, dict):
            for key in ("risk", "name", "description", "summary", "concept"):
                if str(item.get(key, "")).strip():
                    return str(item[key]).strip()
        return ""

    @staticmethod
    def _sanitize_pressure_test(pressure: dict[str, Any]) -> dict[str, Any]:
        """Remove empty findings and prevent the critic itself from leaking implementation detail."""
        cleaned = {**pressure}
        list_fields = [
            "ambiguity", "product_risk", "overreach", "missing_decisions",
            "downstream_blockers", "implementation_leakage",
        ]
        leakage_reported = any(
            str(item).strip().casefold() not in {"", "none", "none identified", "none identified."}
            for item in cleaned.get("implementation_leakage", [])
        )
        for field in list_fields:
            values = [
                str(item).strip()
                for item in cleaned.get(field, [])
                if str(item).strip() and str(item).strip().casefold() not in {"none", "none identified", "none identified."}
            ]
            safe_values = []
            for value in values:
                try:
                    validate_product_level_content(value)
                    safe_values.append(value)
                except ValueError:
                    continue
            cleaned[field] = safe_values
        try:
            validate_product_level_content(cleaned.get("readiness_rationale", ""))
        except ValueError:
            cleaned["readiness_rationale"] = "Product decisions or dependencies remain unresolved before downstream work."
        if leakage_reported:
            cleaned["implementation_leakage"] = [
                "Implementation-level detail was detected in the card review."
            ]
        return cleaned

    @staticmethod
    def _validate_capability_design(payload: dict[str, Any]) -> CapabilityDesignResponse:
        """Validate card structure and reject implementation-spec leakage."""
        try:
            validated = CapabilityDesignResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid Capability Design Card payload: {exc}") from exc
        try:
            validate_product_level_content(validated.model_dump(mode="json"))
        except ValueError as exc:
            raise LLMError(str(exc)) from exc
        return validated

    @staticmethod
    def _validate_capability_section(payload: dict[str, Any], sections: list[str]) -> dict[str, Any]:
        """Validate one compact section batch before merging it into the complete card."""
        card = payload.get("card")
        if not isinstance(card, dict):
            raise LLMError("Capability Design section response must contain a card object.")
        missing = [section for section in sections if section not in card]
        if missing:
            raise LLMError(f"Capability Design section response is missing: {', '.join(missing)}")
        selected = {section: card[section] for section in sections}
        try:
            validate_product_level_content(selected)
        except ValueError as exc:
            raise LLMError(str(exc)) from exc
        return selected

    @staticmethod
    def _validate_capability_pressure_test(payload: dict[str, Any]) -> CapabilityPressureTestResponse:
        """Validate the independent pressure-test response."""
        try:
            return CapabilityPressureTestResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid Capability Design pressure test: {exc}") from exc

    @staticmethod
    def _bounded_layer3_readiness(pressure: dict[str, Any], decisions: list[dict[str, Any]]) -> int:
        """Enforce score ceilings for leakage, blockers, and unresolved product decisions."""
        score = int(pressure["downstream_readiness_score"])
        if pressure.get("implementation_leakage"):
            score = min(score, 40)
        if pressure.get("downstream_blockers"):
            score = min(score, 69)
        if decisions:
            score = min(score, 79)
        return max(0, min(100, score))
