from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from strata.db import Database
from strata.layer3_db import Layer3RevisionConflict
from strata.layer3_revision import reconcile_generated_candidate


class Layer3RevisionTests(unittest.TestCase):
    """Prove the non-destructive Layer 3 candidate and atomic revision contract."""

    @staticmethod
    def _fixture(tmpdir: str) -> tuple[Database, object, object, object]:
        """Create one approved Layer 3 expansion with stable nested IDs."""
        db = Database(Path(tmpdir) / "layer3-revisions.db")
        project = db.create_project("Revision safety", "A survey product")
        db.upsert_project_brief(
            project_id=project.id,
            product_idea=project.idea,
            known_competitors=[],
            constraints="",
            status="published",
        )
        pillar = db.create_node(
            project_id=project.id,
            parent_id=None,
            layer=1,
            node_type="pillar",
            title="Survey authoring",
            description="Author questions.",
            status="kept",
        )
        feature = db.create_layer2_feature(
            project_id=project.id,
            canonical_name="Open text",
            description="Collect qualitative responses.",
            feature_type="question_type",
            granularity_class="feature",
            owner_pillar_id=pillar.id,
            candidate_source_ids=[],
            status="approved",
        )
        expansion = db.upsert_layer3_expansion(
            project_id=project.id,
            feature_id=feature.id,
            parent_pillar_id=pillar.id,
            parent_pillar_title=pillar.title,
            feature_name=feature.canonical_name,
            feature_description=feature.description,
            feature_intent="Collect thoughtful written answers.",
            expansion_groups=[{
                "id": "limits-group",
                "name": "Response limits",
                "description": "Generated group description.",
                "options": [
                    {
                        "id": "one-line-option",
                        "name": "One-line response",
                        "description": "Generated option description.",
                        "selection_state": "include",
                        "configuration_kind": "boolean",
                        "default_recommendation": "Include",
                        "rationale": "Useful for short answers.",
                        "dependencies": [],
                        "overlaps_feature_ids": [],
                    },
                    {
                        "id": "legacy-option",
                        "name": "Legacy format",
                        "description": "Candidate may remove this.",
                        "selection_state": "undecided",
                        "configuration_kind": "text",
                        "default_recommendation": "",
                        "rationale": "",
                        "dependencies": [],
                        "overlaps_feature_ids": [],
                    },
                ],
            }],
            overlap_review=[],
            open_questions=["Should formatting be supported?"],
            review_state="approved",
            provenance={
                "source_layer2_feature_id": feature.id,
                "source_layer2_feature_revision": feature.updated_at.isoformat(),
            },
        )
        return db, project, feature, expansion

    @staticmethod
    def _generated_payload(*, intent: str = "Collect revised written answers.") -> dict[str, object]:
        """Return model-shaped content with untrusted IDs and one new option."""
        return {
            "feature_intent": intent,
            "expansion_groups": [{
                "id": "model-group-id",
                "name": " response limits ",
                "description": "New generated group description.",
                "options": [
                    {
                        "id": "model-option-id",
                        "name": "ONE-LINE response",
                        "description": "New generated option description.",
                        "selection_state": "exclude",
                        "configuration_kind": "boolean",
                        "default_recommendation": "Exclude",
                        "rationale": "New rationale.",
                        "dependencies": [],
                        "overlaps_feature_ids": [],
                    },
                    {
                        "id": "model-new-id",
                        "name": "Character limit",
                        "description": "Set a maximum length.",
                        "selection_state": "include",
                        "configuration_kind": "numeric",
                        "default_recommendation": "500",
                        "rationale": "Bounds response size.",
                        "dependencies": [],
                        "overlaps_feature_ids": [],
                    },
                ],
            }],
            "overlap_review": [],
            "open_questions": ["What maximum should be recommended?"],
        }

    def _candidate(self, db: Database, project: object, feature: object, expansion: object, **changes: object) -> dict[str, object]:
        """Reconcile and persist one candidate against the current active revision."""
        active_revision = db.get_layer3_revision(expansion.active_revision_id)
        generated = self._generated_payload(**changes)
        content, diff, ownership = reconcile_generated_candidate(
            active_revision["payload"], generated, active_revision["field_ownership"]
        )
        artifact = {**active_revision["payload"], **content}
        return db.create_layer3_candidate(
            project_id=project.id,
            feature_id=feature.id,
            artifact_payload=artifact,
            structured_diff=diff,
            field_ownership=ownership,
            source_layer2_feature_revision=feature.updated_at.isoformat(),
            source_brief_revision="brief-r1",
            source_pillar_revision="pillar-r1",
            generation_reference="generation-test",
            origin="regeneration",
            actor="system",
        )

    def test_regeneration_keeps_active_and_reconciles_ids_with_visible_removals(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, feature, expansion = self._fixture(tmpdir)
            before = db.get_layer3_expansion(expansion.id).model_dump(mode="json")

            candidate = self._candidate(db, project, feature, expansion)
            after = db.get_layer3_expansion(expansion.id).model_dump(mode="json")

            self.assertEqual(after, before)
            self.assertEqual(candidate["workflow_state"], "candidate")
            group = candidate["payload"]["expansion_groups"][0]
            self.assertEqual(group["id"], "limits-group")
            self.assertEqual(group["options"][0]["id"], "one-line-option")
            self.assertEqual(group["options"][0]["selection_state"], "include")
            self.assertNotIn(group["options"][1]["id"], {"model-new-id", "one-line-option", "legacy-option"})
            removed_ids = {item["id"] for item in candidate["structured_diff"]["removed"]}
            self.assertIn("legacy-option", removed_ids)
            self.assertTrue(candidate["structured_diff"]["id_matches"])

    def test_human_edited_fields_survive_candidate_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, feature, expansion = self._fixture(tmpdir)
            groups = expansion.model_dump(mode="json")["expansion_groups"]
            groups[0]["description"] = "Human-owned group description."
            groups[0]["options"][0]["description"] = "Human-owned option description."
            db.revise_active_expansion(expansion.id, {"expansion_groups": groups}, actor="user", origin="test")
            current = db.get_layer3_expansion(expansion.id)

            candidate = self._candidate(db, project, feature, current)
            group = candidate["payload"]["expansion_groups"][0]

            self.assertEqual(group["description"], "Human-owned group description.")
            self.assertEqual(group["options"][0]["description"], "Human-owned option description.")
            self.assertEqual(group["options"][0]["selection_state"], "include")

    def test_full_accept_is_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, feature, expansion = self._fixture(tmpdir)
            candidate = self._candidate(db, project, feature, expansion)
            expected = expansion.active_revision_id

            first = db.apply_layer3_candidate(
                project_id=project.id,
                logical_expansion_id=expansion.id,
                candidate_revision_id=candidate["id"],
                expected_active_revision_id=expected,
                request_id="accept-once",
            )
            revision_count = len(db.list_layer3_revisions(expansion.id))
            second = db.apply_layer3_candidate(
                project_id=project.id,
                logical_expansion_id=expansion.id,
                candidate_revision_id=candidate["id"],
                expected_active_revision_id=expected,
                request_id="accept-once",
            )

            active = db.get_layer3_expansion(expansion.id)
            self.assertEqual(active.active_revision_id, candidate["id"])
            self.assertEqual(active.feature_intent, "Collect revised written answers.")
            self.assertEqual(first["active_revision"]["id"], second["active_revision"]["id"])
            self.assertTrue(second["idempotent"])
            self.assertEqual(len(db.list_layer3_revisions(expansion.id)), revision_count)

    def test_partial_accept_changes_only_selected_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, feature, expansion = self._fixture(tmpdir)
            original_groups = copy.deepcopy(expansion.model_dump(mode="json")["expansion_groups"])
            candidate = self._candidate(db, project, feature, expansion, intent="Only this intent should apply.")

            result = db.apply_layer3_candidate(
                project_id=project.id,
                logical_expansion_id=expansion.id,
                candidate_revision_id=candidate["id"],
                expected_active_revision_id=expansion.active_revision_id,
                request_id="partial-once",
                selected_sections=["feature_intent"],
            )

            active = db.get_layer3_expansion(expansion.id)
            self.assertNotEqual(result["active_revision"]["id"], candidate["id"])
            self.assertEqual(active.feature_intent, "Only this intent should apply.")
            self.assertEqual(active.model_dump(mode="json")["expansion_groups"], original_groups)
            self.assertEqual(db.get_layer3_revision(candidate["id"])["workflow_state"], "applied_partial")

    def test_stale_expected_revision_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, feature, expansion = self._fixture(tmpdir)
            candidate = self._candidate(db, project, feature, expansion)
            db.revise_active_expansion(expansion.id, {"feature_intent": "A concurrent human edit."}, actor="user", origin="test")

            with self.assertRaises(Layer3RevisionConflict):
                db.apply_layer3_candidate(
                    project_id=project.id,
                    logical_expansion_id=expansion.id,
                    candidate_revision_id=candidate["id"],
                    expected_active_revision_id=expansion.active_revision_id,
                    request_id="stale-apply",
                )

    def test_restore_creates_new_revision_from_earlier_accepted_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db, project, feature, expansion = self._fixture(tmpdir)
            first_payload = db.get_layer3_revision(expansion.active_revision_id)["payload"]
            candidate = self._candidate(db, project, feature, expansion)
            accepted = db.apply_layer3_candidate(
                project_id=project.id,
                logical_expansion_id=expansion.id,
                candidate_revision_id=candidate["id"],
                expected_active_revision_id=expansion.active_revision_id,
                request_id="accept-before-restore",
            )

            restored = db.restore_layer3_revision(
                project_id=project.id,
                logical_expansion_id=expansion.id,
                source_revision_id=expansion.active_revision_id,
                expected_active_revision_id=accepted["active_revision"]["id"],
                request_id="restore-once",
            )

            self.assertNotIn(restored["active_revision"]["id"], {expansion.active_revision_id, candidate["id"]})
            self.assertEqual(restored["active_revision"]["payload"], first_payload)
            self.assertEqual(db.get_layer3_expansion(expansion.id).feature_intent, expansion.feature_intent)

    def test_failed_application_leaves_no_partial_writes(self) -> None:
        for failpoint in ("verify", "accept", "supersede", "projection", "audit"):
            with self.subTest(failpoint=failpoint), tempfile.TemporaryDirectory() as tmpdir:
                db, project, feature, expansion = self._fixture(tmpdir)
                candidate = self._candidate(db, project, feature, expansion)
                before_projection = db.get_layer3_expansion(expansion.id).model_dump(mode="json")
                before_action_count = db._fetchone("SELECT COUNT(*) AS count FROM layer3_revision_actions")["count"]

                with self.assertRaises(RuntimeError):
                    db.apply_layer3_candidate(
                        project_id=project.id,
                        logical_expansion_id=expansion.id,
                        candidate_revision_id=candidate["id"],
                        expected_active_revision_id=expansion.active_revision_id,
                        request_id=f"must-roll-back-{failpoint}",
                        fail_after_step=failpoint,
                    )

                self.assertEqual(db.get_layer3_expansion(expansion.id).model_dump(mode="json"), before_projection)
                self.assertEqual(db.get_layer3_revision(candidate["id"])["workflow_state"], "candidate")
                after_action_count = db._fetchone("SELECT COUNT(*) AS count FROM layer3_revision_actions")["count"]
                self.assertEqual(after_action_count, before_action_count)
