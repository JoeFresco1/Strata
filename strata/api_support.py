from __future__ import annotations

import json
from dataclasses import dataclass
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
from strata.jobs import PlatformJobService
from strata.layer3_service import validate_product_level_content
from strata.llm import LlamaCppClient
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


@dataclass(slots=True)
class AppServices:
    config: AppConfig
    db: Database
    generation_service: GenerationService
    brief_service: BriefService
    research_service: ResearchService
    assistant_service: AssistantService
    job_service: PlatformJobService | None = None


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


def _build_services(config: AppConfig | None = None) -> AppServices:
    """Create the shared application services used by the localhost API."""
    config = config or AppConfig()
    ensure_runtime_dirs(config)
    db = build_database(config)
    db.recover_interrupted_platform_jobs()
    db.recover_interrupted_assistant_runs()
    db.recover_interrupted_research_jobs()
    persisted_llama_base_url = db.get_app_setting("llama_base_url")
    persisted_llm_model_name = db.get_app_setting("llm_model_name")
    persisted_preferred_model_path = db.get_app_setting("preferred_model_path")
    persisted_embedding_model = db.get_app_setting("embeddings_model_name")
    persisted_embeddings_enabled = db.get_app_setting("embeddings_enabled")
    if persisted_llama_base_url:
        config.llama_base_url = persisted_llama_base_url
    if persisted_llm_model_name:
        config.model_name = persisted_llm_model_name
    if persisted_preferred_model_path:
        config.preferred_model_path = persisted_preferred_model_path
    if persisted_embedding_model:
        config.embeddings_model_name = persisted_embedding_model
    if persisted_embeddings_enabled:
        config.embeddings_enabled = persisted_embeddings_enabled == "true"
    _normalize_runtime_model_defaults(config)
    llm_client = LlamaCppClient(config, telemetry_store=db)
    server_manager = LlamaServerManager(config)
    embedding_service = EmbeddingService(config)
    db.set_app_setting("llama_base_url", config.llama_base_url)
    db.set_app_setting("llm_model_name", config.model_name)
    db.set_app_setting("preferred_model_path", config.preferred_model_path or "")
    db.set_app_setting("embeddings_model_name", embedding_service.model_name)
    assistant_index = AssistantIndexService(db, embedding_service)
    services = AppServices(
        config=config,
        db=db,
        generation_service=GenerationService(db, llm_client, server_manager, embedding_service),
        brief_service=BriefService(db, llm_client, server_manager),
        research_service=ResearchService(db, llm_client, embedding_service, server_manager),
        assistant_service=AssistantService(db, llm_client, assistant_index, server_manager),
    )
    services.job_service = PlatformJobService(services)
    return services


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
    layer2_graph = services.db.layer2_graph_snapshot(project_id)
    layer3 = services.db.layer3_snapshot(project_id)
    workspace_state = services.db.get_project_workspace_state(project_id)
    valid_pillar_ids = {node.id for node in nodes if node.layer == 1 and node.node_type == "pillar"}
    valid_feature_ids = {str(item.get("id")) for item in layer2_graph.get("features", [])}
    if workspace_state is None:
        workspace_state = services.db.upsert_project_workspace_state(
            project_id=project_id,
            view_mode="map",
            selected_entity_type="brief",
            selected_entity_id="layer0-root",
            table_scope="focused",
            map_state={},
            table_state={},
        )
    elif (
        workspace_state.selected_entity_type == "pillar"
        and workspace_state.selected_entity_id not in valid_pillar_ids
    ) or (
        workspace_state.selected_entity_type == "feature"
        and workspace_state.selected_entity_id not in valid_feature_ids
    ):
        workspace_state = services.db.upsert_project_workspace_state(
            project_id=project_id,
            view_mode=workspace_state.view_mode,
            selected_entity_type="brief",
            selected_entity_id="layer0-root",
            table_scope=workspace_state.table_scope,
            map_state=workspace_state.map_state,
            table_state=workspace_state.table_state,
        )
    return AppSnapshotResponse(
        project=project.model_dump(mode="json"),
        brief=brief.model_dump(mode="json"),
        project_model_settings=model_settings.model_dump(mode="json"),
        workspace_state=workspace_state.model_dump(mode="json"),
        brief_conversation=[turn.model_dump(mode="json") for turn in conversation],
        nodes=[node.model_dump(mode="json") for node in nodes],
        tree=build_tree(nodes),
        memory=[item.model_dump(mode="json") for item in memory],
        research_jobs=[job.model_dump(mode="json") for job in jobs],
        research_findings=[finding.model_dump(mode="json") for finding in findings],
        layer2_graph=layer2_graph,
        layer3=layer3,
    )


