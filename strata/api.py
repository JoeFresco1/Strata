from __future__ import annotations
import json
import threading
import uuid
from dataclasses import dataclass
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from strata.api_models import (
    AssistantActionDecisionRequest,
    CriticFindingResolutionRequest,
    AssistantConversationCreateRequest,
    AssistantConversationUpdateRequest,
    AssistantMessageCreateRequest,
    AppConfigResponse,
    AppSnapshotResponse,
    Layer0ChatRequest,
    Layer0ChatResponse,
    Layer0ProposalDecisionRequest,
    Layer2BulkActionRequest,
    Layer2CompetitiveSettingsRequest,
    Layer2FeatureCreateRequest,
    Layer2FeatureEvidenceRequest,
    Layer2FeatureUpdateRequest,
    Layer1GenerateRequest,
    Layer2GenerateRequest,
    Layer2ReviewActionRequest,
    Layer2ResearchStartRequest,
    Layer3ExpansionUpdateRequest,
    Layer3CandidateApplyRequest,
    Layer3CandidateRejectRequest,
    Layer3GenerateRequest,
    Layer3RevisionRestoreRequest,
    Layer3ReviewRequest,
    ModelProfileResponse,
    NodeUpdateRequest,
    ProjectBriefUpdateRequest,
    PublishBriefResponse,
    ProjectModelSettingsUpdateRequest,
    ProjectWorkspaceStateUpdateRequest,
    ResearchStartRequest,
    RuntimeModelSettingsUpdateRequest,
)
from strata.assistant_index import AssistantIndexService
from strata.assistant_service import AssistantService
from strata.brief import BriefService
from strata.command_types import (
    AcceptLayer3Candidate,
    AppendBriefPlanTurn,
    ApproveFeature,
    BulkResolveFeatureReview,
    CommandActor,
    CommandError,
    CreateFeature,
    CutFeature,
    DismissCriticFinding,
    EditFeature,
    EditLayer3ActiveRevision,
    EditPillar,
    KeepFeature,
    PartiallyAcceptLayer3Candidate,
    PublishBrief,
    RejectLayer3Candidate,
    RequestLayer1Generation,
    RequestLayer2Generation,
    RequestLayer3Generation,
    RequestResearch,
    ReviewLayer3ActiveRevision,
    ResolveCriticFinding,
    ResolveFeatureReview,
    RestoreLayer3Revision,
    UpdateBriefDraft,
)
from strata.config import (
    AppConfig,
    EMBEDDING_MODEL_PRESETS,
    build_model_profiles,
    describe_database_target,
    ensure_runtime_dirs,
    resolve_default_model_profile,
)
from strata.db import Database
from strata.embeddings import EmbeddingService
from strata.generation import GenerationService
from strata.layer3_db import Layer3RevisionConflict
from strata.layer3_service import validate_product_level_content
from strata.llm import LlamaCppClient
from strata.research import ResearchService
from strata.project_settings import (
    DEFAULT_EMBEDDING_PROFILE_ID,
    DEFAULT_LLM_PROFILE_ID,
    default_app_model_settings,
    normalize_model_settings,
    normalize_project_model_settings,
)
from strata.prompts import load_prompt_catalog
from strata.server_manager import LlamaServerManager
from strata.storage import build_database
from strata.tree import build_tree
from strata.api_export import register_export_routes
from strata.api_jobs import register_job_routes
from strata.api_discovery import register_discovery_routes
from strata.api_layer1 import register_layer1_routes
from strata.api_lifecycle import register_lifecycle_routes
from strata.api_overlap import register_overlap_routes
from strata.api_telemetry import register_telemetry_routes
from strata.api_setup import register_setup_routes
from strata.api_support import (
    AppServices,
    _apply_runtime_provider_update,
    _build_services as _build_services_support,
    _command_http_error,
    _ensure_project_model_settings,
    _execute_assistant_action,
    _get_project_layer2_feature,
    _load_app_model_settings,
    _persist_app_model_settings,
    _project_snapshot,
    _resolve_layer1_profiles,
    _sync_default_app_profiles,
    _valid_layer2_status,
    _validate_layer2_owner_pillar,
    _validate_layer3_layer2_gate,
)
from strata.provider_onboarding import provider_status_payload
def _build_services() -> AppServices:
    """Build services while preserving the public AppConfig patch seam used by isolated API tests."""
    return _build_services_support(AppConfig())
