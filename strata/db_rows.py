from __future__ import annotations

from datetime import datetime
from typing import Any

from strata.models import (
    BriefConversationTurn,
    Layer1PillarRecord,
    Node,
    Project,
    ProjectBrief,
    ProjectMemory,
    ProjectModelSettings,
    ResearchChunk,
    ResearchFinding,
    ResearchJob,
    ResearchSource,
)


class DatabaseRowMixin:
    """Convert raw SQLite/PostgreSQL rows into application models."""

    @staticmethod
    def _row_to_project(row: Any) -> Project:
        """Convert a raw database row into a Project model."""
        return Project(
            id=row["id"],
            name=row["name"],
            idea=row["idea"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_project_summary(self, row: Any) -> dict[str, Any]:
        """Convert a project row with summary metadata into a plain payload for the hub."""
        brief_updated_at = row["brief_updated_at"]
        return {
            "id": row["id"],
            "name": row["name"],
            "idea": row["idea"],
            "created_at": datetime.fromisoformat(str(row["created_at"])),
            "brief_status": row["brief_status"],
            "brief_updated_at": datetime.fromisoformat(str(brief_updated_at)) if brief_updated_at else None,
            "node_count": int(row["node_count"]),
            "pillar_count": int(row["pillar_count"]),
        }

    def _row_to_project_brief(self, row: Any) -> ProjectBrief:
        """Convert a raw database row into a ProjectBrief model."""
        return ProjectBrief(
            id=row["id"],
            project_id=row["project_id"],
            product_idea=row["product_idea"],
            known_competitors=self._load_json_list(row["known_competitors"]),
            constraints=row["constraints"],
            target_users=row["target_users"],
            goals=self._load_json_list(row["goals"]),
            preferred_directions=self._load_json_list(row["preferred_directions"]),
            rejected_directions=self._load_json_list(row["rejected_directions"]),
            notes=row["notes"],
            status=row["status"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_project_model_settings(self, row: Any) -> ProjectModelSettings:
        """Convert a raw database row into a ProjectModelSettings model."""
        return ProjectModelSettings(
            project_id=row["project_id"],
            llm_profiles=self._load_json_list(row["llm_profiles"]),
            embedding_profiles=self._load_json_list(row["embedding_profiles"]),
            execution_intent=str(row["execution_intent"]) if row["execution_intent"] else "local_first",
            routing_policy=self._load_json(row["routing_policy"]),
            concurrency_policy=self._load_json(row["concurrency_policy"]),
            assignments=self._load_json(row["assignments"]),
            prompt_catalog=self._load_json(row["prompt_catalog"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_brief_conversation_turn(self, row: Any) -> BriefConversationTurn:
        """Convert a raw database row into a BriefConversationTurn model."""
        return BriefConversationTurn(
            id=row["id"],
            project_id=row["project_id"],
            role=row["role"],
            content=row["content"],
            request_id=row["request_id"],
            extracted_updates=self._load_json(row["extracted_updates"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_node(self, row: Any) -> Node:
        """Convert a raw database row into a Node model."""
        return Node(
            id=row["id"],
            project_id=row["project_id"],
            parent_id=row["parent_id"],
            layer=row["layer"],
            node_type=row["node_type"],
            title=row["title"],
            description=row["description"],
            json_payload=self._load_json(row["json_payload"]),
            status=row["status"],
            priority=row["priority"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_layer1_pillar(self, row: Any) -> Layer1PillarRecord:
        """Convert a raw database row into a Layer 1 pillar graph-boundary record."""
        return Layer1PillarRecord(
            id=row["id"],
            project_id=row["project_id"],
            node_id=row["node_id"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_project_memory(self, row: Any) -> ProjectMemory:
        """Convert a raw database row into a ProjectMemory model."""
        return ProjectMemory(
            id=row["id"],
            project_id=row["project_id"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            memory_type=row["memory_type"],
            content=self._load_json(row["content"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_research_job(self, row: Any) -> ResearchJob:
        """Convert a raw database row into a ResearchJob model."""
        return ResearchJob(
            id=row["id"],
            project_id=row["project_id"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            job_type=row["job_type"],
            status=row["status"],
            progress=int(row["progress"]),
            details=self._load_json(row["details"]),
            error=row["error"],
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_research_source(self, row: Any) -> ResearchSource:
        """Convert a raw database row into a ResearchSource model."""
        return ResearchSource(
            id=row["id"],
            project_id=row["project_id"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            competitor_name=row["competitor_name"],
            domain=row["domain"],
            url=row["url"],
            page_type=row["page_type"],
            title=row["title"],
            status_code=row["status_code"],
            fetched_at=datetime.fromisoformat(str(row["fetched_at"])),
            content_hash=row["content_hash"],
            metadata=self._load_json(row["metadata"]),
        )

    def _row_to_research_chunk(self, row: Any) -> ResearchChunk:
        """Convert a raw database row into a ResearchChunk model."""
        return ResearchChunk(
            id=row["id"],
            project_id=row["project_id"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            source_id=row["source_id"],
            competitor_name=row["competitor_name"],
            domain=row["domain"],
            url=row["url"],
            title=row["title"],
            chunk_index=int(row["chunk_index"]),
            text=row["text"],
            metadata=self._load_json(row["metadata"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )

    def _row_to_research_finding(self, row: Any) -> ResearchFinding:
        """Convert a raw database row into a ResearchFinding model."""
        return ResearchFinding(
            id=row["id"],
            project_id=row["project_id"],
            scope=row["scope"],
            scope_id=row["scope_id"],
            finding_type=row["finding_type"],
            title=row["title"],
            summary=row["summary"],
            payload=self._load_json(row["payload"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

