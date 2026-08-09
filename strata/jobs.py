from __future__ import annotations

import json
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from strata.config import build_model_profiles
from strata.command_types import CommandActor, GenerateLayer3Candidate
from strata.dependency_db import feature_revision_token, pillar_revision_token
from strata.diagnostics import DiagnosticsOptions, build_diagnostics_bundle
from strata.execution_policy import resolved_runtime_request
from strata.llm import LLMError
from strata.models import PlatformJob
from strata.provider_onboarding import assert_provider_ready
from strata.telemetry import model_call_context


class JobCancelled(Exception):
    """Raised when a running job reaches a cancellation checkpoint."""


class PlatformJobService:
    """Run durable background work through one shared lifecycle vocabulary."""

    PROVIDER_REQUIRED_WORKFLOWS = {
        "research",
        "layer1_generation",
        "layer2_generation",
        "layer3_generation",
        "layer1_overlap_critic",
        "layer2_overlap_critic",
        "telemetry_replay",
        "diagnostics_export",
        "assistant_message",
        "product_discovery_generation",
        "competitor_research",
        "layer1_territory_expansion",
        "layer1_territory_adversarial",
        "layer1_architecture_synthesis",
    }

    def __init__(self, services: Any):
        self.services = services
        self._runner_gate = threading.BoundedSemaphore(2)

    def enqueue(
        self,
        *,
        project_id: str,
        kind: str,
        workflow: str,
        scope: str,
        scope_id: str | None = None,
        request_payload: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> PlatformJob:
        self.services.db.get_project(project_id)
        if workflow in self.PROVIDER_REQUIRED_WORKFLOWS:
            assert_provider_ready(self.services.db, f"{workflow.replace('_', ' ').capitalize()} jobs")
        return self.services.db.create_platform_job(
            project_id=project_id,
            kind=kind,
            workflow=workflow,
            scope=scope,
            scope_id=scope_id,
            request_payload=request_payload or {},
            dedupe_key=dedupe_key,
        )

    def run_job(self, job_id: str) -> None:
        """Execute a queued job and persist terminal state."""
        with self._runner_gate:
            job = self.services.db.claim_platform_job(job_id)
            if job is None:
                return
            try:
                result = self._dispatch(job)
                self.services.db.update_platform_job(
                    job.id,
                    status="completed",
                    progress=100,
                    current_step="Completed",
                    result_payload=result or {},
                    completed_at=_utc_now(),
                    error_type=None,
                    error_message=None,
                )
            except JobCancelled:
                self.services.db.update_platform_job(
                    job.id,
                    status="cancelled",
                    progress=100,
                    current_step="Cancelled",
                    completed_at=_utc_now(),
                    error_type=None,
                    error_message="Cancelled by the user.",
                )
            except Exception as exc:  # noqa: BLE001 - durable jobs must capture all local failures.
                self.services.db.update_platform_job(
                    job.id,
                    status="failed",
                    current_step="Failed",
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                    completed_at=_utc_now(),
                )

    def cancel(self, job_id: str) -> PlatformJob:
        return self.services.db.request_platform_job_cancel(job_id)

    def retry(self, job_id: str) -> PlatformJob:
        return self.services.db.retry_platform_job(job_id)

    def _dispatch(self, job: PlatformJob) -> dict[str, Any]:
        handlers: dict[str, Callable[[PlatformJob], dict[str, Any]]] = {
            "research": self._run_research,
            "layer1_generation": self._run_layer1_generation,
            "layer2_generation": self._run_layer2_generation,
            "layer3_generation": self._run_layer3_generation,
            "layer1_overlap_critic": self._run_overlap_critic,
            "layer2_overlap_critic": self._run_overlap_critic,
            "telemetry_replay": self._run_telemetry_replay,
            "diagnostics_export": self._run_diagnostics_export,
            "assistant_message": self._run_assistant_message,
            "product_discovery_generation": self._run_product_discovery,
            "competitor_research": self._run_competitor_research,
            "layer1_territory_expansion": self._run_layer1_territory_expansion,
            "layer1_territory_adversarial": self._run_layer1_territory_adversarial,
            "layer1_architecture_synthesis": self._run_layer1_architecture_synthesis,
        }
        handler = handlers.get(job.workflow)
        if handler is None:
            raise ValueError(f"Unsupported platform job workflow: {job.workflow}")
        return handler(job)

    def _run_layer1_territory_expansion(self, job: PlatformJob) -> dict[str, Any]:
        """Resume independent lens divergence from its durable run checkpoint."""
        payload = job.request_payload
        run_id = str(payload.get("run_id") or "")
        if not run_id:
            raise ValueError("Layer 1 territory jobs require a run_id.")
        self._checkpoint(job.id, "Running independent discovery lenses", 10)
        profiles = self._resolve_layer1_profiles(
            [str(item) for item in payload.get("model_aliases", [])]
        )
        result = self.services.generation_service.run_layer1_territory_expansion(
            run_id,
            runtime_profile=profiles[0],
            lens_execution_id=(
                str(payload["lens_execution_id"])
                if payload.get("lens_execution_id")
                else None
            ),
            temperature_override=(
                float(payload["temperature_override"])
                if payload.get("temperature_override") is not None
                else None
            ),
            stronger_exclusions=bool(payload.get("stronger_exclusions", False)),
        )
        self._checkpoint(job.id, "Checkpointed territory ledger and coverage", 95)
        return result.model_dump(mode="json")

    def _run_layer1_territory_adversarial(self, job: PlatformJob) -> dict[str, Any]:
        """Run a separate failure-scenario pass after normal divergence."""
        payload = job.request_payload
        run_id = str(payload.get("run_id") or "")
        if not run_id:
            raise ValueError("Layer 1 adversarial jobs require a run_id.")
        self._checkpoint(job.id, "Testing the territory map against failure scenarios", 15)
        profiles = self._resolve_layer1_profiles(
            [str(item) for item in payload.get("model_aliases", [])]
        )
        result = self.services.generation_service.run_layer1_adversarial_pass(
            run_id,
            role=str(payload.get("role") or "skeptical implementation consultant"),
            runtime_profile=profiles[0],
        )
        if not bool(result.metrics.get("adversarial_complete")):
            raise LLMError(
                "Layer 1 adversarial review exhausted structured-output retries.",
                error_type="structured_output_exhausted",
            )
        self._checkpoint(job.id, "Checkpointed adversarial findings", 95)
        return result.model_dump(mode="json")

    def _run_layer1_architecture_synthesis(self, job: PlatformJob) -> dict[str, Any]:
        """Generate immutable mapped architecture options after exploration."""
        payload = job.request_payload
        run_id = str(payload.get("run_id") or "")
        if not run_id:
            raise ValueError("Layer 1 synthesis jobs require a run_id.")
        self._checkpoint(job.id, "Building bounded synthesis context", 15)
        profiles = self._resolve_layer1_profiles(
            [str(item) for item in payload.get("model_aliases", [])]
        )
        run = self.services.db.get_layer1_territory_run(run_id)
        requested_views = set(run.config.get("architecture_views") or [
            "coherent_core",
            "expansive_differentiation",
        ])
        existing = self.services.db.list_layer1_architecture_candidates(run_id)
        existing_views = {item.kind.value for item in existing}
        architectures = (
            self.services.generation_service.review_existing_layer1_architecture_candidates(
                run_id,
                runtime_profile=profiles[0],
            )
            if requested_views <= existing_views
            else self.services.generation_service.generate_layer1_architecture_candidates(
                run_id,
                runtime_profile=profiles[0],
            )
        )
        self._checkpoint(job.id, "Checkpointed architecture candidates", 95)
        return {
            "run_id": run_id,
            "architecture_candidates": [
                item.model_dump(mode="json") for item in architectures
            ],
        }

    def _checkpoint(self, job_id: str, step: str, progress: int) -> PlatformJob:
        job = self.services.db.get_platform_job(job_id)
        if job.cancel_requested:
            raise JobCancelled()
        return self.services.db.update_platform_job(job_id, current_step=step, progress=progress)

    def _run_research(self, job: PlatformJob) -> dict[str, Any]:
        payload = job.request_payload
        research_job_id = str(payload.get("research_job_id") or "")
        if not research_job_id:
            raise ValueError("Research platform jobs require a research_job_id.")
        self._checkpoint(job.id, "Running competitive research", 10)
        self.services.research_service.run_job(research_job_id)
        research_job = self.services.db.get_research_job(research_job_id)
        if research_job.status == "failed":
            raise RuntimeError(research_job.error or "Research job failed.")
        if research_job.status == "cancelled":
            raise JobCancelled()
        return {"research_job": research_job.model_dump(mode="json")}

    def _run_product_discovery(self, job: PlatformJob) -> dict[str, Any]:
        """Run the explicit discovery workflow and persist a candidate revision."""
        self._checkpoint(job.id, "Preparing published brief context", 5)
        payload = job.request_payload
        self._checkpoint(job.id, "Resolving optional research mode", 15)
        self._checkpoint(job.id, "Generating structured Product Discovery", 30)
        revision = self.services.discovery_service.generate_candidate(
            project_id=job.project_id,
            competitor_research_mode=str(
                payload.get("competitor_research_mode") or "no_competitor_research"
            ),
            generation_job_id=job.id,
            competitor_research_revision_id=payload.get("competitor_research_revision_id"),
            settings_snapshot=payload.get("runtime_settings"),
            command_id=job.id,
        )
        self._checkpoint(job.id, "Validating and reviewing practicality", 75)
        self._checkpoint(job.id, "Persisting candidate revision", 95)
        return {
            "discovery_revision_id": revision.id,
            "competitor_research_revision_id": revision.competitor_research_revision_id,
            "projection_ids": [],
            "raw_response_preserved": bool(revision.model_authored_fields.get("raw_response")),
            "schema_valid": True,
            "repair_attempts": 0,
            "final_candidate_counts": {
                "lenses": len(revision.discovery.lenses),
                "actors": len(revision.discovery.actors),
                "domains": len(revision.discovery.domains),
                "enterprise_obligations": len(revision.discovery.enterprise_obligations),
                "cross_domain_opportunities": len(revision.discovery.cross_domain_opportunities),
            },
            "stop_reason": "candidate_persisted_for_human_review",
        }

    def _run_competitor_research(self, job: PlatformJob) -> dict[str, Any]:
        """Run independently checkpointed competitor research with partial completion."""
        if self.services.competitor_research_service is None:
            raise ValueError("Competitor research service is not available.")
        return self.services.competitor_research_service.run(
            job,
            lambda step, progress: self._checkpoint(job.id, step, progress),
        )

    def _run_layer1_generation(self, job: PlatformJob) -> dict[str, Any]:
        payload = job.request_payload
        self._checkpoint(job.id, "Generating Layer 1 pillars", 10)
        summary = self.services.generation_service.generate_pillars_until_exhausted(
            job.project_id,
            model_profiles=self._resolve_layer1_profiles(payload.get("model_aliases") or []),
            thinking_enabled=bool(payload.get("thinking_enabled")),
            max_rounds=int(payload.get("max_rounds") or 6),
            target_per_round=int(payload.get("target_per_round") or 12),
            total_cap=payload.get("total_cap"),
            min_new_items_per_round=int(payload.get("min_new_items_per_round") or 2),
            stale_rounds_to_stop=int(payload.get("stale_rounds_to_stop") or 2),
        )
        brief = self.services.brief_service.ensure_brief(job.project_id)
        for node in summary.created_nodes:
            revision_id = pillar_revision_token(node)
            self.services.db.set_artifact_freshness(
                project_id=job.project_id, artifact_type="layer1_pillar", artifact_id=node.id,
                artifact_revision_id=revision_id, freshness_state="current", lineage_quality="exact",
            )
            if brief.current_published_revision_id:
                self.services.db.add_artifact_dependency(
                    project_id=job.project_id, dependent_artifact_type="layer1_pillar",
                    dependent_artifact_id=node.id, dependent_revision_id=revision_id,
                    source_artifact_type="brief", source_artifact_id=brief.id,
                    source_revision_id=str(brief.current_published_revision_id), lineage_quality="exact",
                )
        self._checkpoint(job.id, "Queueing Layer 1 research", 85)
        research_jobs = []
        if self.services.research_service.competitive_intelligence_enabled(job.project_id):
            for node in summary.created_nodes:
                self._checkpoint(job.id, f"Queueing research for {node.title}", 90)
                research_job = self.services.research_service.enqueue_layer1(job.project_id, node.id, reason="layer1_generation")
                research_jobs.append(research_job.model_dump(mode="json"))
                self.services.job_service.enqueue_research_job(job.project_id, research_job)
        return {"summary": asdict(summary), "research_jobs": research_jobs}

    def _run_layer2_generation(self, job: PlatformJob) -> dict[str, Any]:
        payload = job.request_payload
        self._checkpoint(job.id, "Generating Layer 2 feature graph", 10)
        summary = self.services.generation_service.generate_layer2_feature_graph(
            job.project_id,
            [str(item) for item in payload.get("pillar_ids", [])],
            thinking_enabled=bool(payload.get("thinking_enabled")),
            max_rounds=int(payload.get("max_rounds") or 5),
            target_per_lens=max(1, min(int(payload.get("target_per_round") or 10), 8)),
            total_cap=payload.get("total_cap"),
        )
        brief = self.services.brief_service.ensure_brief(job.project_id)
        for feature_id in summary.get("created_feature_ids", []):
            feature = self.services.db.get_layer2_feature(str(feature_id))
            pillar = self.services.db.get_node(feature.owner_pillar_id)
            revision_id = feature_revision_token(feature)
            self.services.db.set_artifact_freshness(
                project_id=job.project_id, artifact_type="layer2_feature", artifact_id=feature.id,
                artifact_revision_id=revision_id, freshness_state="current", lineage_quality="exact",
            )
            for source_type, source_id, source_revision in (
                ("brief", brief.id, str(brief.current_published_revision_id or "")),
                ("layer1_pillar", pillar.id, pillar_revision_token(pillar)),
            ):
                if source_revision:
                    self.services.db.add_artifact_dependency(
                        project_id=job.project_id, dependent_artifact_type="layer2_feature",
                        dependent_artifact_id=feature.id, dependent_revision_id=revision_id,
                        source_artifact_type=source_type, source_artifact_id=source_id,
                        source_revision_id=source_revision, lineage_quality="exact",
                    )
        research_job = None
        if self.services.research_service.competitive_intelligence_enabled(job.project_id):
            self._checkpoint(job.id, "Queueing Layer 2 competitive research", 85)
            research_job = self.services.research_service.enqueue_layer2(job.project_id, reason="layer2_generation")
            self.services.job_service.enqueue_research_job(job.project_id, research_job)
        return {"summary": summary, "research_job": research_job.model_dump(mode="json") if research_job else None}

    def _run_layer3_generation(self, job: PlatformJob) -> dict[str, Any]:
        payload = job.request_payload
        feature_ids = [str(item) for item in payload.get("feature_ids", [])]
        if not feature_ids:
            raise ValueError("Select at least one approved Layer 2 feature.")
        self._checkpoint(job.id, "Generating Layer 3 feature expansions", 10)
        result = self.services.command_service.handle(GenerateLayer3Candidate(
            project_id=job.project_id, actor=CommandActor.system("platform_job"), idempotency_key=job.id,
            feature_ids=tuple(feature_ids), thinking_enabled=bool(payload.get("thinking_enabled")), generation_reference=job.id,
        ))
        return {"created": result.data["candidates"], "command_id": result.command_id}

    def _run_overlap_critic(self, job: PlatformJob) -> dict[str, Any]:
        if self.services.overlap_service is None:
            raise ValueError("Overlap critic service is not available.")
        return self.services.overlap_service.run(
            job,
            lambda step, progress: self._checkpoint(job.id, step, progress),
        )

    def _run_telemetry_replay(self, job: PlatformJob) -> dict[str, Any]:
        call_id = str(job.request_payload.get("call_id") or job.scope_id or "")
        run = self.services.db.get_model_call(job.project_id, call_id)
        if not run.get("system_prompt") or not run.get("user_prompt"):
            raise ValueError("This run cannot be replayed because prompt bodies were not retained.")
        runtime = self._runtime_for_run(job.project_id, run)
        self._checkpoint(job.id, "Replaying retained model call", 20)
        response = self.services.generation_service.llm_client.generate_json(
            system_prompt=str(run["system_prompt"]),
            user_prompt=str(run["user_prompt"]),
            base_url=runtime.get("base_url"),
            model_name=runtime.get("model_name") or run.get("model_name"),
            max_tokens=int((run.get("metadata") or {}).get("max_tokens") or 2500),
            temperature=(run.get("metadata") or {}).get("temperature"),
            telemetry=model_call_context(
                project_id=job.project_id,
                layer=str(run.get("layer") or "shared"),
                workflow=f"{run.get('workflow') or 'run'}_replay",
                runtime_profile=runtime,
                run_id=call_id,
                prompt_key=run.get("prompt_key"),
                metadata={"replayed_from": call_id, "platform_job_id": job.id},
            ),
        )
        return {"replayed_from": call_id, "model_name": response.model_name, "parsed_result": response.parsed_json}

    def _run_diagnostics_export(self, job: PlatformJob) -> dict[str, Any]:
        self._checkpoint(job.id, "Collecting diagnostics", 20)
        payload = build_diagnostics_bundle(
            self.services,
            job.project_id,
            DiagnosticsOptions.from_payload(job.request_payload),
        )
        target = Path(self.services.config.exports_dir) / f"{job.project_id}-diagnostics.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
        return {"json_path": str(target), "markdown_path": ""}

    def _run_assistant_message(self, job: PlatformJob) -> dict[str, Any]:
        message_id = str(job.request_payload.get("assistant_message_id") or job.scope_id or "")
        self._checkpoint(job.id, "Running assistant response", 10)
        self.services.assistant_service.run_message(message_id)
        message = self.services.db.get_assistant_message(message_id)
        run = self.services.db.get_assistant_run_for_message(message_id)
        if message.status == "failed":
            raise RuntimeError(message.error or "Assistant response failed.")
        return {"assistant_message": message.model_dump(mode="json"), "assistant_run": run}

    def enqueue_research_job(self, project_id: str, research_job: Any) -> PlatformJob:
        job = self.enqueue(
            project_id=project_id,
            kind="research",
            workflow="research",
            scope=research_job.scope,
            scope_id=research_job.scope_id,
            request_payload={"research_job_id": research_job.id, "research_job_type": research_job.job_type},
            dedupe_key=f"research:{research_job.id}",
        )
        threading.Thread(
            target=self.run_job,
            args=(job.id,),
            daemon=True,
            name=f"strata-job-{job.id[:8]}",
        ).start()
        return job

    def _resolve_layer1_profiles(self, aliases: list[str]) -> list[Any]:
        profiles = build_model_profiles(self.services.config)
        if not aliases:
            return []
        by_alias = {profile.alias: profile for profile in profiles}
        missing = [alias for alias in aliases if alias not in by_alias]
        if missing:
            raise ValueError(f"Unknown model aliases: {', '.join(missing)}")
        return [by_alias[alias] for alias in aliases]

    def _runtime_for_run(self, project_id: str, run: dict[str, Any]) -> dict[str, Any]:
        settings = self.services.db.get_project_model_settings(project_id)
        profiles = settings.llm_profiles if settings is not None else []
        profile = next((item.model_dump(mode="json") for item in profiles if item.id == run.get("model_profile_id")), None)
        return resolved_runtime_request(
            profile,
            llm_client=self.services.generation_service.llm_client,
            server_manager=self.services.generation_service.server_manager,
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
