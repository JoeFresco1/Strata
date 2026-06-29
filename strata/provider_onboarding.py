from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests


MODEL_API_KEY_SETTING = "model_api_key"
PROVIDER_READINESS_SETTING = "provider_readiness"
RUNTIME_PRESET_SETTING = "setup_runtime_preset"
CONTEXT_WINDOW_SETTING = "llm_context_window"
MAX_OUTPUT_TOKENS_SETTING = "llm_max_output_tokens"

PROVIDER_READINESS_BLOCK_MESSAGE = (
    "Model-backed workflows are blocked until the configured provider passes validation."
)

RUNTIME_PRESETS = [
    {
        "id": "llama_cpp",
        "label": "llama.cpp",
        "llama_base_url": "http://127.0.0.1:8080",
        "model_name": "local-model",
        "context_window": 32768,
        "max_output_tokens": 1800,
    },
    {
        "id": "lm_studio",
        "label": "LM Studio",
        "llama_base_url": "http://127.0.0.1:1234",
        "model_name": "local-model",
        "context_window": 32768,
        "max_output_tokens": 1800,
    },
    {
        "id": "ollama_gateway",
        "label": "Ollama gateway",
        "llama_base_url": "http://127.0.0.1:11434/v1",
        "model_name": "llama3.1",
        "context_window": 32768,
        "max_output_tokens": 1800,
    },
]


@dataclass(slots=True)
class ProviderValidationResult:
    normalized: dict[str, Any]
    readiness: dict[str, Any]


def provider_readiness_payload(db: Any) -> dict[str, Any]:
    raw = db.get_app_setting(PROVIDER_READINESS_SETTING)
    if not raw:
        return default_provider_readiness()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return default_provider_readiness()
    readiness = default_provider_readiness()
    if isinstance(payload, dict):
        readiness.update(payload)
    return readiness


def default_provider_readiness() -> dict[str, Any]:
    return {
        "ready": False,
        "reachable": False,
        "auth_ok": False,
        "model_listed": False,
        "capability_ok": False,
        "last_checked_at": None,
        "preset": "",
        "error_code": "unverified",
        "message": "Provider setup has not been verified yet.",
    }


def persist_provider_readiness(db: Any, readiness: dict[str, Any]) -> dict[str, Any]:
    safe = default_provider_readiness()
    safe.update(readiness)
    db.set_app_setting(PROVIDER_READINESS_SETTING, json.dumps(safe, ensure_ascii=True))
    return safe


def failed_provider_readiness(normalized: dict[str, Any], message: str, *, error_code: str = "validation_failed") -> dict[str, Any]:
    readiness = default_provider_readiness()
    readiness.update({
        "reachable": False,
        "auth_ok": False,
        "model_listed": False,
        "capability_ok": False,
        "preset": normalized.get("runtime_preset", ""),
        "last_checked_at": datetime.now(timezone.utc).isoformat(),
        "error_code": error_code,
        "message": message,
    })
    return readiness


def has_bearer_token(db: Any) -> bool:
    return bool((db.get_app_setting(MODEL_API_KEY_SETTING) or "").strip())


def stored_bearer_token(db: Any) -> str:
    return (db.get_app_setting(MODEL_API_KEY_SETTING) or "").strip()


def persisted_runtime_preset(db: Any) -> str:
    return (db.get_app_setting(RUNTIME_PRESET_SETTING) or "").strip()


def runtime_presets() -> list[dict[str, Any]]:
    return [dict(item) for item in RUNTIME_PRESETS]


def persist_bearer_token(db: Any, *, token: str | None = None, clear: bool = False) -> None:
    if clear and not token:
        db.set_app_setting(MODEL_API_KEY_SETTING, "")
        return
    if token is not None:
        db.set_app_setting(MODEL_API_KEY_SETTING, token.strip())


def provider_gate_message(db: Any, action_label: str = "Model-backed workflows") -> str:
    readiness = provider_readiness_payload(db)
    message = str(readiness.get("message", "")).strip() or PROVIDER_READINESS_BLOCK_MESSAGE
    return f"{action_label} are blocked. {message}"


def assert_provider_ready(db: Any, action_label: str = "Model-backed workflows") -> None:
    readiness = provider_readiness_payload(db)
    setup_completed = (db.get_app_setting("setup_completed") or "").strip().lower() == "true"
    has_existing_projects = bool(db.list_projects(state="all")) if hasattr(db, "list_projects") else False
    if not setup_completed and not has_existing_projects and readiness.get("error_code") == "unverified":
        return
    if readiness.get("ready"):
        return
    raise ValueError(provider_gate_message(db, action_label))


def provider_status_payload(db: Any, config: Any) -> dict[str, Any]:
    readiness = provider_readiness_payload(db)
    token_saved = has_bearer_token(db)
    presets = runtime_presets()
    return {
        "defaults": {
            "llama_base_url": config.llama_base_url,
            "model_name": config.model_name,
            "embeddings_enabled": config.embeddings_enabled,
            "embeddings_model_name": config.embeddings_model_name,
            "context_window": config.context_size,
            "max_output_tokens": config.max_output_tokens,
            "runtime_preset": persisted_runtime_preset(db),
            "has_bearer_token": token_saved,
            "provider_readiness": readiness,
            "runtime_presets": presets,
        },
        "has_bearer_token": token_saved,
        "provider_readiness": readiness,
        "runtime_presets": presets,
    }


