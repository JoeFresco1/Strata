from __future__ import annotations

from fastapi import FastAPI, HTTPException

from strata.api_models import SetupCompleteRequest
from strata.api_support import AppServices


def register_setup_routes(app: FastAPI, services: AppServices) -> None:
    """Register first-run configuration routes for self-hosted installations."""

    @app.get("/api/setup/status")
    def setup_status() -> dict[str, object]:
        completed = services.db.get_app_setting("setup_completed") == "true" or bool(services.db.list_projects())
        return {
            "completed": completed,
            "defaults": {
                "llama_base_url": services.config.llama_base_url,
                "model_name": services.config.model_name,
                "embeddings_enabled": services.config.embeddings_enabled,
                "embeddings_model_name": services.config.embeddings_model_name,
            },
        }

    @app.post("/api/setup/complete")
    def complete_setup(request: SetupCompleteRequest) -> dict[str, object]:
        base_url = request.llama_base_url.strip().rstrip("/")
        model_name = request.model_name.strip()
        if not base_url or not model_name:
            raise HTTPException(status_code=400, detail="Model endpoint and model name are required.")
        services.config.llama_base_url = base_url
        services.config.model_name = model_name
        services.config.embeddings_enabled = request.embeddings_enabled
        services.config.embeddings_model_name = request.embeddings_model_name.strip()
        services.generation_service.llm_client.set_base_url(base_url)
        services.generation_service.llm_client.set_model_name(model_name)
        services.generation_service.embedding_service.set_model_name(services.config.embeddings_model_name)
        for key, value in {
            "llama_base_url": base_url,
            "llm_model_name": model_name,
            "embeddings_enabled": str(request.embeddings_enabled).lower(),
            "embeddings_model_name": services.config.embeddings_model_name,
            "setup_completed": "true",
        }.items():
            services.db.set_app_setting(key, value)
        ok, message = services.generation_service.llm_client.healthcheck()
        return {"completed": True, "model_ok": ok, "model_message": message}
