from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from strata.dependency_db import canonical_content_hash, feature_revision_token, pillar_revision_token
from strata.specification_models import (
    COMPILATION_POLICY_VERSION,
    CompilationMode,
    ManifestIssue,
    ManifestMembership,
    SpecificationManifestV1,
    specification_content_hash,
)


class SpecificationCompiler:
    """Select, validate, and snapshot the canonical product specification deterministically."""

    def __init__(self, db: Any):
        self.db = db

    def compile(
        self, *, project_id: str, mode: CompilationMode, actor: str, origin: str,
        command_id: str, historical_brief_revision_id: str = "",
    ) -> SpecificationManifestV1:
        """Build a typed manifest from canonical sources without invoking a model."""
        project = self.db.get_project(project_id)
        head = self.db.get_brief_head(project_id)
        if not head:
            raise ValueError("A published immutable brief is required before compilation.")
        selected_brief_id = historical_brief_revision_id if mode is CompilationMode.HISTORICAL else str(head.get("current_published_revision_id") or "")
        if not selected_brief_id:
            raise ValueError("A published immutable brief is required before compilation.")
        brief = self.db.get_brief_revision(selected_brief_id)
        if not brief or str(brief.get("project_id")) != project_id or brief.get("published_at") is None:
            raise ValueError("The selected published brief revision is invalid or inaccessible.")

        issues: list[ManifestIssue] = []
        is_noncurrent_history = mode is CompilationMode.HISTORICAL and selected_brief_id != str(head.get("current_published_revision_id") or "")
        pillars = self._select_pillars(project_id, mode, is_noncurrent_history, issues)
        pillar_ids = {pillar.id for pillar in pillars}
        features = self._select_features(project_id, mode, pillar_ids, is_noncurrent_history, issues)
        feature_ids = {feature.id for feature in features}

        memberships: list[ManifestMembership] = []
        layer1: list[dict[str, Any]] = []
        pillar_tokens = {pillar.id: pillar_revision_token(pillar) for pillar in pillars}
        for ordinal, pillar in enumerate(pillars):
            token = pillar_tokens[pillar.id]
            freshness = self.db.freshness_for_artifact(project_id, "layer1_pillar", pillar.id, token)
            authority = self._authority(project_id, "layer1_pillar", pillar.id)
            dependencies = self._dependencies(project_id, "layer1_pillar", pillar.id, token)
            self._validate_freshness(mode, freshness, "layer1_pillar", pillar.id, token, issues)
            if selected_brief_id not in {str(item.get("source_revision_id")) for item in dependencies if item.get("source_artifact_type") == "brief"}:
                self._lineage_issue(mode, "layer1_pillar", pillar.id, token, selected_brief_id, issues)
            payload = pillar.model_dump(mode="json")
            item = {
                "logical_pillar_id": pillar.id, "content_token": token, "name": pillar.title,
                "canonical_payload": payload, "review_state": pillar.status,
                "freshness_state": freshness.get("freshness_state", "unknown"),
                "authority": authority, "dependencies": dependencies,
                "inclusion_reason": "canonical_pillar_state", "ordering": ordinal,
            }
            layer1.append(item)
            memberships.append(ManifestMembership(
                layer=1, artifact_type="layer1_pillar", logical_artifact_id=pillar.id,
                artifact_revision=token, content_token=token, inclusion_reason="canonical_pillar_state",
                ordinal=ordinal, dependency_metadata={"dependencies": dependencies, "freshness": freshness}, authority_metadata=authority,
            ))

        layer2: list[dict[str, Any]] = []
        for ordinal, feature in enumerate(features):
            token = feature_revision_token(feature)
            freshness = self.db.freshness_for_artifact(project_id, "layer2_feature", feature.id, token)
            authority = self._authority(project_id, "layer2_feature", feature.id)
            dependencies = self._dependencies(project_id, "layer2_feature", feature.id, token)
            self._validate_freshness(mode, freshness, "layer2_feature", feature.id, token, issues)
            dependency_coordinates = {
                (str(item.get("source_artifact_type")), str(item.get("source_artifact_id")), str(item.get("source_revision_id")))
                for item in dependencies
            }
            if ("brief", str(head["id"]), selected_brief_id) not in dependency_coordinates:
                self._lineage_issue(mode, "layer2_feature", feature.id, token, selected_brief_id, issues)
            expected_pillar = ("layer1_pillar", feature.owner_pillar_id, pillar_tokens.get(feature.owner_pillar_id, ""))
            if expected_pillar not in dependency_coordinates:
                issues.append(self._issue("SOURCE_PILLAR_DEPENDENCY_MISSING", "source_integrity", "error" if mode is CompilationMode.APPROVED else "warning", "Feature does not depend on the selected owner pillar revision.", "layer2_feature", feature.id, token, {"expected": expected_pillar}))
            if feature.owner_pillar_id not in pillar_ids:
                issues.append(self._issue("STRUCTURE_ORPHAN_FEATURE", "structural", "error", "Feature owner is not included.", "layer2_feature", feature.id, token))
            item = {
                "logical_feature_id": feature.id, "source_pillar_id": feature.owner_pillar_id,
                "content_token": token, "canonical_payload": feature.model_dump(mode="json"),
                "review_state": feature.status, "freshness_state": freshness.get("freshness_state", "unknown"),
                "authority": authority, "dependencies": dependencies,
                "inclusion_reason": "approved_feature" if feature.status == "approved" else "draft_kept_feature",
                "ordering": ordinal,
            }
            layer2.append(item)
            memberships.append(ManifestMembership(
                layer=2, artifact_type="layer2_feature", logical_artifact_id=feature.id,
                artifact_revision=token, content_token=token, inclusion_reason=item["inclusion_reason"],
                ordinal=ordinal, dependency_metadata={"dependencies": dependencies, "freshness": freshness}, authority_metadata=authority,
            ))

        layer3, layer3_memberships = self._select_layer3(
            project_id, mode, selected_brief_id, pillar_ids, feature_ids, issues, is_noncurrent_history,
        )
        memberships.extend(layer3_memberships)
        self._validate_nested_layer3(layer3, feature_ids, issues)
        relationships = self._relationships(project_id, str(head["id"]), pillars, features, layer3, issues)
        self._validate_relationships(relationships, pillar_ids, feature_ids, issues)
        self._add_open_finding_warnings(project_id, memberships, issues)
        if mode is CompilationMode.APPROVED:
            if not pillars:
                issues.append(self._issue("STRUCTURE_NO_PILLARS", "structural", "error", "Approved compilation requires at least one included pillar."))
            if not features:
                issues.append(self._issue("STRUCTURE_NO_FEATURES", "structural", "error", "Approved compilation requires at least one included feature."))
            expanded_features = {str(item["canonical_payload"].get("feature_id", "")) for item in layer3}
            for feature_id in sorted(feature_ids - expanded_features):
                issues.append(self._issue("STRUCTURE_LAYER3_MISSING_FOR_FEATURE", "structural", "error", "Approved feature has no approved current active Layer 3 revision.", "layer2_feature", feature_id))
        excluded = self._excluded_counts(project_id, {p.id for p in pillars}, feature_ids, {item["logical_expansion_id"] for item in layer3})
        lineage_values = [
            str(dependency.get("lineage_quality", "unknown"))
            for membership in memberships
            for dependency in membership.dependency_metadata.get("dependencies", [])
        ]
        lineage_values.extend(
            str(membership.dependency_metadata["freshness"].get("lineage_quality", "unknown"))
            for membership in memberships if membership.dependency_metadata.get("freshness")
        )
        counts = Counter(lineage_values)
        has_errors = any(issue.severity == "error" for issue in issues)
        exportable = mode is CompilationMode.APPROVED and not has_errors
        if mode is not CompilationMode.APPROVED:
            issues.append(self._issue("POLICY_MODE_NOT_CANONICAL", "policy", "warning", f"{mode.value} manifests are not production exports."))
        if not exportable:
            issues.append(self._issue("POLICY_NOT_EXPORTABLE", "policy", "error" if mode is CompilationMode.APPROVED else "warning", "Manifest does not satisfy production export policy."))

        now = datetime.now(timezone.utc)
        manifest_id = str(uuid.uuid4())
        sequence = self.db.next_specification_sequence(project_id)
        root = {
            "brief_head_id": str(head["id"]), "brief_revision_id": selected_brief_id,
            "revision_number": int(brief["revision_number"]), "payload": brief["payload"],
            "content_hash": str(brief["content_hash"]), "published_at": str(brief["published_at"]),
            "authority": {"actor": str(brief["actor"]), "origin": str(brief["origin"])},
            "lineage_quality": str(brief["lineage_quality"]),
        }
        memberships.insert(0, ManifestMembership(
            layer=0, artifact_type="brief", logical_artifact_id=str(head["id"]),
            artifact_revision=selected_brief_id, content_token=str(brief["content_hash"]),
            inclusion_reason="selected_published_root", ordinal=0,
            authority_metadata=root["authority"],
        ))
        validation = {
            "policy_version": COMPILATION_POLICY_VERSION,
            "approval_gates_passed": not any(i.stage == "state_approval" and i.severity == "error" for i in issues),
            "freshness_passed": not any(i.code.startswith("STATE_") and "STALE" in i.code for i in issues),
            "lineage_passed": not any(i.code.startswith(("SOURCE_", "SEMANTIC_")) and i.severity == "error" for i in issues),
            "issue_counts": dict(Counter(issue.severity for issue in issues)),
            "excluded_artifacts": excluded, "lineage_counts": {key: counts.get(key, 0) for key in ("exact", "inferred", "unknown")},
            "exportable": exportable,
        }
        generation_references = sorted({str(item["provenance"].get("generation_reference", "")) for item in layer3 if item["provenance"].get("generation_reference")})
        model_calls = [
            item for item in self.db.list_model_calls(project_id, limit=500)
            if str(item.get("id", "")) in generation_references or str(item.get("run_id", "")) in generation_references
        ]
        logical_expansion_ids = {item["logical_expansion_id"] for item in layer3}
        revision_actions = [
            dict(row) for row in self.db._fetchall(
                f"SELECT id, logical_expansion_id, revision_id, action_type, actor, origin, created_at FROM layer3_revision_actions WHERE project_id = {self.db.param} ORDER BY created_at, id",
                (project_id,),
            ) if str(row["logical_expansion_id"]) in logical_expansion_ids
        ]
        revision_history = self.db.layer3_snapshot(project_id).get("revision_history", [])
        provenance = {
            "brief_revision_id": selected_brief_id,
            "brief_creation_command_id": str(brief.get("creation_command_id", "")),
            "authority_action_ids": sorted({action["id"] for membership in memberships for action in membership.authority_metadata.get("actions", [])}),
            "generation_references": generation_references,
            "model_calls": [{key: item.get(key) for key in ("id", "run_id", "workflow", "model_name", "prompt_key", "prompt_version", "status")} for item in model_calls],
            "layer3_revision_actions": revision_actions,
            "pending_candidate_revision_ids": sorted(str(item["id"]) for item in revision_history if item.get("workflow_state") == "candidate"),
            "superseded_revision_ids": sorted(str(item["id"]) for item in revision_history if item.get("workflow_state") == "superseded"),
            "command_id": command_id,
            "missing": [name for name, present in (("model_call", bool(model_calls or not generation_references)), ("prompt_version", any(item.get("prompt_version") for item in model_calls))) if not present],
        }
        base = {
            "manifest_id": manifest_id, "project_id": project_id, "sequence_number": sequence,
            "created_at": now, "actor": actor, "origin": origin, "command_id": command_id,
            "mode": mode, "status": "invalid" if has_errors else "compiled", "content_hash": "",
            "exportable": exportable, "project": project.model_dump(mode="json"), "root_lineage": root,
            "layer1": layer1, "layer2": layer2, "layer3": layer3, "relationships": relationships,
            "validation_summary": validation, "provenance_summary": provenance,
            "memberships": memberships, "issues": issues,
        }
        hash_payload = SpecificationManifestV1.model_validate(base).model_dump(mode="json")
        base["content_hash"] = specification_content_hash(hash_payload)
        return SpecificationManifestV1.model_validate(base)

    def _select_pillars(self, project_id: str, mode: CompilationMode, historical: bool, issues: list[ManifestIssue]) -> list[Any]:
        pillars = self.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
        if historical:
            issues.append(self._issue("SOURCE_HISTORICAL_DESCENDANTS_UNAVAILABLE", "source_integrity", "error", "Layer 1 and Layer 2 do not yet retain immutable historical descendants; current descendants were not substituted."))
            return []
        allowed = None if mode is CompilationMode.DIAGNOSTIC else {"kept", "prioritized"}
        selected = [item for item in pillars if allowed is None or item.status in allowed]
        return sorted(selected, key=lambda item: (item.priority is None, item.priority or 0, item.title.casefold(), item.id))

    def _select_features(self, project_id: str, mode: CompilationMode, pillar_ids: set[str], historical: bool, issues: list[ManifestIssue]) -> list[Any]:
        if historical:
            return []
        allowed = None if mode is CompilationMode.DIAGNOSTIC else ({"approved"} if mode is CompilationMode.APPROVED else {"kept", "approved"})
        selected = [item for item in self.db.list_layer2_features(project_id) if item.owner_pillar_id in pillar_ids and (allowed is None or item.status in allowed)]
        return sorted(selected, key=lambda item: (item.owner_pillar_id, item.canonical_name.casefold(), item.id))

    def _select_layer3(self, project_id: str, mode: CompilationMode, brief_id: str, pillar_ids: set[str], feature_ids: set[str], issues: list[ManifestIssue], historical: bool) -> tuple[list[dict[str, Any]], list[ManifestMembership]]:
        if historical:
            return [], []
        snapshot = self.db.layer3_snapshot(project_id)
        revisions = {str(item["id"]): item for item in snapshot.get("revision_history", [])}
        output: list[dict[str, Any]] = []
        memberships: list[ManifestMembership] = []
        expansions = sorted(snapshot.get("expansions", []), key=lambda item: (str(item.get("feature_name", "")).casefold(), str(item.get("id", ""))))
        for expansion in expansions:
            if str(expansion.get("feature_id")) not in feature_ids:
                continue
            revision_id = str(expansion.get("active_revision_id") or "")
            revision = revisions.get(revision_id)
            if not revision:
                issues.append(self._issue("SOURCE_LAYER3_ACTIVE_REVISION_MISSING", "source_integrity", "error", "Layer 3 head has no accessible active revision.", "layer3_expansion", str(expansion.get("id", ""))))
                continue
            state = str(revision.get("review_state", expansion.get("review_state", "draft")))
            if mode is CompilationMode.APPROVED and state != "approved":
                issues.append(self._issue("STATE_LAYER3_NOT_APPROVED", "state_approval", "warning", "Non-approved active Layer 3 revision was excluded.", "layer3_revision", str(expansion["id"]), revision_id))
                continue
            freshness = self.db.freshness_for_artifact(project_id, "layer3_revision", str(expansion["id"]), revision_id)
            self._validate_freshness(mode, freshness, "layer3_revision", str(expansion["id"]), revision_id, issues)
            payload = dict(revision.get("payload") or expansion)
            expected = {
                "brief": brief_id,
                "pillar": pillar_revision_token(self.db.get_node(str(payload.get("parent_pillar_id")))) if str(payload.get("parent_pillar_id")) in pillar_ids else "",
                "feature": feature_revision_token(self.db.get_layer2_feature(str(payload.get("feature_id")))) if str(payload.get("feature_id")) in feature_ids else "",
            }
            actual = {
                "brief": str(revision.get("source_brief_revision", "")),
                "pillar": str(revision.get("source_pillar_revision", "")),
                "feature": str(revision.get("source_layer2_feature_revision", "")),
            }
            if actual != expected:
                issues.append(self._issue("SEMANTIC_LAYER3_SOURCE_MISMATCH", "semantic", "error" if mode is CompilationMode.APPROVED else "warning", "Layer 3 source revisions do not match selected ancestors.", "layer3_revision", str(expansion["id"]), revision_id, {"expected": expected, "actual": actual}))
            authority = self._authority(project_id, "layer3_expansion", str(expansion["id"]), revision_id)
            item = {
                "logical_expansion_id": str(expansion["id"]), "active_revision_id": revision_id,
                "revision_number": int(revision["revision_number"]), "source_revisions": actual,
                "freshness_state": freshness.get("freshness_state", "unknown"), "review_state": state,
                "feature_intent": payload.get("feature_intent", ""),
                "groups": payload.get("expansion_groups", payload.get("groups", [])),
                "overlap_review": payload.get("overlap_review", payload.get("overlap_notes", [])),
                "open_questions": payload.get("open_questions", []),
                "field_ownership": revision.get("field_ownership", {}), "canonical_payload": payload,
                "provenance": {"generation_reference": revision.get("generation_reference", ""), "origin": revision.get("origin", ""), "actor": revision.get("actor", ""), "authority": authority},
            }
            output.append(item)
            memberships.append(ManifestMembership(
                layer=3, artifact_type="layer3_revision", logical_artifact_id=str(expansion["id"]),
                artifact_revision=revision_id, content_token=canonical_content_hash(payload),
                inclusion_reason="active_revision", ordinal=len(memberships),
                dependency_metadata={"dependencies": self._dependencies(project_id, "layer3_revision", str(expansion["id"]), revision_id), "source_revisions": actual, "freshness": freshness},
                authority_metadata=authority,
            ))
        return output, memberships

    def _relationships(self, project_id: str, brief_head_id: str, pillars: list[Any], features: list[Any], layer3: list[dict[str, Any]], issues: list[ManifestIssue]) -> list[dict[str, Any]]:
        pillar_ids = {item.id for item in pillars}
        feature_ids = {item.id for item in features}
        rows: list[dict[str, Any]] = [
            {"id": f"brief:{item.id}", "relationship_type": "contains_pillar", "source_artifact_type": "brief", "source_id": brief_head_id, "target_artifact_type": "layer1_pillar", "target_id": item.id}
            for item in pillars
        ]
        rows.extend(
            {"id": f"owner:{item.id}", "relationship_type": "owned_by_pillar", "source_artifact_type": "layer2_feature", "source_id": item.id, "target_artifact_type": "layer1_pillar", "target_id": item.owner_pillar_id}
            for item in features
        )
        for item in self.db.list_layer2_relationships(project_id):
            source_included = item.source_feature_id in feature_ids
            target_included = item.target_feature_id in feature_ids
            if source_included != target_included:
                issues.append(self._issue("STRUCTURE_RELATIONSHIP_ENDPOINT_MISSING", "structural", "error", "A selected feature relationship points outside canonical membership.", "layer2_relationship", item.id, details={"source_feature_id": item.source_feature_id, "target_feature_id": item.target_feature_id}))
                continue
            if source_included and target_included:
                rows.append({**item.model_dump(mode="json"), "source_artifact_type": "layer2_feature", "source_id": item.source_feature_id, "target_artifact_type": "layer2_feature", "target_id": item.target_feature_id})
        rows.extend(
            {"id": item.id, "relationship_type": "pillar_affinity", "source_artifact_type": "layer2_feature", "source_id": item.feature_id, "target_artifact_type": "layer1_pillar", "target_id": item.pillar_id, "affinity_score": item.affinity_score, "recommended_owner_pillar_id": item.recommended_owner_pillar_id}
            for item in self.db.list_layer2_affinities(project_id)
            if item.feature_id in feature_ids and item.pillar_id in pillar_ids
        )
        for expansion in layer3:
            for group in expansion.get("groups", []):
                for option in group.get("options", []):
                    for target_id in option.get("overlaps_feature_ids", []):
                        rows.append({
                            "id": f"layer3-overlap:{expansion['active_revision_id']}:{option.get('id', '')}:{target_id}",
                            "relationship_type": "layer3_overlaps_feature", "source_artifact_type": "layer3_revision",
                            "source_id": expansion["logical_expansion_id"], "target_artifact_type": "layer2_feature", "target_id": str(target_id),
                        })
        return sorted(rows, key=lambda item: (str(item.get("source_artifact_type", "")), str(item.get("source_id", "")), str(item.get("relationship_type", "")), str(item.get("target_id", "")), str(item.get("id", ""))))

    def _validate_nested_layer3(self, expansions: list[dict[str, Any]], feature_ids: set[str], issues: list[ManifestIssue]) -> None:
        """Validate application-owned nested IDs, selections, and cross-feature references."""
        seen: set[str] = set()
        for expansion in expansions:
            for group in expansion.get("groups", []):
                group_id = str(group.get("id", ""))
                if not group_id or group_id in seen:
                    issues.append(self._issue("STRUCTURE_DUPLICATE_ID", "structural", "error", "Layer 3 group IDs must be present and unique.", "layer3_revision", expansion["logical_expansion_id"], expansion["active_revision_id"], {"nested_id": group_id}))
                seen.add(group_id)
                option_ids: set[str] = set()
                for option in group.get("options", []):
                    option_id = str(option.get("id", ""))
                    if not option_id or option_id in seen or option_id in option_ids:
                        issues.append(self._issue("STRUCTURE_DUPLICATE_ID", "structural", "error", "Layer 3 option IDs must be present and unique.", "layer3_revision", expansion["logical_expansion_id"], expansion["active_revision_id"], {"nested_id": option_id}))
                    seen.add(option_id)
                    option_ids.add(option_id)
                    for target in option.get("overlaps_feature_ids", []):
                        if str(target) not in feature_ids:
                            issues.append(self._issue("STRUCTURE_NESTED_REFERENCE_MISSING", "structural", "error", "Layer 3 option references a feature outside canonical membership.", "layer3_revision", expansion["logical_expansion_id"], expansion["active_revision_id"], {"option_id": option_id, "target_feature_id": str(target)}))
                for selected_id in group.get("selected_option_ids", []):
                    if str(selected_id) not in option_ids:
                        issues.append(self._issue("STRUCTURE_SELECTED_OPTION_MISSING", "structural", "error", "Selected option does not exist in the active revision.", "layer3_revision", expansion["logical_expansion_id"], expansion["active_revision_id"], {"group_id": group_id, "selected_option_id": str(selected_id)}))

    def _add_open_finding_warnings(self, project_id: str, memberships: list[ManifestMembership], issues: list[ManifestIssue]) -> None:
        """Surface unresolved model findings as warnings without treating them as decisions."""
        included = {(item.artifact_type, item.logical_artifact_id) for item in memberships}
        included.update(("layer3_expansion", item.logical_artifact_id) for item in memberships if item.artifact_type == "layer3_revision")
        for finding in self.db.list_critic_findings(project_id):
            if finding.get("status") != "open":
                continue
            coordinate = (str(finding.get("artifact_type", "")), str(finding.get("artifact_id", "")))
            if coordinate not in included:
                continue
            issues.append(self._issue("STATE_OPEN_CRITIC_FINDING", "state_approval", "warning", "An unresolved model finding remains for this included artifact.", coordinate[0], coordinate[1], str(finding.get("artifact_revision_id", "")), {"finding_id": finding["id"], "category": finding.get("category", "")}))

    def _validate_relationships(self, relationships: list[dict[str, Any]], pillar_ids: set[str], feature_ids: set[str], issues: list[ManifestIssue]) -> None:
        for item in relationships:
            source_valid = item.get("source_artifact_type") not in {"layer1_pillar", "layer2_feature"} or item.get("source_id") in pillar_ids | feature_ids
            target_valid = item.get("target_artifact_type") not in {"layer1_pillar", "layer2_feature"} or item.get("target_id") in pillar_ids | feature_ids
            if not source_valid or not target_valid:
                issues.append(self._issue("STRUCTURE_RELATIONSHIP_ENDPOINT_MISSING", "structural", "error", "Relationship endpoint is absent from the manifest.", "layer2_relationship", str(item["id"])))

    def _validate_freshness(self, mode: CompilationMode, freshness: dict[str, Any], artifact_type: str, artifact_id: str, revision: str, issues: list[ManifestIssue]) -> None:
        state = str(freshness.get("freshness_state", "unknown"))
        if state != "current":
            severity = "error" if mode is CompilationMode.APPROVED else "warning"
            issues.append(self._issue("STATE_ARTIFACT_STALE" if state == "stale" else "STATE_FRESHNESS_UNKNOWN", "state_approval", severity, f"Artifact freshness is {state}.", artifact_type, artifact_id, revision, {"freshness": freshness}))
        quality = str(freshness.get("lineage_quality", "unknown"))
        if quality != "exact":
            issues.append(self._issue("SOURCE_LINEAGE_NOT_EXACT", "source_integrity", "error" if mode is CompilationMode.APPROVED else "warning", f"Required lineage quality is {quality}, not exact.", artifact_type, artifact_id, revision, {"lineage_quality": quality}))

    def _lineage_issue(self, mode: CompilationMode, artifact_type: str, artifact_id: str, revision: str, brief_id: str, issues: list[ManifestIssue]) -> None:
        issues.append(self._issue("SOURCE_BRIEF_DEPENDENCY_MISSING", "source_integrity", "error" if mode is CompilationMode.APPROVED else "warning", "Artifact does not have a dependency on the selected brief revision.", artifact_type, artifact_id, revision, {"selected_brief_revision_id": brief_id}))

    def _dependencies(self, project_id: str, artifact_type: str, artifact_id: str, revision: str) -> list[dict[str, Any]]:
        rows = self.db._fetchall(
            f"SELECT * FROM artifact_dependencies WHERE project_id = {self.db.param} AND dependent_artifact_type = {self.db.param} AND dependent_artifact_id = {self.db.param} AND dependent_revision_id = {self.db.param} ORDER BY source_artifact_type, source_artifact_id, source_revision_id, dependency_kind",
            (project_id, artifact_type, artifact_id, revision),
        )
        return [dict(row) for row in rows]

    def _authority(self, project_id: str, artifact_type: str, artifact_id: str, revision_id: str = "") -> dict[str, Any]:
        rows = self.db._fetchall(
            f"SELECT id, revision_id, action_type, actor, origin, created_at FROM artifact_authority_actions WHERE project_id = {self.db.param} AND artifact_type = {self.db.param} AND artifact_id = {self.db.param} AND ({self.db.param} = '' OR revision_id IN ('', {self.db.param})) ORDER BY created_at, id",
            (project_id, artifact_type, artifact_id, revision_id, revision_id),
        )
        return {"human_owned": any(str(row["actor"]) not in {"system", "model", "critic"} for row in rows), "actions": [dict(row) for row in rows]}

    def _excluded_counts(self, project_id: str, pillar_ids: set[str], feature_ids: set[str], expansion_ids: set[str]) -> list[dict[str, Any]]:
        values = []
        for kind, all_ids, included in (
            ("layer1_pillar", {item.id for item in self.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")}, pillar_ids),
            ("layer2_feature", {item.id for item in self.db.list_layer2_features(project_id)}, feature_ids),
            ("layer3_expansion", {str(item["id"]) for item in self.db.layer3_snapshot(project_id).get("expansions", [])}, expansion_ids),
        ):
            values.extend({"artifact_type": kind, "artifact_id": item, "reason": "selection_policy"} for item in sorted(all_ids - included))
        return values

    @staticmethod
    def _issue(code: str, stage: str, severity: str, message: str, artifact_type: str = "", artifact_id: str = "", artifact_revision: str = "", details: dict[str, Any] | None = None) -> ManifestIssue:
        return ManifestIssue(code=code, stage=stage, severity=severity, message=message, artifact_type=artifact_type, artifact_id=artifact_id, artifact_revision=artifact_revision, details=details or {})
