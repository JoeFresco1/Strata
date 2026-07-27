from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from strata.discovery_models import (
    CompetitiveGap,
    CompetitiveTerritory,
    CompetitorDerivedLens,
    CompetitorEvidence,
    CompetitorProfile,
    CompetitorResearchJobResult,
    CompetitorResearchMode,
    CompetitorResearchScope,
    InferredCompetitorPillar,
)
from strata.execution_policy import resolve_llm_profile, resolved_runtime_request
from strata.jobs import JobCancelled
from strata.project_settings import default_project_model_settings
from strata.prompts import get_prompt_template
from strata.research import CompetitorSeed
from strata.telemetry import model_call_context


COMPETITOR_EXTRACTION_PROMPT_KEY = "competitor_evidence_extraction_v1"
COMPETITOR_EXTRACTION_PROMPT_VERSION = "1.0.0"
COMPETITOR_PILLAR_PROMPT_KEY = "competitor_pillar_inference_v1"
COMPETITOR_PILLAR_PROMPT_VERSION = "1.0.0"
COMPETITOR_COMPARISON_PROMPT_KEY = "competitor_strategic_comparison_v1"
COMPETITOR_COMPARISON_PROMPT_VERSION = "1.0.0"
MODE_DEFAULTS = {
    CompetitorResearchMode.LIGHTWEIGHT: {
        "max_competitors": 4,
        "source_budget": 12,
        "time_budget_seconds": 120,
        "per_competitor_source_limit": 3,
        "temperature": 0.2,
    },
    CompetitorResearchMode.DEEP: {
        "max_competitors": 8,
        "source_budget": 40,
        "time_budget_seconds": 600,
        "per_competitor_source_limit": 8,
        "temperature": 0.5,
    },
}


