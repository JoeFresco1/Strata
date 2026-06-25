from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pgvector import Vector

from strata.models import AssistantActionProposal, AssistantConversation, AssistantMessage


def utc_now() -> str:
    """Return a stable UTC timestamp for assistant persistence."""
    return datetime.now(timezone.utc).isoformat()


class AssistantDatabaseMixin:
    """Persistence primitives for project assistant conversations, runs, and retrieval documents."""

    def create_assistant_conversation(self, project_id: str, title: str, home_scope: str) -> AssistantConversation:
        """Create one project conversation without binding it permanently to a layer."""
        conversation_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO assistant_conversations (
                id, project_id, title, home_scope, compacted_summary, summary_state, archived, created_at, updated_at
            ) VALUES ({self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param}, {self.param})
            """,
            (conversation_id, project_id, title.strip() or "New conversation", home_scope, "", self._dump_json({}), False, now, now),
        )
        return self.get_assistant_conversation(conversation_id)

    def get_assistant_conversation(self, conversation_id: str) -> AssistantConversation:
        """Return one conversation or fail with a stable domain error."""
        row = self._fetchone(
            f"SELECT * FROM assistant_conversations WHERE id = {self.param}",
            (conversation_id,),
        )
        if row is None:
            raise ValueError(f"Assistant conversation not found: {conversation_id}")
        return self._row_to_assistant_conversation(row)

    def list_assistant_conversations(self, project_id: str, *, include_archived: bool = False) -> list[AssistantConversation]:
        """List newest project conversations for the drawer and reference selector."""
        query = f"SELECT * FROM assistant_conversations WHERE project_id = {self.param}"
        params: list[Any] = [project_id]
        if not include_archived:
            query += f" AND archived = {self.param}"
            params.append(False)
        query += " ORDER BY updated_at DESC"
        return [self._row_to_assistant_conversation(row) for row in self._fetchall(query, tuple(params))]

    def update_assistant_conversation(
        self,
        conversation_id: str,
        *,
        title: str | None = None,
        archived: bool | None = None,
        compacted_summary: str | None = None,
        summary_state: dict[str, Any] | None = None,
    ) -> AssistantConversation:
        """Update conversation metadata or its versioned compaction state."""
        updates: list[str] = []
        params: list[Any] = []
        for column, value in (("title", title), ("archived", archived), ("compacted_summary", compacted_summary)):
            if value is not None:
                updates.append(f"{column} = {self.param}")
                params.append(value)
        if summary_state is not None:
            updates.append(f"summary_state = {self.param}")
            params.append(self._dump_json(summary_state))
        updates.append(f"updated_at = {self.param}")
        params.extend([utc_now(), conversation_id])
        self._execute(
            f"UPDATE assistant_conversations SET {', '.join(updates)} WHERE id = {self.param}",
            tuple(params),
        )
        return self.get_assistant_conversation(conversation_id)

    def create_assistant_message(
        self,
        *,
        conversation_id: str,
        project_id: str,
        role: str,
        content: str = "",
        status: str = "completed",
        request_id: str | None = None,
        active_scope: str = "overall",
        focus: dict[str, Any] | None = None,
        reference_conversation_ids: list[str] | None = None,
        execution_intent_override: str | None = None,
        thinking_enabled: bool = False,
        deep_mode: bool = False,
    ) -> AssistantMessage:
        """Append an idempotent assistant turn and return an existing retry when present."""
        if request_id:
            existing = self.get_assistant_message_by_request(conversation_id, request_id, role)
            if existing is not None:
                return existing
        message_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO assistant_messages (
                id, conversation_id, project_id, role, content, status, request_id, active_scope,
                focus, reference_conversation_ids, execution_intent_override, thinking_enabled, deep_mode, citations,
                proposed_actions, retrieval_trace, error, created_at, updated_at
            ) VALUES ({', '.join([self.param] * 19)})
            ON CONFLICT DO NOTHING
            """,
            (
                message_id, conversation_id, project_id, role, content, status, request_id, active_scope,
                self._dump_json(focus or {}), self._dump_json(reference_conversation_ids or []),
                execution_intent_override, thinking_enabled, deep_mode, self._dump_json([]), self._dump_json([]),
                self._dump_json({}), None, now, now,
            ),
        )
        if request_id:
            existing = self.get_assistant_message_by_request(conversation_id, request_id, role)
            if existing is not None:
                return existing
        return self.get_assistant_message(message_id)

    def get_assistant_message(self, message_id: str) -> AssistantMessage:
        """Return one persisted assistant message."""
        row = self._fetchone(f"SELECT * FROM assistant_messages WHERE id = {self.param}", (message_id,))
        if row is None:
            raise ValueError(f"Assistant message not found: {message_id}")
        return self._row_to_assistant_message(row)

    def get_assistant_message_by_request(
        self,
        conversation_id: str,
        request_id: str,
        role: str,
    ) -> AssistantMessage | None:
        """Resolve a retried client request to its existing durable turn."""
        row = self._fetchone(
            f"""
            SELECT * FROM assistant_messages
            WHERE conversation_id = {self.param} AND request_id = {self.param} AND role = {self.param}
            """,
            (conversation_id, request_id, role),
        )
        return self._row_to_assistant_message(row) if row is not None else None

    def list_assistant_messages(self, conversation_id: str, *, limit: int = 200) -> list[AssistantMessage]:
        """Return conversation turns in chronological order."""
        rows = self._fetchall(
            f"""
            SELECT * FROM assistant_messages WHERE conversation_id = {self.param}
            ORDER BY created_at DESC LIMIT {self.param}
            """,
            (conversation_id, limit),
        )
        return [self._row_to_assistant_message(row) for row in reversed(rows)]

    def update_assistant_message(
        self,
        message_id: str,
        *,
        content: str | None = None,
        status: str | None = None,
        citations: list[dict[str, Any]] | None = None,
        proposed_actions: list[dict[str, Any]] | None = None,
        retrieval_trace: dict[str, Any] | None = None,
        error: str | None | object = ...,
    ) -> AssistantMessage:
        """Advance a background assistant message and persist its evidence trace."""
        updates: list[str] = []
        params: list[Any] = []
        for column, value in (("content", content), ("status", status)):
            if value is not None:
                updates.append(f"{column} = {self.param}")
                params.append(value)
        for column, value in (("citations", citations), ("proposed_actions", proposed_actions), ("retrieval_trace", retrieval_trace)):
            if value is not None:
                updates.append(f"{column} = {self.param}")
                params.append(self._dump_json(value))
        if error is not ...:
            updates.append(f"error = {self.param}")
            params.append(error)
        updates.append(f"updated_at = {self.param}")
        params.extend([utc_now(), message_id])
        self._execute(f"UPDATE assistant_messages SET {', '.join(updates)} WHERE id = {self.param}", tuple(params))
        message = self.get_assistant_message(message_id)
        self._execute(
            f"UPDATE assistant_conversations SET updated_at = {self.param} WHERE id = {self.param}",
            (utc_now(), message.conversation_id),
        )
        return message

    def create_assistant_run(
        self,
        assistant_message_id: str,
        runtime_kind: str,
        model_profile_id: str,
        execution_intent: str,
        effective_parallelism: int,
    ) -> dict[str, Any]:
        """Create the durable execution record associated with one assistant reply."""
        run_id = str(uuid.uuid4())
        self._execute(
            f"""
            INSERT INTO assistant_runs (
                id, assistant_message_id, runtime_kind, model_profile_id, execution_intent, effective_parallelism,
                status, planned_tools, specialist_plan, error, started_at, completed_at
            ) VALUES ({', '.join([self.param] * 12)})
            """,
            (
                run_id, assistant_message_id, runtime_kind, model_profile_id, execution_intent, effective_parallelism,
                "queued", self._dump_json([]), self._dump_json([]), None, None, None,
            ),
        )
        return self.get_assistant_run(run_id)

    def get_assistant_run(self, run_id: str) -> dict[str, Any]:
        """Return one assistant execution record as a JSON-ready dictionary."""
        row = self._fetchone(f"SELECT * FROM assistant_runs WHERE id = {self.param}", (run_id,))
        if row is None:
            raise ValueError(f"Assistant run not found: {run_id}")
        return self._assistant_run_dict(row)

    def get_assistant_run_for_message(self, message_id: str) -> dict[str, Any] | None:
        """Find the execution record for an assistant placeholder message."""
        row = self._fetchone(
            f"SELECT * FROM assistant_runs WHERE assistant_message_id = {self.param}",
            (message_id,),
        )
        return self._assistant_run_dict(row) if row is not None else None

    def update_assistant_run(self, run_id: str, **values: Any) -> dict[str, Any]:
        """Persist planner, specialist, lifecycle, or failure details for a background run."""
        allowed = {
            "status", "planned_tools", "specialist_plan", "error", "started_at", "completed_at",
            "execution_intent", "effective_parallelism",
        }
        updates: list[str] = []
        params: list[Any] = []
        for key, value in values.items():
            if key not in allowed:
                continue
            updates.append(f"{key} = {self.param}")
            params.append(self._dump_json(value) if key in {"planned_tools", "specialist_plan"} else value)
        if updates:
            params.append(run_id)
            self._execute(f"UPDATE assistant_runs SET {', '.join(updates)} WHERE id = {self.param}", tuple(params))
        return self.get_assistant_run(run_id)

    def recover_interrupted_assistant_runs(self) -> int:
        """Fail orphaned queued/running turns on process startup so the UI can offer Retry."""
        rows = self._fetchall(
            """
            SELECT r.id AS run_id, r.assistant_message_id AS message_id
            FROM assistant_runs r
            JOIN assistant_messages m ON m.id = r.assistant_message_id
            WHERE r.status IN ('queued', 'running') OR m.status IN ('queued', 'running')
            """
        )
        error = "Assistant execution was interrupted by an application restart. Retry this response."
        completed_at = utc_now()
        for row in rows:
            run_id = str(self._row_value(row, "run_id"))
            message_id = str(self._row_value(row, "message_id"))
            self.update_assistant_message(message_id, status="failed", error=error)
            self.update_assistant_run(run_id, status="failed", error=error, completed_at=completed_at)
        return len(rows)

    def create_assistant_specialist_run(
        self,
        run_id: str,
        specialist_type: str,
        input_payload: dict[str, Any],
    ) -> str:
        """Create one internal specialist record without exposing it as a user conversation."""
        specialist_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO assistant_specialist_runs (
                id, assistant_run_id, specialist_type, status, input_payload,
                output_payload, error, created_at, updated_at
            ) VALUES ({', '.join([self.param] * 9)})
            """,
            (specialist_id, run_id, specialist_type, "queued", self._dump_json(input_payload), self._dump_json({}), None, now, now),
        )
        return specialist_id

    def update_assistant_specialist_run(
        self,
        specialist_id: str,
        *,
        status: str,
        output_payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Complete or fail a specialist report while retaining its input trace."""
        self._execute(
            f"""
            UPDATE assistant_specialist_runs
            SET status = {self.param}, output_payload = {self.param}, error = {self.param}, updated_at = {self.param}
            WHERE id = {self.param}
            """,
            (status, self._dump_json(output_payload or {}), error, utc_now(), specialist_id),
        )

    def upsert_assistant_document(
        self,
        *,
        project_id: str,
        layer_scope: str,
        source_type: str,
        source_id: str,
        title: str,
        content: str,
        content_hash: str,
        metadata: dict[str, Any],
        embedding_model: str,
        embedding: list[float],
    ) -> None:
        """Insert or refresh one retrieval document only when its source content changes."""
        existing = self._fetchone(
            f"""
            SELECT id, content_hash FROM assistant_documents
            WHERE project_id = {self.param} AND source_type = {self.param} AND source_id = {self.param}
            """,
            (project_id, source_type, source_id),
        )
        if existing is not None and str(self._row_value(existing, "content_hash")) == content_hash:
            return
        document_id = str(self._row_value(existing, "id")) if existing is not None else str(uuid.uuid4())
        vector_value: Any = Vector(embedding) if self.is_postgres and embedding else self._dump_json(embedding)
        self._execute(
            f"""
            INSERT INTO assistant_documents (
                id, project_id, layer_scope, source_type, source_id, title, content,
                content_hash, metadata, embedding_model, embedding, updated_at
            ) VALUES ({', '.join([self.param] * 12)})
            ON CONFLICT (project_id, source_type, source_id) DO UPDATE SET
                layer_scope = EXCLUDED.layer_scope, title = EXCLUDED.title, content = EXCLUDED.content,
                content_hash = EXCLUDED.content_hash, metadata = EXCLUDED.metadata,
                embedding_model = EXCLUDED.embedding_model, embedding = EXCLUDED.embedding, updated_at = EXCLUDED.updated_at
            """,
            (
                document_id, project_id, layer_scope, source_type, source_id, title, content,
                content_hash, self._dump_json(metadata), embedding_model, vector_value, utc_now(),
            ),
        )

    def delete_stale_assistant_documents(self, project_id: str, active_keys: set[tuple[str, str]]) -> None:
        """Remove index rows whose canonical project source no longer exists."""
        rows = self._fetchall(
            f"SELECT source_type, source_id FROM assistant_documents WHERE project_id = {self.param}",
            (project_id,),
        )
        stale = [
            (str(self._row_value(row, "source_type")), str(self._row_value(row, "source_id")))
            for row in rows
            if (str(self._row_value(row, "source_type")), str(self._row_value(row, "source_id"))) not in active_keys
        ]
        for source_type, source_id in stale:
            self._execute(
                f"""
                DELETE FROM assistant_documents
                WHERE project_id = {self.param} AND source_type = {self.param} AND source_id = {self.param}
                """,
                (project_id, source_type, source_id),
            )

    def list_assistant_documents(self, project_id: str, *, layer_scope: str | None = None) -> list[dict[str, Any]]:
        """Return indexed documents for deterministic tools and SQLite fallback retrieval."""
        query = f"SELECT * FROM assistant_documents WHERE project_id = {self.param}"
        params: list[Any] = [project_id]
        if layer_scope and layer_scope != "overall":
            query += f" AND layer_scope = {self.param}"
            params.append(layer_scope)
        query += " ORDER BY updated_at DESC"
        return [self._assistant_document_dict(row) for row in self._fetchall(query, tuple(params))]

    def search_assistant_documents(
        self,
        *,
        project_id: str,
        layer_scope: str,
        query_text: str,
        embedding_model: str,
        embedding: list[float],
        limit: int = 16,
    ) -> list[dict[str, Any]]:
        """Use pgvector when available and deterministic lexical scoring otherwise."""
        if self.is_postgres and embedding:
            scope_clause = "" if layer_scope == "overall" else f" AND layer_scope = {self.param}"
            params: list[Any] = [Vector(embedding), project_id, embedding_model]
            if scope_clause:
                params.append(layer_scope)
            params.extend([Vector(embedding), limit])
            rows = self._fetchall(
                f"""
                SELECT *, 1 - (embedding <=> {self.param}) AS score
                FROM assistant_documents
                WHERE project_id = {self.param} AND embedding_model = {self.param}
                  AND embedding IS NOT NULL {scope_clause}
                ORDER BY embedding <=> {self.param} ASC LIMIT {self.param}
                """,
                tuple(params),
            )
            return [self._assistant_document_dict(row, score=float(self._row_value(row, "score"))) for row in rows]
        terms = {term for term in query_text.casefold().split() if len(term) > 2}
        documents = self.list_assistant_documents(project_id, layer_scope=layer_scope)
        for document in documents:
            haystack = f"{document['title']} {document['content']}".casefold()
            document["score"] = sum(1 for term in terms if term in haystack) / max(1, len(terms))
        return sorted(documents, key=lambda item: item["score"], reverse=True)[:limit]

    def create_assistant_action_proposal(
        self,
        *,
        project_id: str,
        conversation_id: str,
        message_id: str,
        action_type: str,
        label: str,
        payload: dict[str, Any],
        expected_state: dict[str, Any],
    ) -> AssistantActionProposal:
        """Persist a mutation preview that remains inert until the user confirms it."""
        proposal_id = str(uuid.uuid4())
        now = utc_now()
        self._execute(
            f"""
            INSERT INTO assistant_action_proposals (
                id, project_id, conversation_id, message_id, action_type, label,
                payload, expected_state, status, result, created_at, updated_at
            ) VALUES ({', '.join([self.param] * 12)})
            """,
            (
                proposal_id, project_id, conversation_id, message_id, action_type, label,
                self._dump_json(payload), self._dump_json(expected_state), "pending", self._dump_json({}), now, now,
            ),
        )
        return self.get_assistant_action_proposal(proposal_id)

    def get_assistant_action_proposal(self, proposal_id: str) -> AssistantActionProposal:
        """Return one action proposal for confirmation and stale-state validation."""
        row = self._fetchone(f"SELECT * FROM assistant_action_proposals WHERE id = {self.param}", (proposal_id,))
        if row is None:
            raise ValueError(f"Assistant action proposal not found: {proposal_id}")
        return self._row_to_assistant_action(row)

    def list_assistant_action_proposals(self, conversation_id: str) -> list[AssistantActionProposal]:
        """Return confirmation cards for a conversation in creation order."""
        rows = self._fetchall(
            f"SELECT * FROM assistant_action_proposals WHERE conversation_id = {self.param} ORDER BY created_at ASC",
            (conversation_id,),
        )
        return [self._row_to_assistant_action(row) for row in rows]

    def update_assistant_action_proposal(
        self,
        proposal_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> AssistantActionProposal:
        """Record a confirmed, rejected, stale, or failed proposal outcome."""
        self._execute(
            f"""
            UPDATE assistant_action_proposals
            SET status = {self.param}, result = {self.param}, updated_at = {self.param}
            WHERE id = {self.param}
            """,
            (status, self._dump_json(result or {}), utc_now(), proposal_id),
        )
        return self.get_assistant_action_proposal(proposal_id)

    def _row_to_assistant_conversation(self, row: Any) -> AssistantConversation:
        """Map a database row into the public conversation model."""
        return AssistantConversation(
            id=row["id"], project_id=row["project_id"], title=row["title"], home_scope=row["home_scope"],
            compacted_summary=row["compacted_summary"], summary_state=self._load_json(row["summary_state"]),
            archived=bool(row["archived"]), created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_assistant_message(self, row: Any) -> AssistantMessage:
        """Map a database row into a durable assistant turn."""
        return AssistantMessage(
            id=row["id"], conversation_id=row["conversation_id"], project_id=row["project_id"],
            role=row["role"], content=row["content"], status=row["status"], request_id=row["request_id"],
            active_scope=row["active_scope"], focus=self._load_json(row["focus"]),
            reference_conversation_ids=self._load_json_list(row["reference_conversation_ids"]),
            execution_intent_override=row["execution_intent_override"],
            thinking_enabled=bool(row["thinking_enabled"]), deep_mode=bool(row["deep_mode"]),
            citations=self._load_json_list(row["citations"]), proposed_actions=self._load_json_list(row["proposed_actions"]),
            retrieval_trace=self._load_json(row["retrieval_trace"]), error=row["error"],
            created_at=datetime.fromisoformat(str(row["created_at"])), updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _row_to_assistant_action(self, row: Any) -> AssistantActionProposal:
        """Map a persisted confirmation card into its public model."""
        return AssistantActionProposal(
            id=row["id"], project_id=row["project_id"], conversation_id=row["conversation_id"],
            message_id=row["message_id"], action_type=row["action_type"], label=row["label"],
            payload=self._load_json(row["payload"]), expected_state=self._load_json(row["expected_state"]),
            status=row["status"], result=self._load_json(row["result"]),
            created_at=datetime.fromisoformat(str(row["created_at"])), updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _assistant_run_dict(self, row: Any) -> dict[str, Any]:
        """Convert an internal run row into a JSON-ready status object."""
        return {
            "id": row["id"], "assistant_message_id": row["assistant_message_id"],
            "runtime_kind": row["runtime_kind"], "model_profile_id": row["model_profile_id"],
            "execution_intent": row["execution_intent"],
            "effective_parallelism": int(row["effective_parallelism"]),
            "status": row["status"], "planned_tools": self._load_json_list(row["planned_tools"]),
            "specialist_plan": self._load_json_list(row["specialist_plan"]), "error": row["error"],
            "started_at": str(row["started_at"]) if row["started_at"] else None,
            "completed_at": str(row["completed_at"]) if row["completed_at"] else None,
        }

    def _assistant_document_dict(self, row: Any, *, score: float = 0.0) -> dict[str, Any]:
        """Return one indexed source without exposing raw vector storage."""
        return {
            "id": row["id"], "project_id": row["project_id"], "layer_scope": row["layer_scope"],
            "source_type": row["source_type"], "source_id": row["source_id"], "title": row["title"],
            "content": row["content"], "content_hash": row["content_hash"],
            "embedding_model": row["embedding_model"], "metadata": self._load_json(row["metadata"]), "score": score,
        }
