from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

from specforge.config import ModelProfile
from specforge.db import Database
from specforge.embeddings import EmbeddingService
from specforge.llm import LLMError, LlamaCppClient
from specforge.models import Node, ProjectBrief, ResearchJob
from specforge.project_settings import embedding_profiles_by_id, llm_profiles_by_id
from specforge.server_manager import LlamaServerManager, ServerManagerError


SEARCH_URL = "https://duckduckgo.com/html/?q={query}"
REQUEST_HEADERS = {"User-Agent": "SpecForgeLocalResearch/0.1"}
FOCUSED_PATHS = ("", "/features", "/solutions", "/product", "/pricing", "/customers", "/about")


@dataclass(slots=True)
class CompetitorSeed:
    name: str
    url: str | None = None


@dataclass(slots=True)
class ExtractedPage:
    competitor_name: str
    url: str
    domain: str
    title: str | None
    status_code: int | None
    text: str


class ResearchService:
    """Run fully local/free competitor-intelligence jobs with durable job state."""

    def __init__(
        self,
        db: Database,
        llm_client: LlamaCppClient,
        embedding_service: EmbeddingService,
        server_manager: LlamaServerManager | None = None,
    ):
        self.db = db
        self.llm_client = llm_client
        self.embedding_service = embedding_service
        self.server_manager = server_manager

    def enqueue_layer0(self, project_id: str, *, reason: str = "publish") -> ResearchJob:
        """Create a Layer 0 landscape job; callers run it through the local background runner."""
        return self.db.create_research_job(
            project_id=project_id,
            scope="layer0",
            scope_id=None,
            job_type="layer0_competitors",
            details={"reason": reason},
        )

    def enqueue_layer1(self, project_id: str, pillar_id: str, *, reason: str = "layer1_generation") -> ResearchJob:
        """Create a Layer 1 pillar competitor-coverage job."""
        return self.db.create_research_job(
            project_id=project_id,
            scope="layer1",
            scope_id=pillar_id,
            job_type="layer1_pillar_competitors",
            details={"reason": reason},
        )

    def run_job(self, job_id: str) -> None:
        """Execute one queued research job inside the current API process."""
        job = self.db.update_research_job(job_id, status="running", progress=5, error=None)
        try:
            if job.job_type == "layer0_competitors":
                self._run_layer0(job)
            elif job.job_type == "layer1_pillar_competitors":
                self._run_layer1(job)
            else:
                raise ValueError(f"Unsupported research job type: {job.job_type}")
            self.db.update_research_job(job_id, status="completed", progress=100, error=None)
        except Exception as exc:  # noqa: BLE001 - durable job state should capture any local failure.
            self.db.update_research_job(job_id, status="failed", error=str(exc))

    def _run_layer0(self, job: ResearchJob) -> None:
        """Build a project-level competitor landscape from seeds, search, crawl, and evidence."""
        brief = self._published_brief(job.project_id)
        self.db.clear_research_scope(project_id=job.project_id, scope="layer0", scope_id=None)
        seeds = self._competitor_seeds(brief)
        seeds.extend(self._suggest_competitors(brief, existing={seed.name.casefold() for seed in seeds}))
        self.db.update_research_job(job.id, progress=20, details={**job.details, "competitor_count": len(seeds)})
        pages = self._crawl_competitors(brief.product_idea, seeds[:8])
        chunks = self._store_pages(job.project_id, "layer0", None, pages)
        self.db.update_research_job(job.id, progress=70, details={**job.details, "pages": len(pages), "chunks": chunks})
        self._write_layer0_findings(job.project_id, brief, pages)

    def _run_layer1(self, job: ResearchJob) -> None:
        """Analyze one pillar against local competitor evidence and cited public pages."""
        if job.scope_id is None:
            raise ValueError("Layer 1 research jobs require a pillar id.")
        brief = self._published_brief(job.project_id)
        pillar = self.db.get_node(job.scope_id)
        self.db.clear_research_scope(project_id=job.project_id, scope="layer1", scope_id=pillar.id)
        seeds = self._competitor_seeds(brief)
        pages = self._crawl_competitors(f"{brief.product_idea} {pillar.title}", seeds[:8])
        chunks = self._store_pages(job.project_id, "layer1", pillar.id, pages)
        self.db.update_research_job(job.id, progress=75, details={**job.details, "pages": len(pages), "chunks": chunks})
        self._write_layer1_findings(job.project_id, pillar, pages)

    def _published_brief(self, project_id: str) -> ProjectBrief:
        """Return the active published brief required for research and Layer 1."""
        brief = self.db.get_project_brief(project_id)
        if brief is None or brief.status != "published":
            raise ValueError("Publish the Layer 0 brief before running research.")
        return brief

    def _competitor_seeds(self, brief: ProjectBrief) -> list[CompetitorSeed]:
        """Treat user-provided competitors as the highest-trust discovery input."""
        seeds: list[CompetitorSeed] = []
        for item in brief.known_competitors:
            name, url = self._split_competitor_seed(item)
            if name:
                seeds.append(CompetitorSeed(name=name, url=url))
        return seeds

    def _suggest_competitors(self, brief: ProjectBrief, *, existing: set[str]) -> list[CompetitorSeed]:
        """Use the local model for additional names, then resolve them through free search scraping."""
        prompt = (
            "Return JSON only: {\"competitors\":[\"...\"]}. "
            "Suggest public competitors or adjacent products for this product idea. "
            f"Product idea: {brief.product_idea}. Target users: {brief.target_users}. Constraints: {brief.constraints}."
        )
        try:
            runtime = self._llm_runtime(brief.project_id, "layer0_research")
            response = self.llm_client.generate_json(
                system_prompt="Return valid JSON only.",
                user_prompt=prompt,
                base_url=runtime["base_url"],
                model_name=runtime["model_name"],
                max_tokens=500,
                temperature=0.2,
            )
            names = response.parsed_json.get("competitors", [])
        except LLMError:
            names = []
        seeds: list[CompetitorSeed] = []
        for name in names if isinstance(names, list) else []:
            clean_name = str(name).strip()
            if not clean_name or clean_name.casefold() in existing:
                continue
            resolved_url = self._first_search_result(f"{clean_name} product")
            seeds.append(CompetitorSeed(name=clean_name, url=resolved_url))
            existing.add(clean_name.casefold())
            if len(seeds) >= 5:
                break
        return seeds

    def _crawl_competitors(self, query_context: str, seeds: list[CompetitorSeed]) -> list[ExtractedPage]:
        """Fetch a focused set of public pages instead of attempting a full site crawl."""
        pages: list[ExtractedPage] = []
        for seed in seeds:
            start_url = seed.url or self._first_search_result(f"{seed.name} {query_context}")
            if not start_url:
                continue
            for url in self._focused_urls(start_url):
                page = self._fetch_extract(seed.name, url)
                if page and page.text:
                    pages.append(page)
                if len([item for item in pages if item.competitor_name == seed.name]) >= 4:
                    break
        return pages

    def _store_pages(self, project_id: str, scope: str, scope_id: str | None, pages: list[ExtractedPage]) -> int:
        """Persist sources and chunks, embedding each chunk when pgvector is active."""
        embedding_model_name = self._embedding_model_name(project_id, "research_embeddings")
        chunk_count = 0
        for page in pages:
            source = self.db.insert_research_source(
                project_id=project_id,
                scope=scope,
                scope_id=scope_id,
                competitor_name=page.competitor_name,
                domain=page.domain,
                url=page.url,
                page_type=self._page_type(page.url),
                title=page.title,
                status_code=page.status_code,
                content_hash=hashlib.sha256(page.text.encode("utf-8")).hexdigest(),
                metadata={},
            )
            for index, chunk in enumerate(self._chunks(page.text)):
                embedding = self._embedding(chunk, embedding_model_name)
                self.db.insert_research_chunk(
                    project_id=project_id,
                    scope=scope,
                    scope_id=scope_id,
                    source_id=source.id,
                    competitor_name=page.competitor_name,
                    domain=page.domain,
                    url=page.url,
                    title=page.title,
                    chunk_index=index,
                    text=chunk,
                    embedding_model=embedding_model_name,
                    embedding=embedding,
                    metadata={},
                )
                chunk_count += 1
        return chunk_count

    def _write_layer0_findings(self, project_id: str, brief: ProjectBrief, pages: list[ExtractedPage]) -> None:
        """Persist cited market landscape findings for Layer 0 review."""
        competitors = sorted({page.competitor_name for page in pages})
        themes = self._capability_themes(pages)
        evidence = self._evidence_payload(pages, limit=10)
        self.db.insert_research_finding(
            project_id=project_id,
            scope="layer0",
            scope_id=None,
            finding_type="market_landscape",
            title="Competitor Landscape",
            summary=f"Found public evidence for {len(competitors)} competitors: {', '.join(competitors[:8]) or 'none yet'}.",
            payload={
                "competitors": competitors,
                "major_capability_themes": themes,
                "market_saturation_notes": self._saturation_note(competitors, themes),
                "whitespace_opportunity_notes": self._whitespace_note(brief, themes),
                "evidence": evidence,
            },
        )

    def _write_layer1_findings(self, project_id: str, pillar: Node, pages: list[ExtractedPage]) -> None:
        """Persist a cited competitor coverage matrix for a generated pillar."""
        matrix = []
        for competitor in sorted({page.competitor_name for page in pages}):
            competitor_pages = [page for page in pages if page.competitor_name == competitor]
            score = self._pillar_signal_score(pillar, competitor_pages)
            status, adoption, confidence = self._coverage_values(score)
            matrix.append(
                {
                    "competitor_name": competitor,
                    "domain": competitor_pages[0].domain if competitor_pages else None,
                    "coverage_status": status,
                    "adoption_level": adoption,
                    "summary": self._coverage_summary(pillar, score),
                    "evidence": self._evidence_payload(competitor_pages, limit=3),
                    "whitespace_note": self._pillar_whitespace_note(pillar, status),
                    "confidence": confidence,
                }
            )
        self.db.insert_research_finding(
            project_id=project_id,
            scope="layer1",
            scope_id=pillar.id,
            finding_type="pillar_coverage_matrix",
            title=f"Competitor Coverage: {pillar.title}",
            summary=f"Coverage matrix for {pillar.title} across {len(matrix)} competitors.",
            payload={"pillar_id": pillar.id, "pillar_title": pillar.title, "matrix": matrix},
        )
        payload = dict(pillar.json_payload or {})
        payload.pop("research_stale", None)
        self.db.update_node(pillar.id, json_payload=payload)

    def _first_search_result(self, query: str) -> str | None:
        """Scrape the first plausible organic result from DuckDuckGo's HTML endpoint."""
        try:
            response = requests.get(
                SEARCH_URL.format(query=quote_plus(query)),
                headers=REQUEST_HEADERS,
                timeout=12,
            )
            response.raise_for_status()
        except requests.RequestException:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        for link in soup.select("a.result__a"):
            href = link.get("href")
            if href and href.startswith(("http://", "https://")):
                return href
            if href and "uddg=" in href:
                parsed = urlparse(href)
                target = parse_qs(parsed.query).get("uddg", [None])[0]
                if target and target.startswith(("http://", "https://")):
                    return target
        return None

    def _fetch_extract(self, competitor_name: str, url: str) -> ExtractedPage | None:
        """Fetch one page and extract readable text with trafilatura plus HTML fallback."""
        try:
            response = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
        except requests.RequestException:
            return None
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return None
        title = None
        extracted = trafilatura.extract(response.text, include_comments=False, include_tables=False)
        if not extracted:
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else None
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            extracted = " ".join(soup.get_text(" ").split())
        else:
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else None
        text = " ".join((extracted or "").split())
        if len(text) < 160:
            return None
        parsed = urlparse(response.url)
        return ExtractedPage(
            competitor_name=competitor_name,
            url=response.url,
            domain=parsed.netloc.lower(),
            title=title,
            status_code=response.status_code,
            text=text[:16000],
        )

    @staticmethod
    def _split_competitor_seed(value: str) -> tuple[str, str | None]:
        """Accept competitor names or URLs in the same seed field."""
        clean = value.strip()
        if not clean:
            return "", None
        if clean.startswith(("http://", "https://")):
            domain = urlparse(clean).netloc.replace("www.", "")
            return domain.split(".")[0].title(), clean
        if "." in clean and " " not in clean:
            return clean.split(".")[0].title(), f"https://{clean}"
        return clean, None

    @staticmethod
    def _focused_urls(start_url: str) -> list[str]:
        """Generate a bounded set of same-origin pages likely to describe product capabilities."""
        parsed = urlparse(start_url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        urls = [start_url]
        for path in FOCUSED_PATHS:
            candidate = urljoin(base, path)
            if candidate not in urls:
                urls.append(candidate)
        return urls

    @staticmethod
    def _chunks(text: str, max_chars: int = 1200) -> list[str]:
        """Split extracted page text into embed-sized chunks on sentence-ish boundaries."""
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) > max_chars and current:
                chunks.append(current.strip())
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current.strip())
        return chunks[:8]

    def _embedding(self, text: str, model_name: str) -> list[float]:
        """Return a local embedding vector, using zero vectors only for SQLite/test fallback."""
        if self.db.is_postgres:
            return self.embedding_service.embed_text(text, model_name=model_name).vector
        return []

    def _llm_runtime(self, project_id: str, assignment: str) -> dict[str, str | None]:
        """Resolve a project-scoped LLM profile for research-time synthesis or discovery."""
        settings = self.db.get_project_model_settings(project_id)
        if settings is None:
            return {"base_url": None, "model_name": None}
        payload = settings.model_dump(mode="json")
        assignment_id = str(payload.get("assignments", {}).get(assignment, "")).strip()
        profile = llm_profiles_by_id(payload).get(assignment_id)
        if profile is None:
            return {"base_url": None, "model_name": None}
        local_path = str(profile.get("local_path", "")).strip()
        model_name = str(profile.get("model_name", "")).strip() or None
        if local_path and self.server_manager is not None:
            alias = assignment_id
            try:
                self.server_manager.ensure_model_loaded(
                    ModelProfile(alias=alias, display_name=str(profile.get("label", alias)), path=Path(local_path)),
                    thinking_enabled=False,
                )
                model_name = alias
            except (ServerManagerError, OSError) as exc:
                raise LLMError(str(exc)) from exc
        base_url = str(profile.get("base_url", "")).strip() or None
        return {"base_url": base_url, "model_name": model_name}

    def _embedding_model_name(self, project_id: str, assignment: str) -> str:
        """Resolve the embedding model configured for the given research assignment."""
        settings = self.db.get_project_model_settings(project_id)
        if settings is None:
            return self.embedding_service.model_name
        payload = settings.model_dump(mode="json")
        assignment_id = str(payload.get("assignments", {}).get(assignment, "")).strip()
        profile = embedding_profiles_by_id(payload).get(assignment_id)
        if profile is None:
            return self.embedding_service.model_name
        return str(profile.get("model_name", "")).strip() or self.embedding_service.model_name

    @staticmethod
    def _page_type(url: str) -> str:
        path = urlparse(url).path.lower()
        for label in ("features", "solutions", "product", "pricing", "customers", "about"):
            if label in path:
                return label
        return "home"

    @staticmethod
    def _capability_themes(pages: list[ExtractedPage]) -> list[str]:
        terms = ["analytics", "automation", "workflow", "integration", "reporting", "dashboard", "collaboration", "security"]
        found = []
        all_text = " ".join(page.text.lower() for page in pages)
        for term in terms:
            if term in all_text:
                found.append(term.title())
        return found[:8]

    @staticmethod
    def _evidence_payload(pages: list[ExtractedPage], *, limit: int) -> list[dict[str, Any]]:
        evidence = []
        for page in pages[:limit]:
            evidence.append(
                {
                    "url": page.url,
                    "title": page.title,
                    "competitor_name": page.competitor_name,
                    "snippet": page.text[:320],
                }
            )
        return evidence

    @staticmethod
    def _saturation_note(competitors: list[str], themes: list[str]) -> str:
        if len(competitors) >= 5 and len(themes) >= 4:
            return "The space shows multiple competitors with overlapping public capability language."
        if competitors:
            return "The initial crawl found competitors, but evidence is still thin enough to treat saturation as unclear."
        return "No reliable public competitor evidence was collected yet."

    @staticmethod
    def _whitespace_note(brief: ProjectBrief, themes: list[str]) -> str:
        rejected = ", ".join(brief.rejected_directions[:3])
        preferred = ", ".join(brief.preferred_directions[:3])
        return f"Compare preferred directions ({preferred or 'none listed'}) against common themes ({', '.join(themes) or 'unclear'}). Avoid rejected directions ({rejected or 'none listed'})."

    @staticmethod
    def _pillar_signal_score(pillar: Node, pages: list[ExtractedPage]) -> int:
        words = [word.lower() for word in re.findall(r"[A-Za-z]{4,}", f"{pillar.title} {pillar.description or ''}")]
        if not words:
            return 0
        text = " ".join(page.text.lower() for page in pages)
        matches = len({word for word in words if word in text})
        return min(100, int((matches / max(1, len(set(words)))) * 100))

    @staticmethod
    def _coverage_values(score: int) -> tuple[str, str, int]:
        if score >= 60:
            return "supported", "common", min(90, score)
        if score >= 35:
            return "partially_supported", "emerging", max(55, score)
        if score >= 15:
            return "unclear", "unclear", 45
        return "not_evident", "rare", 35

    @staticmethod
    def _coverage_summary(pillar: Node, score: int) -> str:
        if score >= 60:
            return f"Public pages show clear language overlapping {pillar.title}."
        if score >= 35:
            return f"Public pages partially overlap {pillar.title}, but the capability may not be central."
        if score >= 15:
            return f"Evidence for {pillar.title} is ambiguous."
        return f"No direct public evidence for {pillar.title} was found in the focused crawl."

    @staticmethod
    def _pillar_whitespace_note(pillar: Node, status: str) -> str:
        if status in {"not_evident", "unclear"}:
            return f"{pillar.title} may represent whitespace or may need better competitor evidence."
        return f"{pillar.title} appears present in competitor language, so differentiation needs a sharper angle."
