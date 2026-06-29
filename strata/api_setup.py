from __future__ import annotations

from fastapi import FastAPI, HTTPException

from strata.api_models import SetupCompleteRequest
from strata.api_support import AppServices, _apply_runtime_provider_update
from strata.provider_onboarding import provider_status_payload


def register_setup_routes(app: FastAPI, services: AppServices) -> None:
    """Register first-run configuration routes for self-hosted installations."""

    @app.get("/api/setup/status")
    def setup_status() -> dict[str, object]:
        completed = services.db.get_app_setting("setup_completed") == "true" or bool(services.db.list_projects())
        return {"completed": completed, **provider_status_payload(services.db, services.config)}

    @app.post("/api/setup/complete")
    def complete_setup(request: SetupCompleteRequest) -> dict[str, object]:
        try:
            services.config.embeddings_enabled = request.embeddings_enabled
            services.db.set_app_setting("embeddings_enabled", str(request.embeddings_enabled).lower())
            readiness = _apply_runtime_provider_update(
                services,
                request.model_dump(mode="json"),
                mark_setup_completed=True,
                allow_unready=True,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": str(exc),
                    "provider_readiness": provider_status_payload(services.db, services.config)["provider_readiness"],
                },
            ) from exc
        return {
            "completed": True,
            "model_ok": bool(readiness.get("ready")),
            "model_message": readiness.get("message", ""),
            "has_bearer_token": provider_status_payload(services.db, services.config)["has_bearer_token"],
            "provider_readiness": readiness,
        }
