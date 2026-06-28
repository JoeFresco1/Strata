from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from strata.assistant_index import AssistantIndexService
from strata.db import Database
from strata.execution_policy import (
    effective_execution_intent,
    effective_parallelism,
    resolve_llm_profile,
    resolved_runtime_request,
    runtime_kind as policy_runtime_kind,
)
from strata.llm import LLMError, LlamaCppClient
from strata.models import AssistantActionProposal, AssistantConversation, AssistantMessage
from strata.prompts import build_system_prompt, render_prompt
from strata.server_manager import LlamaServerManager
from strata.telemetry import model_call_context


ALLOWED_TOOLS = {
    "project_summary",
    "search_documents",
    "filter_entities",
    "graph_neighbors",
    "coverage_gaps",
    "research_evidence",
}
SPECIALIST_TYPES = {
    "coverage_reviewer",
    "graph_overlap_analyst",
    "research_evidence_analyst",
    "architecture_critic",
    "decision_analyst",
    "action_validator",
}
ALLOWED_ACTIONS = {
    "update_brief",
    "update_node",
    "layer2_review",
    "update_layer2_feature",
    "run_layer1_research",
    "run_layer2_research",
    "generate_layer1",
    "generate_layer2",
    "generate_layer3",
}


class AssistantService:
    """Coordinate one layer-aware project assistant across durable conversations and bounded tools."""

    def __init__(
        self,
        db: Database,
        llm_client: LlamaCppClient,
        index_service: AssistantIndexService,
        server_manager: LlamaServerManager | None = None,
    ):
        self.db = db
        self.llm_client = llm_client
        self.index_service = index_service
        self.server_manager = server_manager

    def create_conversation(self, project_id: str, title: str, home_scope: str) -> AssistantConversation:
        """Create one conversation after validating the owning project."""
        self.db.get_project(project_id)
        return self.db.create_assistant_conversation(project_id, title, home_scope)

    def submit_message(
        self,
        *,
        project_id: str,
        conversation_id: str,
        content: str,
        request_id: str,
        active_scope: str,
        focus: dict[str, Any],
        reference_conversation_ids: list[str],
        execution_intent_override: str | None,
        thinking_enabled: bool,
        deep_mode: bool,
    ) -> dict[str, Any]:
        """Persist an idempotent user turn, assistant placeholder, and background execution record."""
        conversation = self._project_conversation(project_id, conversation_id)
        clean = content.strip()
        if not clean:
            raise ValueError("Assistant messages cannot be blank.")
        profile = self._profile(
            project_id,
            "assistant_orchestration",
            override=execution_intent_override,
            thinking_enabled=thinking_enabled,
        )
        references = self._validated_references(project_id, conversation.id, reference_conversation_ids)
        existing = self.db.get_assistant_message_by_request(conversation.id, request_id, "assistant")
        if existing is not None:
            return {"user_message": self.db.get_assistant_message_by_request(conversation.id, request_id, "user"), "assistant_message": existing, "run": self.db.get_assistant_run_for_message(existing.id)}
        user_message = self.db.create_assistant_message(
            conversation_id=conversation.id,
            project_id=project_id,
            role="user",
            content=clean,
            request_id=request_id,
            active_scope=active_scope,
            focus=focus,
            reference_conversation_ids=references,
            execution_intent_override=execution_intent_override,
            thinking_enabled=thinking_enabled,
            deep_mode=deep_mode,
        )
        assistant_message = self.db.create_assistant_message(
            conversation_id=conversation.id,
            project_id=project_id,
            role="assistant",
            status="queued",
            request_id=request_id,
            active_scope=active_scope,
            focus=focus,
            reference_conversation_ids=references,
            execution_intent_override=execution_intent_override,
            thinking_enabled=thinking_enabled,
            deep_mode=deep_mode,
        )
        settings_payload = self._settings_payload(project_id)
        resolved_intent = effective_execution_intent(settings_payload, execution_intent_override)
        run = self.db.create_assistant_run(
            assistant_message.id,
            policy_runtime_kind(profile),
            str(profile["id"]),
            resolved_intent,
            effective_parallelism(settings_payload, profile),
        )
        return {"user_message": user_message, "assistant_message": assistant_message, "run": run}

    def run_message(self, assistant_message_id: str) -> None:
        """Execute one queued assistant turn and retain a complete failure trace on any error."""
        message = self.db.get_assistant_message(assistant_message_id)
        run = self.db.get_assistant_run_for_message(message.id)
        if run is None:
            raise ValueError(f"Assistant run missing for message: {message.id}")
        if message.status == "completed":
            return
        now = datetime.now(timezone.utc).isoformat()
        self.db.update_assistant_message(message.id, status="running", error=None)
        self.db.update_assistant_run(run["id"], status="running", started_at=now, error=None)
        try:
            self._execute_message(message, run)
        except Exception as exc:  # noqa: BLE001 - durable state must capture model, retrieval, and provider failures.
            self.db.update_assistant_message(message.id, status="failed", error=str(exc))
            self.db.update_assistant_run(
                run["id"],
                status="failed",
                error=str(exc),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

    def retry_message(self, message_id: str) -> dict[str, Any]:
        """Reset a failed assistant turn and its existing run for another background attempt."""
        message = self.db.get_assistant_message(message_id)
        if message.role != "assistant" or message.status not in {"failed", "completed"}:
            raise ValueError("Only completed or failed assistant messages can be retried.")
        run = self.db.get_assistant_run_for_message(message.id)
        if run is None:
            raise ValueError("Assistant run is missing.")
        self.db.update_assistant_message(message.id, content="", status="queued", citations=[], proposed_actions=[], retrieval_trace={}, error=None)
        self.db.update_assistant_run(run["id"], status="queued", planned_tools=[], specialist_plan=[], error=None, started_at=None, completed_at=None)
        return {"assistant_message": self.db.get_assistant_message(message.id), "run": self.db.get_assistant_run(run["id"])}

    def _execute_message(self, message: AssistantMessage, run: dict[str, Any]) -> None:
        """Refresh retrieval, compact history, plan tools, run specialists, and synthesize one answer."""
        user_message = self.db.get_assistant_message_by_request(message.conversation_id, message.request_id or "", "user")
        if user_message is None:
            raise ValueError("Assistant user turn is missing.")
        index_stats = self.index_service.refresh_project(message.project_id)
        profile = self._profile(
            message.project_id,
            "assistant_orchestration",
            override=message.execution_intent_override,
            thinking_enabled=message.thinking_enabled,
        )
        self._compact_if_needed(message.conversation_id, profile)
        context = self._conversation_context(message)
        plan = self._plan(message, user_message.content, context, profile)
        tools = self._validated_tools(plan.get("tools", []), user_message.content, message.active_scope, message.focus)
        self.db.update_assistant_run(run["id"], planned_tools=tools)
        tool_results = [self.index_service.execute_tool(message.project_id, tool, message.active_scope, user_message.content) for tool in tools]
        specialist_plan = self._specialist_plan(plan, message, profile, user_message.content)
        self.db.update_assistant_run(run["id"], specialist_plan=specialist_plan)
        specialist_reports = self._run_specialists(run["id"], message, user_message.content, tool_results, specialist_plan, profile)
        synthesis = self._synthesize(message, user_message.content, context, tool_results, specialist_reports)
        citations = self._validated_citations(synthesis.get("citations", []), tool_results)
        proposals = self._persist_action_proposals(message, synthesis.get("proposed_actions", []))
        trace = {
            "index": index_stats,
            "scope": message.active_scope,
            "focus": message.focus,
            "tools": [{"name": item["tool"], "result_count": self._result_count(item["result"])} for item in tool_results],
            "specialists": [item["specialist_type"] for item in specialist_reports],
            "referenced_conversations": message.reference_conversation_ids,
        }
        self.db.update_assistant_message(
            message.id,
            content=str(synthesis.get("answer", "")).strip() or "I could not produce a grounded answer from the available project data.",
            status="completed",
            citations=citations,
            proposed_actions=[proposal.model_dump(mode="json") for proposal in proposals],
            retrieval_trace=trace,
            error=None,
        )
        self.db.update_assistant_run(run["id"], status="completed", completed_at=datetime.now(timezone.utc).isoformat())

    def _plan(
        self,
        message: AssistantMessage,
        question: str,
        context: dict[str, Any],
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        """Ask the orchestrator for a bounded JSON tool and specialist plan."""
        prompt = render_prompt(
            "assistant_query_planner",
            {
                "active_scope": message.active_scope,
                "focus": json.dumps(message.focus, ensure_ascii=True),
                "question": question,
                "conversation_summary": context["summary"],
                "available_tools": ", ".join(sorted(ALLOWED_TOOLS)),
                "available_specialists": ", ".join(sorted(SPECIALIST_TYPES)),
                "deep_mode": str(message.deep_mode).lower(),
            },
            prompt_catalog=self._prompt_catalog(message.project_id),
        )
        try:
            response = self.llm_client.generate_json(
                system_prompt=build_system_prompt(prompt_catalog=self._prompt_catalog(message.project_id)),
                user_prompt=prompt,
                base_url=self._base_url(profile),
                model_name=self._model_name(profile),
                temperature=0.1,
                max_tokens=min(1200, int(profile.get("max_output_tokens", 1800))),
                telemetry=model_call_context(
                    project_id=message.project_id,
                    layer="assistant",
                    workflow="assistant_plan",
                    runtime_profile=profile,
                    prompt_key="assistant_query_planner",
                ),
            )
            return response.parsed_json
        except LLMError:
            return {"tools": [{"name": "project_summary", "arguments": {}}, {"name": "search_documents", "arguments": {"query": question, "scope": message.active_scope}}], "specialists": []}

    def _synthesize(
        self,
        message: AssistantMessage,
        question: str,
        context: dict[str, Any],
        tool_results: list[dict[str, Any]],
        specialist_reports: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Produce a cited answer and inert action previews from bounded evidence."""
        profile = self._profile(
            message.project_id,
            "assistant_synthesis",
            override=message.execution_intent_override,
            thinking_enabled=message.thinking_enabled,
        )
        prompt = render_prompt(
            "assistant_synthesis",
            {
                "active_scope": message.active_scope,
                "focus": json.dumps(message.focus, ensure_ascii=True),
                "question": question,
                "conversation_context": json.dumps(context, ensure_ascii=True),
                "tool_results": json.dumps(tool_results, ensure_ascii=True, default=str)[:48000],
                "specialist_reports": json.dumps(specialist_reports, ensure_ascii=True, default=str)[:24000],
                "allowed_actions": ", ".join(sorted(ALLOWED_ACTIONS)),
            },
            prompt_catalog=self._prompt_catalog(message.project_id),
        )
        response = self.llm_client.generate_json(
            system_prompt=build_system_prompt(prompt_catalog=self._prompt_catalog(message.project_id)),
            user_prompt=prompt,
            base_url=self._base_url(profile),
            model_name=self._model_name(profile),
            temperature=0.2,
            max_tokens=int(profile.get("max_output_tokens", 1800)),
            telemetry=model_call_context(
                project_id=message.project_id,
                layer="assistant",
                workflow="assistant_synthesis",
                runtime_profile=profile,
                prompt_key="assistant_synthesis",
            ),
        )
        return response.parsed_json

    def _run_specialists(
        self,
        run_id: str,
        message: AssistantMessage,
        question: str,
        tool_results: list[dict[str, Any]],
        specialist_plan: list[str],
        orchestration_profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Run specialists sequentially for managed local models and bounded-parallel for API profiles."""
        if not specialist_plan:
            return []
        profile = self._profile(
            message.project_id,
            "assistant_specialists",
            override=message.execution_intent_override,
            thinking_enabled=message.thinking_enabled,
        )

        def execute(specialist_type: str) -> dict[str, Any]:
            specialist_id = self.db.create_assistant_specialist_run(run_id, specialist_type, {"question": question, "scope": message.active_scope})
            try:
                prompt = render_prompt(
                    "assistant_specialist",
                    {
                        "specialist_type": specialist_type,
                        "active_scope": message.active_scope,
                        "question": question,
                        "evidence": json.dumps(tool_results, ensure_ascii=True, default=str)[:32000],
                    },
                    prompt_catalog=self._prompt_catalog(message.project_id),
                )
                response = self.llm_client.generate_json(
                    system_prompt=build_system_prompt(prompt_catalog=self._prompt_catalog(message.project_id)),
                    user_prompt=prompt,
                    base_url=self._base_url(profile),
                    model_name=self._model_name(profile),
                    temperature=0.15,
                    max_tokens=min(1400, int(profile.get("max_output_tokens", 1800))),
                    telemetry=model_call_context(
                        project_id=message.project_id,
                        layer="assistant",
                        workflow="assistant_specialist",
                        runtime_profile=profile,
                        run_id=run_id,
                        prompt_key="assistant_specialist",
                        metadata={"specialist_type": specialist_type},
                    ),
                )
                output = {"specialist_type": specialist_type, **response.parsed_json}
                self.db.update_assistant_specialist_run(specialist_id, status="completed", output_payload=output)
                return output
            except Exception as exc:  # noqa: BLE001 - one specialist failure should not discard other reports.
                self.db.update_assistant_specialist_run(specialist_id, status="failed", error=str(exc))
                return {"specialist_type": specialist_type, "error": str(exc)}

        settings_payload = self._settings_payload(message.project_id)
        allowed_parallelism = effective_parallelism(settings_payload, profile)
        is_parallel = policy_runtime_kind(profile) == "remote_api" and bool(profile.get("supports_parallel")) and allowed_parallelism > 1
        if not is_parallel:
            return [execute(specialist) for specialist in specialist_plan]
        workers = min(
            len(specialist_plan),
            int(profile.get("max_parallel_requests", 1)),
            allowed_parallelism,
        )
        reports: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = [executor.submit(execute, specialist) for specialist in specialist_plan]
            for future in as_completed(futures):
                reports.append(future.result())
        return reports

    def _compact_if_needed(self, conversation_id: str, profile: dict[str, Any]) -> None:
        """Compact older turns when they exceed the provider-aware context budget; raw messages remain stored."""
        messages = self.db.list_assistant_messages(conversation_id, limit=500)
        completed = [item for item in messages if item.status == "completed" and item.content]
        if len(completed) <= 10:
            return
        estimated_tokens = sum(max(1, len(item.content) // 4) for item in completed)
        threshold = max(4000, int(profile.get("context_window", 32768) * 0.35))
        conversation = self.db.get_assistant_conversation(conversation_id)
        if estimated_tokens <= threshold:
            return
        compactable = completed[:-8]
        last_compacted_id = str(conversation.summary_state.get("through_message_id", ""))
        if compactable and compactable[-1].id == last_compacted_id:
            return
        transcript = "\n".join(f"{item.role}: {item.content}" for item in compactable)
        summary = self._compact_summary(conversation.project_id, conversation.compacted_summary, transcript)
        state = {
            "version": int(conversation.summary_state.get("version", 0)) + 1,
            "through_message_id": compactable[-1].id,
            "compacted_message_count": len(compactable),
            **summary.get("state", {}),
        }
        self.db.update_assistant_conversation(
            conversation.id,
            compacted_summary=str(summary.get("summary", "")).strip(),
            summary_state=state,
        )

    def _compact_summary(self, project_id: str, previous_summary: str, transcript: str) -> dict[str, Any]:
        """Produce a structured rolling summary while preserving decisions and unresolved work."""
        profile = self._profile(project_id, "assistant_compaction", thinking_enabled=False)
        prompt = render_prompt(
            "assistant_compaction",
            {"previous_summary": previous_summary, "transcript": transcript[-48000:]},
            prompt_catalog=self._prompt_catalog(project_id),
        )
        try:
            return self.llm_client.generate_json(
                system_prompt=build_system_prompt(prompt_catalog=self._prompt_catalog(project_id)),
                user_prompt=prompt,
                base_url=self._base_url(profile),
                model_name=self._model_name(profile),
                temperature=0.1,
                max_tokens=min(1400, int(profile.get("max_output_tokens", 1800))),
                telemetry=model_call_context(
                    project_id=project_id,
                    layer="assistant",
                    workflow="assistant_compaction",
                    runtime_profile=profile,
                    prompt_key="assistant_compaction",
                ),
            ).parsed_json
        except LLMError:
            return {"summary": (previous_summary + "\n" + transcript[-8000:]).strip(), "state": {}}

    def _conversation_context(self, message: AssistantMessage) -> dict[str, Any]:
        """Assemble recent turns, compacted memory, selected thread references, and Layer 0 planning context."""
        conversation = self.db.get_assistant_conversation(message.conversation_id)
        recent = [
            {"role": item.role, "content": item.content, "scope": item.active_scope}
            for item in self.db.list_assistant_messages(conversation.id, limit=10)
            if item.status == "completed" and item.content
        ]
        references = []
        for reference_id in message.reference_conversation_ids:
            reference = self._project_conversation(message.project_id, reference_id)
            recent_reference_turns = [
                {"role": item.role, "content": item.content, "scope": item.active_scope}
                for item in self.db.list_assistant_messages(reference.id, limit=6)
                if item.status == "completed" and item.content
            ]
            references.append({
                "id": reference.id,
                "title": reference.title,
                "summary": reference.compacted_summary,
                "recent": recent_reference_turns,
            })
        return {"summary": conversation.compacted_summary, "summary_state": conversation.summary_state, "recent": recent, "references": references}

    def _validated_tools(
        self,
        raw_tools: Any,
        question: str,
        active_scope: str,
        focus: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Filter planner output through the fixed tool registry and enforce a small call budget."""
        tools: list[dict[str, Any]] = []
        for item in raw_tools if isinstance(raw_tools, list) else []:
            if not isinstance(item, dict) or str(item.get("name")) not in ALLOWED_TOOLS:
                continue
            tools.append({"name": str(item["name"]), "arguments": item.get("arguments", {}) if isinstance(item.get("arguments"), dict) else {}})
            if len(tools) >= 6:
                break
        if not any(item["name"] == "project_summary" for item in tools):
            tools.insert(0, {"name": "project_summary", "arguments": {"scope": active_scope}})
        if not any(item["name"] == "search_documents" for item in tools):
            tools.append({"name": "search_documents", "arguments": {"query": question, "scope": active_scope, "limit": 16}})
        focused_id = str((focus or {}).get("entity_id", "")).strip()
        focused_type = str((focus or {}).get("entity_type", "")).strip()
        if focused_id:
            tools.insert(0, {
                "name": "filter_entities",
                "arguments": {
                    "scope": active_scope,
                    "source_id": focused_id,
                    "source_type": "layer2_feature" if focused_type == "feature" else focused_type,
                    "limit": 8,
                },
            })
            if focused_type == "feature":
                tools.insert(1, {"name": "graph_neighbors", "arguments": {"feature_ids": [focused_id]}})
        return tools[:8]

    def _specialist_plan(
        self,
        plan: dict[str, Any],
        message: AssistantMessage,
        profile: dict[str, Any],
        question: str,
    ) -> list[str]:
        """Bound automatic and Deep-mode specialists according to the active provider profile."""
        requested = [str(item) for item in plan.get("specialists", []) if str(item) in SPECIALIST_TYPES]
        if not requested and message.deep_mode:
            requested = ["architecture_critic", "decision_analyst"]
            if message.active_scope == "layer2":
                requested.insert(0, "graph_overlap_analyst")
        automatic_terms = {"conflict", "overlap", "compare", "competitor", "decision", "tradeoff", "coverage"}
        if not requested and any(term in question.casefold() for term in automatic_terms):
            requested = ["decision_analyst"]
        maximum = int(profile.get("max_specialists", 2))
        return list(dict.fromkeys(requested))[:maximum]

    def _validated_citations(self, raw: Any, tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep only citations that resolve to records actually returned by retrieval tools."""
        available: dict[str, dict[str, Any]] = {}
        for tool in tool_results:
            result = tool.get("result")
            if not isinstance(result, list):
                continue
            for item in result:
                if not isinstance(item, dict):
                    continue
                source_id = str(item.get("source_id") or item.get("id") or item.get("feature_id") or "")
                if source_id:
                    available[source_id] = item
        citations: list[dict[str, Any]] = []
        for item in raw if isinstance(raw, list) else []:
            source_id = str(item.get("source_id", "")) if isinstance(item, dict) else str(item)
            source = available.get(source_id)
            if not source:
                continue
            citations.append({
                "source_id": source_id,
                "source_type": source.get("source_type", "project_record"),
                "layer": source.get("layer_scope", "overall"),
                "label": source.get("title") or source.get("canonical_name") or source.get("family_name") or source_id,
                "metadata": source.get("metadata", {}),
            })
        return citations[:20]

    def _persist_action_proposals(self, message: AssistantMessage, raw: Any) -> list[AssistantActionProposal]:
        """Validate action vocabulary and persist inert confirmation cards with expected state snapshots."""
        proposals: list[AssistantActionProposal] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            action_type = str(item.get("action_type", ""))
            payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
            if action_type not in ALLOWED_ACTIONS or not payload:
                continue
            try:
                expected = self._expected_state(message.project_id, action_type, payload)
            except ValueError:
                continue
            proposals.append(self.db.create_assistant_action_proposal(
                project_id=message.project_id,
                conversation_id=message.conversation_id,
                message_id=message.id,
                action_type=action_type,
                label=str(item.get("label", action_type.replace("_", " "))).strip(),
                payload=payload,
                expected_state=expected,
            ))
            if len(proposals) >= 6:
                break
        return proposals

    def _expected_state(self, project_id: str, action_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Capture the minimum canonical state required to reject stale confirmations later."""
        if action_type == "update_node":
            node = self.db.get_node(str(payload.get("node_id", "")))
            if node.project_id != project_id:
                raise ValueError("Node belongs to another project.")
            return {"node_id": node.id, "status": node.status, "title": node.title}
        if action_type in {"layer2_review", "update_layer2_feature"}:
            feature = self.db.get_layer2_feature(str(payload.get("feature_id", "")))
            if feature.project_id != project_id:
                raise ValueError("Feature belongs to another project.")
            return {"feature_id": feature.id, "status": feature.status, "updated_at": feature.updated_at.isoformat()}
        if action_type == "update_brief":
            brief = self.db.get_project_brief(project_id)
            return {"status": brief.status if brief else "missing", "updated_at": brief.updated_at.isoformat() if brief else None}
        self.db.get_project(project_id)
        return {"project_id": project_id}

    def action_is_stale(self, proposal: AssistantActionProposal) -> bool:
        """Recompute expected state immediately before execution to prevent stale chat mutations."""
        try:
            return self._expected_state(proposal.project_id, proposal.action_type, proposal.payload) != proposal.expected_state
        except ValueError:
            return True

    def _profile(
        self,
        project_id: str,
        assignment: str,
        *,
        override: str | None = None,
        thinking_enabled: bool = False,
    ) -> dict[str, Any]:
        """Resolve one project model profile and its provider execution limits."""
        profile = resolve_llm_profile(self._settings_payload(project_id), assignment, override=override)
        if profile is None:
            raise ValueError(f"Assistant model assignment is invalid: {assignment}")
        return resolved_runtime_request(
            profile,
            llm_client=self.llm_client,
            server_manager=self.server_manager,
            thinking_enabled=thinking_enabled,
        )

    @staticmethod
    def _base_url(profile: dict[str, Any]) -> str | None:
        return str(profile.get("base_url", "")).strip() or None

    @staticmethod
    def _model_name(profile: dict[str, Any]) -> str | None:
        return str(profile.get("model_name", "")).strip() or str(profile.get("id", "")).strip() or None

    def _prompt_catalog(self, project_id: str) -> dict[str, str]:
        """Use the editable prompt snapshot attached to the active project."""
        settings = self.db.get_project_model_settings(project_id)
        return settings.prompt_catalog if settings and settings.prompt_catalog else {}

    def _settings_payload(self, project_id: str) -> dict[str, Any]:
        """Return the normalized project settings payload required by execution routing."""
        settings = self.db.get_project_model_settings(project_id)
        if settings is None:
            raise ValueError("Project model settings are missing.")
        return settings.model_dump(mode="json")

    def _project_conversation(self, project_id: str, conversation_id: str) -> AssistantConversation:
        """Validate conversation ownership before reading context or accepting mutations."""
        conversation = self.db.get_assistant_conversation(conversation_id)
        if conversation.project_id != project_id:
            raise ValueError("Assistant conversation belongs to another project.")
        return conversation

    def _validated_references(self, project_id: str, current_id: str, reference_ids: list[str]) -> list[str]:
        """Keep selected conversation references project-local and deduplicated."""
        valid: list[str] = []
        for reference_id in dict.fromkeys(reference_ids):
            if reference_id == current_id:
                continue
            self._project_conversation(project_id, reference_id)
            valid.append(reference_id)
        return valid[:12]

    @staticmethod
    def _result_count(result: Any) -> int:
        if isinstance(result, (list, dict)):
            return len(result)
        return 1
