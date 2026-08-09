from __future__ import annotations

import uuid
from typing import Any

from strata.command_types import state_token
from strata.dependency_db import canonical_content_hash, utc_now_value
from strata.discovery_models import (
    CompetitorResearchMode,
    CompetitorResearchRevision,
    DiscoveryRevisionState,
    ProductDiscoveryRevision,
)


class DiscoveryDatabaseMixin:
    """Persist immutable discovery/research revisions and deterministic projections."""

    def ensure_discovery_head(self, project_id: str) -> dict[str, Any]:
        """Return the project discovery head, creating its stable identity when absent."""
        self.get_project(project_id)
        row = self._fetchone(
            f"SELECT * FROM product_discovery_heads WHERE project_id = {self.param}",
            (project_id,),
        )
        if row is not None:
            return dict(row)
        now = utc_now_value()
        head_id = str(uuid.uuid4())
        self._execute(
            f"INSERT INTO product_discovery_heads (id, project_id, revision_counter, created_at, updated_at) "
            f"VALUES ({', '.join([self.param] * 5)})",
            (head_id, project_id, 0, now, now),
        )
        return dict(self._fetchone(
            f"SELECT * FROM product_discovery_heads WHERE id = {self.param}",
            (head_id,),
        ))

    def ensure_competitor_research_head(self, project_id: str) -> dict[str, Any]:
        """Return the competitor-research head without starting any research."""
        self.get_project(project_id)
        row = self._fetchone(
            f"SELECT * FROM competitor_research_heads WHERE project_id = {self.param}",
            (project_id,),
        )
        if row is not None:
            return dict(row)
        now = utc_now_value()
        head_id = str(uuid.uuid4())
        self._execute(
            f"INSERT INTO competitor_research_heads (id, project_id, revision_counter, created_at, updated_at) "
            f"VALUES ({', '.join([self.param] * 5)})",
            (head_id, project_id, 0, now, now),
        )
        return dict(self._fetchone(
            f"SELECT * FROM competitor_research_heads WHERE id = {self.param}",
            (head_id,),
        ))

    def create_discovery_revision(
        self,
        *,
        project_id: str,
        source_brief_revision_id: str,
        competitor_research_mode: str,
        payload: dict[str, Any],
        model_authored_fields: dict[str, Any] | None = None,
        human_owned_fields: dict[str, Any] | None = None,
        review_findings: list[dict[str, Any]] | None = None,
        runtime_provenance: list[dict[str, Any]] | None = None,
        generation_job_id: str | None = None,
        competitor_research_revision_id: str | None = None,
        command_id: str = "",
        actor: str = "strata",
        origin: str = "system_workflow",
    ) -> ProductDiscoveryRevision:
        """Append one candidate revision linked to the exact published brief revision."""
        brief_head = self.get_brief_head(project_id)
        if brief_head is None or str(brief_head.get("current_published_revision_id") or "") != source_brief_revision_id:
            raise ValueError("Product Discovery requires the current published Layer 0 brief revision.")
        mode = CompetitorResearchMode(competitor_research_mode)
        if competitor_research_revision_id:
            research = self.get_competitor_research_revision(competitor_research_revision_id)
            if research.project_id != project_id or research.state not in {
                DiscoveryRevisionState.APPROVED,
                DiscoveryRevisionState.PUBLISHED,
            }:
                raise ValueError("Only approved project-local competitor research can be attached.")
        head = self.ensure_discovery_head(project_id)
        number = int(head["revision_counter"]) + 1
        revision_id = str(uuid.uuid4())
        now = utc_now_value()
        model_fields = model_authored_fields or {}
        human_fields = human_owned_fields or {}
        findings = review_findings or []
        provenance = runtime_provenance or []
        dependency = {
            "source_brief_revision_id": source_brief_revision_id,
            "competitor_research_revision_id": competitor_research_revision_id,
        }
        content = {
            "discovery": payload,
            "model_authored_fields": model_fields,
            "human_owned_fields": human_fields,
            "review_findings": findings,
            "runtime_provenance": provenance,
        }
        audit = [{
            "action": "created",
            "actor": actor,
            "origin": origin,
            "command_id": command_id,
            "timestamp": now,
        }]
        self._execute(
            f"""
            INSERT INTO product_discovery_revisions (
                id, head_id, project_id, revision_number, source_brief_revision_id, state,
                competitor_research_mode, competitor_research_revision_id, generation_job_id,
                payload, model_authored_fields, human_owned_fields, review_findings,
                runtime_provenance, audit_history, dependency_metadata, freshness_state,
                stale_reason, content_hash, creation_command_id, created_at
            ) VALUES ({', '.join([self.param] * 21)})
            """,
            (
                revision_id, head["id"], project_id, number, source_brief_revision_id,
                DiscoveryRevisionState.CANDIDATE.value, mode.value,
                competitor_research_revision_id, generation_job_id,
                self._dump_json(payload), self._dump_json(model_fields), self._dump_json(human_fields),
                self._dump_json(findings), self._dump_json(provenance), self._dump_json(audit),
                self._dump_json(dependency), "current", "", canonical_content_hash(content),
                command_id, now,
            ),
        )
        self._execute(
            f"UPDATE product_discovery_heads SET current_candidate_revision_id = {self.param}, "
            f"revision_counter = {self.param}, updated_at = {self.param} WHERE id = {self.param}",
            (revision_id, number, now, head["id"]),
        )
        self.set_artifact_freshness(
            project_id=project_id,
            artifact_type="product_discovery",
            artifact_id=str(head["id"]),
            artifact_revision_id=revision_id,
            freshness_state="current",
            lineage_quality="exact",
        )
        self.add_artifact_dependency(
            project_id=project_id,
            dependent_artifact_type="product_discovery",
            dependent_artifact_id=str(head["id"]),
            dependent_revision_id=revision_id,
            source_artifact_type="brief",
            source_artifact_id=str(brief_head["id"]),
            source_revision_id=source_brief_revision_id,
            dependency_kind="content",
            lineage_quality="exact",
        )
        if competitor_research_revision_id:
            research = self.get_competitor_research_revision(competitor_research_revision_id)
            self.add_artifact_dependency(
                project_id=project_id,
                dependent_artifact_type="product_discovery",
                dependent_artifact_id=str(head["id"]),
                dependent_revision_id=revision_id,
                source_artifact_type="competitor_research",
                source_artifact_id=research.head_id,
                source_revision_id=research.id,
                dependency_kind="research",
                lineage_quality="exact",
            )
        return self.get_discovery_revision(revision_id)

    def get_discovery_revision(self, revision_id: str) -> ProductDiscoveryRevision:
        """Load and validate one project discovery revision."""
        row = self._fetchone(
            f"SELECT * FROM product_discovery_revisions WHERE id = {self.param}",
            (revision_id,),
        )
        if row is None:
            raise ValueError(f"Product Discovery revision not found: {revision_id}")
        return ProductDiscoveryRevision.model_validate(self._discovery_revision_payload(dict(row)))

    def list_discovery_revisions(self, project_id: str) -> list[ProductDiscoveryRevision]:
        """List every retained Product Discovery revision in stable order."""
        rows = self._fetchall(
            f"SELECT * FROM product_discovery_revisions WHERE project_id = {self.param} ORDER BY revision_number",
            (project_id,),
        )
        return [
            ProductDiscoveryRevision.model_validate(self._discovery_revision_payload(dict(row)))
            for row in rows
        ]

    def discovery_snapshot(self, project_id: str) -> dict[str, Any]:
        """Return current discovery/research heads, revisions, and compact projections."""
        discovery_head = self._fetchone(
            f"SELECT * FROM product_discovery_heads WHERE project_id = {self.param}",
            (project_id,),
        )
        research_head = self._fetchone(
            f"SELECT * FROM competitor_research_heads WHERE project_id = {self.param}",
            (project_id,),
        )
        discovery_revisions = self.list_discovery_revisions(project_id) if discovery_head else []
        research_revisions = self.list_competitor_research_revisions(project_id) if research_head else []
        projections = self.list_discovery_context_projections(project_id)
        discovery_payloads = [
            {**item.model_dump(mode="json"), "state_token": state_token(item.model_dump(mode="json"))}
            for item in discovery_revisions
        ]
        research_payloads = [
            {**item.model_dump(mode="json"), "state_token": state_token(item.model_dump(mode="json"))}
            for item in research_revisions
        ]
        return {
            "head": dict(discovery_head) if discovery_head else None,
            "current_candidate": next((
                item for item in discovery_payloads
                if discovery_head and item["id"] == discovery_head["current_candidate_revision_id"]
            ), None),
            "published": next((
                item for item in discovery_payloads
                if discovery_head and item["id"] == discovery_head["current_published_revision_id"]
            ), None),
            "revisions": discovery_payloads,
            "competitor_research": {
                "head": dict(research_head) if research_head else None,
                "current_candidate": next((
                    item for item in research_payloads
                    if research_head and item["id"] == research_head["current_candidate_revision_id"]
                ), None),
                "published": next((
                    item for item in research_payloads
                    if research_head and item["id"] == research_head["current_published_revision_id"]
                ), None),
                "revisions": research_payloads,
            },
            "projections": projections,
            "state_token": state_token({
                "discovery": [item.content_hash for item in discovery_revisions],
                "research": [item.content_hash for item in research_revisions],
                "projections": [item["content_hash"] for item in projections],
            }),
        }

    def transition_discovery_revision(
        self,
        *,
        revision_id: str,
        target_state: str,
        command_id: str,
        actor: str,
        origin: str,
    ) -> ProductDiscoveryRevision:
        """Apply an allowed human authority transition without mutating published content."""
        revision = self.get_discovery_revision(revision_id)
        target = DiscoveryRevisionState(target_state)
        allowed = {
            DiscoveryRevisionState.CANDIDATE: {
                DiscoveryRevisionState.APPROVED,
                DiscoveryRevisionState.REJECTED,
            },
            DiscoveryRevisionState.APPROVED: {
                DiscoveryRevisionState.PUBLISHED,
                DiscoveryRevisionState.REJECTED,
            },
            DiscoveryRevisionState.REJECTED: {DiscoveryRevisionState.CANDIDATE},
        }
        if target not in allowed.get(revision.state, set()):
            raise ValueError(f"Cannot transition discovery from {revision.state.value} to {target.value}.")
        now = utc_now_value()
        timestamp_column = {
            DiscoveryRevisionState.APPROVED: "approved_at",
            DiscoveryRevisionState.PUBLISHED: "published_at",
            DiscoveryRevisionState.REJECTED: "rejected_at",
            DiscoveryRevisionState.CANDIDATE: None,
        }[target]
        audit = list(revision.audit_history)
        audit.append({
            "action": target.value,
            "actor": actor,
            "origin": origin,
            "command_id": command_id,
            "timestamp": now,
        })
        assignments = [f"state = {self.param}", f"audit_history = {self.param}"]
        values: list[Any] = [target.value, self._dump_json(audit)]
        if timestamp_column:
            assignments.append(f"{timestamp_column} = {self.param}")
            values.append(now)
        values.append(revision_id)
        self._execute(
            f"UPDATE product_discovery_revisions SET {', '.join(assignments)} WHERE id = {self.param}",
            tuple(values),
        )
        if target == DiscoveryRevisionState.PUBLISHED:
            head = self.ensure_discovery_head(revision.project_id)
            previous_id = str(head.get("current_published_revision_id") or "")
            if previous_id and previous_id != revision_id:
                self._execute(
                    f"UPDATE product_discovery_revisions SET state = {self.param}, superseded_at = {self.param}, "
                    f"freshness_state = {self.param} WHERE id = {self.param}",
                    (DiscoveryRevisionState.SUPERSEDED.value, now, "superseded", previous_id),
                )
            self._execute(
                f"UPDATE product_discovery_heads SET current_published_revision_id = {self.param}, "
                f"current_candidate_revision_id = NULL, updated_at = {self.param} WHERE id = {self.param}",
                (revision_id, now, revision.head_id),
            )
        return self.get_discovery_revision(revision_id)

    def revise_discovery_human_fields(
        self,
        *,
        revision_id: str,
        human_owned_fields: dict[str, Any],
        command_id: str,
        actor: str,
        origin: str,
        competitor_research_revision_id: str | None | object = ...,
    ) -> ProductDiscoveryRevision:
        """Create a new candidate so human edits never mutate an existing revision."""
        source = self.get_discovery_revision(revision_id)
        attached_revision = (
            source.competitor_research_revision_id
            if competitor_research_revision_id is ...
            else competitor_research_revision_id
        )
        mode = source.competitor_research_mode.value
        if attached_revision:
            mode = self.get_competitor_research_revision(str(attached_revision)).scope.mode.value
        replacement = self.create_discovery_revision(
            project_id=source.project_id,
            source_brief_revision_id=source.source_brief_revision_id,
            competitor_research_mode=mode,
            payload=source.discovery.model_dump(mode="json"),
            model_authored_fields=source.model_authored_fields,
            human_owned_fields=human_owned_fields,
            review_findings=[item.model_dump(mode="json") for item in source.review_findings],
            runtime_provenance=[item.model_dump(mode="json") for item in source.runtime_provenance],
            generation_job_id=source.generation_job_id,
            competitor_research_revision_id=attached_revision,
            command_id=command_id,
            actor=actor,
            origin=origin,
        )
        if source.state != DiscoveryRevisionState.PUBLISHED:
            self._execute(
                f"UPDATE product_discovery_revisions SET state = {self.param}, superseded_at = {self.param}, "
                f"freshness_state = {self.param} WHERE id = {self.param}",
                (DiscoveryRevisionState.SUPERSEDED.value, utc_now_value(), "superseded", source.id),
            )
        return replacement

    def create_competitor_research_revision(
        self,
        *,
        project_id: str,
        source_brief_revision_id: str,
        scope: dict[str, Any],
        payload: dict[str, Any],
        command_id: str = "",
        state: str = "candidate",
    ) -> CompetitorResearchRevision:
        """Persist a checkpointable research revision without attaching it to discovery."""
        mode = CompetitorResearchMode(str(scope.get("mode") or "no_competitor_research"))
        if mode == CompetitorResearchMode.NONE:
            raise ValueError("No competitor-research revision is created when research is disabled.")
        brief_head = self.get_brief_head(project_id)
        if brief_head is None or str(brief_head.get("current_published_revision_id") or "") != source_brief_revision_id:
            raise ValueError("Competitor research requires the current published Layer 0 brief revision.")
        head = self.ensure_competitor_research_head(project_id)
        number = int(head["revision_counter"]) + 1
        revision_id = str(uuid.uuid4())
        now = utc_now_value()
        content_hash = canonical_content_hash({"scope": scope, "payload": payload})
        values = (
            revision_id, head["id"], project_id, number, source_brief_revision_id,
            DiscoveryRevisionState(state).value, self._dump_json(scope),
            self._dump_json(payload.get("profiles") or []),
            self._dump_json(payload.get("evidence") or []),
            self._dump_json(payload.get("inferred_pillars") or []),
            self._dump_json(payload.get("territories") or []),
            self._dump_json(payload.get("gaps") or []),
            self._dump_json(payload.get("derived_lenses") or []),
            self._dump_json(payload.get("human_decisions") or {}),
            self._dump_json(payload.get("runtime_provenance") or []),
            self._dump_json(payload.get("checkpoint_state") or {}),
            bool(payload.get("partial_completion")),
            "current", "", content_hash, command_id, now,
            payload.get("research_date"), payload.get("last_verified_at"),
        )
        self._execute(
            f"""
            INSERT INTO competitor_research_revisions (
                id, head_id, project_id, revision_number, source_brief_revision_id, state,
                scope, profiles, evidence, inferred_pillars, territories, gaps, derived_lenses,
                human_decisions, runtime_provenance, checkpoint_state, partial_completion,
                freshness_state, stale_reason, content_hash, creation_command_id, created_at,
                research_date, last_verified_at
            ) VALUES ({', '.join([self.param] * 24)})
            """,
            values,
        )
        self._execute(
            f"UPDATE competitor_research_heads SET current_candidate_revision_id = {self.param}, "
            f"revision_counter = {self.param}, updated_at = {self.param} WHERE id = {self.param}",
            (revision_id, number, now, head["id"]),
        )
        self.set_artifact_freshness(
            project_id=project_id,
            artifact_type="competitor_research",
            artifact_id=str(head["id"]),
            artifact_revision_id=revision_id,
            freshness_state="current",
            lineage_quality="exact",
        )
        self.add_artifact_dependency(
            project_id=project_id,
            dependent_artifact_type="competitor_research",
            dependent_artifact_id=str(head["id"]),
            dependent_revision_id=revision_id,
            source_artifact_type="brief",
            source_artifact_id=str(brief_head["id"]),
            source_revision_id=source_brief_revision_id,
            dependency_kind="research",
            lineage_quality="exact",
        )
        return self.get_competitor_research_revision(revision_id)

    def get_competitor_research_revision(self, revision_id: str) -> CompetitorResearchRevision:
        """Load and validate one competitor-research revision."""
        row = self._fetchone(
            f"SELECT * FROM competitor_research_revisions WHERE id = {self.param}",
            (revision_id,),
        )
        if row is None:
            raise ValueError(f"Competitor research revision not found: {revision_id}")
        payload = dict(row)
        for key in (
            "scope", "profiles", "evidence", "inferred_pillars", "territories", "gaps",
            "derived_lenses", "human_decisions", "runtime_provenance", "checkpoint_state",
        ):
            payload[key] = self._load_json(payload[key])
        return CompetitorResearchRevision.model_validate(payload)

    def list_competitor_research_revisions(self, project_id: str) -> list[CompetitorResearchRevision]:
        """List retained competitor research independently from discovery revisions."""
        rows = self._fetchall(
            f"SELECT id FROM competitor_research_revisions WHERE project_id = {self.param} ORDER BY revision_number",
            (project_id,),
        )
        return [self.get_competitor_research_revision(str(row["id"])) for row in rows]

    def transition_competitor_research_revision(
        self,
        *,
        revision_id: str,
        target_state: str,
        command_id: str,
        actor: str,
        origin: str,
    ) -> CompetitorResearchRevision:
        """Apply human approval transitions to an independent research revision."""
        revision = self.get_competitor_research_revision(revision_id)
        target = DiscoveryRevisionState(target_state)
        allowed = {
            DiscoveryRevisionState.CANDIDATE: {
                DiscoveryRevisionState.APPROVED,
                DiscoveryRevisionState.REJECTED,
            },
            DiscoveryRevisionState.APPROVED: {
                DiscoveryRevisionState.PUBLISHED,
                DiscoveryRevisionState.REJECTED,
            },
            DiscoveryRevisionState.REJECTED: {DiscoveryRevisionState.CANDIDATE},
        }
        if target not in allowed.get(revision.state, set()):
            raise ValueError(f"Cannot transition competitor research from {revision.state.value} to {target.value}.")
        now = utc_now_value()
        timestamp_column = {
            DiscoveryRevisionState.APPROVED: "approved_at",
            DiscoveryRevisionState.PUBLISHED: "published_at",
            DiscoveryRevisionState.REJECTED: "rejected_at",
            DiscoveryRevisionState.CANDIDATE: None,
        }[target]
        assignments = [f"state = {self.param}"]
        values: list[Any] = [target.value]
        if timestamp_column:
            assignments.append(f"{timestamp_column} = {self.param}")
            values.append(now)
        values.append(revision_id)
        self._execute(
            f"UPDATE competitor_research_revisions SET {', '.join(assignments)} WHERE id = {self.param}",
            tuple(values),
        )
        if target == DiscoveryRevisionState.PUBLISHED:
            head = self.ensure_competitor_research_head(revision.project_id)
            previous_id = str(head.get("current_published_revision_id") or "")
            if previous_id and previous_id != revision_id:
                self._execute(
                    f"UPDATE competitor_research_revisions SET state = {self.param}, superseded_at = {self.param}, "
                    f"freshness_state = {self.param} WHERE id = {self.param}",
                    (DiscoveryRevisionState.SUPERSEDED.value, now, "superseded", previous_id),
                )
            self._execute(
                f"UPDATE competitor_research_heads SET current_published_revision_id = {self.param}, "
                f"current_candidate_revision_id = NULL, updated_at = {self.param} WHERE id = {self.param}",
                (revision_id, now, revision.head_id),
            )
        return self.get_competitor_research_revision(revision_id)

    def revise_competitor_human_decisions(
        self,
        *,
        revision_id: str,
        human_decisions: dict[str, Any],
        command_id: str,
    ) -> CompetitorResearchRevision:
        """Create a candidate revision so research regeneration cannot overwrite human authority."""
        source = self.get_competitor_research_revision(revision_id)
        payload = {
            "profiles": [item.model_dump(mode="json") for item in source.profiles],
            "evidence": [item.model_dump(mode="json") for item in source.evidence],
            "inferred_pillars": [item.model_dump(mode="json") for item in source.inferred_pillars],
            "territories": [item.model_dump(mode="json") for item in source.territories],
            "gaps": [item.model_dump(mode="json") for item in source.gaps],
            "derived_lenses": [item.model_dump(mode="json") for item in source.derived_lenses],
            "human_decisions": human_decisions,
            "runtime_provenance": [item.model_dump(mode="json") for item in source.runtime_provenance],
            "checkpoint_state": source.checkpoint_state,
            "partial_completion": source.partial_completion,
            "research_date": source.research_date,
            "last_verified_at": source.last_verified_at,
        }
        replacement = self.create_competitor_research_revision(
            project_id=source.project_id,
            source_brief_revision_id=source.source_brief_revision_id,
            scope=source.scope.model_dump(mode="json"),
            payload=payload,
            command_id=command_id,
        )
        if source.state != DiscoveryRevisionState.PUBLISHED:
            self._execute(
                f"UPDATE competitor_research_revisions SET state = {self.param}, superseded_at = {self.param}, "
                f"freshness_state = {self.param} WHERE id = {self.param}",
                (DiscoveryRevisionState.SUPERSEDED.value, utc_now_value(), "superseded", source.id),
            )
        return replacement

    def persist_discovery_context_projection(
        self,
        *,
        project_id: str,
        projection_type: str,
        discovery_revision_id: str,
        competitor_research_revision_id: str | None,
        compiler_version: str,
        payload: dict[str, Any],
        included_item_ids: list[str],
        excluded_item_ids: list[str],
        inclusion_rationale: dict[str, str],
        exclusion_rationale: dict[str, str],
        token_estimate: int,
        command_id: str = "",
    ) -> dict[str, Any]:
        """Insert or reuse a deterministic compact projection for fixed source revisions."""
        if projection_type not in {"layer1_discovery", "competitive"}:
            raise ValueError("Unsupported discovery projection type.")
        discovery = self.get_discovery_revision(discovery_revision_id)
        if discovery.project_id != project_id or discovery.state not in {
            DiscoveryRevisionState.APPROVED,
            DiscoveryRevisionState.PUBLISHED,
        }:
            raise ValueError("Context projections require approved Product Discovery.")
        content = {
            "projection_type": projection_type,
            "source_discovery_revision_id": discovery_revision_id,
            "source_competitor_research_revision_id": competitor_research_revision_id,
            "compiler_version": compiler_version,
            "payload": payload,
            "included_item_ids": included_item_ids,
            "excluded_item_ids": excluded_item_ids,
            "inclusion_rationale": inclusion_rationale,
            "exclusion_rationale": exclusion_rationale,
        }
        content_hash = canonical_content_hash(content)
        existing = self._fetchone(
            f"SELECT * FROM discovery_context_projections WHERE project_id = {self.param} "
            f"AND projection_type = {self.param} AND content_hash = {self.param}",
            (project_id, projection_type, content_hash),
        )
        if existing is not None:
            return self._projection_payload(dict(existing))
        projection_id = str(uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO discovery_context_projections (
                id, project_id, projection_type, source_discovery_revision_id,
                source_competitor_research_revision_id, compiler_version, payload,
                included_item_ids, excluded_item_ids, inclusion_rationale, exclusion_rationale,
                token_estimate, content_hash, creation_command_id, created_at
            ) VALUES ({', '.join([self.param] * 15)})
            """,
            (
                projection_id, project_id, projection_type, discovery_revision_id,
                competitor_research_revision_id, compiler_version, self._dump_json(payload),
                self._dump_json(included_item_ids), self._dump_json(excluded_item_ids),
                self._dump_json(inclusion_rationale), self._dump_json(exclusion_rationale),
                token_estimate, content_hash, command_id, utc_now_value(),
            ),
        )
        return self._projection_payload(dict(self._fetchone(
            f"SELECT * FROM discovery_context_projections WHERE id = {self.param}",
            (projection_id,),
        )))

    def list_discovery_context_projections(self, project_id: str) -> list[dict[str, Any]]:
        """Return compact projections without any raw research corpus."""
        rows = self._fetchall(
            f"SELECT * FROM discovery_context_projections WHERE project_id = {self.param} ORDER BY created_at",
            (project_id,),
        )
        return [self._projection_payload(dict(row)) for row in rows]

    def _discovery_revision_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        """Decode JSON database columns into the typed discovery revision contract."""
        row["head_id"] = row.pop("head_id")
        row["discovery"] = self._load_json(row.pop("payload"))
        for key in (
            "model_authored_fields", "human_owned_fields", "review_findings",
            "runtime_provenance", "audit_history", "dependency_metadata",
        ):
            row[key] = (
                self._load_json_list(row[key])
                if key in {"review_findings", "runtime_provenance", "audit_history"}
                else self._load_json(row[key])
            )
        return row

    def _projection_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        """Decode one deterministic context projection for API and job use."""
        for key in (
            "payload", "included_item_ids", "excluded_item_ids",
            "inclusion_rationale", "exclusion_rationale",
        ):
            row[key] = self._load_json(row[key])
        return row
