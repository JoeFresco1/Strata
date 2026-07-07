from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from rapidfuzz import fuzz

from strata.execution_policy import effective_parallelism, preferred_provider, resolve_llm_profile, resolved_runtime_request
from strata.llm import LLMError
from strata.models import PlatformJob, SimilarityMatch
from strata.prompts import build_overlap_critic_prompt


OVERLAP_RELATIONS = {
    "same_capability",
    "broader",
    "narrower",
    "merge",
    "link",
    "distinct",
    "fake_novelty",
    "needs_review",
}
HIGH_IMPACT_RELATIONS = {"same_capability", "merge"}


class OverlapVerdictItem(BaseModel):
    neighbor_id: str
    relation: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    rationale: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class OverlapCriticResponse(BaseModel):
    verdicts: list[OverlapVerdictItem] = Field(default_factory=list)


@dataclass(slots=True)
class OverlapItem:
    id: str
    title: str
    description: str
    status: str
    owner_id: str = ""
    metadata: dict[str, Any] | None = None

    @property
    def text(self) -> str:
        return "\n".join([self.title, self.description, self.owner_id, self.status]).strip()

    def prompt_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "owner_id": self.owner_id,
            "metadata": self.metadata or {},
        }


@dataclass(slots=True)
class Neighbor:
    item: OverlapItem
    score: float


