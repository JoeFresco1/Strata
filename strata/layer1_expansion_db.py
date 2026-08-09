from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def expansion_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Layer1ExpansionDatabaseMixin:
    """Durable state and candidate dispositions for Layer 1 expansion runs."""

    def create_layer1_expansion_run(
        self,
        *,
        project_id: str,
        source_discovery_revision_id: str | None,
        max_rounds: int,
        target_per_round: int,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        now = expansion_now()
        self._execute(
            f"""
            INSERT INTO layer1_expansion_runs (
                id, project_id, source_discovery_revision_id, algorithm, status,
                max_rounds, target_per_round, stop_reason, created_at, completed_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, 'stateful_discovery_loop', 'running',
                {self.param}, {self.param}, '', {self.param}, NULL
            )
            """,
            (run_id, project_id, source_discovery_revision_id, max_rounds, target_per_round, now),
        )
        return self.get_layer1_expansion_run(run_id)

    def get_layer1_expansion_run(self, run_id: str) -> dict[str, Any]:
        row = self._fetchone(
            f"SELECT * FROM layer1_expansion_runs WHERE id = {self.param}",
            (run_id,),
        )
        if row is None:
            raise ValueError(f"Layer 1 expansion run not found: {run_id}")
        return dict(row)

    def finish_layer1_expansion_run(self, run_id: str, stop_reason: str) -> dict[str, Any]:
        self._execute(
            f"""
            UPDATE layer1_expansion_runs
            SET status = 'completed', stop_reason = {self.param}, completed_at = {self.param}
            WHERE id = {self.param}
            """,
            (stop_reason, expansion_now(), run_id),
        )
        return self.get_layer1_expansion_run(run_id)

    def create_layer1_expansion_lens(
        self,
        *,
        run_id: str,
        project_id: str,
        ordinal: int,
        source_type: str,
        source_item_id: str,
        title: str,
        instruction: str,
        required: bool,
    ) -> dict[str, Any]:
        lens_id = str(uuid.uuid4())
        now = expansion_now()
        self._execute(
            f"""
            INSERT INTO layer1_expansion_lenses (
                id, run_id, project_id, ordinal, source_type, source_item_id,
                title, instruction, required, status, attempts, stale_rounds,
                created_count, last_critic, created_at, updated_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, 'pending', 0, 0, 0,
                {self.param}, {self.param}, {self.param}
            )
            """,
            (
                lens_id, run_id, project_id, ordinal, source_type, source_item_id,
                title, instruction, required, self._dump_json({}), now, now,
            ),
        )
        return self.get_layer1_expansion_lens(lens_id)

    def get_layer1_expansion_lens(self, lens_id: str) -> dict[str, Any]:
        row = self._fetchone(
            f"SELECT * FROM layer1_expansion_lenses WHERE id = {self.param}",
            (lens_id,),
        )
        if row is None:
            raise ValueError(f"Layer 1 expansion lens not found: {lens_id}")
        payload = dict(row)
        payload["last_critic"] = self._load_json(payload["last_critic"])
        return payload

    def update_layer1_expansion_lens(
        self,
        lens_id: str,
        *,
        status: str,
        attempts: int,
        stale_rounds: int,
        created_count: int,
        last_critic: dict[str, Any],
    ) -> dict[str, Any]:
        self._execute(
            f"""
            UPDATE layer1_expansion_lenses
            SET status = {self.param}, attempts = {self.param}, stale_rounds = {self.param},
                created_count = {self.param}, last_critic = {self.param}, updated_at = {self.param}
            WHERE id = {self.param}
            """,
            (
                status, attempts, stale_rounds, created_count,
                self._dump_json(last_critic), expansion_now(), lens_id,
            ),
        )
        return self.get_layer1_expansion_lens(lens_id)

    def create_layer1_candidate_record(
        self,
        *,
        run_id: str,
        lens_id: str,
        project_id: str,
        round_index: int,
        ordinal: int,
        raw_payload: dict[str, Any],
    ) -> str:
        record_id = str(uuid.uuid4())
        now = expansion_now()
        self._execute(
            f"""
            INSERT INTO layer1_candidate_dispositions (
                id, run_id, lens_id, project_id, round_index, ordinal,
                raw_payload, normalized_payload, assessment_payload,
                disposition, disposition_reason, target_node_id,
                duplicate_of_node_id, created_at, updated_at
            ) VALUES (
                {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param},
                {self.param}, {self.param}, {self.param}, 'generated', '', NULL, NULL,
                {self.param}, {self.param}
            )
            """,
            (
                record_id, run_id, lens_id, project_id, round_index, ordinal,
                self._dump_json(raw_payload), self._dump_json({}), self._dump_json({}),
                now, now,
            ),
        )
        return record_id

    def update_layer1_candidate_record(
        self,
        record_id: str,
        *,
        disposition: str,
        reason: str,
        normalized_payload: dict[str, Any] | None = None,
        assessment_payload: dict[str, Any] | None = None,
        target_node_id: str | None = None,
        duplicate_of_node_id: str | None = None,
    ) -> None:
        self._execute(
            f"""
            UPDATE layer1_candidate_dispositions
            SET disposition = {self.param}, disposition_reason = {self.param},
                normalized_payload = {self.param}, assessment_payload = {self.param},
                target_node_id = {self.param}, duplicate_of_node_id = {self.param},
                updated_at = {self.param}
            WHERE id = {self.param}
            """,
            (
                disposition, reason, self._dump_json(normalized_payload or {}),
                self._dump_json(assessment_payload or {}), target_node_id,
                duplicate_of_node_id, expansion_now(), record_id,
            ),
        )

    def list_layer1_candidate_dispositions(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            f"""
            SELECT * FROM layer1_candidate_dispositions
            WHERE run_id = {self.param}
            ORDER BY round_index, ordinal
            """,
            (run_id,),
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for field in ("raw_payload", "normalized_payload", "assessment_payload"):
                item[field] = self._load_json(item[field])
            results.append(item)
        return results
