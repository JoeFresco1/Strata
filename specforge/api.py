from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from specforge.api_models import (
    AppConfigResponse,
    AppSnapshotResponse,
    ExportResponse,
    Layer0ChatRequest,
    Layer0ChatResponse,
    Layer1GenerateRequest,
    Layer2GenerateRequest,
    Layer2ReviewActionRequest,
    Layer3GenerateRequest,
    ModelProfileResponse,
    NodeUpdateRequest,
    ProjectBriefUpdateRequest,
    ProjectCreateRequest,
    PublishBriefResponse,
    ProjectModelSettingsUpdateRequest,
    ResearchStartRequest,
    RuntimeModelSettingsUpdateRequest,
)
from specforge.brief import BriefService
from specforge.config import (
    AppConfig,
    EMBEDDING_MODEL_PRESETS,
    build_model_profiles,
    describe_database_target,
    ensure_runtime_dirs,
    resolve_default_model_profile,
)
from specforge.db import Database
from specforge.embeddings import EmbeddingService
from specforge.export import export_project
from specforge.generation import GenerationService
from specforge.llm import LLMError, LlamaCppClient
from specforge.research import ResearchService
from specforge.project_settings import (
    DEFAULT_EMBEDDING_PROFILE_ID,
    DEFAULT_LLM_PROFILE_ID,
    default_app_model_settings,
    default_project_model_settings,
    normalize_model_settings,
    normalize_project_model_settings,
)
from specforge.prompts import load_prompt_catalog
from specforge.server_manager import LlamaServerManager
from specforge.storage import build_database
from specforge.tree import build_tree


@dataclass(slots=True)
class AppServices:
    config: AppConfig
    db: Database
    generation_service: GenerationService
    brief_service: BriefService
    research_service: ResearchService


def _normalize_runtime_model_defaults(config: AppConfig) -> None:
    """Repair stale runtime model settings when a previously saved GGUF path no longer exists."""
    profiles = build_model_profiles(config)
    default_profile = resolve_default_model_profile(config, profiles)
    preferred_path = Path(config.preferred_model_path) if config.preferred_model_path else None

    if preferred_path is not None and not preferred_path.exists():
        config.preferred_model_path = str(default_profile.path) if default_profile and default_profile.path else None
        if default_profile is not None:
            config.model_name = default_profile.alias
        return

    if preferred_path is None and default_profile is not None and default_profile.path is not None:
        config.preferred_model_path = str(default_profile.path)
        if not (config.model_name or "").strip():
            config.model_name = default_profile.alias

    if preferred_path is not None and preferred_path.exists():
        matching_profile = next((profile for profile in profiles if profile.path == preferred_path), None)
        if matching_profile is not None and not (config.model_name or "").strip():
            config.model_name = matching_profile.alias


def _build_services() -> AppServices:
    """Create the shared application services used by the localhost API."""
    config = AppConfig()
    ensure_runtime_dirs(config)
    db = build_database(config)
    persisted_llama_base_url = db.get_app_setting("llama_base_url")
    persisted_llm_model_name = db.get_app_setting("llm_model_name")
    persisted_preferred_model_path = db.get_app_setting("preferred_model_path")
    persisted_embedding_model = db.get_app_setting("embeddings_model_name")
    if persisted_llama_base_url:
        config.llama_base_url = persisted_llama_base_url
    if persisted_llm_model_name:
        config.model_name = persisted_llm_model_name
    if persisted_preferred_model_path:
        config.preferred_model_path = persisted_preferred_model_path
    if persisted_embedding_model:
        config.embeddings_model_name = persisted_embedding_model
    _normalize_runtime_model_defaults(config)
    llm_client = LlamaCppClient(config)
    server_manager = LlamaServerManager(config)
    embedding_service = EmbeddingService(config)
    db.set_app_setting("llama_base_url", config.llama_base_url)
    db.set_app_setting("llm_model_name", config.model_name)
    db.set_app_setting("preferred_model_path", config.preferred_model_path or "")
    db.set_app_setting("embeddings_model_name", embedding_service.model_name)
    return AppServices(
        config=config,
        db=db,
        generation_service=GenerationService(db, llm_client, server_manager, embedding_service),
        brief_service=BriefService(db, llm_client, server_manager),
        research_service=ResearchService(db, llm_client, embedding_service, server_manager),
    )


