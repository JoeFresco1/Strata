from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import requests

from specforge.config import AppConfig


class LLMError(RuntimeError):
    pass


@dataclass(slots=True)
class LLMResponse:
    content: str
    parsed_json: dict[str, Any]
    model_name: str | None
    raw_payload: dict[str, Any]


class LlamaCppClient:
    def __init__(self, config: AppConfig):
        self.base_url = config.llama_base_url.rstrip("/")
        self.timeout = config.llama_timeout_seconds
        self.default_temperature = config.default_temperature
        self.default_top_p = config.default_top_p
        self.model_name = config.model_name

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

    @staticmethod
    def _strip_reasoning_wrappers(content: str) -> str:
        cleaned = re.sub(r"(?is)<think>\s*</think>\s*", "", content).strip()
        cleaned = re.sub(r"(?is)^<think>.*?</think>\s*", "", cleaned).strip()
        return cleaned

    def healthcheck(self) -> tuple[bool, str]:
        for path in ("/health", "/v1/models"):
            try:
                response = requests.get(
                    f"{self.base_url}{path}",
                    timeout=10,
                )
                if response.ok:
                    return True, f"Reachable via {path}"
            except requests.RequestException:
                continue
        return False, "Unable to reach llama.cpp server."

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
        try:
            response = requests.post(
                f"{target_base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(f"llama.cpp request failed: {exc}") from exc
        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected llama.cpp response shape: {body}") from exc
        try:
            parsed = json.loads(self._strip_reasoning_wrappers(content))
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model returned non-JSON content: {content}") from exc
        return LLMResponse(
            content=content,
            parsed_json=parsed,
            model_name=body.get("model", self.model_name),
            raw_payload=body,
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
        try:
            response = requests.post(
                f"{target_base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise LLMError(f"llama.cpp request failed: {exc}") from exc
        body = response.json()
        try:
            return self._strip_reasoning_wrappers(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Unexpected llama.cpp response shape: {body}") from exc
