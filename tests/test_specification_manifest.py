from __future__ import annotations

import json
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from strata.api_export import register_export_routes
from strata.api_support import _build_services
from strata.command_types import (
    CommandActor,
    CommandConflictError,
    CommandValidationError,
    CompileSpecificationManifest,
    CreateFeature,
    CreatePillar,
    IdempotencyConflictError,
    PublishBrief,
    RenderSpecificationManifest,
    UpdateBriefDraft,
)
from strata.config import AppConfig
from strata.dependency_db import feature_revision_token, pillar_revision_token
from strata.specification_models import SpecificationManifestV1, specification_content_hash
from strata.specification_render import render_specification_json, render_specification_markdown
from strata.specification_compiler import SpecificationCompiler


class SpecificationManifestTests(unittest.TestCase):
    """Ticket 5 compiler, durability, command, rendering, and lifecycle contract."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.exports = Path(self.tmp.name) / "exports"
        self.config = AppConfig(
            database_backend="sqlite", db_path=Path(self.tmp.name) / "specification.db",
            exports_dir=self.exports, embeddings_enabled=False,
        )
        self.services = _build_services(self.config)
        self.db = self.services.db
        self.actor = CommandActor.human_ui("manifest-reviewer")
        self.project = self.db.create_project("Canonical Product", "Compile reviewed product decisions")
        brief = self.services.brief_service.ensure_brief(self.project.id)
        self.services.command_service.handle(PublishBrief(
            project_id=self.project.id, actor=self.actor,
            expected_state_token=self.services.command_service.brief_state_token(brief), request_research=False,
        ))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed_approved(self, *, second_feature: bool = False):
        pillar_result = self.services.command_service.handle(CreatePillar(
            project_id=self.project.id, actor=self.actor, title="Authoring", description="Design content.",
        ))
        pillar = self.db.get_node(pillar_result.target_id)
        features = []
        for index, name in enumerate(["Question builder", "Template library"] if second_feature else ["Question builder"]):
            result = self.services.command_service.handle(CreateFeature(
                project_id=self.project.id, actor=self.actor, canonical_name=name,
                description=f"Configure {name}.", owner_pillar_id=pillar.id, status="approved",
            ))
            feature = self.db.get_layer2_feature(result.target_id)
            features.append(feature)
            brief = self.services.brief_service.ensure_brief(self.project.id)
            expansion = self.db.upsert_layer3_expansion(
                project_id=self.project.id, feature_id=feature.id, parent_pillar_id=pillar.id,
                parent_pillar_title=pillar.title, feature_name=feature.canonical_name,
                feature_description=feature.description, feature_intent=f"Intent {index}",
                expansion_groups=[{
                    "id": f"group-{index}", "name": "Behavior", "description": "Human-reviewed behavior.",
                    "options": [{
                        "id": f"option-{index}", "name": "Required", "description": "A required choice.",
                        "selection_state": "include", "configuration_kind": "boolean",
                        "default_recommendation": "Include", "rationale": "Chosen by reviewer.",
                        "dependencies": [], "overlaps_feature_ids": [],
                    }],
                }],
                overlap_review=[], open_questions=["Confirm limits"], review_state="approved",
                provenance={
                    "source_brief_revision": brief.current_published_revision_id,
                    "source_pillar_revision": pillar_revision_token(pillar),
                    "source_layer2_feature_revision": feature_revision_token(feature),
                    "generation_reference": f"model-call-{index}",
                },
            )
            revision_id = str(expansion.active_revision_id)
            self.db.set_artifact_freshness(
                project_id=self.project.id, artifact_type="layer3_revision", artifact_id=expansion.id,
                artifact_revision_id=revision_id, freshness_state="current", lineage_quality="exact",
            )
            for source_type, source_id, revision in (
                ("brief", brief.id, str(brief.current_published_revision_id)),
                ("layer1_pillar", pillar.id, pillar_revision_token(pillar)),
                ("layer2_feature", feature.id, feature_revision_token(feature)),
            ):
                self.db.add_artifact_dependency(
                    project_id=self.project.id, dependent_artifact_type="layer3_revision",
                    dependent_artifact_id=expansion.id, dependent_revision_id=revision_id,
                    source_artifact_type=source_type, source_artifact_id=source_id,
                    source_revision_id=revision, lineage_quality="exact",
                )
        return pillar, features

    def _compile(self, mode: str = "approved", *, request_id: str | None = None, expected: str | None = None, historical: str = ""):
        return self.services.command_service.handle(CompileSpecificationManifest(
            project_id=self.project.id, actor=self.actor, mode=mode,
            historical_brief_revision_id=historical,
            expected_state_token=expected or self.services.command_service.specification_source_state_token(self.project.id),
            idempotency_key=request_id or str(uuid.uuid4()),
        ))

    def test_approved_selection_uses_published_root_reviewed_layers_and_active_l3(self) -> None:
        pillar, features = self._seed_approved()
        manifest = self._compile().data["manifest"]
        self.assertTrue(manifest["exportable"])
        self.assertEqual(manifest["root_lineage"]["brief_revision_id"], self.services.brief_service.ensure_brief(self.project.id).current_published_revision_id)
        self.assertEqual([item["logical_pillar_id"] for item in manifest["layer1"]], [pillar.id])
        self.assertEqual([item["logical_feature_id"] for item in manifest["layer2"]], [features[0].id])
        self.assertEqual(manifest["layer3"][0]["active_revision_id"], self.db.get_layer3_expansion_for_feature(self.project.id, features[0].id).active_revision_id)

    def test_human_owned_layer3_fields_and_selections_are_preserved_verbatim(self) -> None:
        self._seed_approved()
        manifest = self._compile().data["manifest"]
        option = manifest["layer3"][0]["groups"][0]["options"][0]
        self.assertEqual(option["id"], "option-0")
        self.assertEqual(option["selection_state"], "include")
        self.assertEqual(option["rationale"], "Chosen by reviewer.")

    def test_features_under_excluded_pillars_and_cut_or_merged_features_are_excluded(self) -> None:
        pillar, features = self._seed_approved()
        self.db.update_node(pillar.id, status="cut")
        self.db.create_layer2_feature(
            project_id=self.project.id, canonical_name="Merged", description="Old duplicate",
            feature_type="capability", granularity_class="feature", owner_pillar_id=pillar.id,
            candidate_source_ids=[], status="merged",
        )
        manifest = self._compile("draft").data["manifest"]
        self.assertEqual(manifest["layer1"], [])
        self.assertEqual(manifest["layer2"], [])
        excluded = {(item["artifact_type"], item["artifact_id"]) for item in manifest["validation_summary"]["excluded_artifacts"]}
        self.assertIn(("layer2_feature", features[0].id), excluded)

    def test_layer_ordering_is_deterministic_across_compilations(self) -> None:
        self._seed_approved(second_feature=True)
        first = self._compile().data["manifest"]
        second = self._compile().data["manifest"]
        self.assertEqual([item["logical_pillar_id"] for item in first["layer1"]], [item["logical_pillar_id"] for item in second["layer1"]])
        self.assertEqual([item["logical_feature_id"] for item in first["layer2"]], [item["logical_feature_id"] for item in second["layer2"]])
        self.assertEqual(first["relationships"], second["relationships"])

    def test_pending_candidate_never_replaces_active_revision(self) -> None:
        pillar, features = self._seed_approved()
        expansion = self.db.get_layer3_expansion_for_feature(self.project.id, features[0].id)
        active_id = expansion.active_revision_id
        active = self.db.get_layer3_revision(active_id)
        candidate_payload = {**active["payload"], "feature_intent": "Unaccepted candidate intent"}
        candidate = self.db.create_layer3_candidate(
            project_id=self.project.id, feature_id=features[0].id, artifact_payload=candidate_payload,
            structured_diff={}, field_ownership=active["field_ownership"],
            source_layer2_feature_revision=feature_revision_token(features[0]),
            source_brief_revision=str(self.services.brief_service.ensure_brief(self.project.id).current_published_revision_id),
            source_pillar_revision=pillar_revision_token(pillar), generation_reference="candidate-call",
            origin="regeneration", actor="model",
        )
        manifest = self._compile().data["manifest"]
        self.assertEqual(manifest["layer3"][0]["active_revision_id"], active_id)
        self.assertNotEqual(manifest["layer3"][0]["active_revision_id"], candidate["id"])
        self.assertEqual(manifest["layer3"][0]["feature_intent"], "Intent 0")

    def test_stale_pillar_and_feature_block_only_their_identified_branches(self) -> None:
        pillar, features = self._seed_approved(second_feature=True)
        pillar_token = pillar_revision_token(pillar)
        feature_token = feature_revision_token(features[0])
        self.db.set_artifact_freshness(project_id=self.project.id, artifact_type="layer1_pillar", artifact_id=pillar.id, artifact_revision_id=pillar_token, freshness_state="stale", lineage_quality="exact")
        self.db.set_artifact_freshness(project_id=self.project.id, artifact_type="layer2_feature", artifact_id=features[0].id, artifact_revision_id=feature_token, freshness_state="stale", lineage_quality="exact")
        manifest = self._compile().data["manifest"]
        stale_ids = {item["artifact_id"] for item in manifest["issues"] if item["code"] == "STATE_ARTIFACT_STALE"}
        self.assertIn(pillar.id, stale_ids)
        self.assertIn(features[0].id, stale_ids)
        self.assertNotIn(features[1].id, stale_ids)
        self.assertEqual({item["logical_feature_id"] for item in manifest["layer2"]}, {item.id for item in features})

    def test_wrong_layer3_feature_revision_is_detected(self) -> None:
        pillar_result = self.services.command_service.handle(CreatePillar(project_id=self.project.id, actor=self.actor, title="Wrong lineage", description="Test"))
        pillar = self.db.get_node(pillar_result.target_id)
        feature_result = self.services.command_service.handle(CreateFeature(project_id=self.project.id, actor=self.actor, canonical_name="Feature", description="Test", owner_pillar_id=pillar.id, status="approved"))
        feature = self.db.get_layer2_feature(feature_result.target_id)
        brief = self.services.brief_service.ensure_brief(self.project.id)
        expansion = self.db.upsert_layer3_expansion(
            project_id=self.project.id, feature_id=feature.id, parent_pillar_id=pillar.id,
            parent_pillar_title=pillar.title, feature_name=feature.canonical_name, feature_description=feature.description,
            feature_intent="Wrong source", expansion_groups=[], overlap_review=[], open_questions=[], review_state="approved",
            provenance={"source_brief_revision": brief.current_published_revision_id, "source_pillar_revision": pillar_revision_token(pillar), "source_layer2_feature_revision": "wrong-feature-token"},
        )
        self.db.set_artifact_freshness(project_id=self.project.id, artifact_type="layer3_revision", artifact_id=expansion.id, artifact_revision_id=expansion.active_revision_id, freshness_state="current", lineage_quality="exact")
        manifest = self._compile().data["manifest"]
        self.assertIn("SEMANTIC_LAYER3_SOURCE_MISMATCH", {item["code"] for item in manifest["issues"]})
        self.assertFalse(manifest["exportable"])

    def test_mixed_brief_lineage_is_detected(self) -> None:
        pillar_result = self.services.command_service.handle(CreatePillar(project_id=self.project.id, actor=self.actor, title="Mixed root", description="Test"))
        pillar = self.db.get_node(pillar_result.target_id)
        feature_result = self.services.command_service.handle(CreateFeature(project_id=self.project.id, actor=self.actor, canonical_name="Mixed feature", description="Test", owner_pillar_id=pillar.id, status="approved"))
        feature = self.db.get_layer2_feature(feature_result.target_id)
        expansion = self.db.upsert_layer3_expansion(
            project_id=self.project.id, feature_id=feature.id, parent_pillar_id=pillar.id,
            parent_pillar_title=pillar.title, feature_name=feature.canonical_name, feature_description=feature.description,
            feature_intent="Mixed lineage", expansion_groups=[], overlap_review=[], open_questions=[], review_state="approved",
            provenance={"source_brief_revision": "different-published-root", "source_pillar_revision": pillar_revision_token(pillar), "source_layer2_feature_revision": feature_revision_token(feature)},
        )
        self.db.set_artifact_freshness(project_id=self.project.id, artifact_type="layer3_revision", artifact_id=expansion.id, artifact_revision_id=expansion.active_revision_id, freshness_state="current", lineage_quality="exact")
        manifest = self._compile().data["manifest"]
        issue = next(item for item in manifest["issues"] if item["code"] == "SEMANTIC_LAYER3_SOURCE_MISMATCH")
        self.assertNotEqual(issue["details"]["actual"]["brief"], issue["details"]["expected"]["brief"])

    def test_feature_with_wrong_pillar_revision_dependency_is_rejected(self) -> None:
        pillar, features = self._seed_approved()
        feature = features[0]
        token = feature_revision_token(feature)
        self.db._execute(
            "DELETE FROM artifact_dependencies WHERE project_id = ? AND dependent_artifact_type = 'layer2_feature' AND dependent_artifact_id = ? AND source_artifact_type = 'layer1_pillar'",
            (self.project.id, feature.id),
        )
        self.db.add_artifact_dependency(
            project_id=self.project.id, dependent_artifact_type="layer2_feature", dependent_artifact_id=feature.id,
            dependent_revision_id=token, source_artifact_type="layer1_pillar", source_artifact_id=pillar.id,
            source_revision_id="wrong-pillar-revision", lineage_quality="exact",
        )
        manifest = self._compile().data["manifest"]
        self.assertIn("SOURCE_PILLAR_DEPENDENCY_MISSING", {item["code"] for item in manifest["issues"]})
        self.assertFalse(manifest["exportable"])

    def test_missing_or_inaccessible_published_brief_fails_without_manifest(self) -> None:
        other = self.db.create_project("No published brief", "Cannot compile")
        self.services.brief_service.ensure_brief(other.id)
        with self.assertRaises(CommandValidationError):
            self.services.command_service.handle(CompileSpecificationManifest(
                project_id=other.id, actor=self.actor, mode="draft",
                expected_state_token=self.services.command_service.specification_source_state_token(other.id),
                idempotency_key=str(uuid.uuid4()),
            ))
        self.assertEqual(self.db.list_specification_manifests(other.id), [])
        self.db.purge_project(other.id, confirmation_token=f"PURGE-{other.id[:8]}")

    def test_inferred_legacy_lineage_is_explicit_and_blocks_approved_mode(self) -> None:
        pillar, _ = self._seed_approved()
        token = pillar_revision_token(pillar)
        self.db.set_artifact_freshness(project_id=self.project.id, artifact_type="layer1_pillar", artifact_id=pillar.id, artifact_revision_id=token, freshness_state="current", lineage_quality="inferred")
        manifest = self._compile().data["manifest"]
        self.assertIn("SOURCE_LINEAGE_NOT_EXACT", {item["code"] for item in manifest["issues"]})
        self.assertGreaterEqual(manifest["validation_summary"]["lineage_counts"]["inferred"], 1)

    def test_open_critic_finding_is_warning_not_canonical_decision(self) -> None:
        pillar, _ = self._seed_approved()
        finding = self.db.create_critic_finding(
            project_id=self.project.id, artifact_type="layer1_pillar", artifact_id=pillar.id,
            artifact_revision_id=pillar_revision_token(pillar), critic_type="test", category="overlap",
            severity="warning", explanation="Model concern", evidence={}, recommended_action="review",
            source_payload={"pillar": pillar.id}, model_reference="critic-call",
        )
        manifest = self._compile().data["manifest"]
        warning = next(item for item in manifest["issues"] if item["code"] == "STATE_OPEN_CRITIC_FINDING")
        self.assertEqual(warning["details"]["finding_id"], finding["id"])
        self.assertNotIn("recommended_action", json.dumps(manifest["relationships"]))

    def test_duplicate_nested_ids_and_missing_selected_options_are_blocking(self) -> None:
        issues = []
        SpecificationCompiler(self.db)._validate_nested_layer3([{
            "logical_expansion_id": "exp", "active_revision_id": "rev",
            "groups": [
                {"id": "duplicate", "options": [{"id": "same", "overlaps_feature_ids": []}], "selected_option_ids": ["missing"]},
                {"id": "duplicate", "options": [{"id": "same", "overlaps_feature_ids": ["absent"]}]},
            ],
        }], {"included"}, issues)
        codes = {item.code for item in issues}
        self.assertIn("STRUCTURE_DUPLICATE_ID", codes)
        self.assertIn("STRUCTURE_SELECTED_OPTION_MISSING", codes)
        self.assertIn("STRUCTURE_NESTED_REFERENCE_MISSING", codes)

    def test_dangling_relationship_is_excluded_with_blocking_issue(self) -> None:
        _, features = self._seed_approved(second_feature=True)
        relation = self.db.insert_layer2_relationship(
            project_id=self.project.id, source_feature_id=features[0].id, target_feature_id=features[1].id,
            relationship_type="depends_on", strength=1.0,
        )
        self.db.update_layer2_feature(features[1].id, status="cut")
        manifest = self._compile().data["manifest"]
        self.assertNotIn(relation.id, {item["id"] for item in manifest["relationships"]})
        self.assertIn("STRUCTURE_RELATIONSHIP_ENDPOINT_MISSING", {item["code"] for item in manifest["issues"]})

    def test_recompile_after_source_change_creates_new_version_and_keeps_old(self) -> None:
        _, features = self._seed_approved()
        first = self._compile().data["manifest"]
        self.db.update_layer2_feature(features[0].id, description="Changed after first compilation")
        second = self._compile().data["manifest"]
        self.assertEqual(second["sequence_number"], first["sequence_number"] + 1)
        self.assertNotEqual(second["content_hash"], first["content_hash"])
        self.assertEqual(self.db.get_specification_manifest(self.project.id, first["manifest_id"]).content_hash, first["content_hash"])

    def test_issue_rows_exactly_match_serialized_manifest(self) -> None:
        pillar_result = self.services.command_service.handle(CreatePillar(project_id=self.project.id, actor=self.actor, title="No features", description="Empty"))
        self.assertTrue(pillar_result.target_id)
        manifest = self._compile().data["manifest"]
        rows = self.db._fetchall("SELECT issue_code, stage, severity, message FROM specification_manifest_issues WHERE manifest_id = ? ORDER BY ordinal", (manifest["manifest_id"],))
        serialized = [(item["code"], item["stage"], item["severity"], item["message"]) for item in manifest["issues"]]
        self.assertEqual([(row["issue_code"], row["stage"], row["severity"], row["message"]) for row in rows], serialized)

    def test_old_manifest_render_is_reproducible_after_source_change(self) -> None:
        _, features = self._seed_approved()
        manifest = self.db.get_specification_manifest(self.project.id, self._compile().data["manifest"]["manifest_id"])
        before_json = render_specification_json(manifest)
        before_markdown = render_specification_markdown(manifest)
        self.db.update_layer2_feature(features[0].id, canonical_name="Changed current state")
        stored = self.db.get_specification_manifest(self.project.id, manifest.manifest_id)
        self.assertEqual(render_specification_json(stored), before_json)
        self.assertEqual(render_specification_markdown(stored), before_markdown)

    def test_draft_includes_kept_content_but_is_explicitly_nonexportable(self) -> None:
        pillar_result = self.services.command_service.handle(CreatePillar(project_id=self.project.id, actor=self.actor, title="Draft", description="Draft"))
        self.services.command_service.handle(CreateFeature(
            project_id=self.project.id, actor=self.actor, canonical_name="Kept", description="Draft feature",
            owner_pillar_id=pillar_result.target_id, status="kept",
        ))
        manifest = self._compile("draft").data["manifest"]
        self.assertEqual(len(manifest["layer2"]), 1)
        self.assertFalse(manifest["exportable"])
        self.assertIn("POLICY_MODE_NOT_CANONICAL", {item["code"] for item in manifest["issues"]})

    def test_approved_excludes_kept_feature_and_records_missing_layer_error(self) -> None:
        pillar_result = self.services.command_service.handle(CreatePillar(project_id=self.project.id, actor=self.actor, title="Only", description="Only"))
        self.services.command_service.handle(CreateFeature(
            project_id=self.project.id, actor=self.actor, canonical_name="Kept", description="Not approved",
            owner_pillar_id=pillar_result.target_id, status="kept",
        ))
        manifest = self._compile().data["manifest"]
        self.assertEqual(manifest["layer2"], [])
        self.assertFalse(manifest["exportable"])
        self.assertIn("STRUCTURE_NO_FEATURES", {item["code"] for item in manifest["issues"]})

    def test_stale_layer3_blocks_approved_export_and_remains_visible_as_issue(self) -> None:
        _, features = self._seed_approved()
        expansion = self.db.get_layer3_expansion_for_feature(self.project.id, features[0].id)
        self.db.set_artifact_freshness(
            project_id=self.project.id, artifact_type="layer3_revision", artifact_id=expansion.id,
            artifact_revision_id=expansion.active_revision_id, freshness_state="stale", lineage_quality="exact",
        )
        manifest = self._compile().data["manifest"]
        self.assertFalse(manifest["exportable"])
        self.assertIn("STATE_ARTIFACT_STALE", {item["code"] for item in manifest["issues"]})

    def test_historical_mode_never_substitutes_current_descendants(self) -> None:
        self._seed_approved()
        old_revision = self.services.brief_service.ensure_brief(self.project.id).current_published_revision_id
        brief = self.services.brief_service.ensure_brief(self.project.id)
        self.services.command_service.handle(UpdateBriefDraft(
            project_id=self.project.id, actor=self.actor,
            expected_state_token=self.services.command_service.brief_state_token(brief), updates={"problem": "New root"},
        ))
        brief = self.services.brief_service.ensure_brief(self.project.id)
        self.services.command_service.handle(PublishBrief(
            project_id=self.project.id, actor=self.actor,
            expected_state_token=self.services.command_service.brief_state_token(brief), request_research=False,
        ))
        manifest = self._compile("historical", historical=str(old_revision)).data["manifest"]
        self.assertEqual(manifest["root_lineage"]["brief_revision_id"], old_revision)
        self.assertEqual(manifest["layer1"], [])
        self.assertIn("SOURCE_HISTORICAL_DESCENDANTS_UNAVAILABLE", {item["code"] for item in manifest["issues"]})

    def test_manifest_payload_survives_later_source_edits_and_removals(self) -> None:
        _, features = self._seed_approved()
        compiled = self._compile().data["manifest"]
        self.db.update_layer2_feature(features[0].id, canonical_name="Changed later", status="cut")
        stored = self.db.get_specification_manifest(self.project.id, compiled["manifest_id"])
        self.assertEqual(stored.layer2[0]["canonical_payload"]["canonical_name"], "Question builder")
        self.assertEqual(stored.content_hash, compiled["content_hash"])

    def test_manifest_memberships_and_issues_are_durable_and_ordered(self) -> None:
        self._seed_approved(second_feature=True)
        manifest = self._compile().data["manifest"]
        rows = self.db._fetchall("SELECT * FROM specification_manifest_memberships WHERE manifest_id = ? ORDER BY layer, ordinal", (manifest["manifest_id"],))
        self.assertEqual(len(rows), 1 + len(manifest["layer1"]) + len(manifest["layer2"]) + len(manifest["layer3"]))
        self.assertEqual(len({(row["layer"], row["ordinal"]) for row in rows}), len(rows))

    def test_manifest_rows_reject_in_place_update(self) -> None:
        self._seed_approved()
        manifest = self._compile().data["manifest"]
        with self.assertRaises(Exception):
            self.db._execute("UPDATE specification_manifests SET status = 'invalid' WHERE id = ?", (manifest["manifest_id"],))

    def test_repeated_compile_submission_is_idempotent(self) -> None:
        self._seed_approved()
        request_id = str(uuid.uuid4())
        first = self._compile(request_id=request_id)
        second = self._compile(request_id=request_id)
        self.assertEqual(first.target_id, second.target_id)
        self.assertTrue(second.idempotent)
        self.assertEqual(len(self.db.list_specification_manifests(self.project.id)), 1)

    def test_reused_key_with_different_mode_conflicts(self) -> None:
        self._seed_approved()
        request_id = str(uuid.uuid4())
        self._compile(request_id=request_id)
        with self.assertRaises(IdempotencyConflictError):
            self._compile("draft", request_id=request_id)

    def test_stale_source_token_conflicts_without_manifest_write(self) -> None:
        self._seed_approved()
        before = len(self.db.list_specification_manifests(self.project.id))
        with self.assertRaises(CommandConflictError):
            self._compile(expected="stale-token")
        self.assertEqual(len(self.db.list_specification_manifests(self.project.id)), before)

    def test_compile_list_get_and_render_api_contract(self) -> None:
        self._seed_approved()
        app = FastAPI()
        register_export_routes(app, self.services)
        with TestClient(app) as client:
            context = client.get(f"/api/projects/{self.project.id}/specification/compilation-context")
            self.assertEqual(context.status_code, 200)
            request_id = str(uuid.uuid4())
            compiled = client.post(
                f"/api/projects/{self.project.id}/specification/manifests/compile",
                json={"mode": "approved", "historical_brief_revision_id": "", "expected_state_token": context.json()["source_state_token"], "request_id": request_id},
            )
            self.assertEqual(compiled.status_code, 200)
            manifest = compiled.json()["manifest"]
            replay = client.post(
                f"/api/projects/{self.project.id}/specification/manifests/compile",
                json={"mode": "approved", "historical_brief_revision_id": "", "expected_state_token": context.json()["source_state_token"], "request_id": request_id},
            )
            self.assertTrue(replay.json()["idempotent"])
            self.assertEqual(client.get(f"/api/projects/{self.project.id}/specification/manifests").json()[0]["id"], manifest["manifest_id"])
            self.assertEqual(client.get(f"/api/projects/{self.project.id}/specification/manifests/{manifest['manifest_id']}").json()["content_hash"], manifest["content_hash"])
            rendered = client.post(
                f"/api/projects/{self.project.id}/specification/manifests/{manifest['manifest_id']}/render",
                json={"formats": ["json", "markdown"], "expected_state_token": manifest["content_hash"], "request_id": str(uuid.uuid4())},
            )
            self.assertEqual(rendered.status_code, 200)
            downloaded_json = client.get(f"/api/projects/{self.project.id}/specification/manifests/{manifest['manifest_id']}/artifacts/json")
            downloaded_markdown = client.get(f"/api/projects/{self.project.id}/specification/manifests/{manifest['manifest_id']}/artifacts/markdown")
            self.assertEqual(downloaded_json.json()["manifest_id"], manifest["manifest_id"])
            self.assertIn("Question builder", downloaded_markdown.text)
            conflict = client.post(
                f"/api/projects/{self.project.id}/specification/manifests/compile",
                json={"mode": "approved", "historical_brief_revision_id": "", "expected_state_token": "stale", "request_id": str(uuid.uuid4())},
            )
            self.assertEqual(conflict.status_code, 409)
            primary = client.post(f"/api/projects/{self.project.id}/export")
            self.assertEqual(primary.status_code, 200)
            self.assertTrue(primary.json()["manifest_id"])
            self.assertTrue(primary.json()["exportable"])

    def test_injected_compile_failures_at_every_command_stage_roll_back_all_rows(self) -> None:
        self._seed_approved()
        for failure_stage in ("after_command_started", "after_canonical_write", "after_audit_write"):
            self.services.command_service.failure_injector = lambda step, target=failure_stage: (_ for _ in ()).throw(RuntimeError("injected")) if step == target else None
            with self.assertRaises(RuntimeError, msg=failure_stage):
                self._compile()
            self.assertEqual(self.db.list_specification_manifests(self.project.id), [])
            self.assertEqual(self.db._fetchone("SELECT COUNT(*) AS count FROM specification_manifest_memberships")["count"], 0)
            self.assertEqual(self.db._fetchone("SELECT COUNT(*) AS count FROM command_executions WHERE command_type = 'CompileSpecificationManifest'")["count"], 0)
        self.services.command_service.failure_injector = None

    def test_json_and_markdown_renderers_use_only_typed_manifest(self) -> None:
        self._seed_approved()
        manifest = SpecificationManifestV1.model_validate(self._compile().data["manifest"])
        json_payload = json.loads(render_specification_json(manifest))
        markdown = render_specification_markdown(manifest)
        self.assertEqual(json_payload["manifest_id"], manifest.manifest_id)
        self.assertIn("Question builder", markdown)
        self.assertIn("[include] Required", markdown)

    def test_render_command_persists_both_artifact_records_and_replays_idempotently(self) -> None:
        self._seed_approved()
        manifest = self._compile().data["manifest"]
        request_id = str(uuid.uuid4())
        command = RenderSpecificationManifest(
            project_id=self.project.id, actor=self.actor, manifest_id=manifest["manifest_id"],
            expected_state_token=manifest["content_hash"], idempotency_key=request_id,
        )
        first = self.services.command_service.handle(command)
        second = self.services.command_service.handle(command)
        self.assertTrue(Path(first.data["rendered"]["json_path"]).exists())
        self.assertTrue(Path(first.data["rendered"]["markdown_path"]).exists())
        self.assertTrue(second.idempotent)
        self.assertEqual(self.db._fetchone("SELECT COUNT(*) AS count FROM specification_rendered_artifacts")["count"], 2)

    def test_renderer_rejects_stale_manifest_hash(self) -> None:
        self._seed_approved()
        manifest = self._compile().data["manifest"]
        with self.assertRaises(CommandConflictError):
            self.services.command_service.handle(RenderSpecificationManifest(
                project_id=self.project.id, actor=self.actor, manifest_id=manifest["manifest_id"],
                expected_state_token="wrong", idempotency_key=str(uuid.uuid4()),
            ))

    def test_content_hash_is_stable_across_distinct_compile_records(self) -> None:
        self._seed_approved()
        first = self._compile().data["manifest"]
        second = self._compile().data["manifest"]
        self.assertNotEqual(first["manifest_id"], second["manifest_id"])
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(specification_content_hash(first), first["content_hash"])

    def test_clone_starts_clean_while_archive_contains_manifest_history(self) -> None:
        self._seed_approved()
        manifest = self._compile().data["manifest"]
        clone = self.db.clone_project(self.project.id)
        self.assertEqual(self.db.list_specification_manifests(clone.id), [])
        archive = self.db.export_project_archive(self.project.id, self.exports)
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            self.assertIn("tables/specification_manifests.json", names)
            rows = json.loads(bundle.read("tables/specification_manifests.json"))
            self.assertEqual(rows[0]["id"], manifest["manifest_id"])

    def test_archive_import_remaps_manifest_identity_and_preserves_payload(self) -> None:
        self._seed_approved()
        source = self._compile().data["manifest"]
        archive = self.db.export_project_archive(self.project.id, self.exports)
        imported = self.db.import_project_archive(archive)["project"]
        headers = self.db.list_specification_manifests(imported.id)
        self.assertEqual(len(headers), 1)
        self.assertNotEqual(headers[0]["id"], source["manifest_id"])
        restored = self.db.get_specification_manifest(imported.id, headers[0]["id"])
        self.assertEqual(restored.project_id, imported.id)
        self.assertEqual(restored.root_lineage["payload"], source["root_lineage"]["payload"])
        self.assertTrue(restored.imported_historical)
        self.assertEqual(restored.import_metadata["source"]["manifest_id"], source["manifest_id"])
        membership_rows = self.db._fetchall("SELECT * FROM specification_manifest_memberships WHERE manifest_id = ?", (restored.manifest_id,))
        self.assertEqual(len(membership_rows), len(restored.memberships))
        self.assertTrue(all(row["project_id"] == imported.id for row in membership_rows))

    def test_purge_removes_manifest_and_derived_rows(self) -> None:
        self._seed_approved()
        manifest = self._compile().data["manifest"]
        rendered = self.services.command_service.handle(RenderSpecificationManifest(
            project_id=self.project.id, actor=self.actor, manifest_id=manifest["manifest_id"],
            expected_state_token=manifest["content_hash"], idempotency_key=str(uuid.uuid4()),
        )).data["rendered"]
        paths = [Path(value) for value in rendered.values()]
        self.db.purge_project(
            self.project.id, confirmation_token=f"PURGE-{self.project.id[:8]}",
            delete_artifacts=True, exports_dir=self.exports,
        )
        for table in ("specification_manifests", "specification_manifest_memberships", "specification_manifest_issues", "specification_rendered_artifacts"):
            self.assertEqual(self.db._fetchone(f"SELECT COUNT(*) AS count FROM {table}")["count"], 0)
        self.assertTrue(all(not path.exists() for path in paths))


if __name__ == "__main__":
    unittest.main()