def _project_snapshot(services: AppServices, project_id: str) -> AppSnapshotResponse:
    """Return the full project state needed by the React client in one payload."""
    project = services.db.get_project(project_id)
    nodes = services.db.list_all_nodes(project_id)
    memory = services.db.list_project_memory(project_id)
    brief = services.brief_service.ensure_brief(project_id)
    model_settings = _ensure_project_model_settings(services, project_id)
    conversation = services.db.list_brief_conversation(project_id)
    jobs = services.db.list_research_jobs(project_id)
    findings = services.db.list_research_findings(project_id)
    return AppSnapshotResponse(
        project=project.model_dump(mode="json"),
        brief=brief.model_dump(mode="json"),
        project_model_settings=model_settings.model_dump(mode="json"),
        brief_conversation=[turn.model_dump(mode="json") for turn in conversation],
        nodes=[node.model_dump(mode="json") for node in nodes],
        tree=build_tree(nodes),
        memory=[item.model_dump(mode="json") for item in memory],
        research_jobs=[job.model_dump(mode="json") for job in jobs],
        research_findings=[finding.model_dump(mode="json") for finding in findings],
        layer2_graph=services.db.layer2_graph_snapshot(project_id),
    )


def _load_app_model_settings(services: AppServices) -> dict[str, object]:
    """Load reusable app-level profiles and assignments from persisted settings."""
    raw_llm_profiles = services.db.get_app_setting("app_llm_profiles")
    raw_embedding_profiles = services.db.get_app_setting("app_embedding_profiles")
    raw_assignments = services.db.get_app_setting("app_assignments")
    raw_prompt_catalog = services.db.get_app_setting("app_prompt_catalog")
    payload: dict[str, object] = {}
    try:
        payload["llm_profiles"] = json.loads(raw_llm_profiles) if raw_llm_profiles else []
    except json.JSONDecodeError:
        payload["llm_profiles"] = []
    try:
        payload["embedding_profiles"] = json.loads(raw_embedding_profiles) if raw_embedding_profiles else []
    except json.JSONDecodeError:
        payload["embedding_profiles"] = []
    try:
        payload["assignments"] = json.loads(raw_assignments) if raw_assignments else {}
    except json.JSONDecodeError:
        payload["assignments"] = {}
    try:
        payload["prompt_catalog"] = json.loads(raw_prompt_catalog) if raw_prompt_catalog else load_prompt_catalog()
    except json.JSONDecodeError:
        payload["prompt_catalog"] = load_prompt_catalog()
    return normalize_model_settings(payload, services.config)


def _persist_app_model_settings(services: AppServices, settings: dict[str, object]) -> None:
    """Persist reusable app-level profiles and assignment defaults."""
    services.db.set_app_setting("app_llm_profiles", json.dumps(settings.get("llm_profiles", [])))
    services.db.set_app_setting("app_embedding_profiles", json.dumps(settings.get("embedding_profiles", [])))
    services.db.set_app_setting("app_assignments", json.dumps(settings.get("assignments", {})))
    services.db.set_app_setting("app_prompt_catalog", json.dumps(settings.get("prompt_catalog", {})))


def _sync_default_app_profiles(settings: dict[str, object], services: AppServices) -> dict[str, object]:
    """Keep the built-in global default profiles aligned with runtime defaults."""
    llm_profiles = list(settings.get("llm_profiles", []))
    embedding_profiles = list(settings.get("embedding_profiles", []))
    for profile in llm_profiles:
        if str(profile.get("id", "")).strip() == DEFAULT_LLM_PROFILE_ID:
            profile["base_url"] = services.config.llama_base_url
            profile["model_name"] = services.config.model_name
            profile["local_path"] = services.config.preferred_model_path or ""
    for profile in embedding_profiles:
        if str(profile.get("id", "")).strip() == DEFAULT_EMBEDDING_PROFILE_ID:
            profile["model_name"] = services.config.embeddings_model_name
    return {
        **settings,
        "llm_profiles": llm_profiles,
        "embedding_profiles": embedding_profiles,
    }


