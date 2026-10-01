"""Platform control plane: roles, persons, role grants, verticals, merchant bots."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import Field

from arada.api.auth import CurrentPrincipal
from arada.api.deps import container_of, platform
from arada.api.schemas import RequestModel, ResponseModel
from arada.bots import service as bots
from arada.identity import service as identity
from arada.rbac import service as rbac
from arada.verticals import service as verticals

router = APIRouter(prefix="/v1", tags=["platform"])


class RoleOut(ResponseModel):
    key: str
    scope_type: str
    description: str
    permissions: list[str]


class PersonOut(ResponseModel):
    person_id: UUID
    display_name: str
    username: str | None
    status: str


class RoleGrantIn(RequestModel):
    person_id: UUID
    role: str = Field(pattern=r"^[A-Z][A-Z_]{2,39}$")
    vertical: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,39}$")


class VerticalIn(RequestModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    name_en: str = Field(min_length=1, max_length=80)
    name_am: str | None = Field(default=None, min_length=1, max_length=80)


class VerticalOut(ResponseModel):
    id: UUID
    key: str
    name_en: str
    name_am: str | None
    status: str


@router.get("/roles", response_model=list[RoleOut], summary="Role catalogue")
async def list_roles(
    principal: CurrentPrincipal,
    request: Request,
    scope_type: Literal["platform", "vertical", "tenant"] | None = Query(default=None),
) -> list[RoleOut]:
    async with container_of(request).db.transaction(person_id=principal.person_id) as conn:
        roles = await rbac.catalogue(conn, scope_type)
    return [RoleOut(**{**asdict(r), "permissions": list(r.permissions)}) for r in roles]


@router.get("/platform/persons", response_model=PersonOut, summary="Find a person (users.read)")
async def find_person(
    principal: CurrentPrincipal,
    request: Request,
    username: str = Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$"),
) -> PersonOut:
    async with platform(request, principal) as scope:
        person = await identity.find_by_username(scope, username)
    return PersonOut(
        person_id=person.id,
        display_name=person.display_name,
        username=person.username,
        status=person.status,
    )


@router.post("/platform/role-grants", status_code=204, summary="Grant a platform/vertical role")
async def grant(body: RoleGrantIn, principal: CurrentPrincipal, request: Request) -> Response:
    async with platform(request, principal) as scope:
        await rbac.grant_role(
            scope, person_id=body.person_id, role=body.role, vertical_key=body.vertical
        )
    return Response(status_code=204)


@router.post("/platform/role-grants:revoke", status_code=204, summary="Revoke a role")
async def revoke(body: RoleGrantIn, principal: CurrentPrincipal, request: Request) -> Response:
    async with platform(request, principal) as scope:
        await rbac.revoke_role(
            scope, person_id=body.person_id, role=body.role, vertical_key=body.vertical
        )
    return Response(status_code=204)


@router.post(
    "/platform/verticals", response_model=VerticalOut, status_code=201, summary="Create vertical"
)
async def create_vertical(
    body: VerticalIn, principal: CurrentPrincipal, request: Request
) -> VerticalOut:
    async with platform(request, principal) as scope:
        v = await verticals.create(scope, key=body.key, name_en=body.name_en, name_am=body.name_am)
    return VerticalOut(**asdict(v))


@router.get("/platform/verticals", response_model=list[VerticalOut], summary="List verticals")
async def list_verticals(principal: CurrentPrincipal, request: Request) -> list[VerticalOut]:
    async with platform(request, principal) as scope:
        items = await verticals.list_visible(scope)
    return [VerticalOut(**asdict(v)) for v in items]


# ------------------------------------------------- merchant Telegram bots (Phase 2)
class TelegramBotIn(RequestModel):
    """A merchant's own bot. ``bot_id`` is supplied explicitly (decision D6):
    it is never parsed from the token. Neither value is ever echoed back."""

    bot_id: int = Field(gt=0, lt=2**53)
    bot_token: str = Field(min_length=16, max_length=256)


class TelegramBotOut(ResponseModel):
    tenant_id: UUID
    bot_id: int
    status: str
    registered_at: datetime


def _bot_out(status: bots.BotStatus) -> TelegramBotOut:
    return TelegramBotOut(
        tenant_id=status.tenant_id,
        bot_id=status.telegram_bot_id,
        status=status.status,
        registered_at=status.created_at,
    )


@router.put(
    "/platform/tenants/{tenant_id}/telegram-bot",
    response_model=TelegramBotOut,
    summary="Bind or replace a tenant's own Telegram bot",
    description=(
        "Stores the token encrypted. Replacing a bot revokes the tenant's customer "
        "sessions. No call is made to Telegram: a wrong bot_id fails closed at login."
    ),
)
async def put_telegram_bot(
    tenant_id: UUID, body: TelegramBotIn, principal: CurrentPrincipal, request: Request
) -> TelegramBotOut:
    c = container_of(request)
    async with platform(request, principal) as scope:
        status = await bots.register(
            scope, c.keyring, tenant_id=tenant_id, bot_id=body.bot_id, token=body.bot_token
        )
    return _bot_out(status)


@router.get(
    "/platform/tenants/{tenant_id}/telegram-bot",
    response_model=TelegramBotOut,
    summary="The tenant's active Telegram bot (never the token)",
)
async def get_telegram_bot(
    tenant_id: UUID, principal: CurrentPrincipal, request: Request
) -> TelegramBotOut:
    async with platform(request, principal) as scope:
        status = await bots.status_of(scope, tenant_id)
    return _bot_out(status)


@router.delete(
    "/platform/tenants/{tenant_id}/telegram-bot",
    status_code=204,
    summary="Disable the tenant's Telegram bot and revoke its customer sessions",
)
async def delete_telegram_bot(
    tenant_id: UUID, principal: CurrentPrincipal, request: Request
) -> Response:
    async with platform(request, principal) as scope:
        await bots.disable(scope, tenant_id)
    return Response(status_code=204)