def create_app() -> FastAPI:
    """Create the FastAPI localhost app and wire it to the existing Strata services."""
    services = _build_services()
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        for job in services.db.list_queued_platform_jobs():
            threading.Thread(
                target=services.job_service.run_job,
                args=(job.id,),
                daemon=True,
                name=f"strata-job-{job.id[:8]}",
            ).start()
        for job in services.db.list_queued_research_jobs():
            platform_jobs = services.db.list_platform_jobs(job.project_id, limit=500)
            if any(
                item.workflow == "research"
                and item.request_payload.get("research_job_id") == job.id
                and item.status in {"queued", "running"}
                for item in platform_jobs
            ):
                continue
            threading.Thread(
                target=services.research_service.run_job,
                args=(job.id,),
                daemon=True,
                name=f"strata-research-{job.id[:8]}",
            ).start()
        yield
    app = FastAPI(title="Strata API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(services.config.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    @app.get("/api/health")
    def health() -> dict[str, object]:
        """Expose a lightweight health payload for frontend startup checks."""
        ok, message = services.generation_service.llm_client.healthcheck()
        return {"ok": ok, "llm_message": message}
    register_setup_routes(app, services)
    @app.get("/api/config", response_model=AppConfigResponse)
    def get_config() -> AppConfigResponse:
        """Return frontend-visible runtime configuration and discovered model profiles."""
        profiles = build_model_profiles(services.config)
        default_profile = resolve_default_model_profile(services.config, profiles)
        app_model_settings = _load_app_model_settings(services)
        provider_status = provider_status_payload(services.db, services.config)
        return AppConfigResponse(
            database_backend=services.config.database_backend,
            database_target=describe_database_target(services.config),
            llama_base_url=services.config.llama_base_url,
            llm_model_name=services.generation_service.llm_client.model_name or services.config.model_name,
            preferred_model_path=services.config.preferred_model_path,
            exports_dir=str(services.config.exports_dir),
            default_model_alias=default_profile.alias if default_profile else None,
            embeddings_model_name=services.generation_service.embedding_service.model_name if services.generation_service.embedding_service else services.config.embeddings_model_name,
            has_bearer_token=provider_status["has_bearer_token"],
            context_window=services.config.context_size,
            max_output_tokens=services.config.max_output_tokens,
            embedding_model_presets=EMBEDDING_MODEL_PRESETS,
            provider_readiness=provider_status["provider_readiness"],
            runtime_presets=provider_status["runtime_presets"],
            model_profiles=[
                ModelProfileResponse(
                    alias=profile.alias,
                    display_name=profile.display_name,
                    path=str(profile.path) if profile.path else None,
                )
                for profile in profiles
            ],
            execution_intent=app_model_settings["execution_intent"],
            routing_policy=app_model_settings["routing_policy"],
            concurrency_policy=app_model_settings["concurrency_policy"],
            llm_profiles=app_model_settings["llm_profiles"],
            embedding_profiles=app_model_settings["embedding_profiles"],
            assignments=app_model_settings["assignments"],
            prompt_catalog=app_model_settings["prompt_catalog"],
            discovery_settings=app_model_settings["discovery_settings"],
        )
    register_lifecycle_routes(app, services)
    register_telemetry_routes(app, services)
    register_job_routes(app, services)
    register_discovery_routes(app, services)
    register_layer1_routes(app, services)
    register_overlap_routes(app, services)
    register_export_routes(app, services)
    @app.get("/api/projects/{project_id}/assistant/conversations")
    def list_assistant_conversations(project_id: str) -> list[dict[str, object]]:
        """List the project's durable assistant conversations."""
        try:
            services.db.get_project(project_id)
            conversations = services.db.list_assistant_conversations(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [conversation.model_dump(mode="json") for conversation in conversations]
    @app.post("/api/projects/{project_id}/assistant/conversations")
    def create_assistant_conversation(
        project_id: str,
        request: AssistantConversationCreateRequest,
    ) -> dict[str, object]:
        """Start a new thread for the same unified project assistant."""
        try:
            conversation = services.assistant_service.create_conversation(
                project_id,
                request.title.strip() or "New conversation",
                request.home_scope,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return conversation.model_dump(mode="json")
    @app.patch("/api/projects/{project_id}/assistant/conversations/{conversation_id}")
    def update_assistant_conversation(
        project_id: str,
        conversation_id: str,
        request: AssistantConversationUpdateRequest,
    ) -> dict[str, object]:
        """Rename or archive one project-local assistant conversation."""
        try:
            conversation = services.db.get_assistant_conversation(conversation_id)
            if conversation.project_id != project_id:
                raise ValueError("Assistant conversation belongs to another project.")
            updated = services.db.update_assistant_conversation(
                conversation_id,
                title=request.title.strip() if request.title is not None else None,
                archived=request.archived,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return updated.model_dump(mode="json")
    @app.get("/api/projects/{project_id}/assistant/conversations/{conversation_id}")
    def get_assistant_conversation(project_id: str, conversation_id: str) -> dict[str, object]:
        """Return a conversation with turn status, run traces, and action outcomes."""
        try:
            conversation = services.db.get_assistant_conversation(conversation_id)
            if conversation.project_id != project_id:
                raise ValueError("Assistant conversation belongs to another project.")
            messages = services.db.list_assistant_messages(conversation_id)
            actions = services.db.list_assistant_action_proposals(conversation_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "conversation": conversation.model_dump(mode="json"),
            "messages": [
                {
                    **message.model_dump(mode="json"),
                    "run": services.db.get_assistant_run_for_message(message.id),
                }
                for message in messages
            ],
            "actions": [action.model_dump(mode="json") for action in actions],
        }
    @app.post("/api/projects/{project_id}/assistant/conversations/{conversation_id}/messages")
    def create_assistant_message(
        project_id: str,
        conversation_id: str,
        request: AssistantMessageCreateRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        """Queue one grounded assistant turn with idempotent request handling."""
        try:
            result = services.assistant_service.submit_message(
                project_id=project_id,
                conversation_id=conversation_id,
                content=request.content,
                request_id=request.request_id,
                active_scope=request.active_scope,
                focus=request.focus,
                reference_conversation_ids=request.reference_conversation_ids,
                execution_intent_override=request.execution_intent_override,
                thinking_enabled=request.thinking_enabled,
                deep_mode=request.deep_mode,
            )
            assistant_message = result["assistant_message"]
            if assistant_message.status == "queued":
                job = services.job_service.enqueue(
                    project_id=project_id,
                    kind="assistant",
                    workflow="assistant_message",
                    scope="assistant",
                    scope_id=assistant_message.id,
                    request_payload={"assistant_message_id": assistant_message.id},
                    dedupe_key=f"assistant:{assistant_message.id}",
                )
                background_tasks.add_task(services.job_service.run_job, job.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            for key, value in result.items()
        }
    @app.post("/api/projects/{project_id}/assistant/messages/{message_id}/retry")
    def retry_assistant_message(
        project_id: str,
        message_id: str,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        """Retry a failed or completed assistant response without duplicating the user turn."""
        try:
            message = services.db.get_assistant_message(message_id)
            if message.project_id != project_id:
                raise ValueError("Assistant message belongs to another project.")
            result = services.assistant_service.retry_message(message_id)
            job = services.job_service.enqueue(
                project_id=project_id,
                kind="assistant",
                workflow="assistant_message",
                scope="assistant",
                scope_id=message_id,
                request_payload={"assistant_message_id": message_id},
                dedupe_key=f"assistant:{message_id}",
            )
            background_tasks.add_task(services.job_service.run_job, job.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            for key, value in result.items()
        }
    @app.post("/api/projects/{project_id}/assistant/actions/{proposal_id}")
    def decide_assistant_action(
        project_id: str,
        proposal_id: str,
        request: AssistantActionDecisionRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        """Reject or explicitly confirm an assistant mutation preview."""
        proposal = None
        try:
            proposal = services.db.get_assistant_action_proposal(proposal_id)
            if proposal.project_id != project_id:
                raise ValueError("Assistant action belongs to another project.")
            if proposal.status != "pending":
                raise ValueError("Assistant action has already been resolved.")
            if request.decision == "reject":
                updated = services.db.update_assistant_action_proposal(proposal.id, status="rejected")
            elif services.assistant_service.action_is_stale(proposal):
                updated = services.db.update_assistant_action_proposal(
                    proposal.id,
                    status="stale",
                    result={"error": "Project state changed after this action was proposed."},
                )
            else:
                result = _execute_assistant_action(services, proposal, background_tasks)
                updated = services.db.update_assistant_action_proposal(proposal.id, status="applied", result=result)
        except CommandError as exc:
            if proposal is not None and proposal.status == "pending" and request.decision == "apply":
                services.db.update_assistant_action_proposal(proposal.id, status="failed", result={"error": exc.message, "code": exc.code})
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            if proposal is not None and proposal.status == "pending" and request.decision == "apply":
                services.db.update_assistant_action_proposal(
                    proposal.id,
                    status="failed",
                    result={"error": str(exc)},
                )
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return updated.model_dump(mode="json")
    @app.patch("/api/config/models", response_model=AppConfigResponse)
    def update_runtime_model_settings(request: RuntimeModelSettingsUpdateRequest) -> AppConfigResponse:
        """Persist runtime model settings for chat and embeddings and apply them immediately."""
        try:
            payload = request.model_dump(mode="json")
            services.config.preferred_model_path = request.preferred_model_path.strip() or None
            services.db.set_app_setting("preferred_model_path", request.preferred_model_path.strip())
            _apply_runtime_provider_update(services, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return get_config()
    @app.patch("/api/projects/{project_id}/settings/models")
    def update_project_model_settings(project_id: str, request: ProjectModelSettingsUpdateRequest) -> dict[str, object]:
        """Persist project-scoped LLM and embedding profiles plus assignment routing."""
        try:
            services.db.get_project(project_id)
            payload_data = request.model_dump(mode="json")
            existing = services.db.get_project_model_settings(project_id)
            if existing is not None and not payload_data.get("prompt_catalog"):
                payload_data["prompt_catalog"] = existing.prompt_catalog
            payload = normalize_project_model_settings(payload_data, services.config)
            settings = services.db.upsert_project_model_settings(project_id=project_id, **payload)
            if not settings.competitive_intelligence_enabled:
                services.db.cancel_active_research_jobs(
                    project_id,
                    "Competitive intelligence was disabled in project settings.",
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return settings.model_dump(mode="json")
    @app.get("/api/projects/{project_id}", response_model=AppSnapshotResponse)
    def get_project(project_id: str) -> AppSnapshotResponse:
        """Return the current project snapshot for the main workspace view."""
        try:
            services.db.touch_project(project_id, opened=True, updated=False)
            return _project_snapshot(services, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/api/projects/{project_id}/workspace-state")
    def update_project_workspace_state(project_id: str, request: ProjectWorkspaceStateUpdateRequest) -> dict[str, object]:
        """Persist the selected entity and Map/Table workspace preferences."""
        try:
            services.db.get_project(project_id)
            state = services.db.upsert_project_workspace_state(
                project_id=project_id,
                **request.model_dump(mode="json"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return state.model_dump(mode="json")

    @app.patch("/api/projects/{project_id}/brief")
    def update_project_brief(project_id: str, request: ProjectBriefUpdateRequest) -> dict[str, object]:
        """Update the canonical Layer 0 draft brief from Form mode."""
        try:
            payload = request.model_dump(exclude={"expected_state_token", "request_id"})
            result = services.command_service.handle(UpdateBriefDraft(
                project_id=project_id, actor=CommandActor.human_ui(),
                idempotency_key=request.request_id or str(uuid.uuid4()),
                expected_state_token=request.expected_state_token, updates=payload,
            ))
            brief = result.data["brief"]
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return brief

    @app.post("/api/projects/{project_id}/brief/chat", response_model=Layer0ChatResponse)
    def append_layer0_chat(project_id: str, request: Layer0ChatRequest) -> Layer0ChatResponse:
        """Append a non-streaming Layer 0 turn and retain inferred edits as a proposal."""
        try:
            result = services.command_service.handle(AppendBriefPlanTurn(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()),
                expected_state_token=request.expected_state_token, message=request.message,
            ))
            reply, brief, guidance = result.data["reply"], result.data["brief"], result.data["guidance"]
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Layer0ChatResponse(
            reply=reply,
            brief={**brief, "state_token": result.state_token},
            conversation=[
                turn.model_dump(mode="json")
                for turn in services.db.list_brief_conversation(project_id)
            ],
            plan_guidance=guidance,
            proposal=(
                services.db.get_brief_conversation_by_request(project_id, request.request_id, "assistant")
                .extracted_updates.get("proposal")
                if request.request_id and services.db.get_brief_conversation_by_request(project_id, request.request_id, "assistant")
                else None
            ),
        )

    @app.post("/api/projects/{project_id}/brief/chat/stream")
    def stream_layer0_chat(project_id: str, request: Layer0ChatRequest) -> StreamingResponse:
        """Stream a real provider response as NDJSON while preserving durable partial state."""
        current = services.brief_service.ensure_brief(project_id)
        actual_token = services.command_service.brief_state_token(current)
        if request.expected_state_token and request.expected_state_token != actual_token:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "conflict",
                    "message": "The Layer 0 brief changed before generation started.",
                    "expected_revision": request.expected_state_token,
                    "actual_revision": actual_token,
                    "recovery": "reload_or_compare",
                },
            )
        request_id = request.request_id or str(uuid.uuid4())

        def event_stream():
            """Encode each service event without buffering the provider response."""
            for event in services.brief_service.stream_plan_turn(
                project_id, request.message, request_id,
                base_state_token=actual_token, retry=request.retry,
            ):
                yield "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/projects/{project_id}/brief/chat/{request_id}/stop")
    def stop_layer0_chat(project_id: str, request_id: str) -> dict[str, object]:
        """Signal cancellation for one project-local active Layer 0 response."""
        services.db.get_project(project_id)
        return {"request_id": request_id, "cancellation_requested": services.brief_service.cancel_plan_turn(request_id)}

    @app.post("/api/projects/{project_id}/brief/proposals/{turn_id}/decision")
    def decide_layer0_proposal(
        project_id: str,
        turn_id: str,
        request: Layer0ProposalDecisionRequest,
    ) -> dict[str, object]:
        """Apply reviewed proposal fields through the canonical command layer or dismiss them."""
        turn = services.db.get_brief_conversation_turn(turn_id)
        if turn.project_id != project_id or turn.role != "assistant":
            raise HTTPException(status_code=404, detail="Layer 0 proposal not found for this project.")
        proposal = dict(turn.extracted_updates.get("proposal") or {})
        if not proposal:
            raise HTTPException(status_code=400, detail="This assistant message has no proposed brief update.")
        if request.decision == "dismiss":
            updated_turn = services.brief_service.record_proposal_decision(turn, status="dismissed")
            return {
                "brief": {**services.brief_service.ensure_brief(project_id).model_dump(mode="json"), "state_token": services.command_service.brief_state_token(services.brief_service.ensure_brief(project_id))},
                "turn": updated_turn.model_dump(mode="json"),
                "conversation": [item.model_dump(mode="json") for item in services.db.list_brief_conversation(project_id)],
            }
        try:
            updates = services.brief_service.proposal_updates(turn, request.selected_fields, request.edited_values)
            result = services.command_service.handle(UpdateBriefDraft(
                project_id=project_id,
                actor=CommandActor.human_ui(),
                idempotency_key=request.request_id or str(uuid.uuid4()),
                expected_state_token=request.expected_state_token or str(proposal.get("base_state_token") or ""),
                updates=updates,
            ))
        except CommandError as exc:
            if exc.code == "conflict":
                services.brief_service.record_proposal_decision(
                    turn, status="stale", conflict={"message": exc.message, **exc.details},
                )
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        updated_turn = services.brief_service.record_proposal_decision(
            turn, status="applied", fields=list(updates), command_id=result.command_id,
            next_state_token=result.state_token,
        )
        return {
            "brief": {**result.data["brief"], "state_token": result.state_token},
            "turn": updated_turn.model_dump(mode="json"),
            "conversation": [item.model_dump(mode="json") for item in services.db.list_brief_conversation(project_id)],
            "command_id": result.command_id,
        }

    @app.post("/api/projects/{project_id}/brief/publish", response_model=PublishBriefResponse)
    def publish_project_brief(project_id: str, background_tasks: BackgroundTasks, expected_state_token: str | None = None, request_id: str | None = None) -> PublishBriefResponse:
        """Publish Layer 0 without automatically starting model or research work."""
        try:
            result = services.command_service.handle(PublishBrief(
                project_id=project_id, actor=CommandActor.human_ui(), expected_state_token=expected_state_token,
                idempotency_key=request_id or str(uuid.uuid4()),
            ))
            brief = result.data["brief"]
            for job_id in result.data.get("job_ids", []):
                background_tasks.add_task(services.job_service.run_job, job_id)
            snapshot = _project_snapshot(services, project_id).model_dump(mode="json")
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return PublishBriefResponse(brief=brief, snapshot=snapshot)

    @app.post("/api/projects/{project_id}/research/layer0")
    def rerun_layer0_research(project_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
        """Rerun the Layer 0 local competitor landscape job."""
        try:
            result = services.command_service.handle(RequestResearch(project_id=project_id, actor=CommandActor.human_ui(), layer="layer0"))
            for job_id in result.data["job_ids"]:
                background_tasks.add_task(services.job_service.run_job, job_id)
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        return {"job": result.data["research_jobs"][0], "platform_job": result.data["jobs"][0]}

    @app.post("/api/projects/{project_id}/research/layer1")
    def rerun_layer1_research(
        project_id: str,
        request: ResearchStartRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        """Rerun Layer 1 local competitor coverage for selected or all pillars."""
        pillar_ids = request.pillar_ids or [
            node.id
            for node in services.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
        ]
        jobs = []
        try:
            result = services.command_service.handle(RequestResearch(project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()), layer="layer1", artifact_ids=tuple(pillar_ids)))
            for job_id in result.data["job_ids"]:
                background_tasks.add_task(services.job_service.run_job, job_id)
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        return {"jobs": result.data["research_jobs"]}

    @app.post("/api/projects/{project_id}/research/layer2")
    def rerun_layer2_research(
        project_id: str,
        request: Layer2ResearchStartRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        """Research selected Layer 2 features or the complete active feature set."""
        try:
            result = services.command_service.handle(RequestResearch(project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()), layer="layer2", artifact_ids=tuple(request.feature_ids)))
            for job_id in result.data["job_ids"]:
                background_tasks.add_task(services.job_service.run_job, job_id)
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        return {"job": result.data["research_jobs"][0], "platform_job": result.data["jobs"][0]}

    @app.patch("/api/nodes/{node_id}")
    def update_node(node_id: str, request: NodeUpdateRequest) -> dict[str, object]:
        """Update editable node fields from the review workflow."""
        try:
            before = services.db.get_node(node_id)
            if before.layer != 1 or before.node_type != "pillar":
                raise ValueError("Only canonical Layer 1 pillars may be mutated through this route.")
            result = services.command_service.handle(EditPillar(
                project_id=before.project_id, actor=CommandActor.human_ui(),
                idempotency_key=request.request_id or str(uuid.uuid4()),
                expected_state_token=request.expected_state_token, pillar_id=node_id,
                title=request.title, description=request.description, status=request.status,
                priority=request.priority,
            ))
            node = result.data["pillar"]
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return node

    @app.post("/api/projects/{project_id}/generate/layer1")
    def generate_layer1(
        project_id: str,
        request: Layer1GenerateRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        """Run Layer 1 pillar broadening with the selected model sequence."""
        try:
            _resolve_layer1_profiles(services.config, request.model_aliases)
            result = services.command_service.handle(RequestLayer1Generation(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()),
                payload=request.model_dump(mode="json", exclude={"request_id"}),
            ))
            job = result.data["job"]
            background_tasks.add_task(services.job_service.run_job, job["id"])
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "job": job,
            "snapshot": _project_snapshot(services, project_id).model_dump(mode="json"),
        }

    @app.post("/api/projects/{project_id}/generate/layer2")
    def generate_layer2(
        project_id: str,
        request: Layer2GenerateRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        """Run graph-native Layer 2 feature generation for selected kept pillars."""
        try:
            payload = request.model_dump(mode="json", exclude={"request_id"})
            if not payload["pillar_ids"]:
                payload["pillar_ids"] = [item.id for item in services.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar") if item.status in {"kept", "prioritized"}]
            result = services.command_service.handle(RequestLayer2Generation(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()), payload=payload,
            ))
            job = result.data["job"]
            background_tasks.add_task(services.job_service.run_job, job["id"])
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "job": job,
            "snapshot": _project_snapshot(services, project_id).model_dump(mode="json"),
        }

    @app.post("/api/projects/{project_id}/layer2/review")
    def review_layer2_feature(project_id: str, request: Layer2ReviewActionRequest) -> dict[str, object]:
        """Apply a review decision to the Layer 2 graph and keep rejected concepts in negative memory."""
        try:
            if not request.feature_id:
                raise ValueError("A feature is required for this review action.")
            services.command_service.handle(ResolveFeatureReview(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()),
                expected_state_token=request.expected_state_token, feature_id=request.feature_id,
                action=request.action_type, payload={**request.payload, "expected_target_state_token": request.expected_target_state_token},
                target_feature_id=request.target_feature_id, owner_pillar_id=request.owner_pillar_id,
                relationship_type=request.relationship_type, title=request.title, description=request.description,
            ))
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer2/features")
    def create_layer2_feature(project_id: str, request: Layer2FeatureCreateRequest) -> dict[str, object]:
        """Manually add one Layer 2 feature into the review workbench."""
        try:
            services.command_service.handle(CreateFeature(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()),
                canonical_name=request.canonical_name, description=request.description, owner_pillar_id=request.owner_pillar_id,
                feature_type=request.feature_type, granularity_class=request.granularity_class, aliases=tuple(request.aliases),
                status=request.status, coverage_family=request.coverage_family, priority=request.priority, notes=request.notes,
            ))
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.patch("/api/projects/{project_id}/layer2/features/{feature_id}")
    def update_layer2_feature(project_id: str, feature_id: str, request: Layer2FeatureUpdateRequest) -> dict[str, object]:
        """Inline-edit one Layer 2 feature from the workbench drawer/table."""
        try:
            updates = request.model_dump(exclude_none=True, exclude={"expected_state_token", "request_id"})
            services.command_service.handle(EditFeature(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()),
                expected_state_token=request.expected_state_token, feature_id=feature_id, updates=updates,
            ))
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer2/bulk")
    def bulk_layer2_action(project_id: str, request: Layer2BulkActionRequest) -> dict[str, object]:
        """Apply one review action to many Layer 2 features."""
        try:
            services.command_service.handle(BulkResolveFeatureReview(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()),
                feature_ids=tuple(request.feature_ids), action=request.action_type,
                expected_state_tokens=request.expected_state_tokens, payload=request.payload,
            ))
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer2/evidence")
    def create_layer2_feature_evidence(project_id: str, request: Layer2FeatureEvidenceRequest) -> dict[str, object]:
        """Save manual competitor evidence for one Layer 2 feature."""
        try:
            _get_project_layer2_feature(services, project_id, request.feature_id)
            services.db.create_layer2_feature_evidence(
                project_id=project_id,
                feature_id=request.feature_id,
                competitor_name=request.competitor_name.strip(),
                coverage_status=request.coverage_status,
                confidence=request.confidence,
                source_url=request.source_url.strip(),
                evidence_snippet=request.evidence_snippet.strip(),
                notes=request.notes.strip(),
                source_type=request.source_type,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.patch("/api/projects/{project_id}/competitive/layer2/settings")
    def update_layer2_competitive_settings(project_id: str, request: Layer2CompetitiveSettingsRequest) -> dict[str, object]:
        """Save known competitors and feature research mode for competitive intelligence views."""
        try:
            services.db.get_project(project_id)
            services.db.upsert_layer2_competitive_settings(
                project_id=project_id,
                known_competitors=request.known_competitors,
                research_mode=request.research_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/generate/layer3")
    def generate_layer3(project_id: str, request: Layer3GenerateRequest, background_tasks: BackgroundTasks) -> dict[str, object]:
        """Generate editable Feature Expansions for approved Layer 2 features."""
        try:
            if not request.feature_ids:
                raise ValueError("Select at least one approved Layer 2 feature.")
            _validate_layer3_layer2_gate(services, project_id, request.feature_ids)
            result = services.command_service.handle(RequestLayer3Generation(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()),
                feature_ids=tuple(request.feature_ids), thinking_enabled=request.thinking_enabled,
            ))
            job = result.data["job"]
            background_tasks.add_task(services.job_service.run_job, job["id"])
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "job": job,
            "snapshot": _project_snapshot(services, project_id).model_dump(mode="json"),
        }

    @app.patch("/api/projects/{project_id}/layer3/expansions/{expansion_id}")
    def update_layer3_expansion(project_id: str, expansion_id: str, request: Layer3ExpansionUpdateRequest) -> dict[str, object]:
        """Persist human edits to Layer 3 feature-expansion groups and options."""
        try:
            expansion = services.db.get_layer3_expansion(expansion_id)
            if expansion.project_id != project_id:
                raise ValueError("Layer 3 expansion belongs to another project.")
            updates = request.model_dump(exclude_none=True, exclude={"expected_state_token", "request_id"})
            if not updates:
                raise ValueError("Provide at least one Layer 3 expansion field to update.")
            validate_product_level_content(updates)
            if "expansion_groups" in updates:
                known_feature_ids = {
                    item.id
                    for item in services.db.list_layer2_features(project_id)
                    if item.status in {"kept", "approved"} and item.id != expansion.feature_id
                }
                invalid_targets = [
                    target_id
                    for group in updates["expansion_groups"]
                    for option in group.get("options", [])
                    for target_id in option.get("overlaps_feature_ids", [])
                    if target_id not in known_feature_ids
                ]
                if invalid_targets:
                    raise ValueError("Layer 3 overlap links require active Layer 2 feature targets.")
            services.command_service.handle(EditLayer3ActiveRevision(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()),
                expected_state_token=request.expected_state_token, expansion_id=expansion_id, updates=updates,
            ))
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.get("/api/projects/{project_id}/critic-findings")
    def list_critic_findings(project_id: str) -> dict[str, object]:
        """Return model challenges that were prevented from mutating human-owned artifacts."""
        try:
            services.db.get_project(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        findings = services.db.list_critic_findings(project_id)
        return {"findings": [{**item, "state_token": services.command_service.finding_state_token(item)} for item in findings]}

    @app.post("/api/projects/{project_id}/critic-findings/{finding_id}/resolve")
    def resolve_critic_finding(project_id: str, finding_id: str, request: CriticFindingResolutionRequest) -> dict[str, object]:
        """Record a human finding resolution; artifact changes still use their explicit command route."""
        try:
            command_cls = DismissCriticFinding if request.action == "dismissed" else ResolveCriticFinding
            kwargs = dict(
                project_id=project_id, actor=CommandActor.human_ui(request.resolved_by),
                idempotency_key=request.request_id or str(uuid.uuid4()), expected_state_token=request.expected_state_token,
                finding_id=finding_id, note=request.note,
            )
            if command_cls is ResolveCriticFinding:
                kwargs["resolution"] = request.action
            result = services.command_service.handle(command_cls(**kwargs))
            finding = result.data["finding"]
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"finding": finding, "snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer3/expansions/{expansion_id}/review")
    def review_layer3_expansion(project_id: str, expansion_id: str, request: Layer3ReviewRequest) -> dict[str, object]:
        try:
            state = {"approve": "approved", "reject": "rejected", "needs_review": "needs_review"}[request.action]
            services.command_service.handle(ReviewLayer3ActiveRevision(
                project_id=project_id, actor=CommandActor.human_ui(), idempotency_key=request.request_id or str(uuid.uuid4()),
                expected_state_token=request.expected_state_token, expansion_id=expansion_id, review_state=state, note=request.note,
            ))
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer3/expansions/{expansion_id}/candidates/{candidate_revision_id}/apply")
    def apply_layer3_candidate(
        project_id: str,
        expansion_id: str,
        candidate_revision_id: str,
        request: Layer3CandidateApplyRequest,
    ) -> dict[str, object]:
        """Atomically accept a full candidate or only explicitly selected top-level sections."""
        try:
            command_cls = PartiallyAcceptLayer3Candidate if request.selected_sections else AcceptLayer3Candidate
            kwargs = dict(project_id=project_id, actor=CommandActor.human_ui(request.actor), idempotency_key=request.request_id,
                          expected_state_token=request.expected_active_revision_id, expansion_id=expansion_id,
                          candidate_revision_id=candidate_revision_id)
            if request.selected_sections:
                kwargs["selected_sections"] = tuple(request.selected_sections)
            result = services.command_service.handle(command_cls(**kwargs)).data
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"result": result, "snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer3/expansions/{expansion_id}/candidates/{candidate_revision_id}/reject")
    def reject_layer3_candidate(
        project_id: str,
        expansion_id: str,
        candidate_revision_id: str,
        request: Layer3CandidateRejectRequest,
    ) -> dict[str, object]:
        """Reject a candidate while leaving the current active expansion untouched."""
        try:
            result = services.command_service.handle(RejectLayer3Candidate(
                project_id=project_id, actor=CommandActor.human_ui(request.actor), idempotency_key=request.request_id,
                expected_state_token=request.expected_active_revision_id, expansion_id=expansion_id,
                candidate_revision_id=candidate_revision_id, note=request.note,
            )).data
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"result": result, "snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer3/expansions/{expansion_id}/revisions/{revision_id}/restore")
    def restore_layer3_revision(
        project_id: str,
        expansion_id: str,
        revision_id: str,
        request: Layer3RevisionRestoreRequest,
    ) -> dict[str, object]:
        """Restore an earlier accepted revision by creating a new active revision atomically."""
        try:
            result = services.command_service.handle(RestoreLayer3Revision(
                project_id=project_id, actor=CommandActor.human_ui(request.actor), idempotency_key=request.request_id,
                expected_state_token=request.expected_active_revision_id, expansion_id=expansion_id, revision_id=revision_id,
            )).data
        except CommandError as exc:
            raise _command_http_error(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"result": result, "snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app


app = create_app()
