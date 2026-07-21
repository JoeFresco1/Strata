from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from strata.critic_policy import CriticAuthorityPolicy, CriticDisposition
from strata.db import Database
from strata.layer2_coverage import Layer2CoverageMixin
from strata.layer2_critics import Layer2CriticMixin
from strata.models import Layer2DuplicateMergeDirective, Layer2GraphCriticResponse


class CriticPolicyTests(unittest.TestCase):
    """Prove generated reviewers cannot silently reverse durable human decisions."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "critic-policy.db")
        self.project = self.db.create_project("Authority", "A planning product")
        self.pillar = self.db.create_node(
            project_id=self.project.id, parent_id=None, layer=1, node_type="pillar",
            title="Planning", description="Plan work", status="generated",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _feature(self, *, status: str = "candidate", name: str = "Roadmaps"):
        """Create one generated Layer 2 feature for policy tests."""
        return self.db.create_layer2_feature(
            project_id=self.project.id, canonical_name=name, description="Plan releases",
            feature_type="capability", granularity_class="feature", owner_pillar_id=self.pillar.id,
            candidate_source_ids=[str(uuid.uuid4())], status=status,
        )

    def _human_action(self, artifact_type: str, artifact_id: str, action: str) -> None:
        """Record an explicit authority event independent of mutable status."""
        self.db.record_human_artifact_action(
            project_id=self.project.id, artifact_type=artifact_type, artifact_id=artifact_id,
            action_type=action, actor="user", origin="test",
        )

    def test_new_unreviewed_layer1_candidate_allows_automatic_routing(self) -> None:
        result = CriticAuthorityPolicy(self.db).evaluate(
            project_id=self.project.id, artifact_type="layer1_pillar", artifact_id=self.pillar.id,
        )
        self.assertEqual(CriticDisposition.AUTOMATIC_ROUTING, result.disposition)

    def test_human_kept_layer1_pillar_cannot_be_downgraded(self) -> None:
        self._human_action("layer1_pillar", self.pillar.id, "keep")
        result = CriticAuthorityPolicy(self.db).evaluate(
            project_id=self.project.id, artifact_type="layer1_pillar", artifact_id=self.pillar.id,
        )
        self.assertEqual(CriticDisposition.FINDING_ONLY, result.disposition)
        self.assertEqual("generated", self.db.get_node(self.pillar.id).status)

    def test_human_prioritized_pillar_remains_protected_in_needs_review(self) -> None:
        self._human_action("layer1_pillar", self.pillar.id, "prioritize")
        self.db.update_node(self.pillar.id, status="cut")
        self.assertTrue(CriticAuthorityPolicy(self.db).evaluate(
            project_id=self.project.id, artifact_type="layer1_pillar", artifact_id=self.pillar.id,
        ).protected)

    def test_new_layer2_candidate_may_be_marked_needs_review(self) -> None:
        feature = self._feature()
        Layer2CoverageMixin._apply_layer2_drift_flags(SimpleNamespace(db=self.db), self.project.id, [feature.id])
        self.assertEqual("needs_review", self.db.get_layer2_feature(feature.id).status)

    def test_human_kept_layer2_feature_is_finding_only(self) -> None:
        feature = self._feature(status="kept")
        self.db.record_layer2_review_action(project_id=self.project.id, feature_id=feature.id, action_type="keep", payload={})
        result = CriticAuthorityPolicy(self.db).evaluate(
            project_id=self.project.id, artifact_type="layer2_feature", artifact_id=feature.id,
        )
        self.assertEqual(CriticDisposition.FINDING_ONLY, result.disposition)

    def test_human_approved_feature_not_downgraded_by_coverage_critic(self) -> None:
        feature = self._feature(status="approved")
        self.db.record_layer2_review_action(project_id=self.project.id, feature_id=feature.id, action_type="approve_for_layer3", payload={})
        Layer2CoverageMixin._apply_layer2_drift_flags(SimpleNamespace(db=self.db), self.project.id, [feature.id])
        self.assertEqual("approved", self.db.get_layer2_feature(feature.id).status)
        self.assertEqual(1, len(self.db.list_critic_findings(self.project.id, artifact_id=feature.id)))

    def test_graph_critic_cannot_mutate_human_approved_feature(self) -> None:
        source = self._feature(status="approved", name="Source")
        target = self._feature(name="Target")
        self.db.record_layer2_review_action(project_id=self.project.id, feature_id=source.id, action_type="approve_for_layer3", payload={})
        response = Layer2GraphCriticResponse(duplicate_merges=[Layer2DuplicateMergeDirective(
            source_feature_id=source.id, target_feature_id=target.id, confidence=.9, reason="Similar",
        )])
        stats = {"duplicate_recommendations": 0}
        Layer2CriticMixin._apply_layer2_graph_directives(SimpleNamespace(db=self.db), self.project.id, response, stats)
        self.assertEqual("approved", self.db.get_layer2_feature(source.id).status)
        self.assertEqual([], self.db.list_layer2_relationships(self.project.id))

    def test_human_renamed_and_merged_artifacts_retain_protection(self) -> None:
        for action in ("rename", "merge"):
            feature = self._feature(status="needs_review", name=f"Feature {action}")
            self.db.record_layer2_review_action(project_id=self.project.id, feature_id=feature.id, action_type=action, payload={})
            self.assertTrue(CriticAuthorityPolicy(self.db).evaluate(
                project_id=self.project.id, artifact_type="layer2_feature", artifact_id=feature.id,
            ).protected)

    def test_restored_layer3_revision_is_finding_only(self) -> None:
        feature = self._feature(status="approved")
        expansion = self.db.upsert_layer3_expansion(
            project_id=self.project.id, feature_id=feature.id, parent_pillar_id=self.pillar.id,
            parent_pillar_title=self.pillar.title, feature_name=feature.canonical_name,
            feature_description=feature.description, feature_intent="Plan", expansion_groups=[],
            overlap_review=[], open_questions=[], review_state="approved", provenance={},
        )
        restored = self.db.restore_layer3_revision(
            project_id=self.project.id, logical_expansion_id=expansion.id,
            source_revision_id=expansion.active_revision_id, expected_active_revision_id=expansion.active_revision_id,
            request_id="restore-policy", actor="user",
        )
        restored_revision_id = restored["active_revision"]["id"]
        result = CriticAuthorityPolicy(self.db).evaluate(
            project_id=self.project.id, artifact_type="layer3_expansion", artifact_id=expansion.id,
            revision_id=restored_revision_id,
        )
        self.assertEqual(CriticDisposition.FINDING_ONLY, result.disposition)

    def test_finding_targets_logical_artifact_and_revision(self) -> None:
        finding = self.db.create_critic_finding(
            project_id=self.project.id, artifact_type="layer1_pillar", artifact_id=self.pillar.id,
            artifact_revision_id="revision-2", critic_type="reviewer", category="scope",
            severity="medium", explanation="Concern", evidence={"ref": "x"}, recommended_action="Review",
        )
        self.assertEqual((self.pillar.id, "revision-2"), (finding["artifact_id"], finding["artifact_revision_id"]))

    def test_identical_finding_is_idempotent(self) -> None:
        kwargs = dict(
            project_id=self.project.id, artifact_type="layer1_pillar", artifact_id=self.pillar.id,
            critic_type="coverage", category="gap", severity="low", explanation="Gap",
            evidence={"area": "billing"}, recommended_action="Review", source_payload={"source": 1},
        )
        first = self.db.create_critic_finding(**kwargs)
        second = self.db.create_critic_finding(**kwargs)
        self.assertEqual(first["id"], second["id"])

    def test_changed_source_fingerprint_creates_new_finding(self) -> None:
        base = dict(
            project_id=self.project.id, artifact_type="layer1_pillar", artifact_id=self.pillar.id,
            critic_type="coverage", category="gap", severity="low", explanation="Gap",
            evidence={}, recommended_action="Review",
        )
        self.db.create_critic_finding(**base, source_payload={"revision": 1})
        self.db.create_critic_finding(**base, source_payload={"revision": 2})
        self.assertEqual(2, len(self.db.list_critic_findings(self.project.id)))

    def test_finding_resolution_and_authoritative_command_are_separate(self) -> None:
        feature = self._feature(status="approved")
        finding = self.db.create_critic_finding(
            project_id=self.project.id, artifact_type="layer2_feature", artifact_id=feature.id,
            critic_type="coverage", category="drift", severity="medium", explanation="Drift",
            evidence={}, recommended_action="Cut",
        )
        resolved = self.db.resolve_critic_finding(finding["id"], action="accepted", note="Agreed", resolved_by="user")
        self.assertEqual("accepted", resolved["status"])
        self.assertEqual("approved", self.db.get_layer2_feature(feature.id).status)
        self.db.update_layer2_feature(feature.id, status="cut")
        self.assertEqual("cut", self.db.get_layer2_feature(feature.id).status)

    def test_audit_distinguishes_model_finding_from_human_action(self) -> None:
        feature = self._feature(status="kept")
        self.db.record_layer2_review_action(project_id=self.project.id, feature_id=feature.id, action_type="keep", payload={})
        finding = self.db.create_critic_finding(
            project_id=self.project.id, artifact_type="layer2_feature", artifact_id=feature.id,
            critic_type="graph", category="duplicate", severity="high", explanation="Possible duplicate",
            evidence={}, recommended_action="Review",
        )
        self.db.record_human_artifact_action(
            project_id=self.project.id, artifact_type="layer2_feature", artifact_id=feature.id,
            action_type="resolve_finding", actor="reviewer", origin="api", payload={"finding_id": finding["id"]},
        )
        self.assertEqual("graph", self.db.list_critic_findings(self.project.id)[0]["critic_type"])
        self.assertTrue(self.db.has_human_artifact_action(self.project.id, "layer2_feature", feature.id))

    def test_retry_cannot_bypass_policy_or_duplicate_finding(self) -> None:
        source = self._feature(status="approved", name="Retry source")
        target = self._feature(name="Retry target")
        self.db.record_layer2_review_action(project_id=self.project.id, feature_id=source.id, action_type="approve_for_layer3", payload={})
        response = Layer2GraphCriticResponse(duplicate_merges=[Layer2DuplicateMergeDirective(
            source_feature_id=source.id, target_feature_id=target.id, confidence=.9, reason="Same",
        )])
        for _ in range(2):
            Layer2CriticMixin._apply_layer2_graph_directives(SimpleNamespace(db=self.db), self.project.id, response, {"duplicate_recommendations": 0})
        self.assertEqual("approved", self.db.get_layer2_feature(source.id).status)
        self.assertEqual(1, len(self.db.list_critic_findings(self.project.id, artifact_id=source.id)))

    def test_assistant_and_api_authority_origins_receive_same_protection(self) -> None:
        for origin in ("api", "assistant_confirmed"):
            feature = self._feature(name=origin)
            self.db.record_human_artifact_action(
                project_id=self.project.id, artifact_type="layer2_feature", artifact_id=feature.id,
                action_type="edit", actor="user", origin=origin,
            )
            self.assertTrue(CriticAuthorityPolicy(self.db).evaluate(
                project_id=self.project.id, artifact_type="layer2_feature", artifact_id=feature.id,
            ).protected)

    def test_freshness_change_does_not_erase_layer3_approval(self) -> None:
        feature = self._feature(status="approved")
        expansion = self.db.upsert_layer3_expansion(
            project_id=self.project.id, feature_id=feature.id, parent_pillar_id=self.pillar.id,
            parent_pillar_title=self.pillar.title, feature_name=feature.canonical_name,
            feature_description=feature.description, feature_intent="Plan", expansion_groups=[],
            overlap_review=[], open_questions=[], review_state="approved", provenance={},
        )
        self.db._execute(
            f"UPDATE layer3_expansion_revision_states SET freshness_state = {self.db.param} WHERE revision_id = {self.db.param}",
            ("stale", expansion.active_revision_id),
        )
        revision = self.db.get_layer3_revision(expansion.active_revision_id)
        self.assertEqual(("approved", "stale"), (revision["review_state"], revision["freshness_state"]))

    def test_invalid_artifact_type_is_explicit(self) -> None:
        result = CriticAuthorityPolicy(self.db).evaluate(
            project_id=self.project.id, artifact_type="unknown", artifact_id="x",
        )
        self.assertEqual(CriticDisposition.INVALID, result.disposition)