def top_k_for_context(context_window: int, *, prompt_overhead: int = 1800, neighbor_token_budget: int = 260) -> int:
    """Derive neighbor count from the assigned profile context window."""
    usable = max(0, int(context_window or 32768) - prompt_overhead)
    return max(2, min(24, usable // neighbor_token_budget))


def split_oversized_clusters(
    member_ids: list[str],
    edge_scores: dict[tuple[str, str], float],
    *,
    max_size: int = 8,
) -> list[list[str]]:
    """Split connected groups by strongest edges so no cluster call is unbounded."""
    if len(member_ids) <= max_size:
        return [sorted(member_ids)]
    sorted_edges = sorted(
        ((score, left, right) for (left, right), score in edge_scores.items() if left in member_ids and right in member_ids),
        reverse=True,
    )
    groups: list[list[str]] = []
    assigned: set[str] = set()
    for _, left, right in sorted_edges:
        if left in assigned and right in assigned:
            continue
        group = []
        for candidate in (left, right):
            if candidate not in assigned and len(group) < max_size:
                group.append(candidate)
                assigned.add(candidate)
        for _, edge_left, edge_right in sorted_edges:
            if len(group) >= max_size:
                break
            if edge_left in group and edge_right not in assigned:
                group.append(edge_right)
                assigned.add(edge_right)
            elif edge_right in group and edge_left not in assigned:
                group.append(edge_left)
                assigned.add(edge_left)
        if group:
            groups.append(sorted(group))
    leftovers = [item for item in sorted(member_ids) if item not in assigned]
    for index in range(0, len(leftovers), max_size):
        groups.append(leftovers[index:index + max_size])
    return [group for group in groups if len(group) > 1]


class OverlapCriticRunner:
    """Run full-project Layer 1/Layer 2 overlap checks as durable jobs."""

    def __init__(self, services: Any):
        self.services = services

    def run(self, job: PlatformJob, checkpoint) -> dict[str, Any]:
        layer = "layer1" if job.workflow == "layer1_overlap_critic" else "layer2"
        items = self._active_items(job.project_id, layer)
        if len(items) < 2:
            return {"layer": layer, "processed_items": 0, "verdicts": 0, "clusters": 0}
        settings = self.services.db.get_project_model_settings(job.project_id)
        settings_payload = settings.model_dump(mode="json") if settings is not None else {}
        assignment = f"{layer}_overlap_critic"
        profile = resolve_llm_profile(settings_payload, assignment)
        runtime = resolved_runtime_request(
            profile,
            llm_client=self.services.generation_service.llm_client,
            server_manager=self.services.generation_service.server_manager,
        )
        provider = preferred_provider(settings_payload, assignment)
        concurrency = 1 if provider == "local" else effective_parallelism(settings_payload, profile)
        top_k = top_k_for_context(int((profile or {}).get("context_window", 32768)))
        threshold = 0.7 if provider == "local" else 0.76
        checkpoint("Preparing embeddings and shortlist", 8)
        shortlist = self.build_shortlist(job.project_id, layer, items, top_k=top_k, sim_threshold=threshold)
        existing_items = {item.item_id: item for item in self.services.db.list_overlap_job_items(job.id)}
        for item in items:
            if item.id not in existing_items:
                self.services.db.upsert_overlap_job_item(
                    project_id=job.project_id,
                    job_id=job.id,
                    layer=layer,
                    item_id=item.id,
                    item_hash=self.services.db._stable_overlap_hash(item.text),
                )
        processed = 0
        verdict_count = 0
        if concurrency <= 1:
            for item in items:
                job_item = self.services.db.get_overlap_job_item(job.id, item.id)
                if job_item.status == "completed" and job_item.item_hash == self.services.db._stable_overlap_hash(item.text):
                    processed += 1
                    continue
                verdict_count += self._process_item(job, layer, item, shortlist.get(item.id, []), runtime, provider)
                processed += 1
                checkpoint(f"Reviewed {processed} of {len(items)} {layer} items", 10 + int((processed / len(items)) * 70))
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {
                    pool.submit(self._process_item, job, layer, item, shortlist.get(item.id, []), runtime, provider): item.id
                    for item in items
                    if self.services.db.get_overlap_job_item(job.id, item.id).status != "completed"
                }
                for future in as_completed(futures):
                    verdict_count += int(future.result())
                    processed += 1
                    checkpoint(f"Reviewed {processed} of {len(futures)} queued {layer} items", 10 + int((processed / max(1, len(futures))) * 70))
        checkpoint("Building overlap clusters", 88)
        clusters = self._persist_clusters(job.project_id, job.id, layer)
        return {"layer": layer, "processed_items": processed, "verdicts": verdict_count, "clusters": clusters, "executor": provider}

    def build_shortlist(
        self,
        project_id: str,
        layer: str,
        items: list[OverlapItem],
        *,
        top_k: int,
        sim_threshold: float,
    ) -> dict[str, list[Neighbor]]:
        if self.services.generation_service.embedding_service is not None and self.services.db.is_postgres:
            return self._embedding_shortlist(project_id, layer, items, top_k=top_k, sim_threshold=sim_threshold)
        return self._lexical_shortlist(items, top_k=top_k, sim_threshold=sim_threshold)

    def _embedding_shortlist(
        self,
        project_id: str,
        layer: str,
        items: list[OverlapItem],
        *,
        top_k: int,
        sim_threshold: float,
    ) -> dict[str, list[Neighbor]]:
        embedding_service = self.services.generation_service.embedding_service
        embedding_assignment = "layer1_similarity_embeddings" if layer == "layer1" else "layer2_similarity_embeddings"
        embedding_model = self.services.generation_service._embedding_model_name(project_id, embedding_assignment)
        by_id = {item.id: item for item in items}
        result: dict[str, list[Neighbor]] = {item.id: [] for item in items}
        for item in items:
            embedding = embedding_service.embed_text(item.text, model_name=embedding_model)
            if layer == "layer1":
                existing_hash = self.services.db.get_node_embedding_hash(item.id, embedding_model)
                if existing_hash != embedding.content_hash:
                    self.services.db.upsert_node_embedding(
                        project_id=project_id,
                        node_id=item.id,
                        embedding_model=embedding_model,
                        embedding=embedding.vector,
                        content_hash=embedding.content_hash,
                    )
                matches = self.services.db.find_similar_nodes(
                    project_id=project_id,
                    embedding_model=embedding_model,
                    embedding=embedding.vector,
                    layer=1,
                    node_type="pillar",
                    exclude_node_ids=[item.id],
                    min_similarity=sim_threshold,
                    limit=top_k,
                )
            else:
                existing_hash = self.services.db.get_layer2_feature_embedding_hash(item.id, embedding_model)
                if existing_hash != embedding.content_hash:
                    self.services.db.upsert_layer2_feature_embedding(
                        project_id=project_id,
                        feature_id=item.id,
                        embedding_model=embedding_model,
                        embedding=embedding.vector,
                        content_hash=embedding.content_hash,
                    )
                matches = self.services.db.find_similar_layer2_features(
                    project_id=project_id,
                    embedding_model=embedding_model,
                    embedding=embedding.vector,
                    exclude_feature_ids=[item.id],
                    min_similarity=sim_threshold,
                    limit=top_k,
                )
            result[item.id] = [Neighbor(by_id[match.node_id], match.score) for match in matches if match.node_id in by_id]
        return result

    @staticmethod
    def _lexical_shortlist(items: list[OverlapItem], *, top_k: int, sim_threshold: float) -> dict[str, list[Neighbor]]:
        result: dict[str, list[Neighbor]] = {}
        for item in items:
            scored = []
            for neighbor in items:
                if item.id == neighbor.id:
                    continue
                score = fuzz.token_set_ratio(item.text, neighbor.text) / 100
                if score >= sim_threshold:
                    scored.append(Neighbor(neighbor, score))
            result[item.id] = sorted(scored, key=lambda entry: entry.score, reverse=True)[:top_k]
        return result

    def _process_item(
        self,
        job: PlatformJob,
        layer: str,
        item: OverlapItem,
        neighbors: list[Neighbor],
        runtime: dict[str, Any],
        provider: str,
    ) -> int:
        self.services.db.upsert_overlap_job_item(
            project_id=job.project_id,
            job_id=job.id,
            layer=layer,
            item_id=item.id,
            item_hash=self.services.db._stable_overlap_hash(item.text),
            status="running",
        )
        try:
            target_hash = self.services.db._stable_overlap_hash(item.text)
            neighbors = self._filter_resolved_neighbors(job.project_id, layer, item, neighbors, target_hash)
            if not neighbors:
                self.services.db.upsert_overlap_job_item(
                    project_id=job.project_id,
                    job_id=job.id,
                    layer=layer,
                    item_id=item.id,
                    item_hash=self.services.db._stable_overlap_hash(item.text),
                    status="completed",
                )
                return 0
            response = self._adjudicate(job.project_id, layer, item, neighbors, runtime)
            if provider == "api":
                second = self._adjudicate(job.project_id, layer, item, neighbors, runtime)
                response = self._resolve_disagreements(response, second)
            count = 0
            neighbor_by_id = {neighbor.item.id: neighbor.item for neighbor in neighbors}
            for verdict in response.verdicts:
                neighbor = neighbor_by_id.get(verdict.neighbor_id)
                if neighbor is None:
                    continue
                relation = verdict.relation if verdict.relation in OVERLAP_RELATIONS else "needs_review"
                self.services.db.insert_overlap_verdict(
                    project_id=job.project_id,
                    job_id=job.id,
                    layer=layer,
                    target_id=item.id,
                    neighbor_id=neighbor.id,
                    relation=relation,
                    confidence=verdict.confidence,
                    rationale=verdict.rationale,
                    critic_source="overlap_critic",
                    target_hash=self.services.db._stable_overlap_hash(item.text),
                    neighbor_hash=self.services.db._stable_overlap_hash(neighbor.text),
                    metadata=getattr(verdict, "metadata", {}) if isinstance(getattr(verdict, "metadata", {}), dict) else {},
                )
                count += 1
            self.services.db.upsert_overlap_job_item(
                project_id=job.project_id,
                job_id=job.id,
                layer=layer,
                item_id=item.id,
                item_hash=self.services.db._stable_overlap_hash(item.text),
                status="completed",
            )
            return count
        except Exception as exc:
            self.services.db.upsert_overlap_job_item(
                project_id=job.project_id,
                job_id=job.id,
                layer=layer,
                item_id=item.id,
                item_hash=self.services.db._stable_overlap_hash(item.text),
                status="failed",
                error=str(exc),
            )
            raise

    def _filter_resolved_neighbors(
        self,
        project_id: str,
        layer: str,
        item: OverlapItem,
        neighbors: list[Neighbor],
        target_hash: str,
    ) -> list[Neighbor]:
        filtered = []
        for neighbor in neighbors:
            neighbor_hash = self.services.db._stable_overlap_hash(neighbor.item.text)
            resolution = self.services.db.latest_active_overlap_resolution(
                project_id,
                layer,
                item.id,
                neighbor.item.id,
                target_hash,
                neighbor_hash,
            )
            if resolution and resolution.action in {"accept_merge", "link", "dismiss", "keep_separate"}:
                continue
            filtered.append(neighbor)
        return filtered

    def _adjudicate(
        self,
        project_id: str,
        layer: str,
        item: OverlapItem,
        neighbors: list[Neighbor],
        runtime: dict[str, Any],
    ) -> OverlapCriticResponse:
        prompt = build_overlap_critic_prompt(
            layer=layer,
            product_idea=self.services.generation_service._published_product_idea(project_id),
            target_item=item.prompt_payload(),
            shortlisted_neighbors=[{**neighbor.item.prompt_payload(), "similarity": round(neighbor.score, 4)} for neighbor in neighbors],
            prompt_catalog=self.services.generation_service._prompt_catalog(project_id),
        )
        _, parsed = self.services.generation_service._call_structured_json_pass(
            project_id=project_id,
            node_id=item.id if layer == "layer1" else None,
            prompt=prompt,
            runtime_profile=runtime,
            max_tokens=2200,
            temperature=0.1,
            validator=self._validate_response,
            schema_label=f"{layer}_overlap_critic",
            schema_instructions='{"verdicts":[{"neighbor_id":"...","relation":"same_capability | broader | narrower | merge | link | distinct | fake_novelty","confidence":0.0,"rationale":"..."}]}',
            telemetry_layer=layer,
            telemetry_workflow=f"{layer}_overlap_critic",
            run_id=None,
        )
        return parsed

    @staticmethod
    def _resolve_disagreements(first: OverlapCriticResponse, second: OverlapCriticResponse) -> OverlapCriticResponse:
        second_by_id = {item.neighbor_id: item for item in second.verdicts}
        resolved: list[OverlapVerdictItem] = []
        for item in first.verdicts:
            other = second_by_id.get(item.neighbor_id)
            if other is None or other.relation == item.relation:
                resolved.append(item)
                continue
            if item.relation in HIGH_IMPACT_RELATIONS or other.relation in HIGH_IMPACT_RELATIONS:
                resolved.append(
                    OverlapVerdictItem(
                        neighbor_id=item.neighbor_id,
                        relation="needs_review",
                        confidence=min(item.confidence, other.confidence),
                        rationale=f"Self-consistency disagreement. First: {item.relation} - {item.rationale} Second: {other.relation} - {other.rationale}",
                        metadata={
                            "self_consistency": "disagreement",
                            "first": item.model_dump(mode="json"),
                            "second": other.model_dump(mode="json"),
                        },
                    )
                )
            else:
                resolved.append(
                    OverlapVerdictItem(
                        neighbor_id=item.neighbor_id,
                        relation="link",
                        confidence=min(item.confidence, other.confidence),
                        rationale=f"Non-identical overlap readings. First: {item.relation}. Second: {other.relation}.",
                        metadata={
                            "self_consistency": "soft_disagreement",
                            "first": item.model_dump(mode="json"),
                            "second": other.model_dump(mode="json"),
                        },
                    )
                )
        return OverlapCriticResponse(verdicts=resolved)

    @staticmethod
    def _validate_response(payload: dict[str, Any]) -> OverlapCriticResponse:
        try:
            response = OverlapCriticResponse.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"Invalid overlap critic payload: {exc}") from exc
        for verdict in response.verdicts:
            if verdict.relation not in OVERLAP_RELATIONS:
                verdict.relation = "needs_review"
        return response

    def _persist_clusters(self, project_id: str, job_id: str, layer: str) -> int:
        verdicts = [
            verdict for verdict in self.services.db.list_overlap_verdicts_for_job(job_id)
            if verdict.relation in {"same_capability", "merge"}
        ]
        adjacency: dict[str, set[str]] = {}
        scores: dict[tuple[str, str], float] = {}
        for verdict in verdicts:
            adjacency.setdefault(verdict.target_id, set()).add(verdict.neighbor_id)
            adjacency.setdefault(verdict.neighbor_id, set()).add(verdict.target_id)
            scores[tuple(sorted((verdict.target_id, verdict.neighbor_id)))] = verdict.confidence
        seen: set[str] = set()
        count = 0
        for start in sorted(adjacency):
            if start in seen:
                continue
            stack = [start]
            members = []
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                members.append(current)
                stack.extend(sorted(adjacency.get(current, set()) - seen))
            for index, group in enumerate(split_oversized_clusters(members, scores, max_size=8), start=1):
                self.services.db.insert_overlap_cluster(
                    project_id=project_id,
                    job_id=job_id,
                    layer=layer,
                    cluster_id=f"{layer}-overlap-{count + index}",
                    member_ids=group,
                    summary=f"{len(group)} {layer} items have merge/same-capability overlap signals.",
                    metadata={"source": "overlap_critic", "oversized_split": len(members) > 8},
                )
                count += 1
        return count

    def _active_items(self, project_id: str, layer: str) -> list[OverlapItem]:
        if layer == "layer1":
            return [
                OverlapItem(
                    id=node.id,
                    title=node.title,
                    description=node.description or "",
                    status=node.status,
                    metadata=node.json_payload,
                )
                for node in self.services.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
                if node.status not in {"cut", "merged"}
            ]
        return [
            OverlapItem(
                id=feature.id,
                title=feature.canonical_name,
                description=feature.description,
                status=feature.status,
                owner_id=feature.owner_pillar_id,
                metadata=feature.metadata,
            )
            for feature in self.services.db.list_layer2_features(project_id)
            if feature.status not in {"cut", "merged"}
        ]
