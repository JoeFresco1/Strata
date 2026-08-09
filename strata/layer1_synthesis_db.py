from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from strata.layer1_territory_db import territory_now
from strata.layer1_territory_models import (
    ArchitectureKind,
    ArchitectureState,
    GlobalArchitectureAssessment,
    Layer1ArchitectureApplication,
    Layer1CoverageState,
    Layer1SynthesisResult,
    LensCoverageAssessment,
    LensCoverageRecommendation,
    ModelRuntimeProvenance,
    PillarArchitectureCandidate,
    PillarTerritoryMapping,
)


class Layer1SynthesisDatabaseMixin:
    """Persist lens-local evaluation, global coverage, and immutable architectures."""

    def persist_layer1_lens_coverage(
        self,
        *,
        lens_execution_id: str,
        attempt_number: int,
        payload: dict[str, Any],
    ) -> LensCoverageAssessment:
        """Append the lens-local critic output separately from global coverage."""
        lens = self.get_layer1_lens_work_item(lens_execution_id)
        assessment = LensCoverageAssessment(
            id=str(uuid.uuid4()),
            run_id=lens.run_id,
            lens_execution_id=lens.id,
            project_id=lens.project_id,
            attempt_number=attempt_number,
            addressed_discovery_item_ids=self._l1_string_list(
                payload.get("addressed_discovery_item_ids")
            ),
            unresolved_discovery_item_ids=self._l1_string_list(
                payload.get("unresolved_discovery_item_ids")
            ),
            high_severity_unresolved_item_ids=self._l1_string_list(
                payload.get("high_severity_unresolved_item_ids")
            ),
            lens_adherence_score=self._l1_score(payload.get("lens_adherence_score"), 0),
            useful_novelty_score=self._l1_score(payload.get("useful_novelty_score"), 0),
            generic_repetition_rate=self._l1_rate(
                payload.get("generic_repetition_rate"),
                0,
            ),
            duplicate_rate=self._l1_rate(payload.get("duplicate_rate"), 0),
            weak_attribution_rate=self._l1_rate(
                payload.get("weak_attribution_rate"),
                0,
            ),
            recommendation=self._l1_recommendation(payload.get("recommendation")),
            rationale=str(payload.get("rationale") or ""),
            created_at=territory_now(),
        )
        self._execute(
            f"""
            INSERT INTO layer1_lens_coverage_assessments (
                id, run_id, lens_execution_id, project_id, attempt_number,
                addressed_discovery_item_ids, unresolved_discovery_item_ids,
                high_severity_unresolved_item_ids, lens_adherence_score,
                useful_novelty_score, generic_repetition_rate, duplicate_rate,
                weak_attribution_rate, recommendation, rationale, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}
            )
            """,
            (
                assessment.id,
                assessment.run_id,
                assessment.lens_execution_id,
                assessment.project_id,
                assessment.attempt_number,
                self._dump_json(assessment.addressed_discovery_item_ids),
                self._dump_json(assessment.unresolved_discovery_item_ids),
                self._dump_json(assessment.high_severity_unresolved_item_ids),
                assessment.lens_adherence_score,
                assessment.useful_novelty_score,
                assessment.generic_repetition_rate,
                assessment.duplicate_rate,
                assessment.weak_attribution_rate,
                assessment.recommendation.value,
                assessment.rationale,
                assessment.created_at.isoformat(),
            ),
        )
        return assessment

    def list_layer1_lens_coverage(
        self,
        lens_execution_id: str,
    ) -> list[LensCoverageAssessment]:
        """Return lens-local assessments in attempt order."""
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_lens_coverage_assessments
            WHERE lens_execution_id = {self.param} ORDER BY attempt_number
            """,
            (lens_execution_id,),
        )
        results: list[LensCoverageAssessment] = []
        for row in rows:
            payload = dict(row)
            for field in (
                "addressed_discovery_item_ids",
                "unresolved_discovery_item_ids",
                "high_severity_unresolved_item_ids",
            ):
                payload[field] = self._load_json_list(payload[field])
            results.append(LensCoverageAssessment.model_validate(payload))
        return results

    def persist_layer1_coverage_state(
        self,
        *,
        run_id: str,
        discovery_coverage: dict[str, Any],
        territory_diversity: dict[str, Any],
        lens_adherence: dict[str, Any],
        candidate_integrity: dict[str, Any],
        architecture_breadth: dict[str, Any],
        runtime_cost: dict[str, Any],
        unresolved_high_severity_item_ids: list[str],
        ready_for_synthesis: bool,
        incomplete_reasons: list[str],
    ) -> Layer1CoverageState:
        """Append one reproducible global coverage snapshot."""
        run = self.get_layer1_territory_run(run_id)
        latest = self._fetchone(
            f"SELECT MAX(version) AS version FROM layer1_coverage_states WHERE run_id = {self.param}",
            (run_id,),
        )
        state = Layer1CoverageState(
            id=str(uuid.uuid4()),
            run_id=run.id,
            project_id=run.project_id,
            version=int(latest["version"] or 0) + 1,
            discovery_coverage=discovery_coverage,
            territory_diversity=territory_diversity,
            lens_adherence=lens_adherence,
            candidate_integrity=candidate_integrity,
            architecture_breadth=architecture_breadth,
            runtime_cost=runtime_cost,
            unresolved_high_severity_item_ids=unresolved_high_severity_item_ids,
            ready_for_synthesis=ready_for_synthesis,
            incomplete_reasons=incomplete_reasons,
            created_at=territory_now(),
        )
        self._execute(
            f"""
            INSERT INTO layer1_coverage_states (
                id, run_id, project_id, version, discovery_coverage,
                territory_diversity, lens_adherence, candidate_integrity,
                architecture_breadth, runtime_cost,
                unresolved_high_severity_item_ids, ready_for_synthesis,
                incomplete_reasons, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}
            )
            """,
            (
                state.id,
                state.run_id,
                state.project_id,
                state.version,
                self._dump_json(state.discovery_coverage),
                self._dump_json(state.territory_diversity),
                self._dump_json(state.lens_adherence),
                self._dump_json(state.candidate_integrity),
                self._dump_json(state.architecture_breadth),
                self._dump_json(state.runtime_cost),
                self._dump_json(state.unresolved_high_severity_item_ids),
                state.ready_for_synthesis,
                self._dump_json(state.incomplete_reasons),
                state.created_at.isoformat(),
            ),
        )
        return state

    def get_latest_layer1_coverage_state(
        self,
        run_id: str,
    ) -> Layer1CoverageState | None:
        """Load the newest global coverage snapshot for a run."""
        row = self._fetchone(
            f"""
            SELECT * FROM layer1_coverage_states
            WHERE run_id = {self.param} ORDER BY version DESC LIMIT 1
            """,
            (run_id,),
        )
        if row is None:
            return None
        payload = dict(row)
        for field in (
            "discovery_coverage",
            "territory_diversity",
            "lens_adherence",
            "candidate_integrity",
            "architecture_breadth",
            "runtime_cost",
        ):
            payload[field] = self._load_json(payload[field])
        for field in ("unresolved_high_severity_item_ids", "incomplete_reasons"):
            payload[field] = self._load_json_list(payload[field])
        return Layer1CoverageState.model_validate(payload)

    def persist_layer1_architecture_candidate(
        self,
        *,
        run_id: str,
        kind: ArchitectureKind,
        title: str,
        rationale: str,
        pillars: list[dict[str, Any]],
        mappings: list[dict[str, Any]],
        significant_non_pillar_territory_ids: list[str],
        unresolved_risk_ids: list[str],
        runtime_provenance: ModelRuntimeProvenance,
    ) -> PillarArchitectureCandidate:
        """Persist immutable architecture content and its territory mappings."""
        run = self.get_layer1_territory_run(run_id)
        self._validate_architecture_mappings(run_id, pillars, mappings)
        latest = self._fetchone(
            f"""
            SELECT MAX(version) AS version FROM layer1_architecture_candidates
            WHERE run_id = {self.param} AND kind = {self.param}
            """,
            (run_id, kind.value),
        )
        version = int(latest["version"] or 0) + 1
        content = {
            "kind": kind.value,
            "title": title,
            "rationale": rationale,
            "pillars": pillars,
            "mappings": mappings,
            "significant_non_pillar_territory_ids": significant_non_pillar_territory_ids,
            "unresolved_risk_ids": unresolved_risk_ids,
        }
        content_hash = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        architecture_id = str(uuid.uuid4())
        created_at = territory_now()
        self._execute(
            f"""
            INSERT INTO layer1_architecture_candidates (
                id, run_id, project_id, kind, version, title, rationale, pillars,
                significant_non_pillar_territory_ids, unresolved_risk_ids,
                content_hash, runtime_provenance, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}
            )
            """,
            (
                architecture_id,
                run.id,
                run.project_id,
                kind.value,
                version,
                title,
                rationale,
                self._dump_json(pillars),
                self._dump_json(significant_non_pillar_territory_ids),
                self._dump_json(unresolved_risk_ids),
                content_hash,
                self._dump_json(runtime_provenance.model_dump(mode="json")),
                created_at,
            ),
        )
        typed_mappings = [
            self._persist_layer1_pillar_mapping(architecture_id, mapping)
            for mapping in mappings
        ]
        return PillarArchitectureCandidate(
            id=architecture_id,
            run_id=run.id,
            project_id=run.project_id,
            kind=kind,
            version=version,
            title=title,
            rationale=rationale,
            pillars=pillars,
            mappings=typed_mappings,
            significant_non_pillar_territory_ids=significant_non_pillar_territory_ids,
            unresolved_risk_ids=unresolved_risk_ids,
            content_hash=content_hash,
            runtime_provenance=runtime_provenance,
            created_at=created_at,
        )

    def _validate_architecture_mappings(
        self,
        run_id: str,
        pillars: list[dict[str, Any]],
        mappings: list[dict[str, Any]],
    ) -> None:
        """Require every synthesized pillar to map to preserved run candidates."""
        pillar_ids = {str(item.get("id") or "") for item in pillars}
        mapping_pillar_ids = {str(item.get("pillar_id") or "") for item in mappings}
        if "" in pillar_ids or pillar_ids != mapping_pillar_ids:
            raise ValueError("Every synthesized pillar requires exactly one territory mapping.")
        known = {item.id for item in self.list_layer1_raw_candidates(run_id)}
        for mapping in mappings:
            territory_ids = self._l1_string_list(mapping.get("territory_candidate_ids"))
            if not territory_ids:
                raise ValueError("Every synthesized pillar must map to territory candidate IDs.")
            unknown = set(territory_ids) - known
            if unknown:
                raise ValueError(f"Architecture references unknown territory IDs: {sorted(unknown)}")

    def _persist_layer1_pillar_mapping(
        self,
        architecture_id: str,
        payload: dict[str, Any],
    ) -> PillarTerritoryMapping:
        """Insert immutable pillar traceability after architecture validation."""
        mapping = PillarTerritoryMapping(
            id=str(uuid.uuid4()),
            architecture_candidate_id=architecture_id,
            pillar_id=str(payload["pillar_id"]),
            territory_candidate_ids=self._l1_string_list(payload.get("territory_candidate_ids")),
            source_discovery_item_ids=self._l1_string_list(
                payload.get("source_discovery_item_ids")
            ),
            covered_actor_ids=self._l1_string_list(payload.get("covered_actor_ids")),
            covered_domain_ids=self._l1_string_list(payload.get("covered_domain_ids")),
            covered_enterprise_obligation_ids=self._l1_string_list(
                payload.get("covered_enterprise_obligation_ids")
            ),
            covered_risk_ids=self._l1_string_list(payload.get("covered_risk_ids")),
            cross_cutting_concern_ids=self._l1_string_list(
                payload.get("cross_cutting_concern_ids")
            ),
            subordinate_feature_family_ids=self._l1_string_list(
                payload.get("subordinate_feature_family_ids")
            ),
        )
        self._execute(
            f"""
            INSERT INTO layer1_pillar_territory_mappings (
                id, architecture_candidate_id, pillar_id, territory_candidate_ids,
                source_discovery_item_ids, covered_actor_ids, covered_domain_ids,
                covered_enterprise_obligation_ids, covered_risk_ids,
                cross_cutting_concern_ids, subordinate_feature_family_ids
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}
            )
            """,
            (
                mapping.id,
                mapping.architecture_candidate_id,
                mapping.pillar_id,
                self._dump_json(mapping.territory_candidate_ids),
                self._dump_json(mapping.source_discovery_item_ids),
                self._dump_json(mapping.covered_actor_ids),
                self._dump_json(mapping.covered_domain_ids),
                self._dump_json(mapping.covered_enterprise_obligation_ids),
                self._dump_json(mapping.covered_risk_ids),
                self._dump_json(mapping.cross_cutting_concern_ids),
                self._dump_json(mapping.subordinate_feature_family_ids),
            ),
        )
        return mapping

    def list_layer1_architecture_candidates(
        self,
        run_id: str,
    ) -> list[PillarArchitectureCandidate]:
        """Return coexisting immutable architecture options."""
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_architecture_candidates
            WHERE run_id = {self.param} ORDER BY created_at
            """,
            (run_id,),
        )
        results: list[PillarArchitectureCandidate] = []
        for row in rows:
            payload = dict(row)
            for field in ("pillars", "significant_non_pillar_territory_ids", "unresolved_risk_ids"):
                payload[field] = self._load_json_list(payload[field])
            payload["runtime_provenance"] = self._load_json(payload["runtime_provenance"])
            payload["mappings"] = [
                item.model_dump(mode="python")
                for item in self._list_layer1_pillar_mappings(str(payload["id"]))
            ]
            results.append(PillarArchitectureCandidate.model_validate(payload))
        return results

    def get_layer1_architecture_candidate(
        self,
        architecture_candidate_id: str,
    ) -> PillarArchitectureCandidate:
        """Return one immutable architecture candidate with all mappings."""
        row = self._fetchone(
            f"SELECT run_id FROM layer1_architecture_candidates WHERE id = {self.param}",
            (architecture_candidate_id,),
        )
        if row is None:
            raise ValueError("Layer 1 architecture candidate was not found.")
        for candidate in self.list_layer1_architecture_candidates(str(row["run_id"])):
            if candidate.id == architecture_candidate_id:
                return candidate
        raise ValueError("Layer 1 architecture candidate was not found.")

    def _list_layer1_pillar_mappings(
        self,
        architecture_id: str,
    ) -> list[PillarTerritoryMapping]:
        """Load traceability rows for one immutable architecture."""
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_pillar_territory_mappings
            WHERE architecture_candidate_id = {self.param} ORDER BY pillar_id
            """,
            (architecture_id,),
        )
        results: list[PillarTerritoryMapping] = []
        for row in rows:
            payload = dict(row)
            for field in (
                "territory_candidate_ids",
                "source_discovery_item_ids",
                "covered_actor_ids",
                "covered_domain_ids",
                "covered_enterprise_obligation_ids",
                "covered_risk_ids",
                "cross_cutting_concern_ids",
                "subordinate_feature_family_ids",
            ):
                payload[field] = self._load_json_list(payload[field])
            results.append(PillarTerritoryMapping.model_validate(payload))
        return results

    def select_layer1_architecture(
        self,
        *,
        run_id: str,
        architecture_candidate_id: str,
        state: ArchitectureState,
        actor: str,
        command_id: str,
        note: str = "",
    ) -> dict[str, Any]:
        """Append a review event without mutating any architecture candidate."""
        run = self.get_layer1_territory_run(run_id)
        candidates = {item.id for item in self.list_layer1_architecture_candidates(run_id)}
        if architecture_candidate_id not in candidates:
            raise ValueError("Architecture candidate does not belong to this run.")
        latest = self._fetchone(
            f"""
            SELECT MAX(sequence_number) AS sequence_number
            FROM layer1_architecture_selection_events WHERE run_id = {self.param}
            """,
            (run_id,),
        )
        event = {
            "id": str(uuid.uuid4()),
            "run_id": run.id,
            "project_id": run.project_id,
            "sequence_number": int(latest["sequence_number"] or 0) + 1,
            "architecture_candidate_id": architecture_candidate_id,
            "state": state.value,
            "actor": actor,
            "command_id": command_id,
            "note": note,
            "created_at": territory_now(),
        }
        self._execute(
            f"""
            INSERT INTO layer1_architecture_selection_events (
                id, run_id, project_id, sequence_number, architecture_candidate_id,
                state, actor, command_id, note, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}
            )
            """,
            tuple(event.values()),
        )
        return event

    def latest_layer1_architecture_selection(self, run_id: str) -> dict[str, Any] | None:
        """Return the latest append-only human architecture decision for a run."""
        row = self._fetchone(
            f"""
            SELECT * FROM layer1_architecture_selection_events
            WHERE run_id = {self.param} ORDER BY sequence_number DESC LIMIT 1
            """,
            (run_id,),
        )
        return dict(row) if row is not None else None

    def apply_layer1_architecture(
        self,
        *,
        application_id: str,
        architecture: PillarArchitectureCandidate,
        selection_event_id: str,
        applied_pillar_ids: list[str],
        superseded_pillar_ids: list[str],
        actor: str,
        command_id: str,
        note: str,
    ) -> Layer1ArchitectureApplication:
        """Activate one explicit application record and preserve prior applications."""
        previous = self._fetchone(
            f"""
            SELECT id FROM layer1_architecture_applications
            WHERE project_id = {self.param} AND state = 'active'
            """,
            (architecture.project_id,),
        )
        now = territory_now()
        if previous is not None:
            self._execute(
                f"""
                UPDATE layer1_architecture_applications
                SET state = 'superseded', superseded_at = {self.param}
                WHERE id = {self.param}
                """,
                (now, str(previous["id"])),
            )
        latest = self._fetchone(
            f"""
            SELECT MAX(sequence_number) AS sequence_number
            FROM layer1_architecture_applications WHERE project_id = {self.param}
            """,
            (architecture.project_id,),
        )
        sequence_number = int(latest["sequence_number"] or 0) + 1
        application = Layer1ArchitectureApplication(
            id=application_id,
            project_id=architecture.project_id,
            run_id=architecture.run_id,
            architecture_candidate_id=architecture.id,
            selection_event_id=selection_event_id,
            sequence_number=sequence_number,
            state="active",
            applied_pillar_ids=applied_pillar_ids,
            superseded_pillar_ids=superseded_pillar_ids,
            retained_territory_candidate_ids=architecture.significant_non_pillar_territory_ids,
            architecture_content_hash=architecture.content_hash,
            actor=actor,
            command_id=command_id,
            note=note,
            created_at=now,
        )
        self._execute(
            f"""
            INSERT INTO layer1_architecture_applications (
                id, project_id, run_id, architecture_candidate_id, selection_event_id,
                sequence_number, state, applied_pillar_ids, superseded_pillar_ids,
                retained_territory_candidate_ids, architecture_content_hash, actor,
                command_id, note, created_at, superseded_at
            ) VALUES ({', '.join([self.param] * 16)})
            """,
            (
                application.id,
                application.project_id,
                application.run_id,
                application.architecture_candidate_id,
                application.selection_event_id,
                application.sequence_number,
                application.state,
                self._dump_json(application.applied_pillar_ids),
                self._dump_json(application.superseded_pillar_ids),
                self._dump_json(application.retained_territory_candidate_ids),
                application.architecture_content_hash,
                application.actor,
                application.command_id,
                application.note,
                application.created_at,
                None,
            ),
        )
        return application

    def get_active_layer1_architecture_application(
        self,
        project_id: str,
    ) -> Layer1ArchitectureApplication | None:
        """Return the active applied architecture, if the project has one."""
        row = self._fetchone(
            f"""
            SELECT * FROM layer1_architecture_applications
            WHERE project_id = {self.param} AND state = 'active'
            """,
            (project_id,),
        )
        if row is None:
            return None
        payload = dict(row)
        for field in (
            "applied_pillar_ids",
            "superseded_pillar_ids",
            "retained_territory_candidate_ids",
        ):
            payload[field] = self._load_json_list(payload[field])
        return Layer1ArchitectureApplication.model_validate(payload)

    def persist_layer1_synthesis_result(
        self,
        *,
        run_id: str,
        source_coverage_state_id: str,
        architecture_candidate_ids: list[str],
        retained_non_pillar_territory_ids: list[str],
        runtime_provenance: ModelRuntimeProvenance,
        status: str = "completed",
        error_type: str = "",
        error_message: str = "",
    ) -> Layer1SynthesisResult:
        """Checkpoint synthesis success or failure without losing exploration work."""
        run = self.get_layer1_territory_run(run_id)
        result = Layer1SynthesisResult(
            id=str(uuid.uuid4()),
            run_id=run.id,
            project_id=run.project_id,
            source_coverage_state_id=source_coverage_state_id,
            architecture_candidate_ids=architecture_candidate_ids,
            retained_non_pillar_territory_ids=retained_non_pillar_territory_ids,
            status=status,
            error_type=error_type,
            error_message=error_message,
            runtime_provenance=runtime_provenance,
            created_at=territory_now(),
        )
        self._execute(
            f"""
            INSERT INTO layer1_synthesis_results (
                id, run_id, project_id, source_coverage_state_id,
                architecture_candidate_ids, retained_non_pillar_territory_ids,
                status, error_type, error_message, runtime_provenance, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}
            )
            """,
            (
                result.id,
                result.run_id,
                result.project_id,
                result.source_coverage_state_id,
                self._dump_json(result.architecture_candidate_ids),
                self._dump_json(result.retained_non_pillar_territory_ids),
                result.status,
                result.error_type,
                result.error_message,
                self._dump_json(result.runtime_provenance.model_dump(mode="json")),
                result.created_at.isoformat(),
            ),
        )
        return result

    def list_layer1_synthesis_results(self, run_id: str) -> list[Layer1SynthesisResult]:
        """Return append-only synthesis checkpoints in creation order."""
        rows = self._fetchall(
            f"SELECT * FROM layer1_synthesis_results WHERE run_id = {self.param} "
            "ORDER BY created_at, id",
            (run_id,),
        )
        results: list[Layer1SynthesisResult] = []
        for row in rows:
            payload = dict(row)
            payload["architecture_candidate_ids"] = self._load_json_list(
                payload["architecture_candidate_ids"]
            )
            payload["retained_non_pillar_territory_ids"] = self._load_json_list(
                payload["retained_non_pillar_territory_ids"]
            )
            payload["runtime_provenance"] = self._load_json(payload["runtime_provenance"])
            results.append(Layer1SynthesisResult.model_validate(payload))
        return results

    def persist_layer1_global_architecture_assessment(
        self,
        *,
        run_id: str,
        architecture_candidate_ids: list[str],
        payload: dict[str, Any],
        runtime_provenance: ModelRuntimeProvenance,
    ) -> GlobalArchitectureAssessment:
        """Append a global architecture critic result without changing lens coverage."""
        run = self.get_layer1_territory_run(run_id)
        assessment = GlobalArchitectureAssessment(
            id=str(uuid.uuid4()),
            run_id=run.id,
            project_id=run.project_id,
            architecture_candidate_ids=architecture_candidate_ids,
            product_domain_coverage_score=self._l1_score(
                payload.get("product_domain_coverage_score"),
                0,
            ),
            actor_coverage_score=self._l1_score(payload.get("actor_coverage_score"), 0),
            lifecycle_coverage_score=self._l1_score(
                payload.get("lifecycle_coverage_score"),
                0,
            ),
            enterprise_obligation_coverage_score=self._l1_score(
                payload.get("enterprise_obligation_coverage_score"),
                0,
            ),
            differentiation_score=self._l1_score(
                payload.get("differentiation_score"),
                0,
            ),
            coherence_score=self._l1_score(payload.get("coherence_score"), 0),
            overbroad_pillar_ids=self._l1_string_list(
                payload.get("overbroad_pillar_ids")
            ),
            fragmented_pillar_ids=self._l1_string_list(
                payload.get("fragmented_pillar_ids")
            ),
            hidden_territory_candidate_ids=self._l1_string_list(
                payload.get("hidden_territory_candidate_ids")
            ),
            unresolved_high_severity_risk_ids=self._l1_string_list(
                payload.get("unresolved_high_severity_risk_ids")
            ),
            needs_additional_exploration_lens=bool(
                payload.get("needs_additional_exploration_lens", False)
            ),
            recommended_lens=str(payload.get("recommended_lens") or ""),
            ready_for_human_review=bool(payload.get("ready_for_human_review", False)),
            rationale=str(payload.get("rationale") or ""),
            runtime_provenance=runtime_provenance,
            created_at=territory_now(),
        )
        json_fields = (
            assessment.architecture_candidate_ids,
            assessment.overbroad_pillar_ids,
            assessment.fragmented_pillar_ids,
            assessment.hidden_territory_candidate_ids,
            assessment.unresolved_high_severity_risk_ids,
        )
        self._execute(
            f"""
            INSERT INTO layer1_global_architecture_assessments (
                id, run_id, project_id, architecture_candidate_ids,
                product_domain_coverage_score, actor_coverage_score,
                lifecycle_coverage_score, enterprise_obligation_coverage_score,
                differentiation_score, coherence_score, overbroad_pillar_ids,
                fragmented_pillar_ids, hidden_territory_candidate_ids,
                unresolved_high_severity_risk_ids,
                needs_additional_exploration_lens, recommended_lens,
                ready_for_human_review, rationale, runtime_provenance, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}
            )
            """,
            (
                assessment.id,
                assessment.run_id,
                assessment.project_id,
                self._dump_json(json_fields[0]),
                assessment.product_domain_coverage_score,
                assessment.actor_coverage_score,
                assessment.lifecycle_coverage_score,
                assessment.enterprise_obligation_coverage_score,
                assessment.differentiation_score,
                assessment.coherence_score,
                self._dump_json(json_fields[1]),
                self._dump_json(json_fields[2]),
                self._dump_json(json_fields[3]),
                self._dump_json(json_fields[4]),
                assessment.needs_additional_exploration_lens,
                assessment.recommended_lens,
                assessment.ready_for_human_review,
                assessment.rationale,
                self._dump_json(assessment.runtime_provenance.model_dump(mode="json")),
                assessment.created_at.isoformat(),
            ),
        )
        return assessment

    def list_layer1_global_architecture_assessments(
        self,
        run_id: str,
    ) -> list[GlobalArchitectureAssessment]:
        """Return architecture-level critic history separately from lens assessments."""
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_global_architecture_assessments
            WHERE run_id = {self.param} ORDER BY created_at
            """,
            (run_id,),
        )
        results: list[GlobalArchitectureAssessment] = []
        for row in rows:
            payload = dict(row)
            for field in (
                "architecture_candidate_ids",
                "overbroad_pillar_ids",
                "fragmented_pillar_ids",
                "hidden_territory_candidate_ids",
                "unresolved_high_severity_risk_ids",
            ):
                payload[field] = self._load_json_list(payload[field])
            payload["runtime_provenance"] = self._load_json(payload["runtime_provenance"])
            results.append(GlobalArchitectureAssessment.model_validate(payload))
        return results

    @staticmethod
    def _l1_string_list(value: Any) -> list[str]:
        """Coerce model list drift into stable string identifiers."""
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    @staticmethod
    def _l1_score(value: Any, default: int) -> int:
        """Clamp lens scores to the canonical zero-to-100 range."""
        try:
            return max(0, min(100, int(float(value))))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _l1_rate(value: Any, default: float) -> float:
        """Clamp lens rates to the canonical zero-to-one range."""
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _l1_recommendation(value: Any) -> LensCoverageRecommendation:
        """Route unknown recommendations to explicit human review."""
        try:
            return LensCoverageRecommendation(str(value))
        except ValueError:
            return LensCoverageRecommendation.REQUIRES_HUMAN_REVIEW
