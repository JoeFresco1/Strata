from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from strata.discovery_models import (
    CompetitiveContextProjection,
    CompetitorResearchMode,
    DiscoveryLens,
    DiscoveryReviewFinding,
    Layer1DiscoveryContextProjection,
    ModelRuntimeProvenance,
    ProductDiscovery,
    ProductDiscoveryRevision,
)
from strata.execution_policy import resolve_llm_profile, resolved_runtime_request
from strata.project_settings import default_project_model_settings, normalize_project_model_settings
from strata.prompts import build_system_prompt, render_prompt
from strata.telemetry import model_call_context


DISCOVERY_PROMPT_KEY = "product_discovery_generation_v1"
DISCOVERY_PROMPT_VERSION = "1.0.0"
DISCOVERY_REVIEW_VERSION = "deterministic-practicality-v1"
DISCOVERY_PROJECTION_COMPILER_VERSION = "discovery-projection-v1"

BASELINE_LENSES = (
    (
        "actors-and-users",
        "Actors and users",
        "Examine every person or organization that uses, operates, buys, governs, supports, or is affected by the product.",
    ),
    (
        "workflows-and-lifecycle",
        "Workflows and lifecycle",
        "Examine configuration, deployment, operation, support, governance, change, and retirement workflows.",
    ),
    (
        "data-and-integrations",
        "Data and integrations",
        "Examine data inputs, outputs, quality, ownership, interoperability, connectors, and ecosystem boundaries.",
    ),
    (
        "administration-and-operations",
        "Administration and operations",
        "Examine tenant and platform administration, including super-administration, delegated control, support, and observability.",
    ),
    (
        "trust-security-privacy-governance",
        "Trust, security, privacy, and governance",
        "Examine access, consent, privacy, security, compliance, explainability, oversight, and audit needs.",
    ),
    (
        "failure-modes-and-recovery",
        "Failure modes and recovery",
        "Examine degraded behavior, incident response, backup, recovery, migration, and safe failure handling.",
    ),
    (
        "commercial-and-platform-obligations",
        "Commercial and platform obligations",
        "Examine entitlements, packaging, metering, billing, quotas, accessibility, localization, and enterprise readiness.",
    ),
)


