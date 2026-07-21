from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from strata.api_support import _build_services
from strata.command_types import (
    ApproveFeature,
    CommandActor,
    CommandConflictError,
    CreateFeature,
    CreatePillar,
    EditFeature,
    EditPillar,
    PublishBrief,
    RestoreLayer3Revision,
    UpdateBriefDraft,
)
from strata.config import AppConfig
from strata.dependency_db import feature_revision_token, pillar_revision_token
from strata.freshness import FreshnessValidationService


class DependencyRevisionTests(unittest.TestCase):
    """Prove immutable brief publication and deterministic dependency freshness behavior."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.services = _build_services(AppConfig(
            database_backend="sqlite", db_path=Path(self.tmp.name) / "dependencies.db",
            embeddings_enabled=False,
        ))
        self.db = self.services.db
        self.project = self.db.create_project("Lineage", "A revision-aware product")
        self.actor = CommandActor.human_ui("reviewer")
        self.services.brief_service.ensure_brief(self.project.id)
        self._publish()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _publish(self):
        brief = self.services.brief_service.ensure_brief(self.project.id)
        return self.services.command_service.handle(PublishBrief(
            project_id=self.project.id, actor=self.actor,
            expected_state_token=self.services.command_service.brief_state_token(brief),
            request_research=False,
        ))

    def _edit_brief(self, **updates):
        brief = self.services.brief_service.ensure_brief(self.project.id)
        return self.services.command_service.handle(UpdateBriefDraft(
            project_id=self.project.id, actor=self.actor,
            expected_state_token=self.services.command_service.brief_state_token(brief), updates=updates,
        ))

    def _pillar(self, title: str = "Authoring"):
        result = self.services.command_service.handle(CreatePillar(
            project_id=self.project.id, actor=self.actor, title=title, description="Design workflows.",
        ))
        return self.db.get_node(result.target_id)

    def _feature(self, pillar, name: str = "Question builder"):
        result = self.services.command_service.handle(CreateFeature(
            project_id=self.project.id, actor=self.actor, canonical_name=name,
            description=f"Configure {name}.", owner_pillar_id=pillar.id, status="approved",
        ))
        return self.db.get_layer2_feature(result.target_id)

    def _active_layer3(self, pillar, feature):
        brief = self.services.brief_service.ensure_brief(self.project.id)
        expansion = self.db.upsert_layer3_expansion(
            project_id=self.project.id, feature_id=feature.id, parent_pillar_id=pillar.id,
            parent_pillar_title=pillar.title, feature_name=feature.canonical_name,
            feature_description=feature.description, feature_intent="Define behavior.",
            expansion_groups=[], overlap_review=[], open_questions=[], review_state="approved",
            provenance={
                "source_brief_revision": brief.current_published_revision_id,
                "source_pillar_revision": pillar_revision_token(pillar),
                "source_layer2_feature_revision": feature_revision_token(feature),
            },
        )
        revision_id = str(expansion.active_revision_id)
        self.db.set_artifact_freshness(
            project_id=self.project.id, artifact_type="layer3_revision", artifact_id=expansion.id,
            artifact_revision_id=revision_id, freshness_state="current", lineage_quality="exact",
        )
        for source_type, source_id, source_revision in (
            ("brief", brief.id, str(brief.current_published_revision_id)),
            ("layer1_pillar", pillar.id, pillar_revision_token(pillar)),
            ("layer2_feature", feature.id, feature_revision_token(feature)),
        ):
            self.db.add_artifact_dependency(
                project_id=self.project.id, dependent_artifact_type="layer3_revision",
                dependent_artifact_id=expansion.id, dependent_revision_id=revision_id,
                source_artifact_type=source_type, source_artifact_id=source_id,
                source_revision_id=source_revision, lineage_quality="exact",
            )
        return expansion

    def test_published_revision_is_immutable_and_prior_revisions_remain_readable(self) -> None:
        first = self.services.brief_service.ensure_brief(self.project.id)
        first_id = first.current_published_revision_id
        first_payload = self.db.get_brief_revision(first_id)["payload"]
        self._edit_brief(problem="A changed problem")
        draft = self.services.brief_service.ensure_brief(self.project.id)
        self.assertEqual(draft.current_published_revision_id, first_id)
        self.assertNotEqual(draft.current_draft_revision_id, first_id)
        self.assertEqual(self.db.get_brief_revision(first_id)["payload"], first_payload)
        self._publish()
        self.assertNotEqual(self.services.brief_service.ensure_brief(self.project.id).current_published_revision_id, first_id)
        self.assertEqual(self.db.get_brief_revision(first_id)["payload"], first_payload)

    def test_identical_publish_is_idempotent_without_duplicate_revision(self) -> None:
        before = self.services.brief_service.ensure_brief(self.project.id)
        count = len(self.db.list_brief_revisions(self.project.id))
        self._publish()
        after = self.services.brief_service.ensure_brief(self.project.id)
        self.assertEqual(after.current_published_revision_id, before.current_published_revision_id)
        self.assertEqual(len(self.db.list_brief_revisions(self.project.id)), count)

    def test_stale_publish_token_conflicts_and_concurrent_publish_has_one_winner(self) -> None:
        stale = self.services.command_service.brief_state_token(self.services.brief_service.ensure_brief(self.project.id))
        self._edit_brief(problem="Prepare concurrent publication")
        current = self.services.brief_service.ensure_brief(self.project.id)
        with self.assertRaises(CommandConflictError):
            self.services.command_service.handle(PublishBrief(
                project_id=self.project.id, actor=self.actor, expected_state_token=stale, request_research=False,
            ))
        token = self.services.command_service.brief_state_token(current)
        outcomes: list[str] = []
        lock = threading.Lock()

        def publish() -> None:
            try:
                self.services.command_service.handle(PublishBrief(
                    project_id=self.project.id, actor=self.actor, expected_state_token=token,
                    request_research=False,
                ))
                result = "published"
            except CommandConflictError:
                result = "conflict"
            with lock:
                outcomes.append(result)

        threads = [threading.Thread(target=publish) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(outcomes), ["conflict", "published"])

    def test_draft_edit_does_not_stale_descendants_but_publish_propagates(self) -> None:
        pillar = self._pillar()
        feature = self._feature(pillar)
        expansion = self._active_layer3(pillar, feature)
        self._edit_brief(problem="A materially changed source")
        self.assertEqual(self.db.freshness_for_artifact(self.project.id, "layer1_pillar", pillar.id, pillar_revision_token(pillar))["freshness_state"], "current")
        result = self._publish()
        self.assertEqual(result.stale_effect.effect, "marked")
        self.assertGreaterEqual(result.stale_effect.propagation_count, 3)
        self.assertEqual(self.db.freshness_for_artifact(self.project.id, "layer1_pillar", pillar.id, pillar_revision_token(pillar))["freshness_state"], "stale")
        self.assertEqual(self.db.freshness_for_artifact(self.project.id, "layer2_feature", feature.id, feature_revision_token(feature))["freshness_state"], "stale")
        self.assertEqual(self.db.freshness_for_artifact(self.project.id, "layer3_revision", expansion.id, str(expansion.active_revision_id))["freshness_state"], "stale")
        self.assertEqual(self.db.get_layer2_feature(feature.id).status, "approved")
        self.assertEqual(self.db.get_layer3_expansion(expansion.id).review_state, "approved")

    def test_repeated_propagation_is_idempotent_and_reason_names_replaced_revision(self) -> None:
        pillar = self._pillar()
        old_brief = str(self.services.brief_service.ensure_brief(self.project.id).current_published_revision_id)
        self._edit_brief(problem="Change")
        self._publish()
        new_brief = str(self.services.brief_service.ensure_brief(self.project.id).current_published_revision_id)
        report = self.db.mark_descendants_stale(
            project_id=self.project.id, source_artifact_type="brief", source_artifact_id=self.services.brief_service.ensure_brief(self.project.id).id,
            previous_source_revision_id=old_brief, replacement_source_revision_id=new_brief,
            command_id="repeat", actor="reviewer", origin="ui", reason_code="brief_republished",
        )
        self.assertIn(pillar.id, {item["artifact_id"] for item in report["already_stale"]})
        reasons = self.db.freshness_for_artifact(self.project.id, "layer1_pillar", pillar.id, pillar_revision_token(pillar))["stale_reasons"]
        self.assertEqual(len(reasons), 1)
        self.assertEqual(reasons[0]["previous_source_revision_id"], old_brief)
        self.assertEqual(reasons[0]["replacement_source_revision_id"], new_brief)

    def test_feature_edit_stales_only_its_layer3_branch_and_status_change_does_not(self) -> None:
        pillar = self._pillar()
        first = self._feature(pillar, "First")
        second = self._feature(pillar, "Second")
        first_expansion = self._active_layer3(pillar, first)
        second_expansion = self._active_layer3(pillar, second)
        approval = self.services.command_service.handle(ApproveFeature(
            project_id=self.project.id, actor=self.actor, feature_id=first.id,
            expected_state_token=self.services.command_service.feature_state_token(first),
        ))
        self.assertEqual(approval.stale_effect.effect, "none")
        current_first = self.db.get_layer2_feature(first.id)
        edit = self.services.command_service.handle(EditFeature(
            project_id=self.project.id, actor=self.actor, feature_id=first.id,
            expected_state_token=self.services.command_service.feature_state_token(current_first),
            updates={"description": "Changed content."},
        ))
        self.assertEqual(edit.stale_effect.effect, "marked")
        self.assertEqual(self.db.freshness_for_artifact(self.project.id, "layer3_revision", first_expansion.id, str(first_expansion.active_revision_id))["freshness_state"], "stale")
        self.assertEqual(self.db.freshness_for_artifact(self.project.id, "layer3_revision", second_expansion.id, str(second_expansion.active_revision_id))["freshness_state"], "current")

    def test_pillar_edit_invalidates_scope_coverage_and_research_without_rewriting_them(self) -> None:
        pillar = self._pillar()
        scope = self.db.upsert_project_memory(
            project_id=self.project.id, scope="layer2", scope_id=pillar.id,
            memory_type="scope_contract", content={"allowed": ["authoring"]},
        )
        coverage = self.db.upsert_layer2_coverage_matrix_row(
            project_id=self.project.id, pillar_id=pillar.id, family_name="authoring",
            status="partial", evidence_feature_ids=[], missing_examples=["branching"],
        )
        finding = self.db.insert_research_finding(
            project_id=self.project.id, scope="layer1", scope_id=pillar.id,
            finding_type="pillar_assessment", title="Assessment", summary="Current source reading.",
        )
        before_scope = dict(scope.content)
        before_coverage = coverage.model_dump(mode="json")
        before_finding = finding.model_dump(mode="json")
        result = self.services.command_service.handle(EditPillar(
            project_id=self.project.id, actor=self.actor, pillar_id=pillar.id,
            expected_state_token=self.services.command_service.pillar_state_token(pillar),
            description="Changed pillar content.",
        ))
        self.assertEqual(result.stale_effect.effect, "marked")
        states = self.db._fetchall(f"SELECT artifact_type, freshness_state FROM artifact_freshness_states WHERE project_id = {self.db.param} AND artifact_id IN ({self.db.param}, {self.db.param}, {self.db.param})", (self.project.id, scope.id, coverage.id, finding.id))
        self.assertEqual({str(row["freshness_state"]) for row in states}, {"stale"})
        self.assertEqual(self.db.get_project_memory(project_id=self.project.id, scope="layer2", scope_id=pillar.id, memory_type="scope_contract").content, before_scope)
        self.assertEqual(self.db.list_layer2_coverage_matrix(self.project.id)[0].model_dump(mode="json"), before_coverage)
        self.assertEqual(self.db.get_research_finding(finding.id).model_dump(mode="json"), before_finding)

    def test_restore_recomputes_freshness_against_current_sources(self) -> None:
        pillar = self._pillar()
        feature = self._feature(pillar)
        expansion = self._active_layer3(pillar, feature)
        original_revision = str(expansion.active_revision_id)
        self.services.command_service.handle(EditFeature(
            project_id=self.project.id, actor=self.actor, feature_id=feature.id,
            expected_state_token=self.services.command_service.feature_state_token(feature),
            updates={"description": "Changed source."},
        ))
        result = self.services.command_service.handle(RestoreLayer3Revision(
            project_id=self.project.id, actor=self.actor, expansion_id=expansion.id,
            revision_id=original_revision, expected_state_token=original_revision,
        ))
        self.assertEqual(result.data["freshness"]["freshness_state"], "stale")
        self.assertEqual(self.db.get_layer3_expansion(expansion.id).review_state, "approved")

    def test_failed_publish_rolls_back_revision_head_staleness_and_audit(self) -> None:
        pillar = self._pillar()
        old_head = dict(self.db.get_brief_head(self.project.id))
        self._edit_brief(problem="Publish should fail")
        before_publish = self.services.brief_service.ensure_brief(self.project.id)
        before_commands = len(self.db._fetchall("SELECT * FROM command_executions"))
        self.services.command_service.failure_injector = lambda step: (_ for _ in ()).throw(RuntimeError("injected")) if step == "after_canonical_write" else None
        with self.assertRaises(RuntimeError):
            self._publish()
        self.services.command_service.failure_injector = None
        head = self.db.get_brief_head(self.project.id)
        self.assertEqual(head["current_published_revision_id"], old_head["current_published_revision_id"])
        self.assertEqual(self.db.freshness_for_artifact(self.project.id, "layer1_pillar", pillar.id, pillar_revision_token(pillar))["freshness_state"], "current")
        self.assertEqual(len(self.db._fetchall("SELECT * FROM command_executions")), before_commands)
        self.assertEqual(self.services.brief_service.ensure_brief(self.project.id).current_draft_revision_id, before_publish.current_draft_revision_id)

    def test_cross_project_and_orphan_dependencies_are_rejected_or_cleaned(self) -> None:
        pillar = self._pillar()
        other = self.db.create_project("Other", "Other scope")
        self.services.brief_service.ensure_brief(other.id)
        with self.assertRaises(ValueError):
            self.db.add_artifact_dependency(
                project_id=other.id, dependent_artifact_type="layer1_pillar", dependent_artifact_id=pillar.id,
                dependent_revision_id=pillar_revision_token(pillar), source_artifact_type="brief",
                source_artifact_id=self.services.brief_service.ensure_brief(other.id).id,
                source_revision_id=str(self.services.brief_service.ensure_brief(other.id).current_draft_revision_id),
            )
        self.db._execute(f"DELETE FROM nodes WHERE id = {self.db.param}", (pillar.id,))
        self.assertEqual(self.db._fetchall(f"SELECT * FROM artifact_dependencies WHERE dependent_artifact_id = {self.db.param} OR source_artifact_id = {self.db.param}", (pillar.id, pillar.id)), [])

    def test_export_validator_blocks_stale_or_mixed_layer3_output(self) -> None:
        pillar = self._pillar()
        feature = self._feature(pillar)
        expansion = self._active_layer3(pillar, feature)
        current = FreshnessValidationService(self.db).validate_layer3_export(self.project.id, [expansion.id])
        self.assertTrue(current["coherent"])
        self.services.command_service.handle(EditFeature(
            project_id=self.project.id, actor=self.actor, feature_id=feature.id,
            expected_state_token=self.services.command_service.feature_state_token(feature),
            updates={"description": "Changed source."},
        ))
        stale = FreshnessValidationService(self.db).validate_layer3_export(self.project.id, [expansion.id])
        self.assertFalse(stale["coherent"])
        self.assertTrue(stale["stale_artifacts"])

    def test_archive_clone_and_lineage_counts_preserve_dependency_rows(self) -> None:
        pillar = self._pillar()
        feature = self._feature(pillar)
        self._active_layer3(pillar, feature)
        counts = self.db.lineage_counts(self.project.id)
        self.assertEqual(counts, {"exact": 6, "inferred": 0, "unknown": 0})
        clone = self.db.clone_project(self.project.id)
        self.assertEqual(self.db.lineage_counts(clone.id), counts)


if __name__ == "__main__":
    unittest.main()
