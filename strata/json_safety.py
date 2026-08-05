from __future__ import annotations

import json
import math
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class JsonSerializationError(TypeError):
    """Raised when a durable result contains a value JSON cannot represent."""

    def __init__(self, path: str, value: Any) -> None:
        self.path = path
        self.value_type = type(value).__name__
        super().__init__(f"Unsupported JSON value at {path}: {self.value_type}")


def to_json_safe(value: Any, *, path: str = "$", _seen: set[int] | None = None) -> Any:
    """Normalize supported domain values and reject unsafe durable-result values."""
    seen = _seen if _seen is not None else set()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise JsonSerializationError(path, value)
        return value
    if isinstance(value, (UUID, datetime, date, time, Decimal, Path)):
        return str(value)
    if isinstance(value, Enum):
        return to_json_safe(value.value, path=path, _seen=seen)

    identity = id(value)
    if identity in seen:
        raise JsonSerializationError(path, value)
    if isinstance(value, BaseModel):
        seen.add(identity)
        try:
            return to_json_safe(value.model_dump(mode="json"), path=path, _seen=seen)
        finally:
            seen.remove(identity)
    if is_dataclass(value) and not isinstance(value, type):
        seen.add(identity)
        try:
            return {
                field.name: to_json_safe(getattr(value, field.name), path=f"{path}.{field.name}", _seen=seen)
                for field in fields(value)
            }
        finally:
            seen.remove(identity)
    if isinstance(value, dict):
        seen.add(identity)
        try:
            result: dict[str, Any] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise JsonSerializationError(f"{path}.<key>", key)
                result[key] = to_json_safe(item, path=f"{path}.{key}", _seen=seen)
            return result
        finally:
            seen.remove(identity)
    if isinstance(value, (list, tuple)):
        seen.add(identity)
        try:
            return [to_json_safe(item, path=f"{path}[{index}]", _seen=seen) for index, item in enumerate(value)]
        finally:
            seen.remove(identity)

    raise JsonSerializationError(path, value)


def ensure_json_safe(value: Any, *, path: str = "$") -> Any:
    """Validate and return a JSON-safe value before it crosses a persistence boundary."""
    normalized = to_json_safe(value, path=path)
    try:
        json.dumps(normalized, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise JsonSerializationError(path, normalized) from exc
    return normalized
