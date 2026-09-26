"""Request/response model conventions.

Every request body forbids unknown fields: a client cannot smuggle
``tenant_id``, ``status`` or ``role`` into an update (mass assignment).
Responses are explicit DTOs; database rows are never returned directly.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


def _contains_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_contains_nul(k) or _contains_nul(v) for k, v in value.items())
    if isinstance(value, list | tuple):
        return any(_contains_nul(v) for v in value)
    return False


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def _reject_nul_bytes(cls, data: Any) -> Any:
        # PostgreSQL text cannot hold NUL; reject at the boundary (422), never 500.
        if _contains_nul(data):
            raise ValueError("text must not contain NUL characters")
        return data


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
