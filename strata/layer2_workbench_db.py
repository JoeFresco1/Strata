from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from strata.models import (
    Layer2CompetitiveSettings,
    Layer2Feature,
    Layer2FeatureEvidence,
    Layer2FeatureRelationship,
    Layer2SharedConcernCluster,
)


def utc_now() -> str:
    """Return an ISO timestamp in UTC for Layer 2 workbench records."""
    return datetime.now(timezone.utc).isoformat()


class Layer2WorkbenchDatabaseMixin:
    """Feature workbench, competitive evidence, and table snapshot storage helpers."""

    def create_layer2_feature_evidence(
        self,
        *,
        project_id: str,
        feature_id: str,
        competitor_name: str,
        coverage_status: str = "unclear",
        confidence: int = 50,
        source_url: str = "",
        evidence_snippet: str = "",
        rationale: str = "",
        notes: str = "",
        source_type: str = "manual",
        research_job_id: str | None = None,
    ) -> Layer2FeatureEvidence:
        """Attach manual or discovered competitor evidence to one Layer 2 feature."""
        evidence_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO layer2_feature_evidence (
                id, project_id, feature_id, competitor_name, coverage_status, confidence,
                source_url, evidence_snippet, rationale, notes, source_type, research_job_id, created_at, updated_at
            )
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (
                evidence_id,
                project_id,
                feature_id,
                competitor_name,
                coverage_status,
                max(0, min(100, int(confidence))),
                source_url,
                evidence_snippet,
                rationale,
                notes,
                source_type,
                research_job_id,
                now,
                now,
            ),
        )
        return self._row_to_layer2_feature_evidence(
            self._fetchone(f"SELECT * FROM layer2_feature_evidence WHERE id = {self.param}", (evidence_id,))
        )

    def list_layer2_feature_evidence(self, project_id: str, *, feature_id: str | None = None) -> list[Layer2FeatureEvidence]:
        """Return feature-level competitive evidence for a project or feature."""
        query = f"SELECT * FROM layer2_feature_evidence WHERE project_id = {self.param}"
        params: list[Any] = [project_id]
        if feature_id is not None:
            query += f" AND feature_id = {self.param}"
            params.append(feature_id)
        query += " ORDER BY competitor_name ASC, updated_at DESC"
        return [self._row_to_layer2_feature_evidence(row) for row in self._fetchall(query, tuple(params))]

    def get_layer2_competitive_settings(self, project_id: str) -> Layer2CompetitiveSettings:
        """Return project-level feature competitive-intelligence settings."""
        row = self._fetchone(f"SELECT * FROM layer2_competitive_settings WHERE project_id = {self.param}", (project_id,))
        if row is not None:
            settings = self._row_to_layer2_competitive_settings(row)
            inherited = self._merged_competitor_seeds(project_id, settings.known_competitors)
            if inherited != settings.known_competitors:
                return self.upsert_layer2_competitive_settings(
                    project_id=project_id,
                    known_competitors=inherited,
                    research_mode=settings.research_mode,
                )
            return settings
        now = utc_now()
        inherited = self._merged_competitor_seeds(project_id, [])
        self._execute(
            f"""
            INSERT INTO layer2_competitive_settings (project_id, known_competitors, research_mode, created_at, updated_at)
            VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (project_id, self._dump_json(inherited), "known_only", now, now),
        )
        return self._row_to_layer2_competitive_settings(
            self._fetchone(f"SELECT * FROM layer2_competitive_settings WHERE project_id = {self.param}", (project_id,))
        )

    def _merged_competitor_seeds(self, project_id: str, configured: list[str]) -> list[str]:
        """Use Layer 0 competitors as the baseline while retaining Layer 2 additions."""
        brief = self.get_project_brief(project_id)
        baseline = brief.known_competitors if brief is not None else []
        merged: list[str] = []
        seen: set[str] = set()
        for value in [*baseline, *configured]:
            clean = value.strip()
            key = clean.casefold()
            if clean and key not in seen:
                seen.add(key)
                merged.append(clean)
        return merged

    def upsert_layer2_competitive_settings(
        self,
        *,
        project_id: str,
        known_competitors: list[str],
        research_mode: str,
    ) -> Layer2CompetitiveSettings:
        """Save feature-level competitive-intelligence settings for the project."""
        now = utc_now()
        cleaned = [item.strip() for item in known_competitors if item.strip()]
        existing = self._fetchone(f"SELECT * FROM layer2_competitive_settings WHERE project_id = {self.param}", (project_id,))
        if existing is None:
            self._execute(
                f"""
                INSERT INTO layer2_competitive_settings (project_id, known_competitors, research_mode, created_at, updated_at)
                VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param})
                """,
                (project_id, self._dump_json(cleaned), research_mode, now, now),
            )
        else:
            self._execute(
                f"""
                UPDATE layer2_competitive_settings
                SET known_competitors = {self.param}, research_mode = {self.param}, updated_at = {self.param}
                WHERE project_id = {self.param}
                """,
                (self._dump_json(cleaned), research_mode, now, project_id),
            )
        return self.get_layer2_competitive_settings(project_id)

    def layer2_workbench_snapshot(
        self,
        project_id: str,
        *,
        features: list[Layer2Feature] | None = None,
        relationships: list[Layer2FeatureRelationship] | None = None,
        shared_concerns: list[Layer2SharedConcernCluster] | None = None,
        evidence: list[Layer2FeatureEvidence] | None = None,
        competitive_settings: Layer2CompetitiveSettings | None = None,
    ) -> dict[str, Any]:
        """Return table-ready Layer 2 feature rows with review and research rollups."""
        source_features = features if features is not None else self.list_layer2_features(project_id)
        source_relationships = relationships if relationships is not None else self.list_layer2_relationships(project_id)
        source_concerns = shared_concerns if shared_concerns is not None else self.list_layer2_shared_concern_clusters(project_id)
        evidence_rows = evidence if evidence is not None else self.list_layer2_feature_evidence(project_id)
        settings = competitive_settings or self.get_layer2_competitive_settings(project_id)
        feature_rows = [feature.model_dump(mode="json") for feature in source_features]
        relationship_rows = [relationship.model_dump(mode="json") for relationship in source_relationships]
        concern_rows = [concern.model_dump(mode="json") for concern in source_concerns]
        evidence_by_feature: dict[str, list[Layer2FeatureEvidence]] = {}
        for item in evidence_rows:
            evidence_by_feature.setdefault(item.feature_id, []).append(item)
        concern_by_feature: dict[str, list[dict[str, Any]]] = {}
        for concern in concern_rows:
            for feature_id in concern.get("connected_feature_ids", []):
                concern_by_feature.setdefault(feature_id, []).append(concern)
        rows = [self._layer2_workbench_row(feature, relationship_rows, evidence_by_feature, concern_by_feature) for feature in feature_rows]
        return {
            "rows": rows,
            "competitive_settings": settings.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in evidence_rows],
        }

    def _layer2_workbench_row(
        self,
        feature: dict[str, Any],
        relationship_rows: list[dict[str, Any]],
        evidence_by_feature: dict[str, list[Layer2FeatureEvidence]],
        concern_by_feature: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Build one UI-ready feature row from graph, metadata, and evidence inputs."""
        feature_evidence = [item.model_dump(mode="json") for item in evidence_by_feature.get(feature["id"], [])]
        current_evidence = self._latest_feature_evidence(feature_evidence)
        related_edges = [
            edge for edge in relationship_rows
            if edge["source_feature_id"] == feature["id"] or edge["target_feature_id"] == feature["id"]
        ]
        unresolved_edges = [
            edge for edge in related_edges
            if edge["relationship_type"] in {"duplicate_of", "conflicts_with"} and feature["status"] not in {"merged", "cut"}
        ]
        metadata = feature.get("metadata") or {}
        readiness_blockers = []
        if feature["status"] != "approved":
            readiness_blockers.append("status_not_approved")
        if metadata.get("scope_drift_flag"):
            readiness_blockers.append("scope_drift")
        if metadata.get("ambiguity_flag"):
            readiness_blockers.append("ambiguity")
        if unresolved_edges:
            readiness_blockers.append("unresolved_relationships")
        return {
            **feature,
            "coverage_family": metadata.get("coverage_family", ""),
            "priority": metadata.get("priority", ""),
            "notes": metadata.get("notes", ""),
            "relationship_count": len(related_edges),
            "shared_concerns": concern_by_feature.get(feature["id"], []),
            "evidence": feature_evidence,
            "evidence_count": len(feature_evidence),
            "research_status": self._feature_research_status(feature_evidence),
            "competitor_coverage_score": self._feature_competitor_coverage_score(current_evidence),
            "layer3_ready": not readiness_blockers,
            "readiness_blockers": readiness_blockers,
        }

    @staticmethod
    def _latest_feature_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Select the newest assessment per competitor while preserving full history elsewhere."""
        latest: dict[str, dict[str, Any]] = {}
        for item in evidence:
            key = str(item.get("competitor_name", "")).casefold()
            if key not in latest or str(item.get("updated_at", "")) > str(latest[key].get("updated_at", "")):
                latest[key] = item
        return list(latest.values())

    @staticmethod
    def _feature_research_status(evidence: list[dict[str, Any]]) -> str:
        """Distinguish automated research from manually entered feature evidence."""
        if any(item.get("source_type") == "discovered" for item in evidence):
            return "researched"
        return "manual_evidence" if evidence else "not_started"

    @staticmethod
    def _feature_competitor_coverage_score(evidence: list[dict[str, Any]]) -> int:
        """Calculate a simple percent score from manual competitor coverage evidence."""
        if not evidence:
            return 0
        weights = {"has_feature": 1.0, "partial": 0.5, "unclear": 0.0, "not_found": 0.0}
        score = sum(weights.get(item.get("coverage_status", "unclear"), 0.0) for item in evidence) / len(evidence)
        return int(round(score * 100))

    def _row_to_layer2_feature_evidence(self, row: Any) -> Layer2FeatureEvidence:
        """Convert a raw database row into Layer 2 competitor evidence."""
        return Layer2FeatureEvidence(
            id=row["id"],
            project_id=row["project_id"],
            feature_id=row["feature_id"],
            competitor_name=row["competitor_name"],
            coverage_status=row["coverage_status"],
            confidence=int(row["confidence"]),
            source_url=row["source_url"],
            evidence_snippet=row["evidence_snippet"],
            rationale=row["rationale"],
            notes=row["notes"],
            source_type=row["source_type"],
            research_job_id=row["research_job_id"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_layer2_competitive_settings(self, row: Any) -> Layer2CompetitiveSettings:
        """Convert a raw database row into project competitive-intelligence settings."""
        return Layer2CompetitiveSettings(
            project_id=row["project_id"],
            known_competitors=self._load_json_list(row["known_competitors"]),
            research_mode=row["research_mode"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )
