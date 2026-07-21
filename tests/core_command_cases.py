from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import BackgroundTasks

from strata.api_support import _build_services, _execute_assistant_action
from strata.command_types import (
    ActorType,
    ApproveFeature,
    BulkResolveFeatureReview,
    CommandActor,
    CommandConflictError,
    CommandOrigin,
    CreateFeature,
    CreateOrUpdateFeatureRelationship,
    CreatePillar,
    CutFeature,
    EditFeature,
    EditPillar,
    HumanAuthorityRequiredError,
    IdempotencyConflictError,
    KeepFeature,
    MergeFeatures,
    InvalidTransitionError,
    ResolveCriticFinding,
    UpdateBriefDraft,
)
from strata.config import AppConfig


class CommandLayerTests(unittest.TestCase):
    """Prove the canonical command boundary's authority, concurrency, and transaction contract."""

    def setUp(self) -> None:
        """Create an isolated SQLite service graph with one published project."""
        self.tmp = tempfile.TemporaryDirectory()
        self.services = _build_services(AppConfig(
            database_backend="sqlite",
            db_path=Path(self.tmp.name) / "commands.db",
            embeddings_enabled=False,
        ))
        self.project = self.services.db.create_project("Commands", "A mutation boundary")
        self.brief = self.services.brief_service.ensure_brief(self.project.id)
        self.services.brief_service.publish(self.project.id)
        self.actor = CommandActor.human_ui("reviewer")

    def tearDown(self) -> None:
        """Release the temporary database after each test."""
        self.tmp.cleanup()

    def _pillar(self, title: str = "Workflows"):
        """Create a pillar through the authoritative handler."""
        result = self.services.command_service.handle(CreatePillar(
            project_id=self.project.id, actor=self.actor, title=title,
        ))
        return self.services.db.get_node(result.target_id)

    def _feature(self, pillar=None, name: str = "Survey builder"):
        """Create a feature through the authoritative handler."""
        pillar = pillar or self._pillar()
        result = self.services.command_service.handle(CreateFeature(
            project_id=self.project.id, actor=self.actor, canonical_name=name,
            description="Build a survey.", owner_pillar_id=pillar.id,
        ))
        return self.services.db.get_layer2_feature(result.target_id)

    def test_brief_command_persists_one_typed_audit_and_stale_effect(self) -> None:
        """A draft edit records its command type without staling published descendants."""
        pillar = self._pillar()
        current = self.services.brief_service.ensure_brief(self.project.id)
        result = self.services.command_service.handle(UpdateBriefDraft(
            project_id=self.project.id, actor=self.actor,
            expected_state_token=self.services.command_service.brief_state_token(current),
            updates={"problem": "Teams lose track of mutation ownership."},
        ))
        rows = self.services.db._fetchall("SELECT * FROM command_executions WHERE id = ?", (result.command_id,))
        self.assertEqual(rows[0]["command_type"], "UpdateBriefDraft")
        self.assertEqual(result.stale_effect.effect, "none")
        self.assertNotIn(pillar.id, result.stale_effect.artifact_ids)

    def test_stale_brief_pillar_and_feature_writes_conflict(self) -> None:
        """Every existing authoritative artifact rejects an obsolete token."""
        pillar = self._pillar()
        feature = self._feature(pillar)
        current = self.services.brief_service.ensure_brief(self.project.id)
        brief_token = self.services.command_service.brief_state_token(current)
        self.services.command_service.handle(UpdateBriefDraft(project_id=self.project.id, actor=self.actor, expected_state_token=brief_token, updates={"notes": "first"}))
        with self.assertRaises(CommandConflictError):
            self.services.command_service.handle(UpdateBriefDraft(project_id=self.project.id, actor=self.actor, expected_state_token=brief_token, updates={"notes": "stale"}))
        pillar_token = self.services.command_service.pillar_state_token(pillar)
        self.services.command_service.handle(EditPillar(project_id=self.project.id, actor=self.actor, expected_state_token=pillar_token, pillar_id=pillar.id, title="Updated"))
        with self.assertRaises(CommandConflictError):
            self.services.command_service.handle(EditPillar(project_id=self.project.id, actor=self.actor, expected_state_token=pillar_token, pillar_id=pillar.id, title="Stale"))
        feature_token = self.services.command_service.feature_state_token(feature)
        self.services.command_service.handle(EditFeature(project_id=self.project.id, actor=self.actor, expected_state_token=feature_token, feature_id=feature.id, updates={"description": "Updated"}))
        with self.assertRaises(CommandConflictError):
            self.services.command_service.handle(EditFeature(project_id=self.project.id, actor=self.actor, expected_state_token=feature_token, feature_id=feature.id, updates={"description": "Stale"}))

    def test_retry_is_idempotent_and_key_reuse_with_other_input_conflicts(self) -> None:
        """A repeated command returns its stored result while payload drift is rejected."""
        feature = self._feature()
        token = self.services.command_service.feature_state_token(feature)
        command = KeepFeature(project_id=self.project.id, actor=self.actor, idempotency_key="keep-once", expected_state_token=token, feature_id=feature.id)
        first = self.services.command_service.handle(command)
        second = self.services.command_service.handle(command)
        self.assertFalse(first.idempotent)
        self.assertTrue(second.idempotent)
        self.assertEqual(first.command_id, second.command_id)
        with self.assertRaises(IdempotencyConflictError):
            self.services.command_service.handle(CutFeature(project_id=self.project.id, actor=self.actor, idempotency_key="keep-once", expected_state_token=token, feature_id=feature.id))

    def test_injected_failure_rolls_back_canonical_authority_and_command_rows(self) -> None:
        """Failure after authority persistence leaves no partial feature mutation or audit."""
        feature = self._feature()
        token = self.services.command_service.feature_state_token(feature)
        before_actions = len(self.services.db._fetchall("SELECT * FROM artifact_authority_actions"))

        def fail(step: str) -> None:
            if step == "after_authority_write":
                raise RuntimeError("injected")

        self.services.command_service.failure_injector = fail
        with self.assertRaises(RuntimeError):
            self.services.command_service.handle(ApproveFeature(project_id=self.project.id, actor=self.actor, idempotency_key="rollback", expected_state_token=token, feature_id=feature.id))
        self.services.command_service.failure_injector = None
        self.assertEqual(self.services.db.get_layer2_feature(feature.id).status, feature.status)
        self.assertEqual(len(self.services.db._fetchall("SELECT * FROM artifact_authority_actions")), before_actions)
        self.assertIsNone(self.services.db._fetchone("SELECT * FROM command_executions WHERE idempotency_key = ?", ("rollback",)))

    def test_model_actor_cannot_invoke_human_only_command(self) -> None:
        """Model output cannot directly perform an authoritative edit."""
        feature = self._feature()
        actor = CommandActor(actor_id="model", actor_type=ActorType.MODEL, origin=CommandOrigin.MODEL_GENERATION)
        with self.assertRaises(HumanAuthorityRequiredError):
            self.services.command_service.handle(EditFeature(project_id=self.project.id, actor=actor, expected_state_token=self.services.command_service.feature_state_token(feature), feature_id=feature.id, updates={"description": "model edit"}))

    def test_assistant_confirmed_actor_remains_human_in_both_audits(self) -> None:
        """Assistant confirmation records a human actor and assistant origin."""
        feature = self._feature()
        actor = CommandActor.human_assistant("reviewer")
        result = self.services.command_service.handle(EditFeature(project_id=self.project.id, actor=actor, expected_state_token=self.services.command_service.feature_state_token(feature), feature_id=feature.id, updates={"description": "Confirmed"}))
        command_row = self.services.db._fetchone("SELECT * FROM command_executions WHERE id = ?", (result.command_id,))
        authority = self.services.db._fetchone("SELECT * FROM artifact_authority_actions WHERE artifact_id = ? ORDER BY created_at DESC LIMIT 1", (feature.id,))
        self.assertEqual(command_row["actor_type"], "human")
        self.assertEqual(command_row["origin"], "assistant_confirmed")
        self.assertEqual(authority["actor"], "reviewer")
        self.assertEqual(authority["origin"], "assistant_confirmed")

    def test_assistant_confirmation_invokes_the_same_typed_handler(self) -> None:
        """Assistant transport adapts a confirmed proposal into the shared command service."""
        feature = self._feature()
        proposal = SimpleNamespace(
            id="proposal-command-path", project_id=self.project.id,
            action_type="update_layer2_feature",
            payload={"feature_id": feature.id, "description": "Confirmed through assistant"},
            expected_state={"state_token": self.services.command_service.feature_state_token(feature)},
        )
        with patch.object(self.services.command_service, "handle", wraps=self.services.command_service.handle) as handle:
            result = _execute_assistant_action(self.services, proposal, BackgroundTasks())
        command = handle.call_args.args[0]
        self.assertIsInstance(command, EditFeature)
        self.assertEqual(command.actor.actor_type, ActorType.HUMAN)
        self.assertEqual(command.actor.origin, CommandOrigin.ASSISTANT_CONFIRMED)
        self.assertEqual(result["feature"]["description"], "Confirmed through assistant")

    def test_merge_conflict_does_not_create_relationship_or_change_source(self) -> None:
        """A stale merge target aborts the whole merge transaction."""
        pillar = self._pillar()
        source = self._feature(pillar, "Source")
        target = self._feature(pillar, "Target")
        source_token = self.services.command_service.feature_state_token(source)
        with self.assertRaises(CommandConflictError):
            self.services.command_service.handle(MergeFeatures(project_id=self.project.id, actor=self.actor, expected_state_token=source_token, source_feature_id=source.id, target_feature_id=target.id, expected_target_state_token="stale"))
        self.assertEqual(self.services.db.get_layer2_feature(source.id).status, source.status)
        self.assertEqual(self.services.db.list_layer2_relationships(self.project.id), [])

    def test_relationship_command_is_atomic_and_declares_layer3_staleness(self) -> None:
        """A relationship, review audit, authority event, and command commit together."""
        pillar = self._pillar()
        source = self._feature(pillar, "Source")
        target = self._feature(pillar, "Target")
        result = self.services.command_service.handle(CreateOrUpdateFeatureRelationship(
            project_id=self.project.id, actor=self.actor,
            expected_state_token=self.services.command_service.feature_state_token(source),
            expected_target_state_token=self.services.command_service.feature_state_token(target),
            source_feature_id=source.id, target_feature_id=target.id, relationship_type="related_to",
        ))
        self.assertEqual(result.stale_effect.effect, "deferred")
        self.assertEqual(len(self.services.db.list_layer2_relationships(self.project.id)), 1)

    def test_finding_resolution_requires_current_token_and_is_idempotent(self) -> None:
        """Finding decisions share optimistic concurrency and command idempotency."""
        feature = self._feature()
        finding = self.services.db.create_critic_finding(
            project_id=self.project.id, artifact_type="layer2_feature", artifact_id=feature.id,
            critic_type="test", category="clarity", severity="medium", explanation="Needs detail",
            evidence={}, recommended_action="Review", source_payload={"version": 1},
        )
        token = self.services.command_service.finding_state_token(finding)
        command = ResolveCriticFinding(project_id=self.project.id, actor=self.actor, idempotency_key="finding-once", expected_state_token=token, finding_id=finding["id"], resolution="dismissed")
        first = self.services.command_service.handle(command)
        self.assertEqual(first.data["finding"]["status"], "dismissed")
        self.assertTrue(self.services.command_service.handle(command).idempotent)
        with self.assertRaises(CommandConflictError):
            self.services.command_service.handle(ResolveCriticFinding(project_id=self.project.id, actor=self.actor, expected_state_token=token, finding_id=finding["id"], resolution="accepted"))

    def test_concurrent_sqlite_edits_yield_one_success_and_one_conflict(self) -> None:
        """SQLite's immediate transaction serializes competing expected-revision checks."""
        feature = self._feature()
        token = self.services.command_service.feature_state_token(feature)
        outcomes: list[str] = []

        def edit(description: str) -> None:
            """Race one edit using the same previously observed feature token."""
            try:
                self.services.command_service.handle(EditFeature(project_id=self.project.id, actor=self.actor, expected_state_token=token, feature_id=feature.id, updates={"description": description}))
                outcomes.append("success")
            except CommandConflictError:
                outcomes.append("conflict")

        threads = [threading.Thread(target=edit, args=(value,)) for value in ("one", "two")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(outcomes, ["success", "conflict"])

    def test_merged_feature_is_a_terminal_authoritative_state(self) -> None:
        """Invalid post-merge edits are rejected consistently by the command layer."""
        pillar = self._pillar()
        source = self._feature(pillar, "Source")
        target = self._feature(pillar, "Target")
        merged = self.services.command_service.handle(MergeFeatures(
            project_id=self.project.id, actor=self.actor,
            expected_state_token=self.services.command_service.feature_state_token(source),
            expected_target_state_token=self.services.command_service.feature_state_token(target),
            source_feature_id=source.id, target_feature_id=target.id,
        ))
        with self.assertRaises(InvalidTransitionError):
            self.services.command_service.handle(EditFeature(
                project_id=self.project.id, actor=self.actor, expected_state_token=merged.state_token,
                feature_id=source.id, updates={"description": "Too late"},
            ))

    def test_bulk_review_conflict_rolls_back_earlier_items(self) -> None:
        """A stale item aborts an entire multi-feature command without partial status writes."""
        pillar = self._pillar()
        first = self._feature(pillar, "First")
        second = self._feature(pillar, "Second")
        tokens = {
            first.id: self.services.command_service.feature_state_token(first),
            second.id: self.services.command_service.feature_state_token(second),
        }
        self.services.command_service.handle(EditFeature(
            project_id=self.project.id, actor=self.actor, expected_state_token=tokens[second.id],
            feature_id=second.id, updates={"description": "Changed elsewhere"},
        ))
        with self.assertRaises(CommandConflictError):
            self.services.command_service.handle(BulkResolveFeatureReview(
                project_id=self.project.id, actor=self.actor, feature_ids=(first.id, second.id),
                action="approve_for_layer3", expected_state_tokens=tokens,
            ))
        self.assertEqual(self.services.db.get_layer2_feature(first.id).status, first.status)
