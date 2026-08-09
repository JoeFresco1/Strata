from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from strata.layer1_territory_models import (
    AntiGenericPattern,
    AttemptStatus,
    ClosedTerritory,
    ClosedTerritoryScope,
    Layer1ExpansionRun,
    Layer1LensAttempt,
    Layer1LensExecution,
    LensTerminalState,
    ModelRuntimeProvenance,
    PolicyHumanState,
    TerritoryRunStage,
    TerritoryRunStatus,
)


def territory_now() -> str:
    """Return one portable UTC timestamp for Layer 1 territory records."""
    return datetime.now(timezone.utc).isoformat()


class Layer1TerritoryDatabaseMixin:
    """Store canonical runs, lens work, attempts, and human-inspectable policies."""

    def create_layer1_territory_run(
        self,
        *,
        project_id: str,
        source_brief_revision_id: str,
        source_discovery_revision_id: str,
        config: dict[str, Any],
        budget: dict[str, Any],
    ) -> Layer1ExpansionRun:
        """Persist one exact-lineage exploration run before scheduling model work."""
        self._validate_layer1_territory_sources(
            project_id,
            source_brief_revision_id,
            source_discovery_revision_id,
        )
        run_id = str(uuid.uuid4())
        now = territory_now()
        self._execute(
            f"""
            INSERT INTO layer1_territory_runs (
                id, project_id, source_brief_revision_id, source_discovery_revision_id,
                status, stage, config, budget, metrics, incomplete_reason,
                created_at, updated_at, completed_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, '',
                {self.param}, {self.param}, NULL
            )
            """,
            (
                run_id,
                project_id,
                source_brief_revision_id,
                source_discovery_revision_id,
                TerritoryRunStatus.RUNNING.value,
                TerritoryRunStage.DIVERGENCE.value,
                self._dump_json(config),
                self._dump_json(budget),
                self._dump_json({}),
                now,
                now,
            ),
        )
        return self.get_layer1_territory_run(run_id)

    def _validate_layer1_territory_sources(
        self,
        project_id: str,
        brief_revision_id: str,
        discovery_revision_id: str,
    ) -> None:
        """Reject runs not tied to the project's current published upstream revisions."""
        brief_head = self._fetchone(
            f"SELECT current_published_revision_id FROM brief_heads WHERE project_id = {self.param}",
            (project_id,),
        )
        if brief_head is None or str(brief_head["current_published_revision_id"] or "") != brief_revision_id:
            raise ValueError("Layer 1 territory exploration requires the current published brief revision.")
        discovery = self._fetchone(
            f"""
            SELECT project_id, source_brief_revision_id, state
            FROM product_discovery_revisions WHERE id = {self.param}
            """,
            (discovery_revision_id,),
        )
        if (
            discovery is None
            or str(discovery["project_id"]) != project_id
            or str(discovery["source_brief_revision_id"]) != brief_revision_id
            or str(discovery["state"]) != "published"
        ):
            raise ValueError("Layer 1 territory exploration requires published Product Discovery for the same brief.")

    def get_layer1_territory_run(self, run_id: str) -> Layer1ExpansionRun:
        """Load one typed canonical expansion run."""
        row = self._fetchone(
            f"SELECT * FROM layer1_territory_runs WHERE id = {self.param}",
            (run_id,),
        )
        if row is None:
            raise ValueError(f"Layer 1 territory run not found: {run_id}")
        return Layer1ExpansionRun.model_validate(self._territory_run_payload(dict(row)))

    def list_layer1_territory_runs(self, project_id: str) -> list[Layer1ExpansionRun]:
        """Return project exploration history without mixing prototype run records."""
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_territory_runs
            WHERE project_id = {self.param} ORDER BY created_at DESC
            """,
            (project_id,),
        )
        return [
            Layer1ExpansionRun.model_validate(self._territory_run_payload(dict(row)))
            for row in rows
        ]

    def update_layer1_territory_run(
        self,
        run_id: str,
        *,
        status: TerritoryRunStatus,
        stage: TerritoryRunStage,
        metrics: dict[str, Any] | None = None,
        incomplete_reason: str = "",
        completed: bool = False,
    ) -> Layer1ExpansionRun:
        """Checkpoint application-owned run state without rewriting source lineage."""
        self._execute(
            f"""
            UPDATE layer1_territory_runs
            SET status = {self.param}, stage = {self.param}, metrics = {self.param},
                incomplete_reason = {self.param}, updated_at = {self.param},
                completed_at = {self.param}
            WHERE id = {self.param}
            """,
            (
                status.value,
                stage.value,
                self._dump_json(metrics or {}),
                incomplete_reason,
                territory_now(),
                territory_now() if completed else None,
                run_id,
            ),
        )
        return self.get_layer1_territory_run(run_id)

    def create_layer1_lens_work_item(
        self,
        *,
        run_id: str,
        source_lens_id: str,
        source_discovery_item_ids: list[str],
        title: str,
        instruction: str,
        required: bool,
        discovery_order: int,
        risk_priority: int,
        relevance_score: float,
        missing_coverage_priority: int,
        human_priority: int,
        max_attempts: int,
        human_order_position: int | None = None,
    ) -> Layer1LensExecution:
        """Persist one ordered independent lens unit tied to its discovery revision."""
        run = self.get_layer1_territory_run(run_id)
        lens_id = str(uuid.uuid4())
        now = territory_now()
        self._execute(
            f"""
            INSERT INTO layer1_lens_work_items (
                id, run_id, project_id, source_discovery_revision_id, source_lens_id,
                source_discovery_item_ids, title, instruction, required, discovery_order,
                risk_priority, relevance_score, missing_coverage_priority, human_priority,
                human_order_position, state, attempt_count, max_attempts, created_at, updated_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, 0, {self.param}, {self.param}, {self.param}
            )
            """,
            (
                lens_id,
                run.id,
                run.project_id,
                run.source_discovery_revision_id,
                source_lens_id,
                self._dump_json(source_discovery_item_ids),
                title,
                instruction,
                required,
                discovery_order,
                risk_priority,
                relevance_score,
                missing_coverage_priority,
                human_priority,
                human_order_position,
                LensTerminalState.PENDING.value,
                max_attempts,
                now,
                now,
            ),
        )
        return self.get_layer1_lens_work_item(lens_id)

    def get_layer1_lens_work_item(self, lens_execution_id: str) -> Layer1LensExecution:
        """Load one typed lens work item."""
        row = self._fetchone(
            f"SELECT * FROM layer1_lens_work_items WHERE id = {self.param}",
            (lens_execution_id,),
        )
        if row is None:
            raise ValueError(f"Layer 1 lens work item not found: {lens_execution_id}")
        payload = dict(row)
        payload["source_discovery_item_ids"] = self._load_json_list(payload["source_discovery_item_ids"])
        return Layer1LensExecution.model_validate(payload)

    def list_layer1_lens_work_items(self, run_id: str) -> list[Layer1LensExecution]:
        """Return the deterministic queue using required/risk/relevance/human priority."""
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_lens_work_items
            WHERE run_id = {self.param}
            ORDER BY
                CASE WHEN human_order_position IS NULL THEN 1 ELSE 0 END,
                human_order_position ASC,
                required DESC, risk_priority DESC, relevance_score DESC,
                missing_coverage_priority DESC, human_priority DESC, discovery_order ASC
            """,
            (run_id,),
        )
        results: list[Layer1LensExecution] = []
        for row in rows:
            payload = dict(row)
            payload["source_discovery_item_ids"] = self._load_json_list(payload["source_discovery_item_ids"])
            results.append(Layer1LensExecution.model_validate(payload))
        return results

    def update_layer1_lens_state(
        self,
        lens_execution_id: str,
        *,
        state: LensTerminalState,
        attempt_count: int,
    ) -> Layer1LensExecution:
        """Checkpoint a lens state chosen by the deterministic scheduler or human."""
        self._execute(
            f"""
            UPDATE layer1_lens_work_items
            SET state = {self.param}, attempt_count = {self.param}, updated_at = {self.param}
            WHERE id = {self.param}
            """,
            (state.value, attempt_count, territory_now(), lens_execution_id),
        )
        return self.get_layer1_lens_work_item(lens_execution_id)

    def create_layer1_lens_attempt(
        self,
        *,
        lens_execution_id: str,
        attempt_number: int,
        attempt_kind: str,
        settings: dict[str, Any],
        source_projection: dict[str, Any],
        closed_territory_revision_ids: list[str],
        anti_generic_pattern_revision_ids: list[str],
        prompt_key: str,
        prompt_version: str,
        prompt_projection_hash: str,
        runtime_provenance: ModelRuntimeProvenance,
    ) -> Layer1LensAttempt:
        """Freeze request settings and provenance before inference begins."""
        lens = self.get_layer1_lens_work_item(lens_execution_id)
        attempt_id = str(uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO layer1_lens_attempts (
                id, run_id, lens_execution_id, project_id, attempt_number, attempt_kind,
                status, settings, source_projection, closed_territory_revision_ids,
                anti_generic_pattern_revision_ids, prompt_key, prompt_version,
                prompt_projection_hash, raw_response, parsed_candidate_count,
                error_type, error_message, runtime_provenance, created_at,
                started_at, completed_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param},
                {self.param}, '', 0, '', '', {self.param}, {self.param}, NULL, NULL
            )
            """,
            (
                attempt_id,
                lens.run_id,
                lens.id,
                lens.project_id,
                attempt_number,
                attempt_kind,
                AttemptStatus.QUEUED.value,
                self._dump_json(settings),
                self._dump_json(source_projection),
                self._dump_json(closed_territory_revision_ids),
                self._dump_json(anti_generic_pattern_revision_ids),
                prompt_key,
                prompt_version,
                prompt_projection_hash,
                self._dump_json(runtime_provenance.model_dump(mode="json")),
                territory_now(),
            ),
        )
        return self.get_layer1_lens_attempt(attempt_id)

    def get_layer1_lens_attempt(self, attempt_id: str) -> Layer1LensAttempt:
        """Load one attempt with its original frozen settings."""
        row = self._fetchone(
            f"SELECT * FROM layer1_lens_attempts WHERE id = {self.param}",
            (attempt_id,),
        )
        if row is None:
            raise ValueError(f"Layer 1 lens attempt not found: {attempt_id}")
        payload = dict(row)
        for field in ("settings", "source_projection", "runtime_provenance"):
            payload[field] = self._load_json(payload[field])
        for field in ("closed_territory_revision_ids", "anti_generic_pattern_revision_ids"):
            payload[field] = self._load_json_list(payload[field])
        return Layer1LensAttempt.model_validate(payload)

    def list_layer1_lens_attempts(
        self,
        run_id: str,
        *,
        lens_execution_id: str | None = None,
    ) -> list[Layer1LensAttempt]:
        """Return frozen call records in deterministic creation order."""
        if lens_execution_id is None:
            rows = self._fetchall(
                f"""
                SELECT id FROM layer1_lens_attempts
                WHERE run_id = {self.param} ORDER BY created_at
                """,
                (run_id,),
            )
        else:
            rows = self._fetchall(
                f"""
                SELECT id FROM layer1_lens_attempts
                WHERE run_id = {self.param} AND lens_execution_id = {self.param}
                ORDER BY created_at
                """,
                (run_id, lens_execution_id),
            )
        return [self.get_layer1_lens_attempt(str(row["id"])) for row in rows]

    def list_layer1_closed_territory_revisions(
        self,
        project_id: str,
    ) -> list[ClosedTerritory]:
        """Return complete project exclusion history for human review."""
        rows = self._fetchall(
            f"""
            SELECT id FROM layer1_closed_territory_revisions
            WHERE project_id = {self.param} ORDER BY created_at
            """,
            (project_id,),
        )
        return [self.get_closed_territory_revision(str(row["id"])) for row in rows]

    def list_layer1_anti_generic_pattern_revisions(
        self,
        project_id: str,
    ) -> list[AntiGenericPattern]:
        """Return complete project anti-generic policy history."""
        rows = self._fetchall(
            f"""
            SELECT id FROM layer1_anti_generic_pattern_revisions
            WHERE project_id = {self.param} ORDER BY created_at
            """,
            (project_id,),
        )
        return [self.get_anti_generic_pattern_revision(str(row["id"])) for row in rows]

    def checkpoint_layer1_lens_attempt(
        self,
        attempt_id: str,
        *,
        status: AttemptStatus,
        raw_response: str | None = None,
        parsed_candidate_count: int | None = None,
        error_type: str = "",
        error_message: str = "",
    ) -> Layer1LensAttempt:
        """Persist raw output or a typed failure without mutating frozen request settings."""
        current = self.get_layer1_lens_attempt(attempt_id)
        started_at = current.started_at or datetime.fromisoformat(territory_now())
        terminal = status in {
            AttemptStatus.COMPLETED,
            AttemptStatus.TIMED_OUT,
            AttemptStatus.SCHEMA_FAILED,
            AttemptStatus.FAILED,
            AttemptStatus.CANCELLED,
        }
        self._execute(
            f"""
            UPDATE layer1_lens_attempts
            SET status = {self.param}, raw_response = {self.param},
                parsed_candidate_count = {self.param}, error_type = {self.param},
                error_message = {self.param}, started_at = {self.param},
                completed_at = {self.param}
            WHERE id = {self.param}
            """,
            (
                status.value,
                current.raw_response if raw_response is None else raw_response,
                current.parsed_candidate_count if parsed_candidate_count is None else parsed_candidate_count,
                error_type,
                error_message,
                started_at.isoformat(),
                territory_now() if terminal else None,
                attempt_id,
            ),
        )
        return self.get_layer1_lens_attempt(attempt_id)

    def append_closed_territory_revision(
        self,
        *,
        project_id: str,
        logical_id: str | None,
        run_id: str | None,
        title: str,
        description: str,
        semantic_examples: list[str],
        source_family_ids: list[str],
        source: str,
        scope: ClosedTerritoryScope,
        active: bool,
        human_state: PolicyHumanState,
        reason: str,
        actor: str,
        command_id: str,
    ) -> ClosedTerritory:
        """Append an add, remove, or reopen revision without deleting policy history."""
        stable_id = logical_id or str(uuid.uuid4())
        row = self._fetchone(
            f"""
            SELECT MAX(revision_number) AS latest
            FROM layer1_closed_territory_revisions WHERE logical_id = {self.param}
            """,
            (stable_id,),
        )
        revision_number = int(row["latest"] or 0) + 1
        revision_id = str(uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO layer1_closed_territory_revisions (
                id, logical_id, project_id, run_id, revision_number, title, description,
                semantic_examples, source_family_ids, source, scope, active, human_state,
                reason, actor, command_id, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}
            )
            """,
            (
                revision_id,
                stable_id,
                project_id,
                run_id,
                revision_number,
                title,
                description,
                self._dump_json(semantic_examples),
                self._dump_json(source_family_ids),
                source,
                scope.value,
                active,
                human_state.value,
                reason,
                actor,
                command_id,
                territory_now(),
            ),
        )
        return self.get_closed_territory_revision(revision_id)

    def get_closed_territory_revision(self, revision_id: str) -> ClosedTerritory:
        """Load one immutable exclusion-policy revision."""
        row = self._fetchone(
            f"SELECT * FROM layer1_closed_territory_revisions WHERE id = {self.param}",
            (revision_id,),
        )
        if row is None:
            raise ValueError(f"Closed territory revision not found: {revision_id}")
        payload = dict(row)
        payload["semantic_examples"] = self._load_json_list(payload["semantic_examples"])
        payload["source_family_ids"] = self._load_json_list(payload["source_family_ids"])
        return ClosedTerritory.model_validate(payload)

    def list_active_closed_territories(
        self,
        project_id: str,
        *,
        run_id: str | None = None,
    ) -> list[ClosedTerritory]:
        """Return only latest active approved revisions applicable to one run."""
        rows = self._fetchall(
            f"""
            SELECT item.* FROM layer1_closed_territory_revisions item
            JOIN (
                SELECT logical_id, MAX(revision_number) AS revision_number
                FROM layer1_closed_territory_revisions
                WHERE project_id = {self.param}
                GROUP BY logical_id
            ) latest ON latest.logical_id = item.logical_id
                AND latest.revision_number = item.revision_number
            WHERE item.project_id = {self.param}
                AND item.active = {self.param}
                AND item.human_state = 'approved'
                AND (item.scope = 'project' OR item.run_id = {self.param})
            ORDER BY item.created_at
            """,
            (project_id, project_id, True, run_id),
        )
        return [self.get_closed_territory_revision(str(row["id"])) for row in rows]

    def append_anti_generic_pattern_revision(
        self,
        *,
        project_id: str,
        logical_id: str | None,
        title: str,
        description: str,
        semantic_examples: list[str],
        source_run_ids: list[str],
        confidence: float,
        scope: str,
        active: bool,
        human_state: PolicyHumanState,
        actor: str,
        command_id: str,
    ) -> AntiGenericPattern:
        """Append a versioned generic-pattern policy revision for auditability."""
        stable_id = logical_id or str(uuid.uuid4())
        row = self._fetchone(
            f"""
            SELECT MAX(revision_number) AS latest
            FROM layer1_anti_generic_pattern_revisions WHERE logical_id = {self.param}
            """,
            (stable_id,),
        )
        revision_number = int(row["latest"] or 0) + 1
        revision_id = str(uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO layer1_anti_generic_pattern_revisions (
                id, logical_id, project_id, revision_number, title, description,
                semantic_examples, source_run_ids, confidence, scope, active,
                human_state, actor, command_id, created_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}
            )
            """,
            (
                revision_id,
                stable_id,
                project_id,
                revision_number,
                title,
                description,
                self._dump_json(semantic_examples),
                self._dump_json(source_run_ids),
                confidence,
                scope,
                active,
                human_state.value,
                actor,
                command_id,
                territory_now(),
            ),
        )
        return self.get_anti_generic_pattern_revision(revision_id)

    def get_anti_generic_pattern_revision(self, revision_id: str) -> AntiGenericPattern:
        """Load one immutable anti-generic policy revision."""
        row = self._fetchone(
            f"SELECT * FROM layer1_anti_generic_pattern_revisions WHERE id = {self.param}",
            (revision_id,),
        )
        if row is None:
            raise ValueError(f"Anti-generic pattern revision not found: {revision_id}")
        payload = dict(row)
        payload["semantic_examples"] = self._load_json_list(payload["semantic_examples"])
        payload["source_run_ids"] = self._load_json_list(payload["source_run_ids"])
        return AntiGenericPattern.model_validate(payload)

    def list_active_anti_generic_patterns(
        self,
        project_id: str,
    ) -> list[AntiGenericPattern]:
        """Return the latest active human-approved generic-pattern revisions."""
        rows = self._fetchall(
            f"""
            SELECT item.* FROM layer1_anti_generic_pattern_revisions item
            JOIN (
                SELECT logical_id, MAX(revision_number) AS revision_number
                FROM layer1_anti_generic_pattern_revisions
                WHERE project_id = {self.param}
                GROUP BY logical_id
            ) latest ON latest.logical_id = item.logical_id
                AND latest.revision_number = item.revision_number
            WHERE item.project_id = {self.param}
                AND item.active = {self.param}
                AND item.human_state = 'approved'
            ORDER BY item.created_at
            """,
            (project_id, project_id, True),
        )
        return [
            self.get_anti_generic_pattern_revision(str(row["id"]))
            for row in rows
        ]

    @staticmethod
    def _territory_run_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Decode JSON fields before typed run validation."""
        payload["config"] = Layer1TerritoryDatabaseMixin._load_territory_json_value(payload["config"])
        payload["budget"] = Layer1TerritoryDatabaseMixin._load_territory_json_value(payload["budget"])
        payload["metrics"] = Layer1TerritoryDatabaseMixin._load_territory_json_value(payload["metrics"])
        return payload

    @staticmethod
    def _load_territory_json_value(value: Any) -> Any:
        """Decode SQLite JSON text while accepting native PostgreSQL objects."""
        if isinstance(value, str):
            import json
            return json.loads(value)
        return value
