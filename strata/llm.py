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
    """Typed provider failure that can retain an unusable raw model response."""

    def __init__(
        self,
        message: str,
        *,
        raw_content: str = "",
        error_type: str = "llm_error",
    ) -> None:
        super().__init__(message)
        self.raw_content = raw_content
        self.error_type = error_type


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

    @staticmethod
    def _remove_trailing_json_commas(content: str) -> str:
        """Remove only commas followed by a closing container outside strings."""
        output: list[str] = []
        in_string = False
        escaped = False
        index = 0
        while index < len(content):
            char = content[index]
            if in_string:
                output.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                index += 1
                continue
            if char == '"':
                in_string = True
                output.append(char)
                index += 1
                continue
            if char == ",":
                cursor = index + 1
                while cursor < len(content) and content[cursor].isspace():
                    cursor += 1
                if cursor < len(content) and content[cursor] in "}]":
                    index += 1
                    continue
            output.append(char)
            index += 1
        return "".join(output)

    @classmethod
    def _parse_json_response(cls, raw_content: str) -> dict[str, Any]:
        """Parse common harmless JSON near-misses without inventing missing content."""
        cleaned = cls._strip_reasoning_wrappers(raw_content)
        candidates = [
            cleaned,
            cls._remove_trailing_json_commas(cleaned),
        ]
        last_error: json.JSONDecodeError | None = None
        for candidate in dict.fromkeys(candidates):
            for strict in (True, False):
                try:
                    parsed = json.loads(candidate, strict=strict)
                except json.JSONDecodeError as exc:
                    last_error = exc
                    continue
                if not isinstance(parsed, dict):
                    raise LLMError(
                        "Model returned JSON with a non-object root.",
                        raw_content=raw_content,
                        error_type="parse_error",
                    )
                return parsed
        raise LLMError(
            f"Model returned non-JSON content: {raw_content}",
            raw_content=raw_content,
            error_type="parse_error",
        ) from last_error

    def _local_json_preflight(
        self,
        *,
        target_base_url: str,
        messages: list[dict[str, str]],
        context_limit: int,
        requested_max_tokens: int,
        headers: dict[str, str] | None,
    ) -> dict[str, Any]:
        """Measure the rendered local prompt and choose a context-safe JSON mode."""
        preflight_mode = "provider_tokenizer"
        try:
            template_response = requests.post(
                f"{target_base_url}/apply-template",
                json={"messages": messages},
                timeout=15,
                headers=headers,
            )
            template_response.raise_for_status()
            rendered_prompt = str(template_response.json()["prompt"])
            token_response = requests.post(
                f"{target_base_url}/tokenize",
                json={"content": rendered_prompt},
                timeout=30,
                headers=headers,
            )
            token_response.raise_for_status()
            prompt_tokens = len(token_response.json()["tokens"])
        except (requests.RequestException, KeyError, TypeError, ValueError):
            # LM Studio, Ollama, and other localhost OpenAI-compatible providers do
            # not expose llama.cpp's tokenizer routes. A deliberately conservative
            # byte estimate preserves output headroom without rejecting the provider.
            serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
            prompt_tokens = max(1, (len(serialized.encode("utf-8")) + 1) // 2)
            preflight_mode = "conservative_estimate"
        safety_tokens = 512
        if prompt_tokens + safety_tokens >= context_limit:
            raise LLMError(
                "Rendered prompt exceeds the configured context before inference: "
                f"prompt={prompt_tokens}, context={context_limit}.",
                error_type="context_preflight",
            )
        # Keep a small measured safety reserve for structured-output bookkeeping.
        # The rendered prompt and completion are the dominant context consumers.
        json_grammar_reserve = 256
        required_completion_tokens = min(
            requested_max_tokens,
            max(1024, min(4096, requested_max_tokens // 2)),
        )
        use_json_object_mode = (
            prompt_tokens
            + json_grammar_reserve
            + required_completion_tokens
            + safety_tokens
            <= context_limit
        )
        active_grammar_reserve = json_grammar_reserve if use_json_object_mode else 0
        available_completion_tokens = (
            context_limit
            - prompt_tokens
            - active_grammar_reserve
            - safety_tokens
        )
        if available_completion_tokens < required_completion_tokens:
            raise LLMError(
                "Rendered prompt leaves too little room for a complete structured response: "
                f"prompt={prompt_tokens}, required_completion={required_completion_tokens}, "
                f"available_completion={max(0, available_completion_tokens)}, "
                f"context={context_limit}.",
                error_type="context_preflight",
            )
        return {
            "prompt_tokens": prompt_tokens,
            "preflight_mode": preflight_mode,
            "context_limit": context_limit,
            "json_grammar_reserve": json_grammar_reserve,
            "required_completion_tokens": required_completion_tokens,
            "structured_output_mode": (
                "json_object" if use_json_object_mode else "prompt_only"
            ),
            "available_completion_tokens": max(
                256,
                available_completion_tokens,
            ),
        }

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
        context_limit: int | None = None,
        max_attempts: int = 4,
    ) -> LLMResponse:
        """Generate one JSON object with bounded retries for recoverable failures."""
        attempts = max(1, int(max_attempts))
        last_error: LLMError | None = None
        attempt_max_tokens = max_tokens
        attempt_temperature = temperature
        for attempt_number in range(1, attempts + 1):
            attempt_telemetry = dict(telemetry or {})
            attempt_telemetry["retry_count"] = (
                int(attempt_telemetry.get("retry_count") or 0) + attempt_number - 1
            )
            attempt_telemetry["metadata"] = {
                **dict(attempt_telemetry.get("metadata") or {}),
                "structured_attempt": attempt_number,
                "structured_max_attempts": attempts,
                "structured_retry_max_tokens": attempt_max_tokens,
                "structured_retry_temperature": attempt_temperature,
            }
            try:
                return self._generate_json_once(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_name=model_name,
                    base_url=base_url,
                    temperature=attempt_temperature,
                    top_p=top_p,
                    max_tokens=attempt_max_tokens,
                    timeout_seconds=timeout_seconds,
                    telemetry=attempt_telemetry,
                    context_limit=context_limit,
                )
            except LLMError as exc:
                last_error = exc
                if (
                    attempt_number >= attempts
                    or exc.error_type in {
                        "context_preflight",
                        "configuration_error",
                        "request_rejected",
                    }
                ):
                    raise
                if exc.error_type == "output_truncated":
                    attempt_max_tokens = min(
                        max(16_000, max_tokens),
                        max(attempt_max_tokens + 512, int(attempt_max_tokens * 1.5)),
                    )
                elif exc.error_type in {"parse_error", "response_shape"}:
                    baseline = (
                        self.default_temperature
                        if attempt_temperature is None
                        else attempt_temperature
                    )
                    attempt_temperature = min(float(baseline), 0.2)
                time.sleep(min(2.0, 0.25 * (2 ** (attempt_number - 1))))
        assert last_error is not None
        raise last_error

    def _generate_json_once(
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
        context_limit: int | None = None,
    ) -> LLMResponse:
        """Perform one OpenAI-compatible structured-output request."""
        target_base_url = (base_url or self.base_url).rstrip("/")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        payload = {
            "model": model_name or self.model_name,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.default_temperature,
            "top_p": top_p if top_p is not None else self.default_top_p,
            "max_tokens": max_tokens,
            "stream": False,
        }
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        response_body: dict[str, Any] = {}
        raw_content = ""
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else None
        effective_telemetry = dict(telemetry or {})
        if context_limit and self._provider_kind(target_base_url) == "local":
            try:
                preflight = self._local_json_preflight(
                    target_base_url=target_base_url,
                    messages=messages,
                    context_limit=context_limit,
                    requested_max_tokens=max_tokens,
                    headers=headers,
                )
            except LLMError as exc:
                self._record_telemetry(
                    effective_telemetry, payload, target_base_url, started_at, started,
                    status="failed", body={}, content="",
                    error_type=exc.error_type, error_message=str(exc),
                )
                raise
            payload["max_tokens"] = min(
                max_tokens,
                int(preflight["available_completion_tokens"]),
            )
            if preflight["structured_output_mode"] == "json_object":
                payload["response_format"] = {"type": "json_object"}
            effective_telemetry["metadata"] = {
                **dict(effective_telemetry.get("metadata", {})),
                **preflight,
                "requested_max_tokens": max_tokens,
                "effective_max_tokens": payload["max_tokens"],
            }
        else:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = requests.post(
                f"{target_base_url}/v1/chat/completions",
                json=payload,
                timeout=timeout_seconds or self.timeout,
                headers=headers,
            )
            response.raise_for_status()
            response_body = response.json()
            if not isinstance(response_body, dict):
                raise LLMError(
                    f"Provider returned a non-object response envelope: {response_body!r}",
                    error_type="response_shape",
                )
            choices = response_body.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise LLMError(
                    f"Provider response did not contain a usable choices list: {response_body}",
                    error_type="response_shape",
                )
            message = choices[0].get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise LLMError(
                    f"Provider response did not contain string message content: {response_body}",
                    error_type="response_shape",
                )
            raw_content = message["content"]
            finish_reason = str(choices[0].get("finish_reason") or "")
            if finish_reason in {"length", "max_tokens"}:
                raise LLMError(
                    "Model structured response was truncated by its output-token limit.",
                    raw_content=raw_content,
                    error_type="output_truncated",
                )
            try:
                parsed = self._parse_json_response(raw_content)
            except LLMError:
                raise
        except requests.Timeout as exc:
            self._record_telemetry(
                effective_telemetry, payload, target_base_url, started_at, started,
                status="failed", body=response_body, content=raw_content,
                error_type="timeout", error_message=str(exc),
            )
            raise LLMError(
                f"llama.cpp request timed out: {exc}",
                raw_content=raw_content,
                error_type="timeout",
            ) from exc
        except requests.RequestException as exc:
            error_response = getattr(exc, "response", None)
            status_code = getattr(error_response, "status_code", None)
            failure_content = raw_content
            if not failure_content and error_response is not None:
                response_text = getattr(error_response, "text", "")
                if isinstance(response_text, str):
                    failure_content = response_text[:20_000]
            permanent_rejection = (
                isinstance(status_code, int)
                and 400 <= status_code < 500
                and status_code not in {408, 409, 425, 429}
            )
            error_type = "request_rejected" if permanent_rejection else "request_error"
            self._record_telemetry(
                effective_telemetry, payload, target_base_url, started_at, started,
                status="failed", body=response_body, content=failure_content,
                error_type=error_type, error_message=str(exc),
            )
            raise LLMError(
                f"llama.cpp request failed: {exc}",
                raw_content=failure_content,
                error_type=error_type,
            ) from exc
        except LLMError as exc:
            self._record_telemetry(
                effective_telemetry, payload, target_base_url, started_at, started,
                status="failed", body=response_body, content=exc.raw_content or raw_content,
                error_type=exc.error_type, error_message=str(exc),
            )
            raise
        self._record_telemetry(
            effective_telemetry, payload, target_base_url, started_at, started,
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
