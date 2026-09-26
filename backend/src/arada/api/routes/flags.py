"""Feature flag API: platform management and per-tenant effective values."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import Field

from arada.api.auth import CurrentPrincipal
from arada.api.deps import platform, tenant
from arada.api.schemas import RequestModel, ResponseModel
from arada.flags import service as flags

router = APIRouter(prefix="/v1", tags=["feature flags"])

FLAG = r"^[a-z][a-z0-9_]{1,39}$"


class OverrideTarget(RequestModel):
    scope_type: Literal["platform", "vertical", "tenant"]
    vertical: str | None = Field(default=None, pattern=FLAG)
    tenant: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")


class OverrideIn(OverrideTarget):
    enabled: bool
    enforced: bool = False
    reason: str | None = Field(default=None, max_length=500)


class FlagOut(ResponseModel):
    key: str
    description: str
    default_enabled: bool
    allowed_scopes: list[str]
    overrides: list[dict[str, Any]]


class FlagValueOut(ResponseModel):
    key: str
    enabled: bool
    source: str


@router.get("/platform/feature-flags", response_model=list[FlagOut], tags=["platform"])
async def list_flags(principal: CurrentPrincipal, request: Request) -> list[FlagOut]:
    async with platform(request, principal) as scope:
        items = await flags.list_flags(scope)
    return [
        FlagOut(
            key=f.key,
            description=f.description,
            default_enabled=f.default_enabled,
            allowed_scopes=list(f.allowed_scopes),
            overrides=[
                {k: (str(v) if isinstance(v, UUID) else v) for k, v in o.items()}
                for o in f.overrides
            ],
        )
        for f in items
    ]


@router.put("/platform/feature-flags/{key}/overrides", status_code=204, tags=["platform"])
async def set_override(
    key: str, body: OverrideIn, principal: CurrentPrincipal, request: Request
) -> Response:
    async with platform(request, principal) as scope:
        await flags.set_override(
            scope,
            key=key,
            scope_type=body.scope_type,
            vertical_key=body.vertical,
            tenant_slug=body.tenant,
            enabled=body.enabled,
            enforced=body.enforced,
            reason=body.reason,
        )
    return Response(status_code=204)


@router.post("/platform/feature-flags/{key}/overrides:clear", status_code=204, tags=["platform"])
async def clear_override(
    key: str, body: OverrideTarget, principal: CurrentPrincipal, request: Request
) -> Response:
    async with platform(request, principal) as scope:
        await flags.clear_override(
            scope,
            key=key,
            scope_type=body.scope_type,
            vertical_key=body.vertical,
            tenant_slug=body.tenant,
        )
    return Response(status_code=204)


@router.get("/t/{tenant_slug}/features", response_model=list[FlagValueOut], tags=["tenant"])
async def tenant_features(
    tenant_slug: str, principal: CurrentPrincipal, request: Request
) -> list[FlagValueOut]:
    async with tenant(request, principal, tenant_slug) as scope:
        values = await flags.for_scope(scope)
    return [
        FlagValueOut(key=v.key, enabled=v.enabled, source=v.source)
        for v in sorted(values.values(), key=lambda v: v.key)
    ]
