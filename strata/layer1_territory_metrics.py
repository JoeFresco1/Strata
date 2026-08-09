from __future__ import annotations

from typing import Any

from strata.layer1_territory_models import (
    AttemptStatus,
    LensTerminalState,
    TerritoryDestination,
)


class Layer1TerritoryMetricsMixin:
    def _territory_diversity_metrics(self, run_id: str) -> dict[str, int]:
        """Calculate durable destination and attribution diversity proxies."""
        candidates = self.db.list_layer1_raw_candidates(run_id)
        destinations = {
            disposition.destination.value
            for item in candidates
            if (disposition := self.db.get_current_layer1_candidate_disposition(item.id))
        }
        return {
            "unique_semantic_families": len(
                self.db.list_layer1_territory_clusters(run_id)
            ),
            "unique_destinations": len(destinations),
            "unique_actor_ids": len(
                {actor for item in candidates for actor in item.affected_actor_ids}
            ),
            "unique_domain_ids": len(
                {domain for item in candidates for domain in item.affected_domain_ids}
            ),
            "unique_lens_mechanisms": len(
                {
                    item.lens_specific_mechanism.casefold()
                    for item in candidates
                    if item.lens_specific_mechanism
                }
            ),
            "unique_workflow_families": sum(
                1 for value in destinations if value == TerritoryDestination.WORKFLOW_FAMILY.value
            ),
            "unique_administrative_responsibilities": sum(
                1 for value in destinations if value in {
                    TerritoryDestination.ENTERPRISE_PLATFORM_OBLIGATION.value,
                    TerritoryDestination.ACTOR_WORKSPACE.value,
                }
            ),
            "unique_decision_mechanisms": sum(
                1
                for value in destinations
                if value == TerritoryDestination.DECISION_MECHANISM.value
            ),
            "unique_data_responsibilities": sum(
                1
                for value in destinations
                if value == TerritoryDestination.DATA_RESPONSIBILITY.value
            ),
            "unique_commercial_capabilities": sum(
                1
                for value in destinations
                if value == TerritoryDestination.COMMERCIAL_CAPABILITY.value
            ),
            "unique_operational_capabilities": sum(
                1
                for value in destinations
                if value == TerritoryDestination.OPERATIONAL_CAPABILITY.value
            ),
        }

    def _discovery_coverage_metrics(
        self,
        run: Any,
        lenses: list[Any],
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        """Calculate required discovery coverage and explicit actor/obligation gaps."""
        snapshot = self.db.discovery_snapshot(run.project_id)
        discovery = snapshot.get("published", {}).get("discovery", {})
        candidates = self.db.list_layer1_raw_candidates(run.id)
        addressed_ids = {
            item_id
            for candidate in candidates
            for item_id in (
                candidate.source_discovery_item_ids
                + candidate.affected_actor_ids
                + candidate.affected_lifecycle_stage_ids
                + candidate.affected_domain_ids
                + candidate.affected_enterprise_obligation_ids
                + candidate.affected_coverage_risk_ids
            )
        }
        required_actor_ids = {
            str(item.get("id") or "")
            for item in discovery.get("actors", [])
            if isinstance(item, dict)
            and str(item.get("downstream_state") or "optional") == "required"
        }
        obligation_ids = {
            str(item.get("id") or "")
            for item in discovery.get("enterprise_obligations", [])
            if isinstance(item, dict)
            and str(item.get("downstream_state") or "required") != "excluded"
        }
        high_risk_ids = {
            str(item.get("id") or "")
            for item in discovery.get("coverage_risks", [])
            if isinstance(item, dict)
            and str(item.get("severity") or "") in {"high", "critical"}
        }
        actor_gaps = sorted(required_actor_ids - addressed_ids)
        obligation_gaps = sorted(obligation_ids - addressed_ids)
        return {
            "required_lenses_visited": sum(
                1 for lens in lenses if lens.required and lens.attempt_count > 0
            ),
            "required_lenses_completed": sum(
                1
                for lens in lenses
                if lens.required
                and lens.state not in {LensTerminalState.PENDING, LensTerminalState.ACTIVE}
            ),
            "required_lenses_total": sum(1 for lens in lenses if lens.required),
            "discovery_domains_addressed": len({
                str(item.get("id") or "")
                for item in discovery.get("domains", [])
                if isinstance(item, dict) and str(item.get("id") or "") in addressed_ids
            }),
            "actors_addressed": len({
                str(item.get("id") or "")
                for item in discovery.get("actors", [])
                if isinstance(item, dict) and str(item.get("id") or "") in addressed_ids
            }),
            "lifecycle_stages_addressed": len({
                str(item.get("id") or "")
                for item in discovery.get("lifecycle_stages", [])
                if isinstance(item, dict) and str(item.get("id") or "") in addressed_ids
            }),
            "enterprise_obligations_addressed": len(obligation_ids & addressed_ids),
            "high_severity_coverage_risks_resolved": len(high_risk_ids & addressed_ids),
            "required_actor_gaps": actor_gaps,
            "enterprise_obligation_gaps": obligation_gaps,
        }, actor_gaps, obligation_gaps

    def _runtime_cost_metrics(self, run_id: str) -> dict[str, Any]:
        """Aggregate durable attempts into reproducible runtime-cost counters."""
        attempts = self.db.list_layer1_lens_attempts(run_id)
        events = self.db._fetchall(
            f"""
            SELECT status, latency_ms, prompt_tokens, completion_tokens,
                   retry_count, error_type
            FROM model_call_events WHERE run_id = {self.db.param}
            """,
            (run_id,),
        )
        elapsed_seconds = sum(int(row["latency_ms"] or 0) for row in events) / 1000
        model_calls = len(events) if events else len(attempts)
        accepted = self.db.layer1_candidate_integrity_metrics(run_id)["accepted_candidates"]
        return {
            "model_calls": model_calls,
            "tokens": sum(
                int(row["prompt_tokens"] or 0) + int(row["completion_tokens"] or 0)
                for row in events
            ),
            "elapsed_seconds": elapsed_seconds,
            "retries": (
                sum(int(row["retry_count"] or 0) for row in events)
                if events
                else sum(max(0, item.attempt_number - 1) for item in attempts)
            ),
            "timeouts": sum(
                1
                for row in events
                if "timeout" in str(row["error_type"] or "").casefold()
            ) if events else sum(
                1 for item in attempts if item.status == AttemptStatus.TIMED_OUT
            ),
            "repair_attempts": sum(
                1 for item in attempts if item.attempt_kind == "repair"
            ),
            "candidate_yield_per_call": (
                sum(item.parsed_candidate_count for item in attempts) / model_calls
                if model_calls
                else 0
            ),
            "useful_territory_per_minute": (
                accepted / (elapsed_seconds / 60) if elapsed_seconds else 0
            ),
        }

    @staticmethod
    def _architecture_breadth_metrics(architectures: list[Any]) -> dict[str, Any]:
        """Calculate mapped breadth and concentration across immutable options."""
        mapping_sizes = [
            len(mapping.territory_candidate_ids)
            for architecture in architectures
            for mapping in architecture.mappings
        ]
        all_mapped_ids = {
            candidate_id
            for architecture in architectures
            for mapping in architecture.mappings
            for candidate_id in mapping.territory_candidate_ids
        }
        cross_cutting_ids = {
            candidate_id
            for architecture in architectures
            for mapping in architecture.mappings
            for candidate_id in mapping.cross_cutting_concern_ids
        }
        obligation_ids = {
            obligation_id
            for architecture in architectures
            for mapping in architecture.mappings
            for obligation_id in mapping.covered_enterprise_obligation_ids
        }
        retained_ids = {
            candidate_id
            for architecture in architectures
            for candidate_id in architecture.significant_non_pillar_territory_ids
        }
        total_mappings = sum(mapping_sizes)
        return {
            "architecture_options": len(architectures),
            "semantic_territories_represented": len(all_mapped_ids),
            "cross_cutting_territories_represented": len(cross_cutting_ids),
            "enterprise_obligations_represented": len(obligation_ids),
            "important_retained_non_pillar_territory": len(retained_ids),
            "largest_pillar_territory_concentration": (
                max(mapping_sizes, default=0) / total_mappings
                if total_mappings else 0
            ),
            "pillars_with_multiple_feature_families": sum(
                1 for size in mapping_sizes if size > 1
            ),
        }

    def _lens_adherence_metrics(
        self,
        run_id: str,
        assessments: list[Any],
    ) -> dict[str, float]:
        """Aggregate latest lens-local metrics without treating them as global judgment."""
        candidates = self.db.list_layer1_raw_candidates(run_id)
        closed_violations = sum(
            1
            for candidate in candidates
            if any(
                item.closed_territory_violation_ids
                for item in self.db.list_layer1_territory_assessments(candidate.id)
            )
        )
        if not assessments:
            return {
                "average_lens_adherence_score": 0,
                "average_generic_repetition_rate": 0,
                "average_weak_attribution_rate": 0,
                "discovery_item_mapping_completeness": 0,
                "closed_territory_violation_rate": 0,
            }
        count = len(assessments)
        return {
            "average_lens_adherence_score": sum(
                item.lens_adherence_score for item in assessments
            ) / count,
            "average_generic_repetition_rate": sum(
                item.generic_repetition_rate for item in assessments
            ) / count,
            "average_weak_attribution_rate": sum(
                item.weak_attribution_rate for item in assessments
            ) / count,
            "discovery_item_mapping_completeness": (
                sum(1 for item in candidates if item.source_discovery_item_ids)
                / len(candidates)
                if candidates else 0
            ),
            "closed_territory_violation_rate": (
                closed_violations / len(candidates) if candidates else 0
            ),
        }
