from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from strata.llm import LLMError
from strata.models import Layer2Feature, ResearchJob
from strata.provider_onboarding import assert_provider_ready
from strata.prompts import render_prompt
from strata.telemetry import model_call_context


ACTIVE_LAYER2_RESEARCH_STATUSES = ["candidate", "kept", "renamed", "needs_review", "approved"]
LAYER2_RESEARCH_BATCH_SIZE = 12
LAYER2_COMPETITOR_BATCH_SIZE = 4
LAYER2_COVERAGE_STATUSES = {"has_feature", "partial", "not_found", "unclear"}


@dataclass(slots=True)
class Layer2CompetitorSeed:
    """Minimal competitor seed shape consumed by the shared focused crawler."""

    name: str
    url: str | None = None


class Layer2ResearchMixin:
    """Feature-level competitor research built on the shared local research service."""

    def enqueue_layer2(
        self,
        project_id: str,
        *,
        feature_ids: list[str] | None = None,
        reason: str = "manual_rerun",
    ) -> ResearchJob:
        """Create a durable Layer 2 job for selected features or the complete active review set."""
        self._ensure_competitive_intelligence_enabled(project_id)
        assert_provider_ready(self.db, "Competitive research")
        self.db.get_project(project_id)
        features = self._layer2_research_features(project_id, feature_ids)
        return self.db.create_research_job(
            project_id=project_id,
            scope="layer2",
            scope_id=None,
            job_type="layer2_feature_competitors",
            details={
                "reason": reason,
                "feature_ids": [feature.id for feature in features],
                "feature_count": len(features),
                "warnings": [],
            },
        )

    def _run_layer2(self, job: ResearchJob) -> None:
        """Crawl competitors once, then classify reusable evidence against feature batches."""
        feature_ids = [str(item) for item in job.details.get("feature_ids", [])]
        features = self._layer2_research_features(job.project_id, feature_ids or None)
        details = {**job.details, "feature_count": len(features), "warnings": []}
        if not features:
            warning = "No active Layer 2 features were eligible for research."
            self.db.update_research_job(job.id, progress=100, details={**details, "warnings": [warning]})
            return

        settings = self.db.get_layer2_competitive_settings(job.project_id)
        seeds = [self._layer2_competitor_seed(item) for item in settings.known_competitors]
        seeds = [seed for seed in seeds if seed.name]
        if settings.research_mode == "expand_from_known":
            seeds = self._expand_layer2_competitors(job.project_id, seeds)
        if not seeds:
            warning = "Add known competitors or select expand-from-known before running Layer 2 research."
            self.db.update_research_job(job.id, progress=100, details={**details, "warnings": [warning]})
            return

        project = self.db.get_project(job.project_id)
        pages = self._crawl_competitors(project.idea, seeds[:12])
        chunks = self._store_pages(job.project_id, "layer2", job.id, pages)
        details.update({"competitor_count": len(seeds), "pages": len(pages), "chunks": chunks})
        researched_names = {page.competitor_name.casefold() for page in pages}
        missing_names = [seed.name for seed in seeds if seed.name.casefold() not in researched_names]
        crawl_warnings = [f"No usable public product pages were found for {name}." for name in missing_names]
        if not pages:
            self.db.update_research_job(job.id, progress=100, details={**details, "warnings": crawl_warnings})
            return
        self.db.update_research_job(job.id, progress=35, details=details)

        warnings = [*crawl_warnings, *self._assess_layer2_batches(job, features, pages)]
        evidence_count = sum(
            1
            for item in self.db.list_layer2_feature_evidence(job.project_id)
            if item.research_job_id == job.id
        )
        self.db.update_research_job(
            job.id,
            progress=95,
            details={**details, "warnings": warnings, "evidence_count": evidence_count},
        )

    def _layer2_research_features(self, project_id: str, feature_ids: list[str] | None) -> list[Layer2Feature]:
        """Return active project features, enforcing project ownership for explicit selections."""
        active = self.db.list_layer2_features(project_id, statuses=ACTIVE_LAYER2_RESEARCH_STATUSES)
        if feature_ids is None:
            return active
        requested = list(dict.fromkeys(feature_ids))
        active_by_id = {feature.id: feature for feature in active}
        missing = [feature_id for feature_id in requested if feature_id not in active_by_id]
        if missing:
            raise ValueError(f"Layer 2 research requires active project features: {', '.join(missing)}")
        return [active_by_id[feature_id] for feature_id in requested]

    def _layer2_competitor_seed(self, value: str) -> Layer2CompetitorSeed:
        """Convert saved competitor text into the service's reusable seed type."""
        name, url = self._split_competitor_seed(value)
        return Layer2CompetitorSeed(name=name, url=url)

    def _expand_layer2_competitors(self, project_id: str, seeds: list[Any]) -> list[Any]:
        """Discover adjacent competitors and persist the expanded set for future runs."""
        brief = self._published_brief(project_id)
        existing = {seed.name.casefold() for seed in seeds}
        expanded = [*seeds, *self._suggest_competitors(brief, existing=existing, assignment="layer2_research")]
        settings = self.db.get_layer2_competitive_settings(project_id)
        self.db.upsert_layer2_competitive_settings(
            project_id=project_id,
            known_competitors=[seed.url or seed.name for seed in expanded],
            research_mode=settings.research_mode,
        )
        return expanded

    def _assess_layer2_batches(
        self,
        job: ResearchJob,
        features: list[Layer2Feature],
        pages: list[Any],
    ) -> list[str]:
        """Evaluate pillar-grouped batches and retain successful results when another batch fails."""
        warnings: list[str] = []
        grouped: dict[str, list[Layer2Feature]] = defaultdict(list)
        for feature in features:
            grouped[feature.owner_pillar_id].append(feature)
        feature_batches = [
            batch
            for items in grouped.values()
            for batch in self._batches(items, LAYER2_RESEARCH_BATCH_SIZE)
        ]
        page_batches = self._competitor_page_batches(pages)
        batches = [(features_batch, pages_batch) for features_batch in feature_batches for pages_batch in page_batches]
        total = max(1, len(batches))
        for index, (feature_batch, page_batch) in enumerate(batches, start=1):
            try:
                assessments = self._classify_layer2_batch(job.project_id, feature_batch, page_batch)
                persisted = self._persist_layer2_assessments(job, feature_batch, page_batch, assessments)
                competitor_count = len({page.competitor_name.casefold() for page in page_batch})
                expected = len(feature_batch) * competitor_count
                if persisted < expected:
                    warnings.append(f"Batch {index} returned {persisted} of {expected} expected assessments.")
            except (LLMError, ValueError) as exc:
                warnings.append(f"Batch {index} failed: {exc}")
            progress = 35 + round((index / total) * 55)
            self.db.update_research_job(job.id, progress=progress, details={**job.details, "warnings": warnings})
        return warnings

    def _classify_layer2_batch(
        self,
        project_id: str,
        features: list[Layer2Feature],
        pages: list[Any],
    ) -> list[dict[str, Any]]:
        """Ask the configured local model for one grounded feature-by-competitor assessment batch."""
        prompt = render_prompt(
            "layer2_feature_competitor_assessment",
            {
                "features": json.dumps([
                    {"id": feature.id, "name": feature.canonical_name, "description": feature.description}
                    for feature in features
                ], ensure_ascii=True),
                "evidence": json.dumps(self._evidence_payload(pages, limit=len(pages)), ensure_ascii=True),
            },
            prompt_catalog=self._prompt_catalog(project_id),
        )
        runtime = self._llm_runtime(project_id, "layer2_research")
        response = self.llm_client.generate_json(
            system_prompt=self._system_prompt(project_id),
            user_prompt=prompt,
            base_url=runtime["base_url"],
            model_name=runtime["model_name"],
            max_tokens=3500,
            temperature=0.1,
            telemetry=model_call_context(
                project_id=project_id,
                layer="layer2",
                workflow="feature_competitor_assessment",
                runtime_profile=runtime,
                prompt_key="layer2_feature_competitor_assessment",
                metadata={"feature_count": len(features), "evidence_page_count": len(pages)},
            ),
        )
        assessments = response.parsed_json.get("assessments", [])
        if not isinstance(assessments, list):
            raise LLMError("Layer 2 research response did not contain an assessments array.")
        return [item for item in assessments if isinstance(item, dict)]

    def _persist_layer2_assessments(
        self,
        job: ResearchJob,
        features: list[Layer2Feature],
        pages: list[Any],
        assessments: list[dict[str, Any]],
    ) -> int:
        """Validate model directives and append grounded evidence rows with job provenance."""
        feature_ids = {feature.id for feature in features}
        pages_by_competitor: dict[str, list[Any]] = defaultdict(list)
        for page in pages:
            pages_by_competitor[page.competitor_name.casefold()].append(page)
        persisted = 0
        seen: set[tuple[str, str]] = set()
        for item in assessments:
            feature_id = str(item.get("feature_id", "")).strip()
            competitor = str(item.get("competitor_name", "")).strip()
            status = str(item.get("coverage_status", "unclear")).strip()
            evidence_key = (feature_id, competitor.casefold())
            if (
                feature_id not in feature_ids
                or not competitor
                or status not in LAYER2_COVERAGE_STATUSES
                or evidence_key in seen
            ):
                continue
            seen.add(evidence_key)
            source_pages = pages_by_competitor.get(competitor.casefold(), [])
            source_url, snippet = self._ground_layer2_evidence(item, source_pages)
            self.db.create_layer2_feature_evidence(
                project_id=job.project_id,
                feature_id=feature_id,
                competitor_name=competitor,
                coverage_status=status,
                confidence=max(0, min(100, int(item.get("confidence", 50)))),
                source_url=source_url,
                evidence_snippet=snippet,
                rationale=str(item.get("rationale", "")).strip(),
                source_type="discovered",
                research_job_id=job.id,
            )
            persisted += 1
        return persisted

    @staticmethod
    def _ground_layer2_evidence(item: dict[str, Any], pages: list[Any]) -> tuple[str, str]:
        """Restrict citations and snippets to pages actually fetched for the named competitor."""
        if not pages:
            return "", ""
        requested_url = str(item.get("source_url", "")).strip()
        page = next((candidate for candidate in pages if candidate.url == requested_url), pages[0])
        requested_snippet = " ".join(str(item.get("evidence_snippet", "")).split())
        snippet = requested_snippet if requested_snippet and requested_snippet.casefold() in page.text.casefold() else page.text[:320]
        return page.url, snippet

    @staticmethod
    def _batches(items: list[Layer2Feature], size: int) -> list[list[Layer2Feature]]:
        """Split feature collections into bounded local-model requests."""
        return [items[index:index + size] for index in range(0, len(items), size)]

    @staticmethod
    def _competitor_page_batches(pages: list[Any]) -> list[list[Any]]:
        """Keep each critic request bounded while reusing pages crawled once for the full run."""
        grouped: dict[str, list[Any]] = defaultdict(list)
        for page in pages:
            grouped[page.competitor_name.casefold()].append(page)
        competitor_groups = list(grouped.values())
        return [
            [page for group in competitor_groups[index:index + LAYER2_COMPETITOR_BATCH_SIZE] for page in group]
            for index in range(0, len(competitor_groups), LAYER2_COMPETITOR_BATCH_SIZE)
        ]