def _resolve_layer1_profiles(config: AppConfig, aliases: list[str]):
    """Map requested model aliases to discovered GGUF profiles for Layer 1 sequencing."""
    profiles = build_model_profiles(config)
    if not aliases:
        return []
    by_alias = {profile.alias: profile for profile in profiles}
    missing = [alias for alias in aliases if alias not in by_alias]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown model aliases: {', '.join(missing)}")
    return [by_alias[alias] for alias in aliases]


def _ensure_project_model_settings(services: AppServices, project_id: str):
    """Return project model settings, creating a default record from app config when missing."""
    existing = services.db.get_project_model_settings(project_id)
    if existing is not None:
        default_prompts = load_prompt_catalog()
        if not existing.prompt_catalog or set(default_prompts) - set(existing.prompt_catalog):
            payload = existing.model_dump(mode="json")
            payload["prompt_catalog"] = {**default_prompts, **existing.prompt_catalog}
            payload.pop("project_id", None)
            payload.pop("created_at", None)
            payload.pop("updated_at", None)
            return services.db.upsert_project_model_settings(project_id=project_id, **payload)
        return existing
    payload = default_project_model_settings(services.config, _load_app_model_settings(services))
    return services.db.upsert_project_model_settings(project_id=project_id, **payload)


def _get_project_layer2_feature(services: AppServices, project_id: str, feature_id: str):
    """Return a Layer 2 feature only when it belongs to the active project."""
    feature = services.db.get_layer2_feature(feature_id)
    if feature.project_id != project_id:
        raise ValueError(f"Layer 2 feature does not belong to project: {feature_id}")
    return feature


def _validate_layer2_owner_pillar(services: AppServices, project_id: str, pillar_id: str) -> None:
    """Ensure owner reassignment targets a Layer 1 pillar in the active project."""
    pillar = services.db.get_node(pillar_id)
    if pillar.project_id != project_id or pillar.layer != 1 or pillar.node_type != "pillar":
        raise ValueError("Layer 2 owner must be a Layer 1 pillar in the active project.")


def _apply_layer2_review_action(
    services: AppServices,
    project_id: str,
    request: Layer2ReviewActionRequest,
) -> None:
    """Apply one Layer 2 review action and persist the audit record."""
    services.db.get_project(project_id)
    feature = _get_project_layer2_feature(services, project_id, request.feature_id) if request.feature_id else None
    payload = request.payload or {}
    if request.action_type == "keep" and feature is not None:
        services.db.update_layer2_feature(feature.id, status="kept")
    elif request.action_type == "cut" and feature is not None:
        feature = services.db.update_layer2_feature(feature.id, status="cut")
        services.db.create_layer2_negative_cache_entry(
            project_id=project_id,
            rejected_name=feature.canonical_name,
            semantic_cluster=payload.get("semantic_cluster") or feature.canonical_name.lower(),
            rejected_aliases=feature.aliases,
            rejected_from_pillar_id=feature.owner_pillar_id,
        )
    elif request.action_type == "rename" and feature is not None:
        if not request.title:
            raise ValueError("Rename requires a title.")
        services.db.update_layer2_feature(
            feature.id,
            canonical_name=request.title.strip(),
            description=request.description.strip() if request.description else None,
            status="renamed",
        )
    elif request.action_type == "reassign_owner" and feature is not None:
        if not request.owner_pillar_id:
            raise ValueError("Owner reassignment requires owner_pillar_id.")
        _validate_layer2_owner_pillar(services, project_id, request.owner_pillar_id)
        services.db.update_layer2_feature(feature.id, owner_pillar_id=request.owner_pillar_id, status="kept")
    elif request.action_type == "merge" and feature is not None:
        _record_layer2_merge(services, project_id, feature.id, request, payload)
    elif request.action_type == "add_relationship":
        _record_layer2_relationship(services, project_id, request, payload)
    elif request.action_type == "remove_relationship":
        _remove_layer2_relationship(services, project_id, request)
    elif request.action_type == "prioritize" and feature is not None:
        services.db.update_layer2_feature(feature.id, metadata={**feature.metadata, "priority": payload.get("priority", "high")})
    elif request.action_type == "approve_for_layer3" and feature is not None:
        services.db.update_layer2_feature(feature.id, status="approved")
    else:
        raise ValueError(f"Unsupported Layer 2 review action: {request.action_type}")
    services.db.record_layer2_review_action(
        project_id=project_id,
        feature_id=request.feature_id,
        action_type=request.action_type,
        payload={
            **payload,
            "target_feature_id": request.target_feature_id,
            "owner_pillar_id": request.owner_pillar_id,
            "relationship_type": request.relationship_type,
        },
    )


