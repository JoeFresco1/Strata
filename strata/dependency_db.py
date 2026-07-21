from __future__ import annotations

import hashlib
import json
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from strata.command_types import state_token

BRIEF_PAYLOAD_FIELDS = (
    "product_idea", "problem", "known_competitors", "constraints", "target_users",
    "goals", "preferred_directions", "rejected_directions", "notes",
)
FRESHNESS_STATES = {"current", "stale", "superseded", "unknown"}
LINEAGE_QUALITIES = {"exact", "inferred", "unknown"}


def utc_now_value() -> str:
    """Return an ISO UTC timestamp without importing the composite database class."""
    return datetime.now(timezone.utc).isoformat()


def canonical_content_hash(payload: dict[str, Any]) -> str:
    """Hash normalized JSON content for immutable revision and cache identity."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def pillar_revision_token(pillar: Any) -> str:
    """Return the temporary deterministic content/version token for a Layer 1 pillar."""
    return state_token({
        "id": pillar.id, "title": pillar.title, "description": pillar.description,
    })


def feature_revision_token(feature: Any) -> str:
    """Return the temporary deterministic content/version token for a Layer 2 feature."""
    return state_token({
        "id": feature.id, "canonical_name": feature.canonical_name, "description": feature.description,
        "feature_type": str(feature.feature_type), "granularity_class": str(feature.granularity_class),
        "owner_pillar_id": feature.owner_pillar_id,
        "aliases": feature.aliases, "metadata": feature.metadata,
    })


class DependencyDatabaseMixin:
    """Persist narrow artifact lineage, freshness projections, and stale history."""

    def brief_payload(self, brief: Any) -> dict[str, Any]:
        """Return only canonical brief content, excluding mutable publication metadata."""
        return {field: getattr(brief, field) for field in BRIEF_PAYLOAD_FIELDS}

    def ensure_brief_revision_head(self, project_id: str, *, origin: str = "migration", actor: str = "strata") -> dict[str, Any]:
        """Backfill one logical head and initial immutable revision for a legacy brief."""
        head = self._fetchone(f"SELECT * FROM brief_heads WHERE project_id = {self.param}", (project_id,))
        if head is not None:
            return dict(head)
        brief = self.get_project_brief(project_id)
        if brief is None:
            raise ValueError(f"Project brief not found: {project_id}")
        now = utc_now_value()
        head_id = brief.id
        revision_id = str(uuid.uuid4())
        payload = self.brief_payload(brief)
        published = brief.status == "published"
        self._execute(
            f"INSERT INTO brief_heads (id, project_id, current_draft_revision_id, current_published_revision_id, revision_counter, created_at, updated_at) VALUES ({', '.join([self.param] * 7)})",
            (head_id, project_id, None, None, 1, brief.created_at.isoformat(), now),
        )
        self._execute(
            f"INSERT INTO brief_revisions (id, brief_head_id, project_id, revision_number, payload, content_hash, origin, actor, creation_command_id, lineage_quality, created_at, published_at, superseded_at) VALUES ({', '.join([self.param] * 13)})",
            (revision_id, head_id, project_id, 1, self._dump_json(payload), canonical_content_hash(payload), origin, actor, "", "exact", brief.created_at.isoformat(), now if published else None, None),
        )
        self._execute(
            f"UPDATE brief_heads SET current_draft_revision_id = {self.param}, current_published_revision_id = {self.param} WHERE id = {self.param}",
            (revision_id, revision_id if published else None, head_id),
        )
        self.set_artifact_freshness(
            project_id=project_id, artifact_type="brief", artifact_id=head_id,
            artifact_revision_id=revision_id, freshness_state="current", lineage_quality="exact",
        )
        return dict(self._fetchone(f"SELECT * FROM brief_heads WHERE id = {self.param}", (head_id,)))

    def create_brief_draft_revision(
        self, project_id: str, *, origin: str, actor: str, creation_command_id: str = "",
    ) -> dict[str, Any]:
        """Snapshot the mutable working draft as a new immutable content revision when changed."""
        head = self.ensure_brief_revision_head(project_id, origin=origin, actor=actor)
        brief = self.get_project_brief(project_id)
        payload = self.brief_payload(brief)
        content_hash = canonical_content_hash(payload)
        current_id = str(head.get("current_draft_revision_id") or "")
        current = self.get_brief_revision(current_id) if current_id else None
        if current and current["content_hash"] == content_hash:
            return current
        revision_id = str(uuid.uuid4())
        number = int(head["revision_counter"]) + 1
        now = utc_now_value()
        self._execute(
            f"INSERT INTO brief_revisions (id, brief_head_id, project_id, revision_number, payload, content_hash, origin, actor, creation_command_id, lineage_quality, created_at, published_at, superseded_at) VALUES ({', '.join([self.param] * 13)})",
            (revision_id, head["id"], project_id, number, self._dump_json(payload), content_hash, origin, actor, creation_command_id, "exact", now, None, None),
        )
        self._execute(
            f"UPDATE brief_heads SET current_draft_revision_id = {self.param}, revision_counter = {self.param}, updated_at = {self.param} WHERE id = {self.param}",
            (revision_id, number, now, head["id"]),
        )
        self.set_artifact_freshness(
            project_id=project_id, artifact_type="brief", artifact_id=str(head["id"]),
            artifact_revision_id=revision_id, freshness_state="current", lineage_quality="exact",
        )
        return self.get_brief_revision(revision_id)

    def publish_brief_revision(
        self, project_id: str, *, origin: str, actor: str, creation_command_id: str = "",
    ) -> dict[str, Any]:
        """Select an immutable draft as published while retaining every prior publication."""
        head = self.ensure_brief_revision_head(project_id, origin=origin, actor=actor)
        draft = self.create_brief_draft_revision(
            project_id, origin=origin, actor=actor, creation_command_id=creation_command_id,
        )
        previous_id = str(head.get("current_published_revision_id") or "")
        previous = self.get_brief_revision(previous_id) if previous_id else None
        if previous and previous["content_hash"] == draft["content_hash"]:
            selected = previous
            selected_id = previous_id
            changed = False
        else:
            selected = draft
            selected_id = str(draft["id"])
            changed = selected_id != previous_id
        now = utc_now_value()
        if selected.get("published_at") is None:
            self._execute(
                f"UPDATE brief_revisions SET published_at = {self.param} WHERE id = {self.param} AND published_at IS NULL",
                (now, selected_id),
            )
        if changed and previous_id:
            self._execute(
                f"UPDATE brief_revisions SET superseded_at = {self.param} WHERE id = {self.param} AND superseded_at IS NULL",
                (now, previous_id),
            )
            self.set_artifact_freshness(
                project_id=project_id, artifact_type="brief", artifact_id=str(head["id"]),
                artifact_revision_id=previous_id, freshness_state="superseded", lineage_quality="exact",
            )
        self._execute(
            f"UPDATE brief_heads SET current_draft_revision_id = {self.param}, current_published_revision_id = {self.param}, updated_at = {self.param} WHERE id = {self.param}",
            (selected_id, selected_id, now, head["id"]),
        )
        self.set_artifact_freshness(
            project_id=project_id, artifact_type="brief", artifact_id=str(head["id"]),
            artifact_revision_id=selected_id, freshness_state="current", lineage_quality="exact",
        )
        return {"revision": self.get_brief_revision(selected_id), "previous_revision_id": previous_id or None, "changed": changed}

    def get_brief_head(self, project_id: str) -> dict[str, Any] | None:
        """Return the logical brief head for one project."""
        row = self._fetchone(f"SELECT * FROM brief_heads WHERE project_id = {self.param}", (project_id,))
        return dict(row) if row is not None else None

    def get_brief_revision(self, revision_id: str) -> dict[str, Any] | None:
        """Read one immutable brief revision with its normalized payload."""
        if not revision_id:
            return None
        row = self._fetchone(f"SELECT * FROM brief_revisions WHERE id = {self.param}", (revision_id,))
        if row is None:
            return None
        value = dict(row)
        value["payload"] = self._load_json(value["payload"])
        return value

    def list_brief_revisions(self, project_id: str) -> list[dict[str, Any]]:
        """Return every retained brief revision in revision order."""
        rows = self._fetchall(
            f"SELECT * FROM brief_revisions WHERE project_id = {self.param} ORDER BY revision_number",
            (project_id,),
        )
        values = []
        for row in rows:
            value = dict(row)
            value["payload"] = self._load_json(value["payload"])
            values.append(value)
        return values

    def current_published_brief_revision_id(self, project_id: str) -> str:
        """Return the exact immutable publication ID, backfilling legacy state if needed."""
        head = self.ensure_brief_revision_head(project_id)
        return str(head.get("current_published_revision_id") or "")

    def set_artifact_freshness(
        self, *, project_id: str, artifact_type: str, artifact_id: str,
        artifact_revision_id: str, freshness_state: str, lineage_quality: str,
    ) -> None:
        """Upsert the independent freshness projection for one artifact revision."""
        if freshness_state not in FRESHNESS_STATES or lineage_quality not in LINEAGE_QUALITIES:
            raise ValueError("Invalid freshness state or lineage quality.")
        now = utc_now_value()
        self._execute(
            f"""
            INSERT INTO artifact_freshness_states
                (project_id, artifact_type, artifact_id, artifact_revision_id, freshness_state, lineage_quality, stale_reason_count, updated_at)
            VALUES ({', '.join([self.param] * 8)})
            ON CONFLICT (project_id, artifact_type, artifact_id, artifact_revision_id)
            DO UPDATE SET freshness_state = EXCLUDED.freshness_state, lineage_quality = EXCLUDED.lineage_quality,
                          stale_reason_count = artifact_freshness_states.stale_reason_count, updated_at = EXCLUDED.updated_at
            """,
            (project_id, artifact_type, artifact_id, artifact_revision_id, freshness_state, lineage_quality, 0, now),
        )

    def add_artifact_dependency(
        self, *, project_id: str, dependent_artifact_type: str, dependent_artifact_id: str,
        dependent_revision_id: str, source_artifact_type: str, source_artifact_id: str,
        source_revision_id: str, dependency_kind: str = "content", lineage_quality: str = "exact",
    ) -> None:
        """Record one validated project-local dependency without creating duplicates."""
        self.get_project(project_id)
        if not all((dependent_artifact_type, dependent_artifact_id, dependent_revision_id, source_artifact_type, source_artifact_id, source_revision_id)):
            raise ValueError("Artifact dependencies require complete source and dependent identities.")
        if lineage_quality not in LINEAGE_QUALITIES:
            raise ValueError("Invalid dependency lineage quality.")
        if not self._artifact_revision_belongs_to_project(
            project_id, dependent_artifact_type, dependent_artifact_id, dependent_revision_id,
        ):
            raise ValueError("Dependent artifact revision does not belong to this project.")
        if not self._artifact_revision_belongs_to_project(
            project_id, source_artifact_type, source_artifact_id, source_revision_id,
        ):
            raise ValueError("Source artifact revision does not belong to this project.")
        self._execute(
            f"""
            INSERT INTO artifact_dependencies
                (id, project_id, dependent_artifact_type, dependent_artifact_id, dependent_revision_id,
                 source_artifact_type, source_artifact_id, source_revision_id, dependency_kind, lineage_quality, created_at)
            VALUES ({', '.join([self.param] * 11)})
            ON CONFLICT (project_id, dependent_artifact_type, dependent_artifact_id, dependent_revision_id,
                         source_artifact_type, source_artifact_id, source_revision_id, dependency_kind) DO NOTHING
            """,
            (str(uuid.uuid4()), project_id, dependent_artifact_type, dependent_artifact_id,
             dependent_revision_id, source_artifact_type, source_artifact_id, source_revision_id,
             dependency_kind, lineage_quality, utc_now_value()),
        )

    def _artifact_revision_belongs_to_project(
        self, project_id: str, artifact_type: str, artifact_id: str, revision_id: str,
    ) -> bool:
        """Resolve ownership for canonical and registered derived artifact revisions."""
        if artifact_type == "brief":
            row = self._fetchone(
                f"SELECT 1 FROM brief_revisions WHERE project_id = {self.param} AND brief_head_id = {self.param} AND id = {self.param}",
                (project_id, artifact_id, revision_id),
            )
            return row is not None
        if artifact_type == "layer1_pillar":
            row = self._fetchone(f"SELECT project_id FROM nodes WHERE id = {self.param}", (artifact_id,))
            return row is not None and str(row["project_id"]) == project_id
        if artifact_type == "layer2_feature":
            row = self._fetchone(f"SELECT project_id FROM layer2_features WHERE id = {self.param}", (artifact_id,))
            return row is not None and str(row["project_id"]) == project_id
        if artifact_type == "layer3_revision":
            row = self._fetchone(
                f"SELECT 1 FROM layer3_expansion_revisions WHERE project_id = {self.param} AND logical_expansion_id = {self.param} AND id = {self.param}",
                (project_id, artifact_id, revision_id),
            )
            return row is not None
        row = self._fetchone(
            f"SELECT 1 FROM artifact_freshness_states WHERE project_id = {self.param} AND artifact_type = {self.param} AND artifact_id = {self.param} AND artifact_revision_id = {self.param}",
            (project_id, artifact_type, artifact_id, revision_id),
        )
        return row is not None

    def carry_forward_dependencies(
        self, *, project_id: str, artifact_type: str, artifact_id: str,
        previous_revision_id: str, replacement_revision_id: str,
    ) -> None:
        """Copy incoming lineage to a new temporary mutable-artifact version token."""
        rows = self._fetchall(
            f"SELECT * FROM artifact_dependencies WHERE project_id = {self.param} AND dependent_artifact_type = {self.param} AND dependent_artifact_id = {self.param} AND dependent_revision_id = {self.param}",
            (project_id, artifact_type, artifact_id, previous_revision_id),
        )
        for row in rows:
            self.add_artifact_dependency(
                project_id=project_id, dependent_artifact_type=artifact_type, dependent_artifact_id=artifact_id,
                dependent_revision_id=replacement_revision_id, source_artifact_type=str(row["source_artifact_type"]),
                source_artifact_id=str(row["source_artifact_id"]), source_revision_id=str(row["source_revision_id"]),
                dependency_kind=str(row["dependency_kind"]), lineage_quality=str(row["lineage_quality"]),
            )

    def mark_descendants_stale(
        self, *, project_id: str, source_artifact_type: str, source_artifact_id: str,
        previous_source_revision_id: str, replacement_source_revision_id: str,
        command_id: str, actor: str, origin: str, reason_code: str,
    ) -> dict[str, Any]:
        """Traverse exact dependency edges and durably mark affected revisions stale."""
        queue = deque([(source_artifact_type, source_artifact_id, previous_source_revision_id, True)])
        visited_sources: set[tuple[str, str, str]] = set()
        visited_targets: set[tuple[str, str, str]] = set()
        direct: list[dict[str, str]] = []
        transitive: list[dict[str, str]] = []
        already: list[dict[str, str]] = []
        while queue:
            source_type, source_id, source_revision, is_direct = queue.popleft()
            source_key = (source_type, source_id, source_revision)
            if source_key in visited_sources:
                continue
            visited_sources.add(source_key)
            rows = self._fetchall(
                f"SELECT * FROM artifact_dependencies WHERE project_id = {self.param} AND source_artifact_type = {self.param} AND source_artifact_id = {self.param} AND source_revision_id = {self.param}",
                (project_id, source_type, source_id, source_revision),
            )
            for row in rows:
                target = {
                    "artifact_type": str(row["dependent_artifact_type"]),
                    "artifact_id": str(row["dependent_artifact_id"]),
                    "revision_id": str(row["dependent_revision_id"]),
                }
                target_key = (target["artifact_type"], target["artifact_id"], target["revision_id"])
                if target_key in visited_targets:
                    continue
                visited_targets.add(target_key)
                state = self._fetchone(
                    f"SELECT freshness_state FROM artifact_freshness_states WHERE project_id = {self.param} AND artifact_type = {self.param} AND artifact_id = {self.param} AND artifact_revision_id = {self.param}",
                    (project_id, target["artifact_type"], target["artifact_id"], target["revision_id"]),
                )
                was_stale = state is not None and str(state["freshness_state"]) == "stale"
                if was_stale:
                    already.append(target)
                else:
                    self.set_artifact_freshness(
                        project_id=project_id, artifact_type=target["artifact_type"], artifact_id=target["artifact_id"],
                        artifact_revision_id=target["revision_id"], freshness_state="stale",
                        lineage_quality=str(row["lineage_quality"]),
                    )
                    self._execute(
                        f"UPDATE artifact_freshness_states SET stale_reason_count = stale_reason_count + 1, updated_at = {self.param} WHERE project_id = {self.param} AND artifact_type = {self.param} AND artifact_id = {self.param} AND artifact_revision_id = {self.param}",
                        (utc_now_value(), project_id, target["artifact_type"], target["artifact_id"], target["revision_id"]),
                    )
                    (direct if is_direct else transitive).append(target)
                self._execute(
                    f"""
                    INSERT INTO artifact_stale_transitions
                        (id, project_id, artifact_type, artifact_id, artifact_revision_id, prior_freshness_state,
                         source_artifact_type, source_artifact_id, previous_source_revision_id,
                         replacement_source_revision_id, triggering_command_id, actor, origin, reason_code, created_at)
                    VALUES ({', '.join([self.param] * 15)})
                    ON CONFLICT (project_id, artifact_type, artifact_id, artifact_revision_id,
                                 source_artifact_type, source_artifact_id, previous_source_revision_id,
                                 replacement_source_revision_id, reason_code) DO NOTHING
                    """,
                    (str(uuid.uuid4()), project_id, target["artifact_type"], target["artifact_id"], target["revision_id"],
                     str(state["freshness_state"]) if state else "unknown", source_type, source_id, source_revision,
                     replacement_source_revision_id, command_id, actor, origin, reason_code, utc_now_value()),
                )
                if target["artifact_type"] == "layer3_revision":
                    self._execute(
                        f"UPDATE layer3_expansion_revision_states SET freshness_state = {self.param}, updated_at = {self.param} WHERE revision_id = {self.param}",
                        ("stale", utc_now_value(), target["revision_id"]),
                    )
                queue.append((target["artifact_type"], target["artifact_id"], target["revision_id"], False))
        return {
            "directly_affected": direct, "transitively_affected": transitive,
            "already_stale": already, "dependency_reason": reason_code,
            "propagation_count": len(direct) + len(transitive), "complete": True,
        }

    def freshness_for_artifact(self, project_id: str, artifact_type: str, artifact_id: str, revision_id: str) -> dict[str, Any]:
        """Return freshness plus durable reasons for API snapshots and export validation."""
        if "artifact_freshness_states" not in self._table_names():
            return {
                "project_id": project_id, "artifact_type": artifact_type, "artifact_id": artifact_id,
                "artifact_revision_id": revision_id, "freshness_state": "unknown",
                "lineage_quality": "unknown", "stale_reason_count": 0, "stale_reasons": [],
                "reconciliation_available": artifact_type == "layer3_revision",
            }
        row = self._fetchone(
            f"SELECT * FROM artifact_freshness_states WHERE project_id = {self.param} AND artifact_type = {self.param} AND artifact_id = {self.param} AND artifact_revision_id = {self.param}",
            (project_id, artifact_type, artifact_id, revision_id),
        )
        reasons = self._fetchall(
            f"SELECT source_artifact_type, source_artifact_id, previous_source_revision_id, replacement_source_revision_id, reason_code, created_at FROM artifact_stale_transitions WHERE project_id = {self.param} AND artifact_type = {self.param} AND artifact_id = {self.param} AND artifact_revision_id = {self.param} ORDER BY created_at DESC",
            (project_id, artifact_type, artifact_id, revision_id),
        )
        value = dict(row) if row else {
            "project_id": project_id, "artifact_type": artifact_type, "artifact_id": artifact_id,
            "artifact_revision_id": revision_id, "freshness_state": "unknown",
            "lineage_quality": "unknown", "stale_reason_count": len(reasons),
        }
        value["stale_reasons"] = [dict(reason) for reason in reasons]
        value["reconciliation_available"] = artifact_type == "layer3_revision"
        return value

    def evaluate_artifact_freshness(
        self, *, project_id: str, artifact_type: str, artifact_id: str, artifact_revision_id: str,
    ) -> dict[str, Any]:
        """Compare stored dependencies with current authoritative source revisions."""
        dependencies = self._fetchall(
            f"SELECT * FROM artifact_dependencies WHERE project_id = {self.param} AND dependent_artifact_type = {self.param} AND dependent_artifact_id = {self.param} AND dependent_revision_id = {self.param}",
            (project_id, artifact_type, artifact_id, artifact_revision_id),
        )
        mismatches: list[dict[str, str]] = []
        for dependency in dependencies:
            source_type = str(dependency["source_artifact_type"])
            source_id = str(dependency["source_artifact_id"])
            expected = str(dependency["source_revision_id"])
            current = ""
            if source_type == "brief":
                head = self.get_brief_head(project_id)
                current = str(head.get("current_published_revision_id") or "") if head else ""
            elif source_type == "layer1_pillar":
                try:
                    pillar = self.get_node(source_id)
                    current = pillar_revision_token(pillar) if pillar.project_id == project_id else ""
                except ValueError:
                    current = ""
            elif source_type == "layer2_feature":
                try:
                    feature = self.get_layer2_feature(source_id)
                    current = feature_revision_token(feature) if feature.project_id == project_id else ""
                except ValueError:
                    current = ""
            if current != expected:
                mismatches.append({
                    "source_artifact_type": source_type, "source_artifact_id": source_id,
                    "expected_source_revision": expected, "current_source_revision": current,
                })
        quality = "unknown" if not dependencies else (
            "exact" if all(str(item["lineage_quality"]) == "exact" for item in dependencies) else "inferred"
        )
        state = "current" if dependencies and not mismatches else ("stale" if mismatches else "unknown")
        self.set_artifact_freshness(
            project_id=project_id, artifact_type=artifact_type, artifact_id=artifact_id,
            artifact_revision_id=artifact_revision_id, freshness_state=state, lineage_quality=quality,
        )
        return {"freshness_state": state, "lineage_quality": quality, "mismatches": mismatches}

    def lineage_counts(self, project_id: str) -> dict[str, int]:
        """Count exact, inferred, and unknown dependencies for diagnostics and tests."""
        rows = self._fetchall(
            f"SELECT lineage_quality, COUNT(*) AS count FROM artifact_dependencies WHERE project_id = {self.param} GROUP BY lineage_quality",
            (project_id,),
        )
        counts = {quality: 0 for quality in LINEAGE_QUALITIES}
        counts.update({str(row["lineage_quality"]): int(row["count"]) for row in rows})
        return counts

    def register_project_memory_lineage(self, memory: Any) -> None:
        """Attach scope/coverage memory to the current pillar source when applicable."""
        if memory.memory_type not in {"scope_contract", "scoped_coverage", "coverage_assessment", "coverage_summary"} or not memory.scope_id:
            return
        try:
            pillar = self.get_node(memory.scope_id)
        except ValueError:
            return
        if pillar.project_id != memory.project_id:
            return
        artifact_type = "layer2_scope_contract" if memory.memory_type == "scope_contract" else "layer2_coverage_state"
        revision_id = canonical_content_hash(memory.content)
        self.set_artifact_freshness(project_id=memory.project_id, artifact_type=artifact_type, artifact_id=memory.id, artifact_revision_id=revision_id, freshness_state="current", lineage_quality="exact")
        self.add_artifact_dependency(
            project_id=memory.project_id, dependent_artifact_type=artifact_type,
            dependent_artifact_id=memory.id, dependent_revision_id=revision_id,
            source_artifact_type="layer1_pillar", source_artifact_id=pillar.id,
            source_revision_id=pillar_revision_token(pillar), dependency_kind="scope" if memory.memory_type == "scope_contract" else "coverage",
            lineage_quality="exact",
        )

    def register_coverage_lineage(self, coverage: Any) -> None:
        """Attach a coverage row to its pillar and evidence feature versions."""
        pillar = self.get_node(coverage.pillar_id)
        revision_id = coverage.updated_at.isoformat()
        self.set_artifact_freshness(project_id=coverage.project_id, artifact_type="layer2_coverage_matrix", artifact_id=coverage.id, artifact_revision_id=revision_id, freshness_state="current", lineage_quality="exact")
        self.add_artifact_dependency(
            project_id=coverage.project_id, dependent_artifact_type="layer2_coverage_matrix",
            dependent_artifact_id=coverage.id, dependent_revision_id=revision_id,
            source_artifact_type="layer1_pillar", source_artifact_id=pillar.id,
            source_revision_id=pillar_revision_token(pillar), dependency_kind="coverage", lineage_quality="exact",
        )
        for feature_id in coverage.evidence_feature_ids:
            try:
                feature = self.get_layer2_feature(feature_id)
            except ValueError:
                continue
            self.add_artifact_dependency(
                project_id=coverage.project_id, dependent_artifact_type="layer2_coverage_matrix",
                dependent_artifact_id=coverage.id, dependent_revision_id=revision_id,
                source_artifact_type="layer2_feature", source_artifact_id=feature.id,
                source_revision_id=feature_revision_token(feature), dependency_kind="coverage", lineage_quality="exact",
            )

    def register_research_lineage(self, finding: Any) -> None:
        """Attach a research assessment to exact current canonical sources where resolvable."""
        revision_id = finding.updated_at.isoformat()
        self.set_artifact_freshness(project_id=finding.project_id, artifact_type="research_assessment", artifact_id=finding.id, artifact_revision_id=revision_id, freshness_state="current", lineage_quality="exact")
        head = self.get_brief_head(finding.project_id)
        if head and head.get("current_published_revision_id"):
            self.add_artifact_dependency(
                project_id=finding.project_id, dependent_artifact_type="research_assessment",
                dependent_artifact_id=finding.id, dependent_revision_id=revision_id,
                source_artifact_type="brief", source_artifact_id=str(head["id"]),
                source_revision_id=str(head["current_published_revision_id"]), dependency_kind="research", lineage_quality="exact",
            )
        if finding.scope_id:
            try:
                pillar = self.get_node(finding.scope_id)
                if pillar.project_id == finding.project_id:
                    self.add_artifact_dependency(
                        project_id=finding.project_id, dependent_artifact_type="research_assessment",
                        dependent_artifact_id=finding.id, dependent_revision_id=revision_id,
                        source_artifact_type="layer1_pillar", source_artifact_id=pillar.id,
                        source_revision_id=pillar_revision_token(pillar), dependency_kind="research", lineage_quality="exact",
                    )
            except ValueError:
                try:
                    feature = self.get_layer2_feature(finding.scope_id)
                    if feature.project_id == finding.project_id:
                        self.add_artifact_dependency(
                            project_id=finding.project_id, dependent_artifact_type="research_assessment",
                            dependent_artifact_id=finding.id, dependent_revision_id=revision_id,
                            source_artifact_type="layer2_feature", source_artifact_id=feature.id,
                            source_revision_id=feature_revision_token(feature), dependency_kind="research", lineage_quality="exact",
                        )
                except ValueError:
                    pass