def _load_app_model_settings(services: AppServices) -> dict[str, object]:
    """Load reusable app-level profiles and assignments from persisted settings."""
    raw_llm_profiles = services.db.get_app_setting("app_llm_profiles")
    raw_embedding_profiles = services.db.get_app_setting("app_embedding_profiles")
    raw_execution_intent = services.db.get_app_setting("app_execution_intent")
    raw_routing_policy = services.db.get_app_setting("app_routing_policy")
    raw_concurrency_policy = services.db.get_app_setting("app_concurrency_policy")
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
    payload["execution_intent"] = raw_execution_intent or ""
    try:
        payload["routing_policy"] = json.loads(raw_routing_policy) if raw_routing_policy else {}
    except json.JSONDecodeError:
        payload["routing_policy"] = {}
    try:
        payload["concurrency_policy"] = json.loads(raw_concurrency_policy) if raw_concurrency_policy else {}
    except json.JSONDecodeError:
        payload["concurrency_policy"] = {}
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
    services.db.set_app_setting("app_execution_intent", str(settings.get("execution_intent", "local_first")))
    services.db.set_app_setting("app_routing_policy", json.dumps(settings.get("routing_policy", {})))
    services.db.set_app_setting("app_concurrency_policy", json.dumps(settings.get("concurrency_policy", {})))
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
        payload = existing.model_dump(mode="json")
        normalized = normalize_project_model_settings(payload, services.config)
        current = {
            key: payload[key]
            for key in ("llm_profiles", "embedding_profiles", "execution_intent", "routing_policy", "concurrency_policy", "assignments", "prompt_catalog")
        }
        if normalized != current:
            return services.db.upsert_project_model_settings(project_id=project_id, **normalized)
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


def _valid_layer2_status(status: str) -> str:
    """Normalize UI-provided Layer 2 status values."""
    allowed = {"candidate", "kept", "cut", "merged", "renamed", "needs_review", "approved"}
    cleaned = status.strip().lower()
    if cleaned == "approve_for_layer3":
        return "approved"
    if cleaned == "keep":
        return "kept"
    if cleaned not in allowed:
        raise ValueError(f"Unsupported Layer 2 status: {status}")
    return cleaned


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
        embedding_model = services.generation_service._embedding_model_name(project_id, "layer1_similarity_embeddings")
        embedding = services.generation_service._layer2_embedding(
            f"{feature.canonical_name} {feature.description} {' '.join(feature.aliases)}",
            embedding_model,
        )
        services.db.create_layer2_negative_cache_entry(
            project_id=project_id,
            rejected_name=feature.canonical_name,
            semantic_cluster=payload.get("semantic_cluster") or feature.canonical_name.lower(),
            rejected_aliases=feature.aliases,
            rejected_from_pillar_id=feature.owner_pillar_id,
            embedding_model=embedding_model,
            embedding=embedding,
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


def _validate_layer3_layer2_gate(services: AppServices, project_id: str, target_ids: list[str]) -> None:
    """Reject Layer 3 generation when graph-native Layer 2 features are not approved."""
    unapproved: list[str] = []
    checked_count = 0
    for target_id in target_ids:
        try:
            feature = services.db.get_layer2_feature(target_id)
        except ValueError:
            continue
        if feature.project_id != project_id:
            continue
        checked_count += 1
        if feature.status != "approved":
            unapproved.append(feature.id)
    if unapproved:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Layer 3 generation requires approved Layer 2 features.",
                "unapproved_feature_count": len(unapproved),
                "unapproved_feature_ids": unapproved,
                "checked_layer2_feature_count": checked_count,
            },
        )