def _record_layer2_merge(
    services: AppServices,
    project_id: str,
    feature_id: str,
    request: Layer2ReviewActionRequest,
    payload: dict[str, object],
) -> None:
    """Record a duplicate edge and mark the source feature merged."""
    if not request.target_feature_id:
        raise ValueError("Merge requires target_feature_id.")
    _get_project_layer2_feature(services, project_id, request.target_feature_id)
    services.db.insert_layer2_relationship(
        project_id=project_id,
        source_feature_id=feature_id,
        target_feature_id=request.target_feature_id,
        relationship_type="duplicate_of",
        strength=float(payload.get("strength", 1.0)),
        rationale=str(payload.get("rationale", "Reviewer merged duplicate Layer 2 features.")),
    )
    services.db.update_layer2_feature(feature_id, status="merged")


def _record_layer2_relationship(
    services: AppServices,
    project_id: str,
    request: Layer2ReviewActionRequest,
    payload: dict[str, object],
) -> None:
    """Create a reviewer-approved Layer 2 relationship edge."""
    if not request.feature_id or not request.target_feature_id:
        raise ValueError("Relationship actions require feature_id and target_feature_id.")
    _get_project_layer2_feature(services, project_id, request.feature_id)
    _get_project_layer2_feature(services, project_id, request.target_feature_id)
    services.db.insert_layer2_relationship(
        project_id=project_id,
        source_feature_id=request.feature_id,
        target_feature_id=request.target_feature_id,
        relationship_type=request.relationship_type or "related_to",
        strength=float(payload.get("strength", 0.75)),
        rationale=str(payload.get("rationale", "Reviewer added relationship.")),
    )


def _remove_layer2_relationship(
    services: AppServices,
    project_id: str,
    request: Layer2ReviewActionRequest,
) -> None:
    """Remove a reviewer-selected Layer 2 relationship edge."""
    if not request.feature_id or not request.target_feature_id:
        raise ValueError("Relationship actions require feature_id and target_feature_id.")
    removed = services.db.delete_layer2_relationship(
        project_id=project_id,
        source_feature_id=request.feature_id,
        target_feature_id=request.target_feature_id,
        relationship_type=request.relationship_type,
    )
    if removed == 0:
        raise ValueError("No matching Layer 2 relationship was found to remove.")


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
            reply, brief, guidance = services.brief_service.append_plan_turn(project_id, request.message)
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
    def generate_layer2(project_id: str, request: Layer2GenerateRequest) -> dict[str, object]:
        """Run graph-native Layer 2 feature generation for selected kept pillars."""
        try:
            summary = services.generation_service.generate_layer2_feature_graph(
                project_id,
                request.pillar_ids,
                thinking_enabled=request.thinking_enabled,
                max_rounds=request.max_rounds,
                target_per_lens=max(1, min(request.target_per_round, 8)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "summary": summary,
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

    @app.post("/api/projects/{project_id}/generate/layer3")
    def generate_layer3(project_id: str, request: Layer3GenerateRequest) -> dict[str, object]:
        """Generate implementation-ready spec nodes for selected subfeatures."""
        try:
            created = services.generation_service.generate_specs(
                project_id,
                request.subfeature_ids,
                thinking_enabled=request.thinking_enabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "created": [node.model_dump(mode="json") for node in created],
            "snapshot": _project_snapshot(services, project_id).model_dump(mode="json"),
        }

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
        """Export structured Layer 2 graph JSON only after human review clears the queue."""
        try:
            project = services.db.get_project(project_id)
            graph = services.db.layer2_graph_snapshot(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if graph.get("review_open"):
            raise HTTPException(
                status_code=409,
                detail="Layer 2 still has candidate or needs_review features. Review them before structured export.",
            )
        slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in project.name).strip("-")
        output_path = Path(services.config.exports_dir) / f"{slug or project.id}-layer2-graph.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({"project": project.model_dump(mode="json"), "layer2_graph": graph}, indent=2),
            encoding="utf-8",
        )
        return {"json_path": str(output_path), "layer2_graph": graph}

    return app


app = create_app()
