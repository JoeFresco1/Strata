from __future__ import annotations

from typing import Any

from strata.layer1_territory_models import (
    LensTerminalState,
    ModelRuntimeProvenance,
    TerritoryDestination,
)
from strata.layer1_territory_policy import DivergencePolicy, ExplorationBudget
from strata.llm import LLMError


class Layer1TerritoryContextMixin:
    def _territory_adversarial_context(self, run: Any) -> dict[str, Any]:
        """Build bounded adversarial input without raw transcripts or rejected nonsense."""
        synthesis = self.build_layer1_synthesis_context(run.id)
        return self._bounded_territory_model_context(synthesis)

    @classmethod
    def _bounded_territory_model_context(
        cls,
        context: dict[str, Any],
        *,
        detailed_candidate_limit: int = 10,
        inventory_candidate_limit: int = 48,
    ) -> dict[str, Any]:
        """Compact synthesis inputs while preserving every accepted candidate ID.

        Local 16k-context models need output headroom. The complete inventory remains
        lossless for identity and routing, while a destination-diverse subset carries
        richer attribution and mechanism detail.
        """
        brief = {
            key: cls._compact_context_value(value, text_limit=150, list_limit=6)
            for key, value in dict(context.get("brief") or {}).items()
        }
        discovery: dict[str, list[dict[str, Any]]] = {}
        for section, raw_items in dict(context.get("discovery") or {}).items():
            discovery[section] = [
                cls._compact_discovery_item(item, section=section)
                for item in raw_items
                if isinstance(item, dict)
            ]

        territory = [
            item for item in context.get("territory", []) if isinstance(item, dict)
        ]
        by_destination: dict[str, list[dict[str, Any]]] = {}
        for item in territory:
            destination = str(item.get("destination") or "unspecified")
            by_destination.setdefault(destination, []).append(item)
        representatives: list[dict[str, Any]] = []
        territory_by_id = {
            str(item.get("candidate_id") or ""): item for item in territory
        }
        for cluster in context.get("semantic_clusters", []):
            if not isinstance(cluster, dict):
                continue
            representative = next(
                (
                    territory_by_id.get(candidate_id)
                    for candidate_id in cls._string_values(cluster.get("candidate_ids"))
                    if territory_by_id.get(candidate_id) not in representatives
                ),
                None,
            )
            if representative is not None:
                representatives.append(representative)
            if len(representatives) >= detailed_candidate_limit:
                break
        ordered_destinations = sorted(by_destination)
        while len(representatives) < detailed_candidate_limit:
            added = False
            for destination in ordered_destinations:
                bucket = by_destination[destination]
                index = sum(
                    1
                    for chosen in representatives
                    if str(chosen.get("destination") or "unspecified") == destination
                )
                remaining = [item for item in bucket if item not in representatives]
                if remaining:
                    representatives.append(remaining[0])
                    added = True
                    if len(representatives) >= detailed_candidate_limit:
                        break
            if not added:
                break

        detailed = [cls._compact_territory_item(item) for item in representatives]
        inventory_items: list[dict[str, Any]] = list(representatives)
        inventory_index = 0
        while len(inventory_items) < min(inventory_candidate_limit, len(territory)):
            added = False
            for destination in ordered_destinations:
                bucket = by_destination[destination]
                if inventory_index < len(bucket):
                    item = bucket[inventory_index]
                    if item not in inventory_items:
                        inventory_items.append(item)
                        added = True
                        if len(inventory_items) >= inventory_candidate_limit:
                            break
            largest_destination = max(
                (len(items) for items in by_destination.values()),
                default=0,
            )
            if not added and inventory_index >= largest_destination:
                break
            inventory_index += 1
        inventory: dict[str, list[str]] = {}
        for item in inventory_items:
            destination = str(item.get("destination") or "unspecified")
            inventory.setdefault(destination, []).append(
                str(item.get("candidate_id") or "")
            )
        clusters = [
            {
                "id": str(item.get("id") or ""),
                "title": cls._truncate_context_text(item.get("title"), 72),
                "semantic_family": cls._truncate_context_text(
                    item.get("semantic_family"), 72
                ),
                "destination_summary": item.get("destination_summary") or {},
            }
            for item in context.get("semantic_clusters", [])
            if isinstance(item, dict)
        ]
        return {
            "brief": brief,
            "discovery": discovery,
            "territory": detailed,
            "territory_inventory": inventory,
            "territory_population_summary": {
                destination: {
                    "total": len(items),
                    "included": len(inventory.get(destination, [])),
                }
                for destination, items in sorted(by_destination.items())
            },
            "semantic_clusters": clusters,
        }

    @classmethod
    def _compact_discovery_item(
        cls,
        item: dict[str, Any],
        *,
        section: str = "",
    ) -> dict[str, Any]:
        """Retain discovery identity, routing, and concise semantics."""
        compact: dict[str, Any] = {}
        prose_keys = {"title", "name", "label", "description", "risk", "obligation"}
        scalar_keys = {
            "id", "severity", "recommendation", "downstream_state", "category",
            "relevance_score", "required",
        }
        for key, value in item.items():
            if key in prose_keys:
                limit = 72 if key in {"title", "name", "label"} else 64
                compact[key] = cls._truncate_context_text(value, limit)
            elif key in scalar_keys and not isinstance(value, (dict, list)):
                compact[key] = value
            elif (
                section == "lenses"
                and key == "required_discovery_item_ids"
                and isinstance(value, list)
            ):
                compact[key] = cls._string_values(value)
        return compact

    @classmethod
    def _compact_territory_item(cls, item: dict[str, Any]) -> dict[str, Any]:
        """Keep concise details for a destination-diverse territory sample."""
        return {
            "candidate_id": str(item.get("candidate_id") or ""),
            "title": cls._truncate_context_text(item.get("title"), 72),
            "description": cls._truncate_context_text(item.get("description"), 120),
            "destination": str(item.get("destination") or "unspecified"),
            "source_discovery_item_ids": cls._string_values(
                item.get("source_discovery_item_ids")
            ),
            "affected_actor_ids": cls._string_values(item.get("affected_actor_ids")),
            "affected_domain_ids": cls._string_values(item.get("affected_domain_ids")),
            "affected_enterprise_obligation_ids": cls._string_values(
                item.get("affected_enterprise_obligation_ids")
            ),
            "affected_coverage_risk_ids": cls._string_values(
                item.get("affected_coverage_risk_ids")
            ),
            "lens_specific_mechanism": cls._truncate_context_text(
                item.get("lens_specific_mechanism"), 80
            ),
        }

    @classmethod
    def _compact_context_value(
        cls,
        value: Any,
        *,
        text_limit: int,
        list_limit: int,
    ) -> Any:
        """Bound user-authored brief fields without changing their ordering."""
        if isinstance(value, str):
            return cls._truncate_context_text(value, text_limit)
        if isinstance(value, list):
            return [
                cls._truncate_context_text(item, text_limit)
                for item in value[:list_limit]
            ]
        return value

    @staticmethod
    def _truncate_context_text(value: Any, limit: int) -> str:
        """Truncate deterministically and visibly for model-only projections."""
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return f"{text[: max(0, limit - 1)].rstrip()}…"

    def _territory_source_projection(self, run: Any, lens: Any) -> dict[str, Any]:
        """Build the bounded source-only context used by every independent retry."""
        brief = self.db.get_project_brief(run.project_id)
        snapshot = self.db.discovery_snapshot(run.project_id)
        published = snapshot.get("published", {})
        discovery = published.get("discovery", {})
        relevant = [
            item
            for collection in self._discovery_collections(discovery)
            for item in collection
            if str(item.get("id") or "") in lens.source_discovery_item_ids
        ]
        return {
            "brief": {
                "product_idea": brief.product_idea,
                "problem": brief.problem,
                "target_users": brief.target_users,
                "constraints": brief.constraints,
                "goals": brief.goals,
                "preferred_directions": brief.preferred_directions,
                "rejected_directions": brief.rejected_directions,
            },
            "lens": {
                "id": lens.source_lens_id,
                "title": lens.title,
                "instruction": lens.instruction,
                "required": lens.required,
            },
            "relevant_discovery_items": relevant,
            "required_source_ids": {"discovery_item_ids": lens.source_discovery_item_ids},
        }

    def _territory_source_projection_for_run(self, run: Any) -> dict[str, Any]:
        """Return bounded published Layer 0 and Product Discovery synthesis context."""
        brief = self.db.get_project_brief(run.project_id)
        snapshot = self.db.discovery_snapshot(run.project_id)
        published = snapshot.get("published", {})
        discovery = published.get("discovery", {})
        return {
            "brief": {
                "product_idea": brief.product_idea,
                "problem": brief.problem,
                "target_users": brief.target_users,
                "constraints": brief.constraints,
                "goals": brief.goals,
                "preferred_directions": brief.preferred_directions,
                "rejected_directions": brief.rejected_directions,
            },
            "discovery": {
                name: discovery.get(name, [])
                for name in (
                    "lenses",
                    "actors",
                    "lifecycle_stages",
                    "domains",
                    "enterprise_obligations",
                    "coverage_risks",
                )
            },
        }

    @staticmethod
    def _territory_lens_specs(published: dict[str, Any]) -> list[dict[str, Any]]:
        """Compile non-alphabetical scheduling inputs from the published discovery."""
        discovery = published.get("discovery", {})
        human = published.get("human_owned_fields", {})
        states = human.get("item_states", {}) if isinstance(human, dict) else {}
        priorities = human.get("item_priorities", {}) if isinstance(human, dict) else {}
        human_order = human.get("lens_order", []) if isinstance(human, dict) else []
        explicit_order = {
            str(lens_id): index
            for index, lens_id in enumerate(human_order)
        } if isinstance(human_order, list) else {}
        specs: list[dict[str, Any]] = []
        for order, lens in enumerate(discovery.get("lenses", [])):
            lens_id = str(lens.get("id") or "")
            state = str(states.get(lens_id) or lens.get("downstream_state") or "")
            if not lens_id or state in {"excluded", "rejected"}:
                continue
            source_ids = Layer1TerritoryContextMixin._lens_source_ids(lens, discovery)
            linked_risks = [
                item
                for item in discovery.get("coverage_risks", [])
                if isinstance(item, dict) and str(item.get("id") or "") in source_ids
            ]
            severity_weight = {"low": 1, "medium": 2, "high": 3, "critical": 4}
            risk_priority = max(
                (
                    severity_weight.get(str(item.get("severity") or ""), 0)
                    for item in linked_risks
                ),
                default=0,
            )
            actor_and_obligation_ids = {
                str(item.get("id") or "")
                for name in ("actors", "enterprise_obligations")
                for item in discovery.get(name, [])
                if isinstance(item, dict)
            }
            specs.append(
                {
                    "source_lens_id": lens_id,
                    "source_discovery_item_ids": source_ids,
                    "title": str(lens.get("title") or "Untitled lens"),
                    "instruction": " ".join(
                        str(lens.get(field) or "")
                        for field in (
                            "description",
                            "why_it_matters",
                            "expected_product_territory",
                        )
                    ).strip(),
                    "required": str(lens.get("recommendation") or "") == "required"
                    or state == "required",
                    "discovery_order": explicit_order.get(lens_id, order),
                    "risk_priority": risk_priority,
                    "relevance_score": float(lens.get("relevance_score") or 0.5),
                    "missing_coverage_priority": len(
                        set(source_ids) & actor_and_obligation_ids
                    ),
                    "human_priority": int(priorities.get(lens_id) or 0),
                    "human_order_position": explicit_order.get(lens_id),
                }
            )
        if not specs:
            raise ValueError("Published Product Discovery contains no active Layer 1 lenses.")
        return specs

    @staticmethod
    def _lens_source_ids(
        lens: dict[str, Any],
        discovery: dict[str, Any] | None = None,
    ) -> list[str]:
        """Collect explicit forward and reverse discovery relationships."""
        values: list[str] = []
        known_ids = {
            str(item.get("id") or "")
            for collection in Layer1TerritoryContextMixin._discovery_collections(
                discovery or {}
            )
            for item in collection
        }
        for key, value in lens.items():
            if key.endswith("_ids") and isinstance(value, list):
                values.extend(
                    str(item)
                    for item in value
                    if str(item).strip() and (not known_ids or str(item) in known_ids)
                )
        lens_id = str(lens.get("id") or "")
        for collection in Layer1TerritoryContextMixin._discovery_collections(
            discovery or {}
        ):
            for item in collection:
                related_lens_ids = [
                    str(reference)
                    for key, references in item.items()
                    if key.endswith("lens_ids") and isinstance(references, list)
                    for reference in references
                ]
                if lens_id in related_lens_ids and item.get("id"):
                    values.append(str(item["id"]))
        return list(dict.fromkeys(values))

    @staticmethod
    def _discovery_collections(discovery: dict[str, Any]) -> list[list[dict[str, Any]]]:
        """Return typed discovery collections relevant to territory attribution."""
        names = (
            "actors",
            "lifecycle_stages",
            "domains",
            "enterprise_obligations",
            "coverage_risks",
            "cross_domain_opportunities",
        )
        return [
            [item for item in discovery.get(name, []) if isinstance(item, dict)]
            for name in names
        ]

    @staticmethod
    def _territory_candidate_payloads(
        payload: dict[str, Any],
        policy: DivergencePolicy,
    ) -> list[dict[str, Any]]:
        """Validate only the response envelope while preserving every raw item."""
        candidates = payload.get("candidates")
        if not isinstance(candidates, list):
            raise LLMError("Territory response must contain a candidates list.")
        if not candidates:
            raise LLMError("Territory response returned no candidates.")
        if any(not isinstance(item, dict) for item in candidates):
            raise LLMError("Territory candidates must contain objects only.")
        valid = [item for item in candidates if isinstance(item, dict)]
        if any(
            not str(item.get("title") or "").strip()
            or not str(item.get("description") or "").strip()
            for item in valid
        ):
            raise LLMError("Every territory candidate requires a title and description.")
        if len(valid) > policy.maximum_raw_candidates:
            valid = valid[: policy.maximum_raw_candidates]
        return valid

    @staticmethod
    def _territory_runtime_provenance(
        profile: dict[str, Any],
        *,
        temperature: float,
        prompt_key: str,
        prompt_version: str,
        timeout_seconds: int | None = None,
        output_limit: int = 7000,
    ) -> ModelRuntimeProvenance:
        """Freeze requested and resolved model facts before inference."""
        return ModelRuntimeProvenance(
            requested_profile_id=str(profile.get("id") or ""),
            resolved_profile_id=str(profile.get("id") or ""),
            provider=str(profile.get("provider") or ""),
            endpoint=str(profile.get("base_url") or ""),
            model_alias=str(profile.get("label") or profile.get("id") or ""),
            exact_model_identifier=str(profile.get("model_name") or ""),
            model_file_hash=str(profile.get("model_file_hash") or ""),
            runtime_build=str(profile.get("runtime_build") or ""),
            prompt_key=prompt_key,
            prompt_version=prompt_version,
            effective_temperature=temperature,
            seed=profile.get("seed"),
            context_limit=(
                int(profile.get("context_limit") or profile.get("context_window") or 0)
                or None
            ),
            output_limit=output_limit,
            timeout_seconds=(
                timeout_seconds
                or profile.get("timeout_seconds")
                or 900
            ),
        )

    def _accepted_territory_keys(self, run_id: str) -> set[str]:
        """Return normalized keys already routed somewhere other than duplicate/reject."""
        keys: set[str] = set()
        rejected = {
            TerritoryDestination.DUPLICATE,
            TerritoryDestination.REJECTED_QUALITY,
            TerritoryDestination.REJECTED_GENERIC_REPETITION,
            TerritoryDestination.REJECTED_UNSUPPORTED,
            TerritoryDestination.REJECTED_BIZARRE,
            TerritoryDestination.OUT_OF_SCOPE,
        }
        for candidate in self.db.list_layer1_raw_candidates(run_id):
            disposition = self.db.get_current_layer1_candidate_disposition(candidate.id)
            if disposition is not None and disposition.destination not in rejected:
                keys.add(self._territory_key(candidate.title, candidate.description))
        return keys

    @staticmethod
    def _territory_key(title: str, description: str) -> str:
        """Build a deterministic exact-normalized retry deduplication key."""
        text = f"{title} {description}".casefold()
        return " ".join("".join(char if char.isalnum() else " " for char in text).split())

    @staticmethod
    def _deterministic_semantic_family(title: str, description: str) -> str:
        """Create a stable coarse family label for identity normalization."""
        stop_words = {
            "a", "an", "and", "for", "from", "in", "of", "on", "the", "to",
            "platform", "service", "system", "workflow",
        }
        title_tokens = Layer1TerritoryContextMixin._territory_key(title, "").split()
        family_tokens = [token for token in title_tokens if token not in stop_words][:3]
        if not family_tokens:
            description_tokens = Layer1TerritoryContextMixin._territory_key(
                description,
                "",
            ).split()
            family_tokens = [
                token for token in description_tokens if token not in stop_words
            ][:3]
        return " ".join(family_tokens) or "uncategorized territory"

    @staticmethod
    def _string_values(value: Any) -> list[str]:
        """Return only non-blank string values from model arrays."""
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def _run_model_call_count(self, run_id: str) -> int:
        """Count persisted attempts so resumed runs honor the original hard budget."""
        row = self.db._fetchone(
            f"SELECT COUNT(*) AS count FROM layer1_lens_attempts WHERE run_id = {self.db.param}",
            (run_id,),
        )
        return int(row["count"])

    def _mark_unvisited_lenses_budget_exhausted(self, run_id: str) -> None:
        """Make hard truncation visible on every still-unvisited lens."""
        for lens in self.db.list_layer1_lens_work_items(run_id):
            if lens.state in {LensTerminalState.PENDING, LensTerminalState.ACTIVE}:
                self.db.update_layer1_lens_state(
                    lens.id,
                    state=LensTerminalState.BUDGET_EXHAUSTED,
                    attempt_count=lens.attempt_count,
                )

    @staticmethod
    def _territory_policy(config: dict[str, Any]) -> DivergencePolicy:
        """Rehydrate the frozen run policy."""
        return DivergencePolicy(
            target_raw_candidates=int(config.get("target_raw_candidates", 18)),
            minimum_raw_candidates=int(config.get("minimum_raw_candidates", 12)),
            maximum_raw_candidates=int(config.get("maximum_raw_candidates", 30)),
            temperature_schedule=tuple(
                float(item)
                for item in config.get("temperature_schedule", (0.65, 0.8, 0.95, 1.05))
            ),
            minimum_lens_adherence=int(config.get("minimum_lens_adherence", 65)),
            minimum_useful_novelty=int(config.get("minimum_useful_novelty", 45)),
            maximum_generic_repetition_rate=float(
                config.get("maximum_generic_repetition_rate", 0.35)
            ),
            max_attempts_per_lens=int(config.get("max_attempts_per_lens", 4)),
            model_call_timeout_seconds=int(
                config.get("model_call_timeout_seconds", 900)
            ),
            divergence_max_output_tokens=int(
                config.get("divergence_max_output_tokens", 7000)
            ),
            enable_adversarial_pass=bool(config.get("enable_adversarial_pass", True)),
            architecture_views=tuple(config.get("architecture_views", ())),
        )

    @staticmethod
    def _territory_budget(config: dict[str, Any]) -> ExplorationBudget:
        """Rehydrate the frozen hard budget."""
        return ExplorationBudget(
            max_model_calls=int(config.get("max_model_calls", 40)),
            max_elapsed_seconds=int(config.get("max_elapsed_seconds", 3600)),
            max_total_candidates=int(config.get("max_total_candidates", 900)),
        )

    @staticmethod
    def _territory_policy_for_profile(
        policy: DivergencePolicy,
        profile: dict[str, Any],
    ) -> DivergencePolicy:
        """Apply optional model-profile workflow overrides to the frozen base policy."""
        workflow_overrides = profile.get("workflow_overrides", {})
        override = (
            workflow_overrides.get("layer1_territory", {})
            if isinstance(workflow_overrides, dict)
            else {}
        )
        if not isinstance(override, dict) or not override:
            return policy
        payload = policy.as_dict()
        allowed = set(payload)
        payload.update({
            key: value for key, value in override.items() if key in allowed
        })
        if "temperature_schedule" in payload:
            payload["temperature_schedule"] = tuple(payload["temperature_schedule"])
        if "architecture_views" in payload:
            payload["architecture_views"] = tuple(payload["architecture_views"])
        return DivergencePolicy(**payload)
