from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from strata.command_service import CommandService
from strata.command_types import (
    CommandConflictError,
    CommandActor,
    GenerateProductDiscovery,
    MarkCompetitorFindingStale,
    UpdateDiscoveryHumanFields,
)
from strata.competitor_research_service import CompetitorResearchService
from strata.config import AppConfig
from strata.db import Database
from strata.discovery_models import (
    CompetitorResearchMode,
    DiscoveryRevisionState,
)
from strata.discovery_service import BASELINE_LENSES, DiscoveryService
from strata.migrations import apply_migrations


def empty_discovery(**updates: object) -> dict[str, object]:
    """Return the smallest valid Product Discovery payload for persistence tests."""
    payload: dict[str, object] = {
        "archetypes": [],
        "lenses": [],
        "actors": [],
        "lifecycle_stages": [],
        "enterprise_obligations": [],
        "domains": [],
        "cross_domain_opportunities": [],
        "coverage_risks": [],
        "open_questions": [],
        "summary": {},
    }
    payload.update(updates)
    return payload


class FakeJobService:
    """Persist queued jobs without invoking a provider during command tests."""

    def __init__(self, db: Database):
        self.db = db

    def enqueue(self, **kwargs: object) -> object:
        """Mirror the platform enqueue contract used by Product Discovery."""
        return self.db.create_platform_job(**kwargs)


class FakeBriefService:
    """Expose the stored brief through the service boundary used by commands."""

    def __init__(self, db: Database):
        self.db = db

    def ensure_brief(self, project_id: str) -> object:
        """Return the project brief or fail as production does."""
        brief = self.db.get_project_brief(project_id)
        if brief is None:
            raise ValueError("Brief missing")
        return brief


class ProductDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        """Create one migrated SQLite project and its exact published brief revision."""
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "discovery.db")
        apply_migrations(self.db)
        self.project = self.db.create_project("Discovery", "Explore a platform")
        self.db.upsert_project_brief(
            project_id=self.project.id,
            product_idea="An enterprise decision-support platform",
            problem="Teams converge too early",
            target_users="Product teams",
            known_competitors=["ExampleCo"],
            constraints="Local first",
            status="published",
        )
        self.brief_head = self.db.ensure_brief_revision_head(self.project.id)
        self.brief_revision_id = str(self.brief_head["current_published_revision_id"])

    def tearDown(self) -> None:
        """Release each disposable database."""
        self.tmp.cleanup()

    def service(self) -> DiscoveryService:
        """Build the deterministic parts of DiscoveryService without an LLM."""
        services = SimpleNamespace(db=self.db, config=AppConfig())
        return DiscoveryService(services)

    def create_revision(self, **kwargs: object) -> object:
        """Persist a valid candidate linked to the current brief."""
        mode = str(kwargs.pop("competitor_research_mode", "no_competitor_research"))
        return self.db.create_discovery_revision(
            project_id=self.project.id,
            source_brief_revision_id=self.brief_revision_id,
            competitor_research_mode=mode,
            payload=empty_discovery(),
            command_id="test-create",
            **kwargs,
        )

    def test_generation_requires_current_published_brief(self) -> None:
        """Discovery creation rejects absent, draft, and superseded brief sources."""
        other = self.db.create_project("Draft", "Not ready")
        self.db.upsert_project_brief(
            project_id=other.id,
            product_idea="Draft",
            known_competitors=[],
            constraints="",
            status="draft",
        )
        draft_head = self.db.ensure_brief_revision_head(other.id)
        with self.assertRaisesRegex(ValueError, "current published"):
            self.db.create_discovery_revision(
                project_id=other.id,
                source_brief_revision_id=str(draft_head["current_draft_revision_id"]),
                competitor_research_mode="no_competitor_research",
                payload=empty_discovery(),
            )

    def test_normalization_assigns_stable_ids_and_all_baseline_lenses(self) -> None:
        """Stable IDs survive regeneration and baseline coverage cannot disappear."""
        payload = empty_discovery(
            actors=[{"title": "Tenant administrator", "description": "Operates a tenant."}],
            domains=[
                {"title": "Administration", "description": "Tenant controls."},
                {"title": "Administration", "description": "Overlapping platform controls."},
            ],
        )
        first = self.service().normalize_discovery(self.project.id, payload)
        second = self.service().normalize_discovery(self.project.id, payload)
        self.assertEqual(
            [item.id for item in first.actors],
            [item.id for item in second.actors],
        )
        self.assertEqual(len(first.lenses), len(BASELINE_LENSES))
        self.assertTrue(all(item.source == "baseline" for item in first.lenses))
        self.assertEqual(len(first.domains), 2, "Overlapping domains must not be normalized into pillars.")
        admin = next(item for item in first.lenses if item.title == "Administration and operations")
        self.assertIn("super-administration", admin.description)

    def test_revision_lifecycle_is_versioned_and_published_content_is_immutable(self) -> None:
        """Approval/publication preserve history and database guards published content."""
        revision = self.create_revision(human_owned_fields={"notes": "human"})
        approved = self.db.transition_discovery_revision(
            revision_id=revision.id,
            target_state="approved",
            command_id="approve",
            actor="user",
            origin="ui",
        )
        self.assertEqual(approved.state, DiscoveryRevisionState.APPROVED)
        published = self.db.transition_discovery_revision(
            revision_id=revision.id,
            target_state="published",
            command_id="publish",
            actor="user",
            origin="ui",
        )
        self.assertEqual(published.state, DiscoveryRevisionState.PUBLISHED)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db._execute(
                f"UPDATE product_discovery_revisions SET payload = {self.db.param} WHERE id = {self.db.param}",
                (self.db._dump_json(empty_discovery(summary={"mutated": True})), revision.id),
            )

    def test_human_fields_and_exclusions_survive_new_candidate_revisions(self) -> None:
        """Human authority remains separate and is carried into replacement candidates."""
        source = self.create_revision(
            model_authored_fields={"raw_response": "{\"discovery\":{}}"},
            human_owned_fields={"item_states": {"lens-1": "excluded"}, "notes": "keep"},
        )
        replacement = self.db.revise_discovery_human_fields(
            revision_id=source.id,
            human_owned_fields={
                **source.human_owned_fields,
                "annotation": "human edit",
            },
            command_id="edit",
            actor="user",
            origin="ui",
        )
        self.assertNotEqual(source.id, replacement.id)
        self.assertEqual(replacement.human_owned_fields["item_states"]["lens-1"], "excluded")
        self.assertEqual(replacement.model_authored_fields["raw_response"], "{\"discovery\":{}}")
        self.assertEqual(
            self.db.get_discovery_revision(source.id).state,
            DiscoveryRevisionState.SUPERSEDED,
        )

    def test_practicality_review_flags_superficial_and_retains_unusual_ideas(self) -> None:
        """Review findings flag rather than delete strange or unsupported analogies."""
        discovery = self.service().normalize_discovery(
            self.project.id,
            empty_discovery(cross_domain_opportunities=[
                {
                    "title": "Air traffic metaphor",
                    "description": "Looks interesting.",
                    "source_domain": "air traffic control",
                    "source_mechanism": "",
                    "structural_similarity": "",
                    "speculation_level": "superficial_metaphor",
                },
                {
                    "title": "Portfolio rebalancing",
                    "description": "Reallocate exploration budget.",
                    "source_domain": "portfolio management",
                    "source_mechanism": "risk-weighted rebalancing",
                    "structural_similarity": "Both allocate scarce capacity under uncertainty.",
                    "speculation_level": "unusual_but_defensible",
                },
            ]),
        )
        findings = self.service().review_discovery(discovery)
        outcomes = {item.item_id: item.outcome for item in findings}
        self.assertEqual(
            outcomes[discovery.cross_domain_opportunities[0].id],
            "rejected_as_superficial",
        )
        self.assertEqual(
            outcomes[discovery.cross_domain_opportunities[1].id],
            "needs_human_review",
        )
        self.assertEqual(len(discovery.cross_domain_opportunities), 2)

    def test_snapshot_exposes_discovery_and_exact_source_revision(self) -> None:
        """Canonical project state contains discovery history and exact brief lineage."""
        revision = self.create_revision()
        snapshot = self.db.discovery_snapshot(self.project.id)
        self.assertEqual(snapshot["current_candidate"]["id"], revision.id)
        self.assertEqual(
            snapshot["current_candidate"]["source_brief_revision_id"],
            self.brief_revision_id,
        )
        json.dumps(snapshot)

    def test_projection_is_reproducible_and_honors_exclusions(self) -> None:
        """Same sources/compiler reuse one hash and excluded content stays out."""
        normalized = self.service().normalize_discovery(
            self.project.id,
            empty_discovery(
                actors=[{"title": "Operator", "description": "Runs the platform.", "downstream_state": "required"}],
                domains=[{"title": "Operations", "description": "Runtime operations."}],
            ),
        )
        excluded_lens = normalized.lenses[0]
        revision = self.db.create_discovery_revision(
            project_id=self.project.id,
            source_brief_revision_id=self.brief_revision_id,
            competitor_research_mode="no_competitor_research",
            payload=normalized.model_dump(mode="json"),
            human_owned_fields={"item_states": {excluded_lens.id: "excluded"}},
        )
        self.db.transition_discovery_revision(
            revision_id=revision.id,
            target_state="approved",
            command_id="approve",
            actor="user",
            origin="ui",
        )
        first = self.service().build_layer1_projection(revision.id)
        second = self.service().build_layer1_projection(revision.id)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertIn(excluded_lens.id, first["excluded_item_ids"])
        projected_lens_ids = {
            item["id"]
            for item in [
                *first["payload"]["required_lenses"],
                *first["payload"]["optional_lenses"],
            ]
        }
        self.assertNotIn(excluded_lens.id, projected_lens_ids)

    def test_new_brief_publication_marks_discovery_stale_with_exact_reason(self) -> None:
        """Brief dependency propagation updates both generic and discovery freshness."""
        revision = self.create_revision()
        self.db.upsert_project_brief(
            project_id=self.project.id,
            product_idea="A changed enterprise platform",
            problem="Teams converge too early",
            target_users="Product teams",
            known_competitors=["ExampleCo"],
            constraints="Local first",
            status="published",
        )
        publication = self.db.publish_brief_revision(
            self.project.id,
            origin="ui",
            actor="user",
            creation_command_id="brief-publish",
        )
        self.db.mark_descendants_stale(
            project_id=self.project.id,
            source_artifact_type="brief",
            source_artifact_id=str(self.brief_head["id"]),
            previous_source_revision_id=self.brief_revision_id,
            replacement_source_revision_id=str(publication["revision"]["id"]),
            command_id="brief-publish",
            actor="user",
            origin="ui",
            reason_code="brief_republished",
        )
        stale = self.db.get_discovery_revision(revision.id)
        self.assertEqual(stale.freshness_state, "stale")
        self.assertIn(self.brief_revision_id, stale.stale_reason)
        self.assertIn(str(publication["revision"]["id"]), stale.stale_reason)

    def test_generate_command_is_idempotent_and_never_starts_research(self) -> None:
        """Explicit discovery command queues exactly one discovery job on retries."""
        services = SimpleNamespace(
            db=self.db,
            config=AppConfig(),
            brief_service=FakeBriefService(self.db),
            job_service=FakeJobService(self.db),
        )
        command_service = CommandService(services)
        services.command_service = command_service
        command = GenerateProductDiscovery(
            project_id=self.project.id,
            actor=CommandActor.human_ui(),
            idempotency_key="same-request",
            competitor_research_mode="no_competitor_research",
        )
        first = command_service.handle(command)
        second = command_service.handle(command)
        self.assertEqual(first.data["job"]["id"], second.data["job"]["id"])
        self.assertTrue(second.idempotent)
        jobs = self.db.list_platform_jobs(self.project.id, limit=20)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].workflow, "product_discovery_generation")

    def test_competitor_modes_have_distinct_budgets_and_none_cannot_run(self) -> None:
        """No mode produces no research artifact while lightweight/deep remain bounded."""
        services = SimpleNamespace(
            db=self.db,
            config=AppConfig(),
            research_service=SimpleNamespace(),
        )
        runner = CompetitorResearchService(services)
        lightweight = runner._scope(
            {"mode": "lightweight_competitor_scan"},
            ["ExampleCo"],
        )
        deep = runner._scope(
            {"mode": "deep_competitor_research"},
            ["ExampleCo"],
        )
        self.assertLess(lightweight.source_budget, deep.source_budget)
        self.assertLess(lightweight.time_budget_seconds, deep.time_budget_seconds)
        with self.assertRaisesRegex(ValueError, "No competitor-research revision"):
            self.db.create_competitor_research_revision(
                project_id=self.project.id,
                source_brief_revision_id=self.brief_revision_id,
                scope={"mode": CompetitorResearchMode.NONE.value},
                payload={},
            )

    def test_competitor_inference_requires_real_evidence_ids(self) -> None:
        """Invented evidence identifiers are discarded before persistence."""
        valid = SimpleNamespace(id="valid")
        self.assertEqual(
            CompetitorResearchService._valid_evidence_ids(
                {"evidence_ids": ["invented", "valid"]},
                [valid],
            ),
            ["valid"],
        )

    def test_partial_research_is_independent_and_compacts_only_approved_findings(self) -> None:
        """Partial research keeps evidence while compact context requires per-finding authority."""
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "profiles": [{
                "id": "competitor-1",
                "name": "ExampleCo",
                "research_status": "complete",
                "confidence": 0.8,
                "evidence_quality": "authoritative",
                "evidence_ids": ["evidence-1"],
                "research_timestamp": now,
                "last_verified_timestamp": now,
            }],
            "evidence": [{
                "id": "evidence-1",
                "competitor_id": "competitor-1",
                "source_title": "Official product page",
                "source_type": "product_page",
                "source_publisher": "ExampleCo",
                "source_location": "https://example.invalid/product",
                "retrieval_date": now,
                "claim_supported": "The product publicly describes an administration suite.",
                "confidence": 0.9,
                "source_quality": "authoritative",
                "first_party": True,
                "claim_type": "competitor_claim",
            }],
            "inferred_pillars": [{
                "id": "pillar-approved",
                "competitor_id": "competitor-1",
                "title": "Administration",
                "evidence_ids": ["evidence-1"],
                "confidence": 0.8,
                "evidence_quality": "authoritative",
                "inference_strength": "strongly_inferred",
                "source_citations": ["https://example.invalid/product"],
                "research_date": now,
            }, {
                "id": "pillar-excluded",
                "competitor_id": "competitor-1",
                "title": "Unapproved territory",
                "evidence_ids": ["evidence-1"],
                "confidence": 0.4,
                "inference_strength": "weakly_inferred",
                "research_date": now,
            }],
            "human_decisions": {
                "finding_states": {
                    "pillar-approved": "required",
                    "pillar-excluded": "excluded",
                },
            },
            "checkpoint_state": {
                "completed_competitor_ids": ["competitor-1"],
                "unresolved_competitor_ids": ["competitor-2"],
            },
            "partial_completion": True,
            "research_date": now,
            "last_verified_at": now,
        }
        research = self.db.create_competitor_research_revision(
            project_id=self.project.id,
            source_brief_revision_id=self.brief_revision_id,
            scope={
                "mode": "deep_competitor_research",
                "competitor_names": ["ExampleCo", "MissingCo"],
                "max_competitors": 2,
                "source_budget": 20,
                "time_budget_seconds": 300,
                "per_competitor_source_limit": 5,
            },
            payload=payload,
        )
        self.assertTrue(research.partial_completion)
        self.assertEqual(research.checkpoint_state["unresolved_competitor_ids"], ["competitor-2"])
        research = self.db.transition_competitor_research_revision(
            revision_id=research.id,
            target_state="approved",
            command_id="approve-research",
            actor="user",
            origin="ui",
        )
        discovery = self.create_revision(
            competitor_research_mode="deep_competitor_research",
            competitor_research_revision_id=research.id,
        )
        discovery = self.db.transition_discovery_revision(
            revision_id=discovery.id,
            target_state="approved",
            command_id="approve-discovery",
            actor="user",
            origin="ui",
        )
        projection = self.service().build_competitive_projection(discovery.id, research.id)
        self.assertEqual(
            [item["id"] for item in projection["payload"]["inferred_competitor_pillars"]],
            ["pillar-approved"],
        )
        self.assertNotIn("extracted_evidence", json.dumps(projection))
        self.assertIn("pillar-excluded", projection["excluded_item_ids"])
        self.assertEqual(
            self.service().build_competitive_projection(discovery.id, research.id)["content_hash"],
            projection["content_hash"],
        )

    def test_research_cannot_silently_attach_or_change_published_discovery(self) -> None:
        """Research needs approval and any attachment creates a separate discovery candidate."""
        research = self.db.create_competitor_research_revision(
            project_id=self.project.id,
            source_brief_revision_id=self.brief_revision_id,
            scope={
                "mode": "lightweight_competitor_scan",
                "max_competitors": 1,
                "source_budget": 3,
                "time_budget_seconds": 30,
                "per_competitor_source_limit": 2,
            },
            payload={"partial_completion": False},
        )
        with self.assertRaisesRegex(ValueError, "Only approved"):
            self.create_revision(
                competitor_research_mode="lightweight_competitor_scan",
                competitor_research_revision_id=research.id,
            )
        published = self.create_revision()
        self.db.transition_discovery_revision(
            revision_id=published.id,
            target_state="approved",
            command_id="approve-discovery",
            actor="user",
            origin="ui",
        )
        self.db.transition_discovery_revision(
            revision_id=published.id,
            target_state="published",
            command_id="publish-discovery",
            actor="user",
            origin="ui",
        )
        approved_research = self.db.transition_competitor_research_revision(
            revision_id=research.id,
            target_state="approved",
            command_id="approve-research",
            actor="user",
            origin="ui",
        )
        attached = self.db.revise_discovery_human_fields(
            revision_id=published.id,
            human_owned_fields=published.human_owned_fields,
            competitor_research_revision_id=approved_research.id,
            command_id="attach",
            actor="user",
            origin="ui",
        )
        self.assertNotEqual(attached.id, published.id)
        self.assertEqual(self.db.get_discovery_revision(published.id).state, DiscoveryRevisionState.PUBLISHED)
        self.assertIsNone(self.db.get_discovery_revision(published.id).competitor_research_revision_id)

    def test_competitor_finding_can_be_marked_stale_independently(self) -> None:
        """Finding freshness is a human-owned research decision, not discovery freshness."""
        research = self.db.create_competitor_research_revision(
            project_id=self.project.id,
            source_brief_revision_id=self.brief_revision_id,
            scope={
                "mode": "lightweight_competitor_scan",
                "max_competitors": 1,
                "source_budget": 3,
                "time_budget_seconds": 30,
                "per_competitor_source_limit": 2,
            },
            payload={},
        )
        services = SimpleNamespace(db=self.db)
        command_service = CommandService(services)
        services.command_service = command_service
        result = command_service.handle(MarkCompetitorFindingStale(
            project_id=self.project.id,
            actor=CommandActor.human_ui(),
            idempotency_key="mark-stale",
            revision_id=research.id,
            finding_id="finding-1",
            expected_state_token=command_service.competitor_research_state_token(research),
        ))
        replacement = self.db.get_competitor_research_revision(result.data["revision"]["id"])
        self.assertEqual(replacement.human_decisions["finding_freshness"]["finding-1"], "stale")
        self.assertEqual(replacement.freshness_state, "current")

    def test_failed_or_cancelled_research_jobs_leave_core_discovery_valid(self) -> None:
        """Terminal research jobs remain independent from non-competitive discovery."""
        discovery = self.create_revision()
        failed = self.db.create_platform_job(
            project_id=self.project.id,
            kind="research",
            workflow="competitor_research",
            scope="product_discovery",
            request_payload={"mode": "deep_competitor_research"},
        )
        self.db.update_platform_job(
            failed.id,
            status="failed",
            error_type="RuntimeError",
            error_message="provider unavailable",
        )
        cancelled = self.db.create_platform_job(
            project_id=self.project.id,
            kind="research",
            workflow="competitor_research",
            scope="product_discovery",
            request_payload={"mode": "lightweight_competitor_scan"},
        )
        self.db.update_platform_job(cancelled.id, status="cancelled")
        current = self.db.discovery_snapshot(self.project.id)["current_candidate"]
        self.assertEqual(current["id"], discovery.id)
        self.assertEqual(current["freshness_state"], "current")

    def test_published_competitor_research_content_is_immutable(self) -> None:
        """Research publication protects retained evidence while preserving history."""
        research = self.db.create_competitor_research_revision(
            project_id=self.project.id,
            source_brief_revision_id=self.brief_revision_id,
            scope={
                "mode": "lightweight_competitor_scan",
                "max_competitors": 1,
                "source_budget": 3,
                "time_budget_seconds": 30,
                "per_competitor_source_limit": 2,
            },
            payload={},
        )
        self.db.transition_competitor_research_revision(
            revision_id=research.id,
            target_state="approved",
            command_id="approve",
            actor="user",
            origin="ui",
        )
        self.db.transition_competitor_research_revision(
            revision_id=research.id,
            target_state="published",
            command_id="publish",
            actor="user",
            origin="ui",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db._execute(
                f"UPDATE competitor_research_revisions SET evidence = {self.db.param} WHERE id = {self.db.param}",
                ("[]", research.id),
            )

    def test_runtime_provenance_resolves_alias_and_competitor_prompt_identity(self) -> None:
        """Runtime records retain exact identifiers, local hashes, usage, and prompt versions."""
        model_path = Path(self.tmp.name) / "model.gguf"
        model_path.write_bytes(b"model")
        generation_service = SimpleNamespace(
            llm_client=SimpleNamespace(base_url="http://127.0.0.1:8080")
        )
        service = DiscoveryService(SimpleNamespace(
            db=self.db,
            config=AppConfig(),
            generation_service=generation_service,
        ))
        provenance = service._runtime_provenance(
            {
                "id": "default-chat",
                "provider_kind": "local",
                "base_url": "http://127.0.0.1:8080",
                "model_name": "friendly-alias",
                "local_path": str(model_path),
                "context_window": 32768,
                "max_output_tokens": 2048,
                "server_process_id": 321,
            },
            {
                "id": "request-1",
                "system_fingerprint": "runtime-build",
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            },
            "exact-model-file.gguf",
            0.25,
            temperature=0.2,
            seed=7,
            prompt_key="competitor_evidence_extraction_v1",
            prompt_version="1.0.0",
        )
        self.assertEqual(provenance.requested_model_profile, "default-chat")
        self.assertEqual(provenance.exact_model_identifier, "exact-model-file.gguf")
        self.assertEqual(len(provenance.model_file_hash), 64)
        self.assertEqual(provenance.prompt_key, "competitor_evidence_extraction_v1")
        self.assertEqual(provenance.prompt_token_count, 20)

    def test_optimistic_concurrency_rejects_conflicting_human_edits(self) -> None:
        """A second editor cannot apply a stale discovery token."""
        revision = self.create_revision()
        services = SimpleNamespace(db=self.db)
        command_service = CommandService(services)
        services.command_service = command_service
        token = command_service.discovery_state_token(revision)
        command_service.handle(UpdateDiscoveryHumanFields(
            project_id=self.project.id,
            actor=CommandActor.human_ui(),
            idempotency_key="editor-one",
            revision_id=revision.id,
            expected_state_token=token,
            updates={"annotation": "first"},
        ))
        with self.assertRaises(CommandConflictError):
            command_service.handle(UpdateDiscoveryHumanFields(
                project_id=self.project.id,
                actor=CommandActor.human_ui(),
                idempotency_key="editor-two",
                revision_id=revision.id,
                expected_state_token=token,
                updates={"annotation": "second"},
            ))

    def test_schema_names_and_job_results_are_json_safe(self) -> None:
        """Named canonical models serialize without ORM or domain object leakage."""
        revision = self.create_revision(
            review_findings=[],
            runtime_provenance=[],
        )
        encoded = json.dumps(revision.model_dump(mode="json"))
        self.assertIn("source_brief_revision_id", encoded)
        self.assertNotIn("Database(", encoded)

    def test_clone_archive_and_purge_keep_discovery_lifecycle_integrity(self) -> None:
        """Project lifecycle operations retain or remove discovery rows with their owner."""
        revision = self.create_revision()
        self.db.transition_discovery_revision(
            revision_id=revision.id,
            target_state="approved",
            command_id="approve",
            actor="user",
            origin="ui",
        )
        self.db.transition_discovery_revision(
            revision_id=revision.id,
            target_state="published",
            command_id="publish",
            actor="user",
            origin="ui",
        )
        clone = self.db.clone_project(self.project.id)
        clone_snapshot = self.db.discovery_snapshot(clone.id)
        self.assertIsNotNone(clone_snapshot["published"])
        self.assertEqual(clone_snapshot["published"]["project_id"], clone.id)
        archive = self.db.export_project_archive(
            self.project.id,
            Path(self.tmp.name) / "exports",
        )
        imported = self.db.import_project_archive(archive)["project"]
        self.assertIsNotNone(self.db.discovery_snapshot(imported.id)["published"])
        self.db.purge_project(
            clone.id,
            confirmation_token=f"PURGE-{clone.id[:8]}",
        )
        self.assertEqual(
            self.db._fetchall(
                f"SELECT id FROM product_discovery_revisions WHERE project_id = {self.db.param}",
                (clone.id,),
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
