from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from strata.db import Database
from strata.generation import GenerationService
from strata.migrations import apply_migrations


class Layer1StatefulExpansionTests(unittest.TestCase):
    def test_candidate_ledger_preserves_terminal_dispositions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Database(Path(tmpdir) / "expansion.db")
            apply_migrations(db)
            project = db.create_project("Expansion", "Test state")
            run = db.create_layer1_expansion_run(
                project_id=project.id,
                source_discovery_revision_id=None,
                max_rounds=2,
                target_per_round=6,
            )
            lens = db.create_layer1_expansion_lens(
                run_id=run["id"],
                project_id=project.id,
                ordinal=0,
                source_type="baseline_lens",
                source_item_id="baseline-0",
                title="Core",
                instruction="Explore core territory.",
                required=True,
            )
            accepted = db.create_layer1_candidate_record(
                run_id=run["id"],
                lens_id=lens["id"],
                project_id=project.id,
                round_index=0,
                ordinal=0,
                raw_payload={"title": "Accepted"},
            )
            dropped = db.create_layer1_candidate_record(
                run_id=run["id"],
                lens_id=lens["id"],
                project_id=project.id,
                round_index=0,
                ordinal=1,
                raw_payload={"title": "Dropped"},
            )
            db.update_layer1_candidate_record(
                accepted,
                disposition="accepted",
                reason="persisted",
                normalized_payload={"title": "Accepted"},
            )
            db.update_layer1_candidate_record(
                dropped,
                disposition="normalization_dropped",
                reason="not preserved",
            )
            records = db.list_layer1_candidate_dispositions(run["id"])
            self.assertEqual([item["disposition"] for item in records], [
                "accepted",
                "normalization_dropped",
            ])
            self.assertTrue(all(item["disposition"] != "generated" for item in records))

    def test_discovery_lens_queue_is_required_first_and_carries_context(self) -> None:
        engine = GenerationService.__new__(GenerationService)
        engine.db = SimpleNamespace(discovery_snapshot=lambda _: {
            "published": {
                "id": "discovery-1",
                "human_owned_fields": {"item_states": {"excluded": "excluded"}},
                "discovery": {
                    "lenses": [
                        {"id": "optional", "title": "Optional Lens", "recommendation": "optional"},
                        {"id": "required", "title": "Required Lens", "recommendation": "required"},
                        {"id": "excluded", "title": "Excluded Lens", "recommendation": "required"},
                    ],
                    "actors": [{"title": "Administrator"}],
                    "domains": [{"title": "Operations"}],
                    "enterprise_obligations": [{"title": "Audit"}],
                    "coverage_risks": [{"title": "Premature convergence"}],
                },
            }
        })
        revision_id, specs = engine._layer1_discovery_lens_specs("project-1")
        self.assertEqual(revision_id, "discovery-1")
        self.assertEqual(specs[0]["title"], "Required Lens")
        self.assertNotIn("Excluded Lens", [item["title"] for item in specs])
        self.assertIn("Administrator", specs[0]["instruction"])
        self.assertIn("Operations", specs[0]["instruction"])
        self.assertIn("Audit", specs[0]["instruction"])
        self.assertIn("Premature convergence", specs[0]["instruction"])


if __name__ == "__main__":
    unittest.main()