def _execute_assistant_action(
    services: AppServices,
    proposal,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    """Execute one confirmed allowlisted proposal through canonical application services."""
    payload = proposal.payload
    project_id = proposal.project_id
    if proposal.action_type == "update_brief":
        brief = services.db.get_project_brief(project_id)
        if brief is None:
            raise ValueError("Project brief is missing.")
        allowed = {
            "product_idea", "known_competitors", "constraints", "target_users", "goals",
            "preferred_directions", "rejected_directions", "notes",
        }
        updates = {**brief.model_dump(mode="json"), **{key: value for key, value in payload.items() if key in allowed}}
        return {"brief": services.brief_service.update_brief(project_id, updates).model_dump(mode="json")}
    if proposal.action_type == "update_node":
        node = services.db.get_node(str(payload.get("node_id", "")))
        if node.project_id != project_id:
            raise ValueError("Node belongs to another project.")
        allowed = {"title", "description", "status", "priority"}
        updates = {key: value for key, value in payload.items() if key in allowed}
        return {"node": services.db.update_node(node.id, **updates).model_dump(mode="json")}
    if proposal.action_type == "layer2_review":
        review = Layer2ReviewActionRequest(**payload)
        _apply_layer2_review_action(services, project_id, review)
        return {"feature_id": review.feature_id, "action_type": review.action_type}
    if proposal.action_type == "update_layer2_feature":
        feature_id = str(payload.get("feature_id", ""))
        feature = _get_project_layer2_feature(services, project_id, feature_id)
        allowed = {
            "canonical_name", "description", "feature_type", "granularity_class",
            "owner_pillar_id", "status", "coverage_family",
        }
        updates = {key: value for key, value in payload.items() if key in allowed}
        if "owner_pillar_id" in updates:
            _validate_layer2_owner_pillar(services, project_id, str(updates["owner_pillar_id"]))
        if "status" in updates:
            updates["status"] = _valid_layer2_status(str(updates["status"]))
        updated = services.db.update_layer2_feature(feature.id, **updates)
        return {"feature": updated.model_dump(mode="json")}
    if proposal.action_type == "run_layer1_research":
        pillar_ids = payload.get("pillar_ids") or [
            node.id for node in services.db.list_nodes(project_id, parent_id=None, layer=1, node_type="pillar")
        ]
        jobs = [services.research_service.enqueue_layer1(project_id, str(item), reason="assistant") for item in pillar_ids]
        platform_jobs = []
        for job in jobs:
            platform_job = services.job_service.enqueue(
                project_id=project_id,
                kind="research",
                workflow="research",
                scope="layer1",
                scope_id=job.scope_id,
                request_payload={"research_job_id": job.id, "research_job_type": job.job_type},
                dedupe_key=f"research:{job.id}",
            )
            platform_jobs.append(platform_job)
            background_tasks.add_task(services.job_service.run_job, platform_job.id)
        return {"job_ids": [job.id for job in jobs], "platform_job_ids": [job.id for job in platform_jobs]}
    if proposal.action_type == "run_layer2_research":
        job = services.research_service.enqueue_layer2(
            project_id,
            feature_ids=[str(item) for item in payload.get("feature_ids", [])] or None,
            reason="assistant",
        )
        platform_job = services.job_service.enqueue(
            project_id=project_id,
            kind="research",
            workflow="research",
            scope="layer2",
            request_payload={"research_job_id": job.id, "research_job_type": job.job_type},
            dedupe_key=f"research:{job.id}",
        )
        background_tasks.add_task(services.job_service.run_job, platform_job.id)
        return {"job_id": job.id, "platform_job_id": platform_job.id}
    if proposal.action_type == "generate_layer1":
        job = services.job_service.enqueue(
            project_id=project_id,
            kind="generation",
            workflow="layer1_generation",
            scope="layer1",
            request_payload={},
            dedupe_key=f"generation:layer1:{project_id}:assistant",
        )
        background_tasks.add_task(services.job_service.run_job, job.id)
        return {"queued": True, "layer": 1, "platform_job_id": job.id}
    if proposal.action_type == "generate_layer2":
        pillar_ids = [str(item) for item in payload.get("pillar_ids", [])]
        if not pillar_ids:
            raise ValueError("Layer 2 generation requires pillar_ids.")
        job = services.job_service.enqueue(
            project_id=project_id,
            kind="generation",
            workflow="layer2_generation",
            scope="layer2",
            request_payload={"pillar_ids": pillar_ids},
            dedupe_key=f"generation:layer2:{project_id}:assistant:{','.join(pillar_ids)}",
        )
        background_tasks.add_task(services.job_service.run_job, job.id)
        return {"queued": True, "layer": 2, "pillar_ids": pillar_ids, "platform_job_id": job.id}
    if proposal.action_type == "generate_layer3":
        feature_ids = [str(item) for item in payload.get("feature_ids", [])]
        _validate_layer3_layer2_gate(services, project_id, feature_ids)
        job = services.job_service.enqueue(
            project_id=project_id,
            kind="generation",
            workflow="layer3_generation",
            scope="layer3",
            request_payload={"feature_ids": feature_ids},
            dedupe_key=f"generation:layer3:{project_id}:assistant:{','.join(feature_ids)}",
        )
        background_tasks.add_task(services.job_service.run_job, job.id)
        return {"queued": True, "layer": 3, "feature_ids": feature_ids, "platform_job_id": job.id}
    raise ValueError(f"Unsupported assistant action: {proposal.action_type}")


