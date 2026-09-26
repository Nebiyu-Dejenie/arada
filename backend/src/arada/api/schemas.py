"""Request/response model conventions.

Every request body forbids unknown fields: a client cannot smuggle
``tenant_id``, ``status`` or ``role`` into an update (mass assignment).
Responses are explicit DTOs; database rows are never returned directly.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