def normalize_provider_payload(payload: dict[str, Any], *, config: Any, db: Any) -> dict[str, Any]:
    base_url = str(payload.get("llama_base_url", config.llama_base_url)).strip().rstrip("/")
    model_name = str(payload.get("model_name", payload.get("llm_model_name", config.model_name))).strip()
    embeddings_model_name = str(payload.get("embeddings_model_name", config.embeddings_model_name)).strip()
    runtime_preset = str(payload.get("runtime_preset", "")).strip()
    bearer_token = str(payload.get("bearer_token", "")).strip()
    clear_bearer_token = bool(payload.get("clear_bearer_token", False))
    context_window = int(payload.get("context_window", config.context_size) or config.context_size)
    max_output_tokens = int(payload.get("max_output_tokens", config.max_output_tokens) or config.max_output_tokens)
    if not base_url:
        raise ValueError("LLM base URL cannot be empty.")
    if not model_name:
        raise ValueError("LLM model name cannot be empty.")
    if not embeddings_model_name:
        raise ValueError("Embedding model name cannot be empty.")
    context_window = max(2048, context_window)
    max_output_tokens = max(256, min(16000, max_output_tokens))
    persisted_token = stored_bearer_token(db)
    effective_token = bearer_token or ("" if clear_bearer_token else persisted_token)
    return {
        "llama_base_url": base_url,
        "model_name": model_name,
        "embeddings_model_name": embeddings_model_name,
        "runtime_preset": runtime_preset,
        "bearer_token": bearer_token,
        "effective_bearer_token": effective_token,
        "clear_bearer_token": clear_bearer_token and not bearer_token,
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
    }


class ProviderValidator:
    """Validate one OpenAI-compatible provider configuration and persist a safe readiness summary."""

    def __init__(self, timeout_seconds: int = 10):
        self.timeout_seconds = timeout_seconds

    def validate(self, normalized: dict[str, Any]) -> ProviderValidationResult:
        base_url = normalized["llama_base_url"]
        model_name = normalized["model_name"]
        token = normalized["effective_bearer_token"]
        self._validate_url(base_url)
        readiness = {
            **default_provider_readiness(),
            "preset": normalized.get("runtime_preset", ""),
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
        }
        headers = {"Authorization": f"Bearer {token}"} if token else None
        try:
            models_response = self._get(f"{base_url}/v1/models", headers=headers, readiness=readiness)
            payload = models_response.json()
            models = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(models, list):
                raise ValueError("The provider returned an unexpected `/v1/models` payload.")
            readiness["reachable"] = True
            readiness["auth_ok"] = True
            readiness["model_listed"] = any(str(item.get("id", "")).strip() == model_name for item in models if isinstance(item, dict))
            if not readiness["model_listed"]:
                available = ", ".join(
                    sorted(
                        str(item.get("id", "")).strip()
                        for item in models
                        if isinstance(item, dict) and str(item.get("id", "")).strip()
                    )[:6]
                )
                details = f" Available models: {available}." if available else ""
                raise ValueError(f"Model `{model_name}` was not returned by `/v1/models`.{details}")
            self._chat_capability_check(base_url, model_name, headers, readiness, normalized["max_output_tokens"])
            readiness.update({
                "ready": True,
                "capability_ok": True,
                "message": f"Connected to `{model_name}` at {base_url}.",
                "error_code": "",
            })
            return ProviderValidationResult(normalized=normalized, readiness=readiness)
        except ValueError as exc:
            readiness["message"] = str(exc)
            setattr(exc, "readiness", readiness)
            raise

    def _validate_url(self, base_url: str) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Model endpoint must be a full http:// or https:// URL.")

    def _get(self, url: str, *, headers: dict[str, str] | None, readiness: dict[str, Any]) -> requests.Response:
        try:
            response = requests.get(url, timeout=self.timeout_seconds, headers=headers)
        except requests.Timeout as exc:
            raise ValueError("The provider timed out while checking `/v1/models`.") from exc
        except requests.ConnectionError as exc:
            raise ValueError("Could not reach the provider endpoint. Check the URL and confirm the server is running.") from exc
        except requests.RequestException as exc:
            raise ValueError(f"Provider validation failed: {exc}") from exc
        if response.status_code in {401, 403}:
            readiness["reachable"] = True
            raise ValueError("The provider rejected the bearer token. Check the token and try again.")
        if response.status_code == 404:
            readiness["reachable"] = True
            raise ValueError("The provider is reachable, but `/v1/models` was not found. Use an OpenAI-compatible base URL.")
        if not response.ok:
            readiness["reachable"] = True
            raise ValueError(f"The provider returned HTTP {response.status_code} while checking `/v1/models`.")
        return response

    def _chat_capability_check(
        self,
        base_url: str,
        model_name: str,
        headers: dict[str, str] | None,
        readiness: dict[str, Any],
        max_output_tokens: int,
    ) -> None:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "Reply with OK."},
                {"role": "user", "content": "Return OK."},
            ],
            "max_tokens": min(16, max_output_tokens),
            "temperature": 0,
            "stream": False,
        }
        try:
            response = requests.post(
                f"{base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout_seconds,
                headers=headers,
            )
        except requests.Timeout as exc:
            raise ValueError("The provider timed out during the chat capability check.") from exc
        except requests.ConnectionError as exc:
            raise ValueError("The provider became unreachable during the chat capability check.") from exc
        except requests.RequestException as exc:
            raise ValueError(f"Chat capability validation failed: {exc}") from exc
        if response.status_code in {401, 403}:
            raise ValueError("The provider rejected the bearer token during the chat capability check.")
        if response.status_code == 404:
            raise ValueError("The provider is reachable, but `/v1/chat/completions` is missing.")
        if not response.ok:
            raise ValueError(f"The provider returned HTTP {response.status_code} during the chat capability check.")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError("The provider returned an unexpected chat completion payload.") from exc
        if not str(content).strip():
            raise ValueError("The provider chat capability check returned an empty response.")
