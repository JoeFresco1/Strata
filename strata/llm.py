from __future__ import annotations

import json
import re
import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from strata.config import AppConfig


class LLMError(RuntimeError):
    pass


@dataclass(slots=True)
class LLMResponse:
    content: str
    parsed_json: dict[str, Any]
    model_name: str | None
    raw_payload: dict[str, Any]


class LlamaCppClient:
    def __init__(self, config: AppConfig, telemetry_store: Any | None = None):
        """Configure the OpenAI-compatible client and optional durable telemetry sink."""
        self.base_url = config.llama_base_url.rstrip("/")
        self.timeout = config.llama_timeout_seconds
        self.default_temperature = config.default_temperature
        self.default_top_p = config.default_top_p
        self.model_name = config.model_name
        self.api_key = config.model_api_key
        self.telemetry_store = telemetry_store

    def set_base_url(self, base_url: str) -> None:
        """Switch the OpenAI-compatible chat endpoint used for model calls."""
        cleaned = base_url.strip().rstrip("/")
        if not cleaned:
            raise ValueError("LLM base URL cannot be empty.")
        self.base_url = cleaned

    def set_model_name(self, model_name: str) -> None:
        """Switch the default chat model id sent to the endpoint."""
        cleaned = model_name.strip()
        if not cleaned:
            raise ValueError("LLM model name cannot be empty.")
        self.model_name = cleaned

    def set_api_key(self, api_key: str) -> None:
        """Switch the bearer token used for OpenAI-compatible requests."""
        self.api_key = api_key.strip()

    @staticmethod
    def _strip_reasoning_wrappers(content: str) -> str:
        cleaned = re.sub(r"(?is)<think>\s*</think>\s*", "", content).strip()
        cleaned = re.sub(r"(?is)^<think>.*?</think>\s*", "", cleaned).strip()
        cleaned = re.sub(r"(?is)^<\|?channel\|?>\s*(?:thought|analysis)\s*", "", cleaned).strip()
        cleaned = re.sub(r"(?is)^<\|?channel\|?>\s*", "", cleaned).strip()
        cleaned = re.sub(r"(?is)^```(?:json)?\s*", "", cleaned).strip()
        cleaned = re.sub(r"(?is)\s*```$", "", cleaned).strip()
        extracted = LlamaCppClient._extract_first_json_block(cleaned)
        if extracted:
            return extracted
        return cleaned

    @staticmethod
    def _extract_first_json_block(content: str) -> str | None:
        """Recover the first balanced JSON object or array from noisy model output."""
        start = -1
        opening = ""
        closing = ""
        for marker, closing_marker in (("{", "}"), ("[", "]")):
            position = content.find(marker)
            if position != -1 and (start == -1 or position < start):
                start = position
                opening, closing = marker, closing_marker
        if start == -1:
            return None

        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(content)):
            char = content[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == opening:
                depth += 1
                continue
            if char == closing:
                depth -= 1
                if depth == 0:
                    return content[start : index + 1].strip()
        return None

    def healthcheck(self) -> tuple[bool, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
        for path in ("/v1/models", "/health"):
            try:
                response = requests.get(
                    f"{self.base_url}{path}",
                    timeout=10,
                    headers=headers,
                )
                if response.status_code in {401, 403}:
                    return False, "Provider rejected the configured bearer token."
                if response.status_code == 404 and path == "/v1/models":
                    return False, "Provider is reachable, but `/v1/models` is missing."
                if response.ok:
                    return True, f"Reachable via {path}"
            except requests.Timeout:
                return False, "Provider health check timed out."
            except requests.ConnectionError:
                continue
            except requests.RequestException:
                continue
        return False, "Unable to reach the configured provider."

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_name: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int = 2500,
        timeout_seconds: int | None = None,
        telemetry: dict[str, Any] | None = None,
    ) -> LLMResponse:
        target_base_url = (base_url or self.base_url).rstrip("/")
        payload = {
            "model": model_name or self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature if temperature is not None else self.default_temperature,
            "top_p": top_p if top_p is not None else self.default_top_p,
            "max_tokens": max_tokens,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        response_body: dict[str, Any] = {}
        raw_content = ""
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
            response = requests.post(
                f"{target_base_url}/v1/chat/completions",
                json=payload,
                timeout=timeout_seconds or self.timeout,
                headers=headers,
            )
            response.raise_for_status()
            response_body = response.json()
            try:
                raw_content = response_body["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as exc:
                raise LLMError(f"Unexpected llama.cpp response shape: {response_body}") from exc
            try:
                parsed = json.loads(self._strip_reasoning_wrappers(raw_content))
            except json.JSONDecodeError as exc:
                raise LLMError(f"Model returned non-JSON content: {raw_content}") from exc
        except requests.Timeout as exc:
            self._record_telemetry(
                telemetry, payload, target_base_url, started_at, started,
                status="failed", body=response_body, content=raw_content,
                error_type="timeout", error_message=str(exc),
            )
            raise LLMError(f"llama.cpp request timed out: {exc}") from exc
        except requests.RequestException as exc:
            self._record_telemetry(
                telemetry, payload, target_base_url, started_at, started,
                status="failed", body=response_body, content=raw_content,
                error_type="request_error", error_message=str(exc),
            )
            raise LLMError(f"llama.cpp request failed: {exc}") from exc
        except LLMError as exc:
            self._record_telemetry(
                telemetry, payload, target_base_url, started_at, started,
                status="failed", body=response_body, content=raw_content,
                error_type="parse_error", error_message=str(exc),
            )
            raise
        self._record_telemetry(
            telemetry, payload, target_base_url, started_at, started,
            status="completed", body=response_body, content=raw_content, parsed=parsed,
        )
        return LLMResponse(
            content=raw_content,
            parsed_json=parsed,
            model_name=response_body.get("model", self.model_name),
            raw_payload=response_body,
        )

    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_name: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int = 900,
        telemetry: dict[str, Any] | None = None,
    ) -> str:
        """Call llama.cpp for plain chat text when JSON response mode is not wanted."""
        target_base_url = (base_url or self.base_url).rstrip("/")
        payload = {
            "model": model_name or self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature if temperature is not None else self.default_temperature,
            "top_p": top_p if top_p is not None else self.default_top_p,
            "max_tokens": max_tokens,
            "stream": False,
        }
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        body: dict[str, Any] = {}
        content = ""
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
            response = requests.post(
                f"{target_base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout,
                headers=headers,
            )
            response.raise_for_status()
            body = response.json()
            content = self._strip_reasoning_wrappers(body["choices"][0]["message"]["content"])
        except requests.Timeout as exc:
            self._record_telemetry(
                telemetry, payload, target_base_url, started_at, started,
                status="failed", body=body, content=content,
                error_type="timeout", error_message=str(exc),
            )
            raise LLMError(f"llama.cpp request timed out: {exc}") from exc
        except requests.RequestException as exc:
            self._record_telemetry(
                telemetry, payload, target_base_url, started_at, started,
                status="failed", body=body, content=content,
                error_type="request_error", error_message=str(exc),
            )
            raise LLMError(f"llama.cpp request failed: {exc}") from exc
        except (KeyError, IndexError) as exc:
            self._record_telemetry(
                telemetry, payload, target_base_url, started_at, started,
                status="failed", body=body, content=content,
                error_type="parse_error", error_message=str(exc),
            )
            raise LLMError(f"Unexpected llama.cpp response shape: {body}") from exc
        self._record_telemetry(
            telemetry, payload, target_base_url, started_at, started,
            status="completed", body=body, content=content,
        )
        return content

    def _record_telemetry(
        self,
        telemetry: dict[str, Any] | None,
        request_payload: dict[str, Any],
        base_url: str,
        started_at: datetime,
        started: float,
        *,
        status: str,
        body: dict[str, Any],
        content: str,
        parsed: dict[str, Any] | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Send one best-effort call record to storage without affecting inference."""
        if self.telemetry_store is None or not telemetry or not telemetry.get("project_id"):
            return
        usage = body.get("usage", {}) if isinstance(body, dict) else {}
        prompt_chars = sum(len(str(item.get("content", ""))) for item in request_payload["messages"])
        prompt_tokens = int(usage.get("prompt_tokens") or max(1, prompt_chars // 4))
        completion_tokens = int(usage.get("completion_tokens") or (max(1, len(content) // 4) if content else 0))
        total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
        input_rate = float(telemetry.get("input_cost_per_million") or 0)
        output_rate = float(telemetry.get("output_cost_per_million") or 0)
        provider_kind = telemetry.get("provider_kind") or self._provider_kind(base_url)
        estimated_cost = 0.0 if provider_kind == "local" else (
            (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
        )
        system_prompt = str(request_payload["messages"][0]["content"])
        user_prompt = str(request_payload["messages"][1]["content"])
        completed_at = datetime.now(timezone.utc)
        record = {
            **telemetry,
            "provider_kind": provider_kind,
            "model_name": body.get("model") or request_payload.get("model"),
            "prompt_version": hashlib.sha256(
                f"{system_prompt}\n---\n{user_prompt}".encode("utf-8")
            ).hexdigest()[:16],
            "status": status,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimated_cost,
            "request_chars": prompt_chars,
            "response_chars": len(content),
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "raw_response": content,
            "parsed_result": parsed or {},
            "error_type": error_type,
            "error_message": error_message,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "metadata": {
                **dict(telemetry.get("metadata", {})),
                "base_url_host": urlparse(base_url).hostname or "",
                "max_tokens": request_payload.get("max_tokens"),
                "temperature": request_payload.get("temperature"),
            },
        }
        try:
            self.telemetry_store.record_model_call(record)
        except Exception:
            return

    @staticmethod
    def _provider_kind(base_url: str) -> str:
        """Classify localhost endpoints separately from remote APIs."""
        host = (urlparse(base_url).hostname or "").casefold()
        return "local" if host in {"localhost", "127.0.0.1", "::1"} else "remote"
