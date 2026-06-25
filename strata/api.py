from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from strata.api_models import (
    AssistantActionDecisionRequest,
    AssistantConversationCreateRequest,
    AssistantConversationUpdateRequest,
    AssistantMessageCreateRequest,
    AppConfigResponse,
    AppSnapshotResponse,
    ExportResponse,
    Layer0ChatRequest,
    Layer0ChatResponse,
    Layer2BulkActionRequest,
    Layer2CompetitiveSettingsRequest,
    Layer2FeatureCreateRequest,
    Layer2FeatureEvidenceRequest,
    Layer2FeatureUpdateRequest,
    Layer1GenerateRequest,
    Layer2GenerateRequest,
    Layer2ReviewActionRequest,
    Layer2ResearchStartRequest,
    Layer3CardUpdateRequest,
    Layer3DecisionUpdateRequest,
    Layer3GenerateRequest,
    Layer3PressureTestRequest,
    Layer3ReviewRequest,
    ModelProfileResponse,
    NodeUpdateRequest,
    ProjectBriefUpdateRequest,
    ProjectCreateRequest,
    PublishBriefResponse,
    ProjectModelSettingsUpdateRequest,
    ProjectWorkspaceStateUpdateRequest,
    ResearchStartRequest,
    RuntimeModelSettingsUpdateRequest,
)
from strata.assistant_index import AssistantIndexService
from strata.assistant_service import AssistantService
from strata.brief import BriefService
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
from strata.export import export_layer2_markdown, export_layer3_manifest, export_project
from strata.generation import GenerationService
from strata.layer3_service import validate_product_level_content
from strata.llm import LLMError, LlamaCppClient
from strata.research import ResearchService
from strata.project_settings import (
    DEFAULT_EMBEDDING_PROFILE_ID,
    DEFAULT_LLM_PROFILE_ID,
    default_app_model_settings,
    default_project_model_settings,
    normalize_model_settings,
    normalize_project_model_settings,
)
from strata.prompts import load_prompt_catalog
from strata.server_manager import LlamaServerManager
from strata.storage import build_database
from strata.tree import build_tree


from strata.api_support import (
    AppServices,
    _apply_layer2_review_action,
    _build_services as _build_services_support,
    _ensure_project_model_settings,
    _execute_assistant_action,
    _get_project_layer2_feature,
    _load_app_model_settings,
    _persist_app_model_settings,
    _project_snapshot,
    _record_layer2_merge,
    _record_layer2_relationship,
    _remove_layer2_relationship,
    _resolve_layer1_profiles,
    _sync_default_app_profiles,
    _valid_layer2_status,
    _validate_layer2_owner_pillar,
    _validate_layer3_layer2_gate,
)


def _build_services() -> AppServices:
    """Build services while preserving the public AppConfig patch seam used by isolated API tests."""
    return _build_services_support(AppConfig())


