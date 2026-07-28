from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.layer1_territory_eval import (
    EVALUATION_LENSES,
    _linked_discovery_coverage,
    _model_file_provenance,
    evaluate_result,
    evaluation_discovery,
    seed_database,
)


class Layer1TerritoryEvaluationTests(unittest.TestCase):
    """Protect controlled fixtures and reproducible metrics across model profiles."""

    def test_required_three_lenses_and_divergent_source_ids_are_fixed(self) -> None:
        """The evaluation fixture covers the three required comparison lenses."""
        discovery = evaluation_discovery()
        self.assertEqual(
            tuple(item["title"] for item in discovery["lenses"]),
            EVALUATION_LENSES,
        )
        self.assertTrue(
            all(item["required_discovery_item_ids"] for item in discovery["lenses"])
        )

    def test_fixture_hash_is_identical_across_isolated_profile_runs(self) -> None:
        """Every model profile receives byte-equivalent discovery content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            first_db, _, first_hash = seed_database(Path(tmpdir) / "first.db")
            second_db, _, second_hash = seed_database(Path(tmpdir) / "second.db")
            self.assertEqual(first_hash, second_hash)
            self.assertEqual(
                first_db._fetchone("SELECT MAX(version) AS version FROM schema_migrations")["version"],
                second_db._fetchone("SELECT MAX(version) AS version FROM schema_migrations")["version"],
            )

    def test_existing_arm_metrics_are_reproducible(self) -> None:
        """The control-arm rubric derives the same values from the same artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project_id, _ = seed_database(Path(tmpdir) / "metrics.db")
            result = {
                "pillars": [{
                    "title": "Delegated Administration",
                    "description": "Administrators delegate tenant operations.",
                    "source_lens": "Actors, Authority, and Decision Rights",
                }]
            }
            self.assertEqual(
                evaluate_result(db, project_id, "existing", result),
                evaluate_result(db, project_id, "existing", result),
            )

    def test_local_model_file_provenance_is_exact(self) -> None:
        """A diagnostic model is identified by path, size, and content hash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir) / "control.gguf"
            model_path.write_bytes(b"model")
            provenance = _model_file_provenance(model_path)
            self.assertEqual(provenance["size_bytes"], 5)
            self.assertEqual(
                provenance["sha256"],
                hashlib.sha256(b"model").hexdigest(),
            )

    def test_discovery_coverage_accepts_source_or_affected_attribution(self) -> None:
        """Coverage does not discard a valid required source-item link."""
        candidates = [
            SimpleNamespace(
                source_discovery_item_ids=["obligation-access"],
                affected_enterprise_obligation_ids=[],
            ),
            SimpleNamespace(
                source_discovery_item_ids=[],
                affected_enterprise_obligation_ids=["obligation-audit"],
            ),
        ]
        self.assertEqual(
            _linked_discovery_coverage(
                candidates,
                "enterprise_obligations",
                "affected_enterprise_obligation_ids",
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
