from __future__ import annotations

from pathlib import Path
from typing import Any

from strata.db import Database
from strata.execution_policy import resolve_llm_profile, resolved_runtime_request
from strata.llm import LLMError, LlamaCppClient
from strata.models import ProjectBrief
from strata.provider_onboarding import assert_provider_ready
from strata.prompts import (
    build_layer0_brief_extraction_prompt,
    build_layer0_plan_reply_prompt,
    build_system_prompt,
    load_prompt_catalog,
)
from strata.server_manager import LlamaServerManager, ServerManagerError
from strata.telemetry import model_call_context


BRIEF_FIELDS = {
    "product_idea",
    "known_competitors",
    "constraints",
    "target_users",
    "goals",
    "preferred_directions",
    "rejected_directions",
    "notes",
}

LIST_FIELDS = {"known_competitors", "goals", "preferred_directions", "rejected_directions"}
BRIEF_FIELD_ORDER = [
    "product_idea",
    "target_users",
    "constraints",
    "goals",
    "known_competitors",
    "preferred_directions",
    "rejected_directions",
    "notes",
]


class BriefService:
    """Manage Layer 0 draft intake, Plan-mode extraction, and explicit publishing."""

    def __init__(
        self,
        db: Database,
        llm_client: LlamaCppClient,
        server_manager: LlamaServerManager | None = None,
    ):
        self.db = db
        self.llm_client = llm_client
        self.server_manager = server_manager

    def ensure_brief(self, project_id: str) -> ProjectBrief:
        """Create the canonical brief from the project idea when no draft exists yet."""
        existing = self.db.get_project_brief(project_id)
        if existing is not None:
            return existing
        project = self.db.get_project(project_id)
        return self.db.upsert_project_brief(
            project_id=project_id,
            product_idea=project.idea,
            known_competitors=[],
            constraints="",
            target_users="",
            goals=[],
            preferred_directions=[],
            rejected_directions=[],
            notes="",
            status="draft",
        )

    def update_brief(self, project_id: str, updates: dict[str, Any]) -> ProjectBrief:
        """Apply direct Form-mode edits to the canonical Layer 0 brief."""
        current = self.ensure_brief(project_id)
        merged = self._merged_brief_payload(current.model_dump(mode="json"), updates)
        status = current.status if current.status == "draft" else "draft"
        return self.db.upsert_project_brief(project_id=project_id, status=status, **merged)

    def append_plan_turn(
        self,
        project_id: str,
        message: str,
        request_id: str | None = None,
    ) -> tuple[str, ProjectBrief, dict[str, Any]]:
        """Extract structured values from a Plan-mode message and store both the turn and reply."""
        clean_message = message.strip()
        if not clean_message:
            raise ValueError("Plan-mode message cannot be empty.")
        assert_provider_ready(self.db, "Layer 0 planning and extraction")
        current = self.ensure_brief(project_id)
        if request_id:
            existing = self.db.get_brief_conversation_by_request(project_id, request_id, "assistant")
            if existing is not None:
                guidance = existing.extracted_updates.get("plan_guidance", {})
                return existing.content, current, guidance
        conversation = self.db.list_brief_conversation(project_id, limit=12)
        tail = [{"role": turn.role, "content": turn.content} for turn in conversation]
        self.db.append_brief_conversation_turn(
            project_id=project_id,
            role="user",
            content=clean_message,
            request_id=request_id,
        )

        updates = self._extract_updates(current, tail, clean_message)
        brief = self.update_brief(project_id, updates) if updates else current
        guidance = self._plan_guidance(brief, tail, clean_message, updates)
        reply = str(guidance.get("assistant_message", "")).strip() or self._fallback_plan_guidance(brief, updates)["assistant_message"]
        self.db.append_brief_conversation_turn(
            project_id=project_id,
            role="assistant",
            content=reply,
            request_id=request_id,
            extracted_updates={
                "brief_updates": updates,
                "plan_guidance": guidance,
            },
        )
        return reply, brief, guidance

    def publish(self, project_id: str) -> ProjectBrief:
        """Freeze the current draft as the active Layer 0 source of truth."""
        current = self.ensure_brief(project_id)
        payload = current.model_dump(mode="json")
        merged = self._merged_brief_payload(payload, {})
        return self.db.upsert_project_brief(project_id=project_id, status="published", **merged)

    def _extract_updates(self, current: ProjectBrief, tail: list[dict[str, str]], message: str) -> dict[str, Any]:
        """Run the local structured extraction pass and normalize unsafe model output."""
        prompt_catalog = self._prompt_catalog(current.project_id)
        prompt = build_layer0_brief_extraction_prompt(
            current_brief=self._brief_payload(current),
            conversation_tail=tail,
            user_message=message,
            prompt_catalog=prompt_catalog,
        )
        try:
            runtime = self._llm_runtime(current.project_id, "layer0_extraction")
            response = self.llm_client.generate_json(
                system_prompt=build_system_prompt(prompt_catalog=prompt_catalog),
                user_prompt=prompt,
                base_url=runtime["base_url"],
                model_name=runtime["model_name"],
                max_tokens=1200,
                temperature=0.1,
                telemetry=model_call_context(
                    project_id=current.project_id,
                    layer="layer0",
                    workflow="brief_extraction",
                    runtime_profile=runtime,
                    prompt_key="layer0_brief_extraction",
                ),
            )
        except LLMError:
            return {"notes": message}
        raw_updates = response.parsed_json.get("updates", {})
        return self._normalized_updates(raw_updates if isinstance(raw_updates, dict) else {})

    def _plan_guidance(
        self,
        brief: ProjectBrief,
        tail: list[dict[str, str]],
        message: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate structured intake guidance with a deterministic fallback."""
        open_fields = self._open_fields(brief)
        prompt_catalog = self._prompt_catalog(brief.project_id)
        prompt = build_layer0_plan_reply_prompt(
            current_brief=self._brief_payload(brief),
            conversation_tail=tail,
            user_message=message,
            extracted_updates=updates,
            open_fields=open_fields,
            prompt_catalog=prompt_catalog,
        )
        try:
            runtime = self._llm_runtime(brief.project_id, "layer0_plan")
            response = self.llm_client.generate_json(
                system_prompt=build_system_prompt(prompt_catalog=prompt_catalog),
                user_prompt=prompt,
                base_url=runtime["base_url"],
                model_name=runtime["model_name"],
                max_tokens=420,
                temperature=0.3,
                telemetry=model_call_context(
                    project_id=brief.project_id,
                    layer="layer0",
                    workflow="plan_guidance",
                    runtime_profile=runtime,
                    prompt_key="layer0_plan_reply",
                ),
            )
            return self._normalized_plan_guidance(response.parsed_json, brief, updates)
        except LLMError:
            return self._fallback_plan_guidance(brief, updates)

    def _normalized_plan_guidance(self, payload: dict[str, Any], brief: ProjectBrief, updates: dict[str, Any]) -> dict[str, Any]:
        """Coerce model guidance into a safe shape for the frontend conversation UI."""
        fallback = self._fallback_plan_guidance(brief, updates)
        assistant_message = str(payload.get("assistant_message", "")).strip() or fallback["assistant_message"]
        recap = str(payload.get("recap", "")).strip() or fallback["recap"]
        focus_area = str(payload.get("focus_area", "")).strip()
        if focus_area not in BRIEF_FIELDS:
            focus_area = fallback["focus_area"]
        missing_fields = [
            str(item).strip()
            for item in payload.get("missing_fields", [])
            if str(item).strip() in BRIEF_FIELDS
        ] or fallback["missing_fields"]
        if focus_area == "notes":
            preferred_focus = next((field for field in missing_fields if field != "notes"), None)
            if preferred_focus is not None:
                focus_area = preferred_focus
        next_questions = [
            str(item).strip()
            for item in payload.get("next_questions", [])
            if str(item).strip()
        ][:3] or fallback["next_questions"]
        confidence = str(payload.get("confidence", "")).strip().lower()
        if confidence not in {"low", "medium", "high"}:
            confidence = fallback["confidence"]
        return {
            "assistant_message": assistant_message,
            "recap": recap,
            "focus_area": focus_area,
            "missing_fields": missing_fields,
            "next_questions": next_questions,
            "confidence": confidence,
        }

    def _fallback_plan_guidance(self, brief: ProjectBrief, updates: dict[str, Any]) -> dict[str, Any]:
        """Provide stable intake guidance when the local model fails or returns weak structure."""
        open_fields = self._open_fields(brief)
        focus_area = open_fields[0] if open_fields else "notes"
        recap_bits: list[str] = []
        if "product_idea" in updates:
            recap_bits.append("the product direction is clearer")
        if "target_users" in updates:
            recap_bits.append("the likely target users are clearer")
        if "constraints" in updates:
            recap_bits.append("some project constraints were captured")
        if any(field in updates for field in ("goals", "preferred_directions", "rejected_directions")):
            recap_bits.append("the brief has more decision context")
        recap = "What became clearer: " + (", ".join(recap_bits) if recap_bits else "the draft brief was updated from your last turn") + "."
        next_questions_map = {
            "product_idea": [
                "What is the single most important problem this product should solve first?",
                "What would make this approach meaningfully different from a generic survey tool?",
            ],
            "target_users": [
                "Who is the primary user that should feel this product was built for them?",
                "Who triggers the workflow and who is only affected by it?",
            ],
            "constraints": [
                "What constraints should shape the first version: data access, compliance, budget, or rollout limits?",
                "Are there any boundaries we should treat as non-negotiable before publish?",
            ],
            "goals": [
                "What outcomes should this product improve if the first version works well?",
                "How would you tell whether the product is succeeding for the team using it?",
            ],
            "known_competitors": [
                "What existing tools would a buyer compare this against, even if they are imperfect substitutes?",
                "What are the closest current workflows or products people use instead of this?",
            ],
            "preferred_directions": [
                "Which direction feels strongest enough that we should bias the brief toward it?",
                "What part of the idea do you want the project to lean into rather than just support?",
            ],
            "rejected_directions": [
                "What should this product explicitly avoid becoming?",
                "Which tempting directions would create noise or pull the project off course?",
            ],
            "notes": [
                "What still feels unresolved or risky enough that we should capture it before publish?",
                "Is there any context you want preserved even if it does not fit neatly into the structured fields?",
            ],
        }
        next_questions = next_questions_map.get(focus_area, next_questions_map["notes"])
        assistant_message = f"{recap} The next thing I would pin down is {focus_area.replace('_', ' ')}."
        return {
            "assistant_message": assistant_message,
            "recap": recap,
            "focus_area": focus_area,
            "missing_fields": open_fields,
            "next_questions": next_questions[:2],
            "confidence": "medium",
        }

    def _prompt_catalog(self, project_id: str) -> dict[str, str]:
        """Resolve the prompt catalog snapshot stored for this project."""
        settings = self.db.get_project_model_settings(project_id)
        if settings is not None and settings.prompt_catalog:
            return settings.prompt_catalog
        return load_prompt_catalog()

    def _merged_brief_payload(self, current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        """Merge clean updates into the canonical brief payload without changing publish state."""
        normalized = self._normalized_updates(updates)
        payload = {
            "product_idea": str(current.get("product_idea") or ""),
            "known_competitors": self._list_value(current.get("known_competitors")),
            "constraints": str(current.get("constraints") or ""),
            "target_users": str(current.get("target_users") or ""),
            "goals": self._list_value(current.get("goals")),
            "preferred_directions": self._list_value(current.get("preferred_directions")),
            "rejected_directions": self._list_value(current.get("rejected_directions")),
            "notes": str(current.get("notes") or ""),
        }
        for field, value in normalized.items():
            if field in LIST_FIELDS:
                payload[field] = self._merge_lists(payload[field], self._list_value(value))
            elif field in payload:
                payload[field] = str(value).strip()
        return payload

    def _open_fields(self, brief: ProjectBrief) -> list[str]:
        """Return the remaining brief fields that still need meaningful human input."""
        payload = self._brief_payload(brief)
        open_fields: list[str] = []
        for field in BRIEF_FIELD_ORDER:
            value = payload.get(field)
            if field in LIST_FIELDS:
                if not self._list_value(value):
                    open_fields.append(field)
            elif not str(value or "").strip():
                open_fields.append(field)
        return open_fields

    @staticmethod
    def _normalized_updates(raw_updates: dict[str, Any]) -> dict[str, Any]:
        """Keep only known v1 brief fields and coerce scalar/list types."""
        updates: dict[str, Any] = {}
        for field, value in raw_updates.items():
            if field not in BRIEF_FIELDS or value in (None, "", []):
                continue
            if field in LIST_FIELDS:
                updates[field] = BriefService._list_value(value)
            else:
                updates[field] = str(value).strip()
        return updates

    @staticmethod
    def _list_value(value: Any) -> list[str]:
        """Normalize model and form values into a deduplicated string list."""
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.replace("\n", ",").split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raw_items = [str(value).strip()]
        return BriefService._merge_lists([], [item for item in raw_items if item])

    @staticmethod
    def _merge_lists(existing: list[str], incoming: list[str]) -> list[str]:
        """Append unique values while preserving human-entered order."""
        merged: list[str] = []
        seen: set[str] = set()
        for item in existing + incoming:
            key = item.casefold()
            if key and key not in seen:
                seen.add(key)
                merged.append(item)
        return merged

    @staticmethod
    def _brief_payload(brief: ProjectBrief) -> dict[str, Any]:
        """Return the prompt-safe subset of a ProjectBrief."""
        payload = brief.model_dump(mode="json")
        return {field: payload.get(field) for field in sorted(BRIEF_FIELDS)}

    def _llm_runtime(self, project_id: str, assignment: str) -> dict[str, str | None]:
        """Resolve the project-specific LLM profile for a Layer 0 assignment."""
        settings = self.db.get_project_model_settings(project_id)
        if settings is None:
            return {"base_url": None, "model_name": None}
        runtime = resolved_runtime_request(
            resolve_llm_profile(settings.model_dump(mode="json"), assignment),
            llm_client=self.llm_client,
            server_manager=self.server_manager,
        )
        return {"base_url": runtime.get("base_url"), "model_name": runtime.get("model_name")}