class CompetitorResearchService:
    """Run bounded evidence-first competitor research as an independent workflow."""

    def __init__(self, services: Any):
        """Reuse Strata's existing local crawl and model runtime services."""
        self.services = services
        self.db = services.db
        self.research = services.research_service

    def run(
        self,
        job: Any,
        checkpoint: Callable[[str, int], Any],
    ) -> dict[str, Any]:
        """Research competitors independently and retain partial candidate revisions."""
        self.research._ensure_competitive_intelligence_enabled(job.project_id)
        brief = self.research._published_brief(job.project_id)
        scope = self._scope(job.request_payload, brief.known_competitors)
        names = scope.competitor_names[:scope.max_competitors]
        started = time.monotonic()
        profiles: list[CompetitorProfile] = []
        evidence: list[CompetitorEvidence] = []
        pillars: list[InferredCompetitorPillar] = []
        territories: list[CompetitiveTerritory] = []
        gaps: list[CompetitiveGap] = []
        lenses: list[CompetitorDerivedLens] = []
        runtime_provenance: list[dict[str, Any]] = []
        raw_model_responses: list[dict[str, Any]] = []
        prior_revisions = self.db.list_competitor_research_revisions(job.project_id)
        human_decisions = dict(prior_revisions[-1].human_decisions) if prior_revisions else {}
        completed: list[str] = []
        unresolved: list[str] = []
        latest_revision_id = ""
        source_count = 0
        checkpoint("Resolving competitors and product suites", 5)
        for index, name in enumerate(names):
            if time.monotonic() - started >= scope.time_budget_seconds:
                unresolved.extend(names[index:])
                break
            progress = 10 + int((index / max(1, len(names))) * 70)
            checkpoint(f"Collecting authoritative sources for {name}", progress)
            try:
                result = self._research_competitor(
                    project_id=job.project_id,
                    product_idea=brief.product_idea,
                    competitor_name=name,
                    scope=scope,
                    remaining_source_budget=max(0, scope.source_budget - source_count),
                    platform_job_id=job.id,
                    settings_snapshot=job.request_payload.get("runtime_settings"),
                )
                profiles.append(result["profile"])
                evidence.extend(result["evidence"])
                pillars.extend(result["pillars"])
                territories.extend(result["territories"])
                gaps.extend(result["gaps"])
                lenses.extend(result["lenses"])
                runtime_provenance.extend(result.get("runtime_provenance") or [])
                raw_model_responses.extend({
                    "competitor_id": result["profile"].id,
                    **item,
                } for item in result.get("raw_model_responses") or [])
                source_count += len(result["evidence"])
                completed.append(result["profile"].id)
            except JobCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - one competitor must not invalidate the rest.
                competitor_id = self._stable_id(job.project_id, "competitor", name)
                profiles.append(CompetitorProfile(
                    id=competitor_id,
                    name=name,
                    research_status="failed",
                    unresolved_questions=[str(exc)],
                ))
                unresolved.append(competitor_id)
            latest_revision_id = self._persist_checkpoint(
                job=job,
                brief_revision_id=str(brief.current_published_revision_id),
                scope=scope,
                profiles=profiles,
                evidence=evidence,
                pillars=pillars,
                territories=territories,
                gaps=gaps,
                lenses=lenses,
                runtime_provenance=runtime_provenance,
                raw_model_responses=raw_model_responses,
                human_decisions=human_decisions,
                completed=completed,
                unresolved=unresolved,
                final=False,
                previous_revision_id=latest_revision_id,
            )
            if source_count >= scope.source_budget:
                unresolved.extend(
                    self._stable_id(job.project_id, "competitor", item)
                    for item in names[index + 1 :]
                )
                break
        checkpoint("Comparing competitive territories", 82)
        checkpoint("Reviewing evidence and inference quality", 88)
        latest_revision_id = self._persist_checkpoint(
            job=job,
            brief_revision_id=str(brief.current_published_revision_id),
            scope=scope,
            profiles=profiles,
            evidence=evidence,
            pillars=pillars,
            territories=territories,
            gaps=gaps,
            lenses=lenses,
            runtime_provenance=runtime_provenance,
            raw_model_responses=raw_model_responses,
            human_decisions=human_decisions,
            completed=completed,
            unresolved=unresolved,
            final=True,
            previous_revision_id=latest_revision_id,
        )
        checkpoint("Persisting competitor research revision", 96)
        result = CompetitorResearchJobResult(
            competitor_research_revision_id=latest_revision_id,
            completed_competitor_ids=completed,
            unresolved_competitor_ids=list(dict.fromkeys(unresolved)),
            evidence_count=len(evidence),
            inferred_pillar_count=len(pillars),
            partial_completion=bool(unresolved),
            checkpoint_state={
                "completed_competitors": len(completed),
                "total_competitors": len(names),
                "source_count": source_count,
            },
            stop_reason="partial_completion" if unresolved else "complete",
        )
        return result.model_dump(mode="json")

    def _scope(self, payload: dict[str, Any], brief_competitors: list[str]) -> CompetitorResearchScope:
        """Apply distinct bounded defaults for lightweight and deep user-selected modes."""
        mode = CompetitorResearchMode(str(payload.get("mode") or "no_competitor_research"))
        if mode == CompetitorResearchMode.NONE:
            raise ValueError("Competitor research cannot run in no-research mode.")
        defaults = MODE_DEFAULTS[mode]
        names = [
            str(item).strip()
            for item in (payload.get("competitor_names") or brief_competitors)
            if str(item).strip()
        ]
        return CompetitorResearchScope.model_validate({
            **payload,
            "mode": mode.value,
            "competitor_names": list(dict.fromkeys(names)),
            "max_competitors": int(payload.get("max_competitors") or defaults["max_competitors"]),
            "source_budget": int(payload.get("source_budget") or defaults["source_budget"]),
            "time_budget_seconds": int(payload.get("time_budget_seconds") or defaults["time_budget_seconds"]),
            "per_competitor_source_limit": int(
                payload.get("per_competitor_source_limit") or defaults["per_competitor_source_limit"]
            ),
        })

    def _research_competitor(
        self,
        *,
        project_id: str,
        product_idea: str,
        competitor_name: str,
        scope: CompetitorResearchScope,
        remaining_source_budget: int,
        platform_job_id: str,
        settings_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Collect public pages and infer evidence-qualified territories for one competitor."""
        name, provided_url = self.research._split_competitor_seed(competitor_name)
        seed = CompetitorSeed(name=name, url=provided_url)
        pages = self.research._crawl_competitors(product_idea, [seed])
        page_limit = min(scope.per_competitor_source_limit, remaining_source_budget)
        pages = pages[:page_limit]
        competitor_id = self._stable_id(project_id, "competitor", name)
        now = datetime.now(timezone.utc)
        evidence = [
            CompetitorEvidence(
                id=self._stable_id(competitor_id, "evidence", page.url),
                competitor_id=competitor_id,
                source_title=page.title or page.url,
                source_type=self.research._page_type(page.url),
                source_publisher=page.domain,
                source_location=page.url,
                retrieval_date=now,
                extracted_evidence=page.text[:1200],
                claim_supported="Public product territory and capability evidence.",
                confidence=0.8,
                source_quality="authoritative" if name.casefold() in page.domain.casefold() else "medium",
                first_party=name.casefold().replace(" ", "") in page.domain.casefold().replace("-", ""),
                claim_type="competitor_claim",
            )
            for page in pages
        ]
        if not evidence:
            return {
                "profile": CompetitorProfile(
                    id=competitor_id,
                    name=name,
                    research_status="skipped",
                    unresolved_questions=["No usable authoritative public source was found."],
                ),
                "evidence": [],
                "pillars": [],
                "territories": [],
                "gaps": [],
                "lenses": [],
            }
        inference = self._infer(
            project_id=project_id,
            product_idea=product_idea,
            competitor_id=competitor_id,
            competitor_name=name,
            evidence=evidence,
            mode=scope.mode,
            platform_job_id=platform_job_id,
            settings_snapshot=settings_snapshot,
        )
        profile = CompetitorProfile.model_validate({
            "id": competitor_id,
            "name": name,
            "research_status": "complete",
            "confidence": inference.get("confidence", 0.6),
            "evidence_quality": inference.get("evidence_quality", "medium"),
            "evidence_ids": [item.id for item in evidence],
            "research_timestamp": now,
            "last_verified_timestamp": now,
            **dict(inference.get("profile") or {}),
        })
        unsupported = [
            f"Unsupported inferred finding retained in raw response: {item.get('title') or 'untitled'}"
            for section in ("inferred_pillars", "territories", "gaps", "derived_lenses")
            for item in inference.get(section, [])
            if isinstance(item, dict) and not self._valid_evidence_ids(item, evidence)
        ]
        if unsupported:
            profile = profile.model_copy(update={
                "unresolved_questions": [*profile.unresolved_questions, *unsupported],
            })
        pillars = [
            self._pillar(competitor_id, name, item, evidence, now)
            for item in inference.get("inferred_pillars", [])
            if isinstance(item, dict) and self._valid_evidence_ids(item, evidence)
        ]
        territories = [
            self._territory(project_id, competitor_id, item, evidence)
            for item in inference.get("territories", [])
            if isinstance(item, dict) and self._valid_evidence_ids(item, evidence)
        ]
        gaps = [
            self._gap(project_id, competitor_id, item, evidence)
            for item in inference.get("gaps", [])
            if isinstance(item, dict) and self._valid_evidence_ids(item, evidence)
        ]
        lenses = [
            self._lens(project_id, competitor_id, item, evidence)
            for item in inference.get("derived_lenses", [])
            if isinstance(item, dict) and self._valid_evidence_ids(item, evidence)
        ]
        return {
            "profile": profile,
            "evidence": evidence,
            "pillars": pillars,
            "territories": territories,
            "gaps": gaps,
            "lenses": lenses,
            "runtime_provenance": inference.pop("_runtime_provenance", []),
            "raw_model_responses": inference.pop("_raw_model_responses", []),
        }

    def _infer(
        self,
        *,
        project_id: str,
        product_idea: str,
        competitor_id: str,
        competitor_name: str,
        evidence: list[CompetitorEvidence],
        mode: CompetitorResearchMode,
        platform_job_id: str,
        settings_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Use the configured local-first model to extract rather than invent findings."""
        settings = self.db.get_project_model_settings(project_id)
        settings_payload = settings_snapshot or (
            settings.model_dump(mode="json")
            if settings
            else default_project_model_settings(self.services.config)
        )
        discovery_settings = dict(settings_payload.get("discovery_settings") or {})
        evidence_text = "\n\n".join(
            f"EVIDENCE {item.id}\nSource: {item.source_location}\n{item.extracted_evidence}"
            for item in evidence
        )
        extraction_prompt = (
            f"{get_prompt_template(COMPETITOR_EXTRACTION_PROMPT_KEY)}\n\n"
            f"Analyze {competitor_name} only from the supplied evidence for comparison with: {product_idea}.\n"
            f"Mode: {mode.value}.\n{evidence_text}\n\n"
            "Return JSON with profile and observed_capabilities. Every claim must cite evidence_ids."
        )
        extraction, extraction_provenance, extraction_raw = self._model_pass(
            project_id=project_id,
            competitor_id=competitor_id,
            mode=mode,
            settings=settings_payload,
            assignment="competitor_evidence_extraction",
            fallback_assignment="layer0_research",
            prompt_key=COMPETITOR_EXTRACTION_PROMPT_KEY,
            prompt_version=COMPETITOR_EXTRACTION_PROMPT_VERSION,
            temperature=float(discovery_settings.get("competitor_evidence_temperature", 0.2)),
            prompt=extraction_prompt,
            platform_job_id=platform_job_id,
        )
        pillar_prompt = (
            f"{get_prompt_template(COMPETITOR_PILLAR_PROMPT_KEY)}\n\n"
            f"Competitor: {competitor_name}\nProduct comparison target: {product_idea}\n"
            f"{evidence_text}\nObserved extraction:\n{extraction}\n\n"
            "Return JSON with inferred_pillars. "
            "Every inferred pillar/territory/gap/lens must include evidence_ids drawn exactly from the supplied IDs, "
            "confidence from 0 to 1, and an inference_strength for pillars. "
            "Use explicit only when the source explicitly publishes that architecture; otherwise use strongly_inferred, "
            "weakly_inferred, or speculative. Never fill missing evidence."
        )
        pillar_output, pillar_provenance, pillar_raw = self._model_pass(
            project_id=project_id,
            competitor_id=competitor_id,
            mode=mode,
            settings=settings_payload,
            assignment="competitor_pillar_inference",
            fallback_assignment="competitor_evidence_extraction",
            prompt_key=COMPETITOR_PILLAR_PROMPT_KEY,
            prompt_version=COMPETITOR_PILLAR_PROMPT_VERSION,
            temperature=float(discovery_settings.get("competitor_pillar_temperature", 0.5)),
            prompt=pillar_prompt,
            platform_job_id=platform_job_id,
        )
        comparison_prompt = (
            f"{get_prompt_template(COMPETITOR_COMPARISON_PROMPT_KEY)}\n\n"
            f"Competitor: {competitor_name}\nProduct comparison target: {product_idea}\n"
            f"{evidence_text}\nApproved-for-review inferred output:\n{pillar_output}\n\n"
            "Return JSON with territories, gaps, and derived_lenses. Every item must cite supplied evidence_ids, "
            "include confidence, remain advisory, and avoid changing STRATA domains or pillars."
        )
        comparison, comparison_provenance, comparison_raw = self._model_pass(
            project_id=project_id,
            competitor_id=competitor_id,
            mode=mode,
            settings=settings_payload,
            assignment="competitor_strategic_comparison",
            fallback_assignment="competitor_evidence_extraction",
            prompt_key=COMPETITOR_COMPARISON_PROMPT_KEY,
            prompt_version=COMPETITOR_COMPARISON_PROMPT_VERSION,
            temperature=float(discovery_settings.get("competitor_comparison_temperature", 0.5)),
            prompt=comparison_prompt,
            platform_job_id=platform_job_id,
        )
        return {
            "profile": extraction.get("profile") or {},
            "inferred_pillars": pillar_output.get("inferred_pillars") or [],
            "territories": comparison.get("territories") or [],
            "gaps": comparison.get("gaps") or [],
            "derived_lenses": comparison.get("derived_lenses") or [],
            "_runtime_provenance": [extraction_provenance, pillar_provenance, comparison_provenance],
            "_raw_model_responses": [
                {"prompt_key": COMPETITOR_EXTRACTION_PROMPT_KEY, "response": extraction_raw},
                {"prompt_key": COMPETITOR_PILLAR_PROMPT_KEY, "response": pillar_raw},
                {"prompt_key": COMPETITOR_COMPARISON_PROMPT_KEY, "response": comparison_raw},
            ],
        }

    def _model_pass(
        self,
        *,
        project_id: str,
        competitor_id: str,
        mode: CompetitorResearchMode,
        settings: dict[str, Any],
        assignment: str,
        fallback_assignment: str,
        prompt_key: str,
        prompt_version: str,
        temperature: float,
        prompt: str,
        platform_job_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        """Run one independently configured evidence-bound competitor model pass."""
        profile = resolve_llm_profile(settings, assignment) or resolve_llm_profile(settings, fallback_assignment)
        runtime = resolved_runtime_request(
            profile,
            llm_client=self.services.generation_service.llm_client,
            server_manager=self.services.generation_service.server_manager,
        )
        started = time.perf_counter()
        response = self.services.generation_service.llm_client.generate_json(
            system_prompt="Extract evidence-qualified competitor findings. Return valid JSON only.",
            user_prompt=prompt,
            base_url=runtime.get("base_url"),
            model_name=runtime.get("model_name"),
            temperature=temperature,
            max_tokens=min(int(runtime.get("max_output_tokens") or 3000), 6000),
            telemetry=model_call_context(
                project_id=project_id,
                layer="layer0",
                workflow=assignment,
                runtime_profile=runtime,
                run_id=platform_job_id,
                prompt_key=prompt_key,
                metadata={
                    "prompt_version": prompt_version,
                    "competitor_id": competitor_id,
                    "mode": mode.value,
                    "temperature": temperature,
                },
            ),
        )
        elapsed = time.perf_counter() - started
        provenance = self.services.discovery_service._runtime_provenance(
            runtime,
            response.raw_payload,
            response.model_name,
            elapsed,
            temperature=temperature,
            seed=(settings.get("discovery_settings") or {}).get("seed"),
            prompt_key=prompt_key,
            prompt_version=prompt_version,
        ).model_dump(mode="json")
        return dict(response.parsed_json), provenance, response.content

    def _pillar(
        self,
        competitor_id: str,
        competitor_name: str,
        payload: dict[str, Any],
        evidence: list[CompetitorEvidence],
        now: datetime,
    ) -> InferredCompetitorPillar:
        """Validate evidence and label competitor architecture as inference by default."""
        evidence_ids = self._valid_evidence_ids(payload, evidence)
        strength = str(payload.get("inference_strength") or "weakly_inferred")
        if strength == "explicit" and not evidence_ids:
            strength = "speculative"
        return InferredCompetitorPillar(
            id=self._stable_id(competitor_id, "inferred_pillar", str(payload.get("title") or "untitled")),
            competitor_id=competitor_id,
            title=str(payload.get("title") or "Untitled inferred territory"),
            description=str(payload.get("description") or ""),
            competitor_product_or_suite=str(payload.get("competitor_product_or_suite") or competitor_name),
            evidence_ids=evidence_ids,
            supporting_product_areas=list(payload.get("supporting_product_areas") or []),
            confidence=float(payload.get("confidence") or 0.0) if evidence_ids else 0.0,
            evidence_quality=str(payload.get("evidence_quality") or "medium"),
            inference_strength=strength,
            source_citations=[
                item.source_location for item in evidence if item.id in evidence_ids
            ],
            research_date=now,
            human_review_state="pending",
        )

    def _territory(
        self,
        project_id: str,
        competitor_id: str,
        payload: dict[str, Any],
        evidence: list[CompetitorEvidence],
    ) -> CompetitiveTerritory:
        """Create an advisory territory that cannot force STRATA architecture."""
        evidence_ids = self._valid_evidence_ids(payload, evidence)
        classification = str(payload.get("classification") or "requires_human_review")
        allowed = {
            "table_stakes", "market_standard", "emerging_pattern", "competitor_specific",
            "differentiation_opportunity", "likely_commodity", "avoid_copying", "requires_human_review",
        }
        if classification not in allowed:
            classification = "requires_human_review"
        return CompetitiveTerritory(
            id=self._stable_id(project_id, competitor_id, "territory", str(payload.get("title") or "untitled")),
            title=str(payload.get("title") or "Untitled competitive territory"),
            description=str(payload.get("description") or ""),
            competitor_ids=[competitor_id],
            classification=classification,
            evidence_ids=evidence_ids,
            confidence=float(payload.get("confidence") or 0.0) if evidence_ids else 0.0,
            advisory_only=True,
            human_review_state="pending",
        )

    def _gap(
        self,
        project_id: str,
        competitor_id: str,
        payload: dict[str, Any],
        evidence: list[CompetitorEvidence],
    ) -> CompetitiveGap:
        """Persist a comparison gap only with source evidence and pending human review."""
        evidence_ids = self._valid_evidence_ids(payload, evidence)
        gap_type = str(payload.get("gap_type") or "market_absence")
        if gap_type not in {"behind_market", "market_absence", "differentiated", "convergence", "avoid_copying"}:
            gap_type = "market_absence"
        return CompetitiveGap(
            id=self._stable_id(project_id, competitor_id, "gap", str(payload.get("title") or "untitled")),
            title=str(payload.get("title") or "Untitled competitive gap"),
            description=str(payload.get("description") or ""),
            gap_type=gap_type,
            territory_ids=list(payload.get("territory_ids") or []),
            evidence_ids=evidence_ids,
            confidence=float(payload.get("confidence") or 0.0) if evidence_ids else 0.0,
            human_review_state="pending",
        )

    def _lens(
        self,
        project_id: str,
        competitor_id: str,
        payload: dict[str, Any],
        evidence: list[CompetitorEvidence],
    ) -> CompetitorDerivedLens:
        """Require evidence and confidence for every competitor-derived lens."""
        evidence_ids = self._valid_evidence_ids(payload, evidence)
        title = str(payload.get("title") or "Competitor-derived review")
        return CompetitorDerivedLens.model_validate({
            **payload,
            "id": self._stable_id(project_id, competitor_id, "lens", title),
            "title": title,
            "source": "competitor_research",
            "evidence_ids": evidence_ids,
            "supporting_competitor_ids": [competitor_id],
            "relevance_score": float(payload.get("confidence") or 0.0) if evidence_ids else 0.0,
            "downstream_state": "optional",
        })

    def _persist_checkpoint(
        self,
        *,
        job: Any,
        brief_revision_id: str,
        scope: CompetitorResearchScope,
        profiles: list[CompetitorProfile],
        evidence: list[CompetitorEvidence],
        pillars: list[InferredCompetitorPillar],
        territories: list[CompetitiveTerritory],
        gaps: list[CompetitiveGap],
        lenses: list[CompetitorDerivedLens],
        runtime_provenance: list[dict[str, Any]],
        raw_model_responses: list[dict[str, Any]],
        human_decisions: dict[str, Any],
        completed: list[str],
        unresolved: list[str],
        final: bool,
        previous_revision_id: str,
    ) -> str:
        """Persist completed competitors so cancellation or later failure cannot erase them."""
        payload = {
            "profiles": [item.model_dump(mode="json") for item in profiles],
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "inferred_pillars": [item.model_dump(mode="json") for item in pillars],
            "territories": [item.model_dump(mode="json") for item in territories],
            "gaps": [item.model_dump(mode="json") for item in gaps],
            "derived_lenses": [item.model_dump(mode="json") for item in lenses],
            "runtime_provenance": runtime_provenance,
            "human_decisions": human_decisions,
            "checkpoint_state": {
                "stage": "complete" if final and not unresolved else "partially_complete",
                "completed_competitor_ids": completed,
                "unresolved_competitor_ids": unresolved,
                "raw_model_responses": raw_model_responses,
            },
            "partial_completion": bool(unresolved) or not final,
            "research_date": datetime.now(timezone.utc),
            "last_verified_at": datetime.now(timezone.utc),
        }
        revision = self.db.create_competitor_research_revision(
            project_id=job.project_id,
            source_brief_revision_id=brief_revision_id,
            scope=scope.model_dump(mode="json"),
            payload=payload,
            command_id=job.id,
        )
        if previous_revision_id:
            self.db._execute(
                f"UPDATE competitor_research_revisions SET state = {self.db.param}, "
                f"freshness_state = {self.db.param}, superseded_at = {self.db.param} WHERE id = {self.db.param}",
                ("superseded", "superseded", datetime.now(timezone.utc).isoformat(), previous_revision_id),
            )
        return revision.id

    @staticmethod
    def _valid_evidence_ids(
        payload: dict[str, Any],
        evidence: list[CompetitorEvidence],
    ) -> list[str]:
        """Discard invented citation IDs before any inference is persisted."""
        allowed = {item.id for item in evidence}
        return [str(item) for item in payload.get("evidence_ids", []) if str(item) in allowed]

    @staticmethod
    def _stable_id(*parts: str) -> str:
        """Return deterministic IDs across retries for the same competitor and source."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(str(item).casefold() for item in parts)))