class DiscoveryService:
    """Generate, review, version, and compact Product Discovery artifacts."""

    def __init__(self, services: Any):
        """Bind discovery behavior to existing database and local-first runtime services."""
        self.services = services
        self.db = services.db

    def generate_candidate(
        self,
        *,
        project_id: str,
        competitor_research_mode: str,
        generation_job_id: str | None = None,
        competitor_research_revision_id: str | None = None,
        settings_snapshot: dict[str, Any] | None = None,
        command_id: str = "",
    ) -> ProductDiscoveryRevision:
        """Run one explicit discovery generation without starting Layer 1 or research."""
        brief = self.services.brief_service.ensure_brief(project_id)
        if brief.status != "published" or not brief.current_published_revision_id:
            raise ValueError("Publish the Layer 0 brief before generating Product Discovery.")
        mode = CompetitorResearchMode(competitor_research_mode)
        if mode == CompetitorResearchMode.NONE and competitor_research_revision_id:
            raise ValueError("Disabled competitor research cannot be attached to discovery.")
        settings = settings_snapshot or self._project_model_settings(project_id)
        discovery_settings = dict(settings.get("discovery_settings") or {})
        runtime = self._runtime(settings)
        prompt = self._generation_prompt(brief.model_dump(mode="json"), mode)
        started = time.perf_counter()
        response = self.services.generation_service.llm_client.generate_json(
            system_prompt=build_system_prompt(),
            user_prompt=prompt,
            base_url=runtime.get("base_url"),
            model_name=runtime.get("model_name"),
            temperature=float(discovery_settings.get("generation_temperature", 0.7)),
            max_tokens=min(
                int(discovery_settings.get("generation_max_output_tokens") or 8000),
                int(runtime.get("max_output_tokens") or 8000),
            ),
            telemetry=model_call_context(
                project_id=project_id,
                layer="layer0",
                workflow="product_discovery_generation",
                runtime_profile=runtime,
                run_id=generation_job_id,
                prompt_key=DISCOVERY_PROMPT_KEY,
                metadata={
                    "prompt_version": DISCOVERY_PROMPT_VERSION,
                    "competitor_research_mode": mode.value,
                    "temperature": float(discovery_settings.get("generation_temperature", 0.7)),
                    "seed": discovery_settings.get("seed"),
                },
            ),
        )
        elapsed = time.perf_counter() - started
        normalized = self.normalize_discovery(
            project_id,
            response.parsed_json.get("discovery", response.parsed_json),
        )
        reviews = self.review_discovery(normalized)
        previous = self._latest_discovery_revision(project_id)
        human_fields = dict(previous.human_owned_fields) if previous else {}
        provenance = self._runtime_provenance(
            runtime,
            response.raw_payload,
            response.model_name,
            elapsed,
            temperature=float(discovery_settings.get("generation_temperature", 0.7)),
            seed=discovery_settings.get("seed"),
        )
        return self.db.create_discovery_revision(
            project_id=project_id,
            source_brief_revision_id=str(brief.current_published_revision_id),
            competitor_research_mode=mode.value,
            payload=normalized.model_dump(mode="json"),
            model_authored_fields={
                "raw_response": response.content,
                "parsed_response": response.parsed_json,
                "prompt_key": DISCOVERY_PROMPT_KEY,
                "prompt_version": DISCOVERY_PROMPT_VERSION,
            },
            human_owned_fields=human_fields,
            review_findings=[item.model_dump(mode="json") for item in reviews],
            runtime_provenance=[provenance.model_dump(mode="json")],
            generation_job_id=generation_job_id,
            competitor_research_revision_id=competitor_research_revision_id,
            command_id=command_id,
            actor="product_discovery_workflow",
            origin="model_generation",
        )

    def normalize_discovery(self, project_id: str, payload: dict[str, Any]) -> ProductDiscovery:
        """Assign stable IDs and enforce the non-optional baseline lens policy."""
        normalized = dict(payload or {})
        section_names = {
            "archetypes": "archetype",
            "lenses": "lens",
            "actors": "actor",
            "lifecycle_stages": "lifecycle",
            "enterprise_obligations": "obligation",
            "domains": "domain",
            "cross_domain_opportunities": "opportunity",
            "coverage_risks": "risk",
            "open_questions": "question",
        }
        for section, item_type in section_names.items():
            items = normalized.get(section)
            if not isinstance(items, list):
                items = []
            normalized[section] = [
                self._normalize_generated_item(
                    section,
                    self._stable_item(project_id, item_type, item, index),
                )
                for index, item in enumerate(items)
                if isinstance(item, dict)
            ]
        normalized["lenses"] = self._merge_baseline_lenses(project_id, normalized["lenses"])
        normalized["lenses"] = self._attach_required_lens_sources(normalized)
        normalized["summary"] = self._summary(normalized)
        return ProductDiscovery.model_validate(normalized)

    @staticmethod
    def _normalize_generated_item(section: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Coerce near-miss model labels to conservative schema values without dropping content."""
        item = dict(payload)
        list_fields = {
            "archetypes": ("brief_evidence", "product_design_implications", "related_lens_ids", "related_actor_ids", "related_obligation_ids"),
            "lenses": ("questions", "expected_product_territory", "applicable_actor_ids", "required_discovery_item_ids", "related_lens_ids", "omission_risks", "supporting_competitor_ids", "evidence_ids"),
            "actors": ("goals", "responsibilities", "workflows", "decisions", "information_needed", "risks", "relevant_lens_ids", "likely_product_areas", "lifecycle_stage_ids", "competitor_expectations"),
            "lifecycle_stages": ("actor_ids", "workflows", "decisions", "failure_modes", "administration_needs", "data_requirements", "likely_capabilities", "competitor_maturity_signals", "unresolved_coverage_risk_ids"),
            "enterprise_obligations": ("affected_actor_ids", "competitor_evidence_ids"),
            "domains": ("actor_ids", "workflows", "dependencies", "risks", "related_lens_ids", "candidate_capabilities", "brief_evidence", "competitor_evidence_ids", "downstream_classifications"),
            "cross_domain_opportunities": ("affected_domain_ids", "required_data", "risks", "evidence_or_provenance"),
            "coverage_risks": ("evidence", "affected_actor_ids", "affected_lens_ids", "competitor_evidence_ids"),
            "open_questions": ("affected_domain_ids", "affected_actor_ids", "affected_lens_ids", "competitor_evidence_ids"),
        }
        for field in list_fields.get(section, ()):
            value = item.get(field)
            if isinstance(value, list):
                continue
            item[field] = [] if value is None or value == "" else [value]
        if section == "lenses":
            layers = item.get("applicable_downstream_layers")
            if not isinstance(layers, list):
                layers = [] if layers is None else [layers]
            parsed_layers: list[int] = []
            for value in layers:
                try:
                    layer = int(value)
                except (TypeError, ValueError):
                    continue
                if layer in {1, 2, 3} and layer not in parsed_layers:
                    parsed_layers.append(layer)
            item["applicable_downstream_layers"] = parsed_layers or [1, 2, 3]
        allowed_source = {"baseline", "model_discovered", "competitor_research", "human_added"}
        if item.get("source") not in allowed_source:
            item["source"] = "model_discovered"
        if item.get("downstream_state") not in {"required", "optional", "excluded"}:
            item["downstream_state"] = "optional"
        enum_defaults = {
            "lenses": ("recommendation", {"required", "recommended", "optional", "rejected"}, "optional"),
            "enterprise_obligations": (
                "strategic_classification",
                {"table_stakes", "market_standard", "emerging", "differentiating", "optional", "out_of_scope"},
                "optional",
            ),
            "cross_domain_opportunities": (
                "speculation_level",
                {"concrete", "speculative", "superficial_metaphor", "unusual_but_defensible", "requires_human_review"},
                "requires_human_review",
            ),
            "coverage_risks": ("severity", {"low", "medium", "high", "critical"}, "medium"),
            "open_questions": (
                "disposition",
                {"requires_human_answer_before_layer1", "useful_but_non_blocking", "safe_for_model_assumption", "intentionally_open"},
                "useful_but_non_blocking",
            ),
        }
        rule = enum_defaults.get(section)
        if rule is not None and item.get(rule[0]) not in rule[1]:
            item[rule[0]] = rule[2]
        for field in ("confidence", "relevance_score"):
            if field in item:
                try:
                    item[field] = min(1.0, max(0.0, float(item[field])))
                except (TypeError, ValueError):
                    item[field] = 0.5
        return item

    @staticmethod
    def _attach_required_lens_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Link each baseline lens to durable discovery items after stable IDs exist."""
        ids = {
            section: [str(item["id"]) for item in payload.get(section, [])]
            for section in (
                "actors", "lifecycle_stages", "enterprise_obligations", "domains",
                "coverage_risks", "cross_domain_opportunities", "open_questions",
            )
        }
        sources_by_title = {
            "Actors and users": ids["actors"],
            "Workflows and lifecycle": [*ids["lifecycle_stages"], *ids["actors"]],
            "Data and integrations": [*ids["domains"], *ids["cross_domain_opportunities"]],
            "Administration and operations": [*ids["enterprise_obligations"], *ids["actors"]],
            "Trust, security, privacy, and governance": [
                *ids["enterprise_obligations"], *ids["coverage_risks"],
            ],
            "Failure modes and recovery": [*ids["lifecycle_stages"], *ids["coverage_risks"]],
            "Commercial and platform obligations": [
                *ids["enterprise_obligations"], *ids["open_questions"],
            ],
        }
        lenses: list[dict[str, Any]] = []
        valid_ids = {item_id for section_ids in ids.values() for item_id in section_ids}
        for lens in payload.get("lenses", []):
            item = dict(lens)
            explicit = [
                str(value) for value in item.get("required_discovery_item_ids", [])
                if str(value) in valid_ids
            ]
            inferred = sources_by_title.get(str(item.get("title") or ""), [])
            item["required_discovery_item_ids"] = list(dict.fromkeys([*explicit, *inferred]))
            lenses.append(item)
        return lenses

    def review_discovery(self, discovery: ProductDiscovery) -> list[DiscoveryReviewFinding]:
        """Retain every generated item while assigning an explainable disposition."""
        findings: list[DiscoveryReviewFinding] = []
        sections: tuple[tuple[str, Iterable[Any]], ...] = (
            ("archetype", discovery.archetypes),
            ("lens", discovery.lenses),
            ("actor", discovery.actors),
            ("lifecycle_stage", discovery.lifecycle_stages),
            ("enterprise_obligation", discovery.enterprise_obligations),
            ("domain", discovery.domains),
            ("cross_domain_opportunity", discovery.cross_domain_opportunities),
            ("coverage_risk", discovery.coverage_risks),
            ("open_question", discovery.open_questions),
        )
        for item_type, items in sections:
            for item in items:
                outcome, rationale, confidence = self._review_outcome(item_type, item)
                findings.append(DiscoveryReviewFinding(
                    id=self._stable_id("review", item.id, DISCOVERY_REVIEW_VERSION),
                    item_type=item_type,
                    item_id=item.id,
                    original_output=item.model_dump(mode="json"),
                    outcome=outcome,
                    rationale=rationale,
                    reviewer_type="deterministic",
                    confidence=confidence,
                    human_review_required=outcome in {
                        "needs_human_review",
                        "rejected_as_superficial",
                        "rejected_as_bizarre",
                        "rejected_as_unsupported",
                    },
                ))
        return findings

    def build_layer1_projection(
        self,
        revision_id: str,
        *,
        command_id: str = "",
    ) -> dict[str, Any]:
        """Compile only approved, non-excluded discovery content deterministically."""
        revision = self.db.get_discovery_revision(revision_id)
        included: list[str] = []
        excluded: list[str] = []
        include_reason: dict[str, str] = {}
        exclude_reason: dict[str, str] = {}

        def select(items: Iterable[Any]) -> list[dict[str, Any]]:
            """Filter nested items solely from durable human/downstream state."""
            selected: list[dict[str, Any]] = []
            for item in items:
                human_state = str(
                    revision.human_owned_fields.get("item_states", {}).get(item.id)
                    or item.downstream_state
                )
                if human_state == "excluded":
                    excluded.append(item.id)
                    exclude_reason[item.id] = "Human exclusion or durable downstream exclusion state."
                    continue
                included.append(item.id)
                include_reason[item.id] = "Approved revision item not excluded by human authority."
                selected.append(item.model_dump(mode="json"))
            return selected

        required_lenses = []
        optional_lenses = []
        human_lenses = [
            DiscoveryLens.model_validate(item)
            for item in revision.human_owned_fields.get("added_lenses", [])
        ]
        for lens_payload in select([*revision.discovery.lenses, *human_lenses]):
            if lens_payload["recommendation"] == "required" or lens_payload["downstream_state"] == "required":
                required_lenses.append(lens_payload)
            else:
                optional_lenses.append(lens_payload)
        payload = {
            "required_lenses": required_lenses,
            "optional_lenses": optional_lenses,
            "actors": select(revision.discovery.actors),
            "domains": select(revision.discovery.domains),
            "enterprise_obligations": select(revision.discovery.enterprise_obligations),
            "cross_domain_opportunities": select(revision.discovery.cross_domain_opportunities),
            "open_questions": select(revision.discovery.open_questions),
            "unresolved_risks": select(revision.discovery.coverage_risks),
        }
        token_estimate = self._token_estimate(payload)
        record = self.db.persist_discovery_context_projection(
            project_id=revision.project_id,
            projection_type="layer1_discovery",
            discovery_revision_id=revision.id,
            competitor_research_revision_id=revision.competitor_research_revision_id,
            compiler_version=DISCOVERY_PROJECTION_COMPILER_VERSION,
            payload=payload,
            included_item_ids=included,
            excluded_item_ids=excluded,
            inclusion_rationale=include_reason,
            exclusion_rationale=exclude_reason,
            token_estimate=token_estimate,
            command_id=command_id,
        )
        typed_payload = {
            **record,
            **record["payload"],
            "source_discovery_revision_id": record["source_discovery_revision_id"],
            "source_competitor_research_revision_id": record["source_competitor_research_revision_id"],
            "unresolved_risks": record["payload"]["unresolved_risks"],
        }
        Layer1DiscoveryContextProjection.model_validate(typed_payload)
        return record

    def build_competitive_projection(
        self,
        discovery_revision_id: str,
        competitor_research_revision_id: str,
        *,
        command_id: str = "",
    ) -> dict[str, Any]:
        """Compile only human-approved competitive findings and concise citations."""
        discovery = self.db.get_discovery_revision(discovery_revision_id)
        research = self.db.get_competitor_research_revision(competitor_research_revision_id)
        if discovery.project_id != research.project_id:
            raise ValueError("Discovery and competitor research must belong to the same project.")
        if research.state.value not in {"approved", "published"}:
            raise ValueError("Competitive context requires approved competitor research.")
        finding_states = dict(research.human_decisions.get("finding_states") or {})
        finding_freshness = dict(research.human_decisions.get("finding_freshness") or {})
        included: list[str] = []
        excluded: list[str] = []
        include_reason: dict[str, str] = {}
        exclude_reason: dict[str, str] = {}

        def approved(item: Any) -> bool:
            """Resolve durable per-finding human authority before projection."""
            explicit = str(finding_states.get(item.id) or "")
            review_state = str(getattr(item, "human_review_state", "pending"))
            if finding_freshness.get(item.id) == "stale":
                excluded.append(item.id)
                exclude_reason[item.id] = "Competitive finding is independently stale."
                return False
            if explicit == "excluded" or review_state in {"rejected", "excluded"}:
                excluded.append(item.id)
                exclude_reason[item.id] = "Human-excluded competitive finding."
                return False
            if explicit not in {"required", "optional"} and review_state != "approved":
                excluded.append(item.id)
                exclude_reason[item.id] = "Competitive finding has not been human-approved."
                return False
            included.append(item.id)
            include_reason[item.id] = "Human-approved competitive finding."
            return True

        pillars = [item.model_dump(mode="json") for item in research.inferred_pillars if approved(item)]
        territories = [item for item in research.territories if approved(item)]
        gaps = [item for item in research.gaps if approved(item)]
        used_evidence_ids = {
            evidence_id
            for item in [*research.inferred_pillars, *research.territories, *research.gaps]
            if item.id in included
            for evidence_id in item.evidence_ids
        }
        evidence_references = [
            {
                key: value
                for key, value in item.model_dump(mode="json").items()
                if key in {
                    "id", "competitor_id", "source_title", "source_type", "source_publisher",
                    "source_location", "publication_date", "retrieval_date", "claim_type", "confidence",
                }
            }
            for item in research.evidence
            if item.id in used_evidence_ids
        ]
        payload = {
            "inferred_competitor_pillars": pillars,
            "table_stakes_territories": [
                item.model_dump(mode="json") for item in territories
                if item.classification == "table_stakes"
            ],
            "emerging_patterns": [
                item.model_dump(mode="json") for item in territories
                if item.classification == "emerging_pattern"
            ],
            "differentiation_opportunities": [
                item.model_dump(mode="json") for item in territories
                if item.classification == "differentiation_opportunity"
            ],
            "market_gaps": [item.model_dump(mode="json") for item in gaps],
            "concise_evidence_references": evidence_references,
            "unresolved_risks": [
                item.model_dump(mode="json")
                for item in discovery.discovery.coverage_risks
                if item.downstream_state != "excluded"
            ],
        }
        record = self.db.persist_discovery_context_projection(
            project_id=discovery.project_id,
            projection_type="competitive",
            discovery_revision_id=discovery.id,
            competitor_research_revision_id=research.id,
            compiler_version=DISCOVERY_PROJECTION_COMPILER_VERSION,
            payload=payload,
            included_item_ids=included,
            excluded_item_ids=excluded,
            inclusion_rationale=include_reason,
            exclusion_rationale=exclude_reason,
            token_estimate=self._token_estimate(payload),
            command_id=command_id,
        )
        CompetitiveContextProjection.model_validate({
            **record,
            **record["payload"],
            "unresolved_risks": record["payload"]["unresolved_risks"],
        })
        return record

    def _project_model_settings(self, project_id: str) -> dict[str, Any]:
        """Load normalized project runtime settings without adding a new architecture."""
        settings = self.db.get_project_model_settings(project_id)
        if settings is None:
            return default_project_model_settings(self.services.config)
        return normalize_project_model_settings(settings.model_dump(mode="json"), self.services.config)

    def _runtime(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Resolve an exact runtime request for Product Discovery generation."""
        profile = resolve_llm_profile(settings, "product_discovery_generation")
        if profile is None:
            profile = resolve_llm_profile(settings, "layer1_generation")
        return resolved_runtime_request(
            profile,
            llm_client=self.services.generation_service.llm_client,
            server_manager=self.services.generation_service.server_manager,
        )

    def _generation_prompt(self, brief: dict[str, Any], mode: CompetitorResearchMode) -> str:
        """Render the editable discovery prompt with the exact published brief."""
        return render_prompt(
            DISCOVERY_PROMPT_KEY,
            {
                "published_brief": json.dumps(brief, indent=2, ensure_ascii=True, default=str),
                "competitor_research_mode": mode.value,
                "baseline_lenses": "\n".join(f"- {title}: {description}" for _, title, description in BASELINE_LENSES),
            },
        )

    def _merge_baseline_lenses(
        self,
        project_id: str,
        generated: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Preserve all baseline lenses while allowing model-authored narrowing rationale."""
        by_id = {str(item.get("id") or ""): dict(item) for item in generated}
        by_title = {self._slug(str(item.get("title") or "")): dict(item) for item in generated}
        merged: list[dict[str, Any]] = []
        consumed: set[str] = set()
        for key, title, description in BASELINE_LENSES:
            stable_id = self._stable_id(project_id, "lens", key)
            generated_item = by_id.get(stable_id) or by_title.get(self._slug(title)) or {}
            consumed.add(str(generated_item.get("id") or ""))
            merged.append({
                **generated_item,
                "id": stable_id,
                "title": title,
                "description": str(generated_item.get("description") or description),
                "source": "baseline",
                "downstream_state": str(generated_item.get("downstream_state") or "required"),
                "recommendation": str(generated_item.get("recommendation") or "required"),
                "why_it_matters": str(generated_item.get("why_it_matters") or description),
                "questions": list(generated_item.get("questions") or []),
                "expected_product_territory": list(generated_item.get("expected_product_territory") or []),
                "relevance_score": float(generated_item.get("relevance_score", 1.0)),
                "applicable_downstream_layers": list(generated_item.get("applicable_downstream_layers") or [1, 2, 3]),
                "applicable_actor_ids": list(generated_item.get("applicable_actor_ids") or []),
                "related_lens_ids": list(generated_item.get("related_lens_ids") or []),
                "omission_risks": list(generated_item.get("omission_risks") or []),
                "supporting_competitor_ids": list(generated_item.get("supporting_competitor_ids") or []),
                "evidence_ids": list(generated_item.get("evidence_ids") or []),
            })
        merged.extend(item for item in generated if str(item.get("id") or "") not in consumed)
        return merged

    def _stable_item(
        self,
        project_id: str,
        item_type: str,
        item: dict[str, Any],
        index: int,
    ) -> dict[str, Any]:
        """Assign a repeatable semantic identity without deduplicating overlapping content."""
        value = dict(item)
        label = str(value.get("title") or value.get("name") or value.get("question") or index)
        value["id"] = self._stable_id(project_id, item_type, self._slug(label))
        if "title" not in value:
            value["title"] = label
        return value

    def _summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Derive a concise count-and-territory summary from normalized sections."""
        return {
            **dict(payload.get("summary") or {}),
            "product_archetypes": [item["title"] for item in payload["archetypes"]],
            "required_lens_ids": [
                item["id"] for item in payload["lenses"]
                if item.get("recommendation") == "required" or item.get("downstream_state") == "required"
            ],
            "optional_lens_ids": [
                item["id"] for item in payload["lenses"]
                if item.get("recommendation") != "required" and item.get("downstream_state") != "required"
            ],
            "actor_count": len(payload["actors"]),
            "major_domain_ids": [item["id"] for item in payload["domains"]],
            "enterprise_obligation_ids": [item["id"] for item in payload["enterprise_obligations"]],
            "cross_domain_opportunity_ids": [item["id"] for item in payload["cross_domain_opportunities"]],
            "unresolved_risk_ids": [item["id"] for item in payload["coverage_risks"]],
        }

    def _review_outcome(self, item_type: str, item: Any) -> tuple[str, str, float]:
        """Apply bounded transparent checks while preserving unusual ideas for people."""
        if item_type == "cross_domain_opportunity":
            if item.speculation_level == "superficial_metaphor":
                return "rejected_as_superficial", "The analogy is labeled superficial and needs human correction.", 0.95
            if not item.source_mechanism or not item.structural_similarity:
                return "rejected_as_unsupported", "A transferable mechanism and structural similarity were not supplied.", 0.9
            if item.speculation_level in {"unusual_but_defensible", "requires_human_review"}:
                return "needs_human_review", "The unusual mechanism is retained for explicit human judgment.", 0.85
        if item.source == "competitor_research" and not getattr(item, "evidence_ids", []):
            return "rejected_as_unsupported", "Competitor-derived content requires durable evidence IDs.", 0.95
        if not str(item.description).strip() and item_type not in {"open_question"}:
            return "accepted_with_revision", "The item is relevant but needs a concrete description.", 0.8
        return "accepted", "The item satisfies the deterministic structural checks.", 0.8

    def _runtime_provenance(
        self,
        runtime: dict[str, Any],
        raw_payload: dict[str, Any],
        response_model: str | None,
        elapsed: float,
        *,
        temperature: float,
        seed: int | None,
        prompt_key: str = DISCOVERY_PROMPT_KEY,
        prompt_version: str = DISCOVERY_PROMPT_VERSION,
    ) -> ModelRuntimeProvenance:
        """Capture exact runtime identity, including a local model hash when available."""
        local_path = str(runtime.get("local_path") or "")
        usage = raw_payload.get("usage") or {}
        return ModelRuntimeProvenance(
            requested_model_profile=str(runtime.get("id") or ""),
            resolved_model_profile=str(runtime.get("id") or ""),
            provider=str(runtime.get("provider_kind") or ""),
            endpoint=str(runtime.get("base_url") or self.services.generation_service.llm_client.base_url),
            model_alias=str(runtime.get("model_name") or ""),
            exact_model_identifier=str(response_model or runtime.get("model_name") or local_path),
            model_file_hash=self._file_hash(local_path),
            runtime_build=str(raw_payload.get("system_fingerprint") or ""),
            server_process_id=str(runtime.get("server_process_id") or ""),
            prompt_key=prompt_key,
            prompt_version=prompt_version,
            effective_temperature=temperature,
            seed=seed,
            context_limit=int(runtime.get("context_window") or 0) or None,
            output_limit=int(runtime.get("max_output_tokens") or 0) or None,
            request_id=str(raw_payload.get("id") or ""),
            prompt_token_count=usage.get("prompt_tokens"),
            completion_token_count=usage.get("completion_tokens"),
            elapsed_time_seconds=elapsed,
        )

    def _latest_discovery_revision(self, project_id: str) -> ProductDiscoveryRevision | None:
        """Return the newest revision solely for carrying forward human authority fields."""
        revisions = self.db.list_discovery_revisions(project_id)
        return revisions[-1] if revisions else None

    @staticmethod
    def _file_hash(path: str) -> str:
        """Hash an available local model file without treating an alias as provenance."""
        target = Path(path)
        if not path or not target.is_file():
            return ""
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _stable_id(*parts: str) -> str:
        """Return a stable UUID for semantic records and review findings."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(str(part) for part in parts)))

    @staticmethod
    def _slug(value: str) -> str:
        """Normalize a human label into a stable identity component."""
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")

    @staticmethod
    def _token_estimate(payload: dict[str, Any]) -> int:
        """Estimate constrained-model tokens deterministically from canonical JSON."""
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return max(1, (len(encoded) + 3) // 4)