def create_app() -> FastAPI:
    """Create the FastAPI localhost app and wire it to the existing Strata services."""
    services = _build_services()
    app = FastAPI(title="Strata API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
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

    @app.get("/api/config", response_model=AppConfigResponse)
    def get_config() -> AppConfigResponse:
        """Return frontend-visible runtime configuration and discovered model profiles."""
        profiles = build_model_profiles(services.config)
        default_profile = resolve_default_model_profile(services.config, profiles)
        app_model_settings = _load_app_model_settings(services)
        return AppConfigResponse(
            database_backend=services.config.database_backend,
            database_target=describe_database_target(services.config),
            llama_base_url=services.config.llama_base_url,
            llm_model_name=services.generation_service.llm_client.model_name or services.config.model_name,
            preferred_model_path=services.config.preferred_model_path,
            exports_dir=str(services.config.exports_dir),
            default_model_alias=default_profile.alias if default_profile else None,
            embeddings_model_name=services.generation_service.embedding_service.model_name if services.generation_service.embedding_service else services.config.embeddings_model_name,
            embedding_model_presets=EMBEDDING_MODEL_PRESETS,
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
        )

    @app.get("/api/projects")
    def list_projects() -> list[dict[str, object]]:
        """List projects so the frontend can populate the project switcher."""
        return [
            {
                **project,
                "created_at": project["created_at"].isoformat(),
                "brief_updated_at": project["brief_updated_at"].isoformat() if project["brief_updated_at"] else None,
            }
            for project in services.db.list_projects()
        ]

    @app.post("/api/projects")
    def create_project(request: ProjectCreateRequest) -> dict[str, object]:
        """Create a new product-spec project from a high-level idea."""
        project = services.db.create_project(request.name.strip(), request.idea.strip())
        services.db.upsert_project_model_settings(
            project_id=project.id,
            **default_project_model_settings(services.config, _load_app_model_settings(services)),
        )
        services.brief_service.update_brief(
            project.id,
            {
                "product_idea": request.idea,
                "known_competitors": request.known_competitors,
                "constraints": request.constraints,
                "target_users": request.target_users,
                "goals": request.goals,
                "preferred_directions": request.preferred_directions,
                "rejected_directions": request.rejected_directions,
                "notes": request.notes,
            },
        )
        return project.model_dump(mode="json")

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
                background_tasks.add_task(services.assistant_service.run_message, assistant_message.id)
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
            background_tasks.add_task(services.assistant_service.run_message, message_id)
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
            cleaned_base_url = request.llama_base_url.strip().rstrip("/")
            cleaned_model_name = request.llm_model_name.strip()
            cleaned_preferred_model_path = request.preferred_model_path.strip()
            cleaned_embeddings_model_name = request.embeddings_model_name.strip()
            if not cleaned_base_url:
                raise ValueError("LLM base URL cannot be empty.")
            if not cleaned_model_name:
                raise ValueError("LLM model name cannot be empty.")
            if not cleaned_embeddings_model_name:
                raise ValueError("Embedding model name cannot be empty.")
            services.config.llama_base_url = cleaned_base_url
            services.config.model_name = cleaned_model_name
            services.config.preferred_model_path = cleaned_preferred_model_path or None
            services.config.embeddings_model_name = cleaned_embeddings_model_name
            services.generation_service.llm_client.set_base_url(cleaned_base_url)
            services.generation_service.llm_client.set_model_name(cleaned_model_name)
            services.generation_service.server_manager.config = services.config
            services.generation_service.server_manager.refresh_runtime_settings()
            services.generation_service.embedding_service.set_model_name(cleaned_embeddings_model_name)
            services.db.set_app_setting("llama_base_url", cleaned_base_url)
            services.db.set_app_setting("llm_model_name", cleaned_model_name)
            services.db.set_app_setting("preferred_model_path", cleaned_preferred_model_path)
            services.db.set_app_setting("embeddings_model_name", cleaned_embeddings_model_name)
            app_model_settings = normalize_model_settings(request.model_dump(mode="json"), services.config)
            app_model_settings = _sync_default_app_profiles(app_model_settings, services)
            _persist_app_model_settings(services, app_model_settings)
        except (ValueError, AttributeError) as exc:
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
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return settings.model_dump(mode="json")

    @app.get("/api/projects/{project_id}", response_model=AppSnapshotResponse)
    def get_project(project_id: str) -> AppSnapshotResponse:
        """Return the current project snapshot for the main workspace view."""
        try:
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
            brief = services.brief_service.update_brief(project_id, request.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return brief.model_dump(mode="json")

    @app.post("/api/projects/{project_id}/brief/chat", response_model=Layer0ChatResponse)
    def append_layer0_chat(project_id: str, request: Layer0ChatRequest) -> Layer0ChatResponse:
        """Append a Plan-mode chat turn and extract fields into the same draft brief."""
        try:
            reply, brief, guidance = services.brief_service.append_plan_turn(
                project_id,
                request.message,
                request.request_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Layer0ChatResponse(
            reply=reply,
            brief=brief.model_dump(mode="json"),
            conversation=[
                turn.model_dump(mode="json")
                for turn in services.db.list_brief_conversation(project_id)
            ],
            plan_guidance=guidance,
        )

    @app.post("/api/projects/{project_id}/brief/publish", response_model=PublishBriefResponse)
    def publish_project_brief(project_id: str, background_tasks: BackgroundTasks) -> PublishBriefResponse:
        """Publish Layer 0 and start local competitor research."""
        try:
            brief = services.brief_service.publish(project_id)
            job = services.research_service.enqueue_layer0(project_id, reason="publish")
            background_tasks.add_task(services.research_service.run_job, job.id)
            snapshot = _project_snapshot(services, project_id).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return PublishBriefResponse(brief=brief.model_dump(mode="json"), snapshot=snapshot)

    @app.post("/api/projects/{project_id}/research/layer0")
    def rerun_layer0_research(project_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
        """Rerun the Layer 0 local competitor landscape job."""
        try:
            job = services.research_service.enqueue_layer0(project_id, reason="manual_rerun")
            background_tasks.add_task(services.research_service.run_job, job.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"job": job.model_dump(mode="json")}

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
            for pillar_id in pillar_ids:
                job = services.research_service.enqueue_layer1(project_id, pillar_id, reason="manual_rerun")
                jobs.append(job)
                background_tasks.add_task(services.research_service.run_job, job.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"jobs": [job.model_dump(mode="json") for job in jobs]}

    @app.post("/api/projects/{project_id}/research/layer2")
    def rerun_layer2_research(
        project_id: str,
        request: Layer2ResearchStartRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        """Research selected Layer 2 features or the complete active feature set."""
        try:
            job = services.research_service.enqueue_layer2(
                project_id,
                feature_ids=request.feature_ids or None,
                reason="manual_rerun",
            )
            background_tasks.add_task(services.research_service.run_job, job.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"job": job.model_dump(mode="json")}

    @app.patch("/api/nodes/{node_id}")
    def update_node(node_id: str, request: NodeUpdateRequest) -> dict[str, object]:
        """Update editable node fields from the review workflow."""
        try:
            before = services.db.get_node(node_id)
            node = services.db.update_node(
                node_id,
                title=request.title.strip() if request.title is not None else None,
                description=request.description.strip() if request.description is not None else None,
                status=request.status,
                priority=request.priority,
            )
            if node.node_type == "pillar" and node.layer == 1:
                node = services.generation_service.refresh_pillar_semantic_metadata(node.id)
                if request.title is not None or request.description is not None:
                    payload = dict(node.json_payload or {})
                    if before.title != node.title or (before.description or "") != (node.description or ""):
                        payload["research_stale"] = {
                            "scope": "layer1",
                            "reason": "pillar_content_changed",
                        }
                        node = services.db.update_node(node.id, json_payload=payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return node.model_dump(mode="json")

    @app.post("/api/projects/{project_id}/generate/layer1")
    def generate_layer1(
        project_id: str,
        request: Layer1GenerateRequest,
        background_tasks: BackgroundTasks,
    ) -> dict[str, object]:
        """Run Layer 1 pillar broadening with the selected model sequence."""
        try:
            summary = services.generation_service.generate_pillars_until_exhausted(
                project_id,
                model_profiles=_resolve_layer1_profiles(services.config, request.model_aliases),
                thinking_enabled=request.thinking_enabled,
                max_rounds=request.max_rounds,
                target_per_round=request.target_per_round,
                min_new_items_per_round=request.min_new_items_per_round,
                stale_rounds_to_stop=request.stale_rounds_to_stop,
            )
            for node in summary.created_nodes:
                job = services.research_service.enqueue_layer1(project_id, node.id, reason="layer1_generation")
                background_tasks.add_task(services.research_service.run_job, job.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "summary": asdict(summary),
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
            summary = services.generation_service.generate_layer2_feature_graph(
                project_id,
                request.pillar_ids,
                thinking_enabled=request.thinking_enabled,
                max_rounds=request.max_rounds,
                target_per_lens=max(1, min(request.target_per_round, 8)),
            )
            research_job = services.research_service.enqueue_layer2(project_id, reason="layer2_generation")
            background_tasks.add_task(services.research_service.run_job, research_job.id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "summary": summary,
            "research_job": research_job.model_dump(mode="json"),
            "snapshot": _project_snapshot(services, project_id).model_dump(mode="json"),
        }

    @app.post("/api/projects/{project_id}/layer2/review")
    def review_layer2_feature(project_id: str, request: Layer2ReviewActionRequest) -> dict[str, object]:
        """Apply a review decision to the Layer 2 graph and keep rejected concepts in negative memory."""
        try:
            _apply_layer2_review_action(services, project_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer2/features")
    def create_layer2_feature(project_id: str, request: Layer2FeatureCreateRequest) -> dict[str, object]:
        """Manually add one Layer 2 feature into the review workbench."""
        try:
            services.db.get_project(project_id)
            _validate_layer2_owner_pillar(services, project_id, request.owner_pillar_id)
            feature = services.db.create_layer2_feature(
                project_id=project_id,
                canonical_name=request.canonical_name.strip(),
                description=request.description.strip(),
                feature_type=request.feature_type.strip() or "capability",
                granularity_class=request.granularity_class.strip() or "feature",
                owner_pillar_id=request.owner_pillar_id,
                candidate_source_ids=[],
                aliases=request.aliases,
                status=_valid_layer2_status(request.status),
                metadata={
                    "source": "manual",
                    "coverage_family": request.coverage_family,
                    "priority": request.priority,
                    "notes": request.notes,
                },
            )
            services.db.record_layer2_review_action(
                project_id=project_id,
                feature_id=feature.id,
                action_type="manual_add",
                payload={"source": "manual_feature_add"},
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.patch("/api/projects/{project_id}/layer2/features/{feature_id}")
    def update_layer2_feature(project_id: str, feature_id: str, request: Layer2FeatureUpdateRequest) -> dict[str, object]:
        """Inline-edit one Layer 2 feature from the workbench drawer/table."""
        try:
            feature = _get_project_layer2_feature(services, project_id, feature_id)
            if request.owner_pillar_id:
                _validate_layer2_owner_pillar(services, project_id, request.owner_pillar_id)
            services.db.update_layer2_feature(
                feature.id,
                canonical_name=request.canonical_name.strip() if request.canonical_name is not None else None,
                description=request.description.strip() if request.description is not None else None,
                feature_type=request.feature_type.strip() if request.feature_type is not None else None,
                granularity_class=request.granularity_class.strip() if request.granularity_class is not None else None,
                owner_pillar_id=request.owner_pillar_id,
                status=_valid_layer2_status(request.status) if request.status is not None else None,
                coverage_family=request.coverage_family,
                priority=request.priority,
                notes=request.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer2/bulk")
    def bulk_layer2_action(project_id: str, request: Layer2BulkActionRequest) -> dict[str, object]:
        """Apply one review action to many Layer 2 features."""
        try:
            if not request.feature_ids:
                raise ValueError("Select at least one feature for a bulk action.")
            status = "approved" if request.action_type == "approve_for_layer3" else _valid_layer2_status(request.action_type)
            for feature_id in request.feature_ids:
                feature = _get_project_layer2_feature(services, project_id, feature_id)
                services.db.update_layer2_feature(feature.id, status=status)
                services.db.record_layer2_review_action(
                    project_id=project_id,
                    feature_id=feature.id,
                    action_type=request.action_type,
                    payload={**request.payload, "source": "bulk_action"},
                )
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
    def generate_layer3(project_id: str, request: Layer3GenerateRequest) -> dict[str, object]:
        """Generate product-level Capability Design Cards for approved Layer 2 features."""
        try:
            if not request.feature_ids:
                raise ValueError("Select at least one approved Layer 2 feature.")
            _validate_layer3_layer2_gate(services, project_id, request.feature_ids)
            created = services.generation_service.generate_capability_cards(
                project_id,
                request.feature_ids,
                thinking_enabled=request.thinking_enabled,
                selected_sections=request.selected_sections or None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "created": [card.model_dump(mode="json") for card in created],
            "snapshot": _project_snapshot(services, project_id).model_dump(mode="json"),
        }

    @app.patch("/api/projects/{project_id}/layer3/cards/{card_id}")
    def update_layer3_card(project_id: str, card_id: str, request: Layer3CardUpdateRequest) -> dict[str, object]:
        """Persist human edits to product-level card sections."""
        try:
            card = services.db.get_layer3_card(card_id)
            if card.project_id != project_id:
                raise ValueError("Layer 3 card belongs to another project.")
            updates = request.model_dump(exclude_none=True)
            if not updates:
                raise ValueError("Provide at least one Layer 3 card field to update.")
            validate_product_level_content(updates)
            relationships = updates.pop("relationships", None)
            decisions = updates.pop("open_decisions", None)
            if relationships is not None:
                known_feature_ids = {
                    item.id
                    for item in services.db.list_layer2_features(project_id)
                    if item.status in {"kept", "approved"}
                }
                allowed_types = {
                    "depends_on", "feeds", "overlaps_with", "conflicts_with", "optionally_uses", "shared_concern",
                }
                if any(
                    item.get("target_feature_id") not in known_feature_ids
                    or item.get("target_feature_id") == card.feature_id
                    or item.get("relationship_type") not in allowed_types
                    for item in relationships
                ):
                    raise ValueError("Layer 3 relationships require a valid target feature and relationship type.")
                services.db.replace_layer3_relationships(
                    project_id=project_id,
                    card_id=card.id,
                    source_feature_id=card.feature_id,
                    relationships=relationships,
                )
            if decisions is not None:
                services.db.replace_layer3_decisions(
                    project_id=project_id,
                    card_id=card.id,
                    decisions=decisions,
                )
            updates.update({
                "pressure_test": {**card.pressure_test, "stale": True},
                "downstream_readiness_score": 0,
                "readiness_rationale": "Card changed. Rerun the pressure test before approval.",
                "review_state": "needs_review",
            })
            services.db.update_layer3_card(card_id, **updates)
            services.db.record_layer3_review_action(
                project_id=project_id,
                card_id=card_id,
                action_type="edit",
                payload={"fields": sorted(request.model_dump(exclude_none=True))},
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer3/cards/{card_id}/pressure-test")
    def pressure_test_layer3_card(
        project_id: str,
        card_id: str,
        request: Layer3PressureTestRequest,
    ) -> dict[str, object]:
        """Recalculate pressure findings and readiness after human edits."""
        try:
            services.generation_service.pressure_test_capability_card(
                project_id,
                card_id,
                thinking_enabled=request.thinking_enabled,
            )
        except (ValueError, LLMError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/layer3/cards/{card_id}/review")
    def review_layer3_card(project_id: str, card_id: str, request: Layer3ReviewRequest) -> dict[str, object]:
        """Approve, reject, or return a Capability Design Card to review."""
        try:
            card = services.db.get_layer3_card(card_id)
            if card.project_id != project_id:
                raise ValueError("Layer 3 card belongs to another project.")
            if request.action == "approve":
                feature = services.db.get_layer2_feature(card.feature_id)
                if feature.project_id != project_id or feature.status != "approved":
                    raise ValueError("The source Layer 2 feature must still be approved before approving its card.")
                unresolved = [
                    item for item in services.db.list_layer3_decisions(card_id)
                    if item.status == "unresolved"
                ]
                leakage = card.pressure_test.get("implementation_leakage", [])
                if card.pressure_test.get("stale"):
                    raise ValueError("Rerun the Layer 3 pressure test before approval.")
                if unresolved or leakage:
                    raise ValueError("Resolve open decisions and implementation leakage before approval.")
            state = {"approve": "approved", "reject": "rejected", "needs_review": "needs_review"}[request.action]
            services.db.update_layer3_card(card_id, review_state=state)
            services.db.record_layer3_review_action(
                project_id=project_id,
                card_id=card_id,
                action_type=request.action,
                payload={"note": request.note},
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.patch("/api/projects/{project_id}/layer3/decisions/{decision_id}")
    def update_layer3_decision(
        project_id: str,
        decision_id: str,
        request: Layer3DecisionUpdateRequest,
    ) -> dict[str, object]:
        """Resolve or reopen one explicit Layer 3 product decision."""
        try:
            current = services.db.get_layer3_decision(decision_id)
            current_card = services.db.get_layer3_card(current.card_id)
            if current_card.project_id != project_id:
                raise ValueError("Layer 3 decision belongs to another project.")
            resolution = request.resolution.strip()
            if request.status == "resolved" and not resolution:
                raise ValueError("Resolved Layer 3 decisions require a resolution.")
            validate_product_level_content(resolution)
            decision = services.db.update_layer3_decision(
                decision_id,
                status=request.status,
                resolution=resolution,
            )
            card = services.db.get_layer3_card(decision.card_id)
            remaining_decisions = [
                item.model_dump(mode="json")
                for item in services.db.list_layer3_decisions(card.id)
                if item.status == "unresolved"
            ]
            services.db.update_layer3_card(
                card.id,
                downstream_readiness_score=services.generation_service._bounded_layer3_readiness(
                    card.pressure_test,
                    remaining_decisions,
                ),
            )
            services.db.record_layer3_review_action(
                project_id=project_id,
                card_id=card.id,
                action_type=f"decision_{request.status}",
                payload={"decision_id": decision_id, "resolution": resolution},
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"snapshot": _project_snapshot(services, project_id).model_dump(mode="json")}

    @app.post("/api/projects/{project_id}/export", response_model=ExportResponse)
    def export_current_project(project_id: str) -> ExportResponse:
        """Export the full product tree to Markdown and JSON and return the saved paths."""
        try:
            project = services.db.get_project(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        markdown_path, json_path = export_project(
            project,
            services.db.list_all_nodes(project_id),
            Path(services.config.exports_dir),
        )
        return ExportResponse(markdown_path=str(markdown_path), json_path=str(json_path))

    @app.post("/api/projects/{project_id}/export/layer2")
    def export_layer2_graph(project_id: str) -> dict[str, object]:
        """Export Layer 2 Markdown and JSON with current review state included."""
        try:
            project = services.db.get_project(project_id)
            graph = services.db.layer2_graph_snapshot(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in project.name).strip("-")
        markdown_path = export_layer2_markdown(project, graph, Path(services.config.exports_dir))
        output_path = Path(services.config.exports_dir) / f"{slug or project.id}-layer2-graph.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({"project": project.model_dump(mode="json"), "layer2_graph": graph}, indent=2),
            encoding="utf-8",
        )
        return {"markdown_path": str(markdown_path), "json_path": str(output_path), "layer2_graph": graph}

    @app.post("/api/projects/{project_id}/export/layer3")
    def export_layer3_cards(project_id: str) -> dict[str, object]:
        """Export approved Capability Design Cards as a downstream agent manifest."""
        try:
            project = services.db.get_project(project_id)
            brief = services.brief_service.ensure_brief(project_id).model_dump(mode="json")
            layer2_graph = services.db.layer2_graph_snapshot(project_id)
            layer3 = services.db.layer3_snapshot(project_id)
            approved_cards = [
                card for card in layer3.get("cards", [])
                if card.get("review_state") == "approved"
            ]
            if not approved_cards:
                raise ValueError("Approve at least one Capability Design Card before export.")
            feature_statuses = {
                feature.id: feature.status
                for feature in services.db.list_layer2_features(project_id)
            }
            stale_card_ids = [
                card["id"]
                for card in approved_cards
                if feature_statuses.get(card.get("feature_id")) != "approved"
            ]
            if stale_card_ids:
                raise ValueError("Approved Layer 3 cards have Layer 2 sources that are no longer approved.")
            allowed_relationship_targets = {
                feature_id
                for feature_id, status in feature_statuses.items()
                if status in {"kept", "approved"}
            }
            if any(
                edge.get("target_feature_id") not in allowed_relationship_targets
                for card in approved_cards
                for edge in card.get("relationships", [])
            ):
                raise ValueError("Approved Layer 3 cards contain relationships to inactive Layer 2 features.")
            for card in approved_cards:
                validate_product_level_content(card)
            output_path = export_layer3_manifest(
                project,
                brief,
                layer2_graph,
                layer3,
                Path(services.config.exports_dir),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"json_path": str(output_path), "approved_card_count": sum(
            1 for card in layer3.get("cards", []) if card.get("review_state") == "approved"
        )}

    return app


app = create_app()
