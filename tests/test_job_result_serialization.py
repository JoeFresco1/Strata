from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from pydantic import BaseModel

from strata.config import AppConfig
from strata.db import Database
from strata.generation_types import IterativeGenerationSummary
from strata.jobs import PlatformJobService
from strata.json_safety import JsonSerializationError, ensure_json_safe
from strata.models import FeatureGranularity


class _ResultEnum(str, Enum):
    COMPLETED = "completed"


class _NestedResult(BaseModel):
    id: UUID
    created_at: datetime
    state: _ResultEnum


@dataclass
class _NestedDataclass:
    value: _NestedResult


class JobResultSerializationTests(unittest.TestCase):
    def _db_and_job(self, tmpdir: str, workflow: str = "layer1_generation") -> tuple[Database, object]:
        db = Database(Path(tmpdir) / "result.db")
        project = db.create_project("Result test", "A published product")
        job = db.create_platform_job(
            project_id=project.id,
            kind="generation",
            workflow=workflow,
            scope=workflow,
        )
        return db, job

    def test_json_safety_handles_nested_domain_values(self) -> None:
        nested = _NestedResult(id=uuid4(), created_at=datetime.now(timezone.utc), state=_ResultEnum.COMPLETED)
        safe = ensure_json_safe({"nested": _NestedDataclass(nested), "granularity": FeatureGranularity.WORKFLOW})

        self.assertEqual(safe["nested"]["value"]["id"], str(nested.id))
        self.assertEqual(safe["nested"]["value"]["state"], "completed")
        self.assertEqual(safe["granularity"], "workflow")

    def test_layer1_job_uses_node_ids_and_completes_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, job = self._db_and_job(tmpdir)
            project = db.get_project(job.project_id)
            db.upsert_project_brief(
                project_id=project.id,
                product_idea=project.idea,
                known_competitors=[],
                constraints="",
                status="published",
            )
            node = db.create_node(
                project_id=project.id,
                parent_id=None,
                layer=1,
                node_type="pillar",
                title="Persisted pillar",
                description="A durable pillar.",
            )
            db.set_artifact_freshness = lambda **kwargs: None  # type: ignore[method-assign]
            db.add_artifact_dependency = lambda **kwargs: None  # type: ignore[method-assign]
            summary = IterativeGenerationSummary(
                created_nodes=[node],
                total_rounds=1,
                duplicate_candidates=2,
                filtered_candidates=1,
                unique_family_count=1,
                stop_reason="coverage_exhausted",
                per_round_new_counts=[1],
                per_round_new_family_counts=[1],
                final_coverage_summary="Coverage is complete.",
                final_novelty_score=12,
                lenses_used=["Core Outcomes"],
                models_used=["Stub model"],
                round_summaries=["Core Outcomes: 1 new"],
                thinking_enabled=False,
            )
            services = SimpleNamespace(
                db=db,
                config=AppConfig(database_backend="sqlite", db_path=Path(tmpdir) / "result.db"),
                generation_service=SimpleNamespace(
                    generate_pillars_until_exhausted=lambda *args, **kwargs: summary,
                ),
                brief_service=SimpleNamespace(ensure_brief=lambda project_id: db.get_project_brief(project_id)),
                research_service=SimpleNamespace(competitive_intelligence_enabled=lambda project_id: False),
            )
            service = PlatformJobService(services)
            services.job_service = service

            service.run_job(job.id)
            completed = db.get_platform_job(job.id)

            self.assertEqual(completed.status, "completed", completed.error_message)
            self.assertEqual(completed.result_payload["summary"]["created_node_ids"], [node.id])
            self.assertNotIn("created_nodes", completed.result_payload["summary"])
            self.assertEqual(len(db.list_nodes(project.id, parent_id=None, layer=1, node_type="pillar")), 1)

    def test_supported_workflow_results_are_json_safe(self) -> None:
        payloads = {
            "layer1_generation": {"summary": {"created_node_ids": [str(uuid4())], "stop_reason": "cap"}},
            "layer2_generation": {"summary": {"created_feature_ids": [str(uuid4())]}},
            "layer3_generation": {"created": [{"id": str(uuid4()), "status": "candidate"}]},
            "research": {"research_job": {"id": str(uuid4()), "created_at": datetime.now(timezone.utc)}},
            "layer1_overlap_critic": {"layer": "layer1", "verdicts": 2},
            "specification_compile": {"manifest_id": uuid4(), "status": _ResultEnum.COMPLETED},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            for workflow, payload in payloads.items():
                with self.subTest(workflow=workflow):
                    db, job = self._db_and_job(tmpdir, workflow)
                    updated = db.update_platform_job(job.id, status="completed", result_payload=payload)
                    self.assertEqual(updated.status, "completed")
                    self.assertIsInstance(updated.result_payload, dict)

    def test_unsupported_value_fails_before_terminal_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, job = self._db_and_job(tmpdir)
            db.update_platform_job(job.id, status="running")

            with self.assertRaisesRegex(JsonSerializationError, r"job\.result_payload\.bad"):
                db.update_platform_job(
                    job.id,
                    status="completed",
                    result_payload={"bad": object()},
                )

            self.assertEqual(db.get_platform_job(job.id).status, "running")
