"""Platform control plane: roles, persons, role grants, verticals."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import Field

from arada.api.auth import CurrentPrincipal
from arada.api.deps import container_of, platform
from arada.api.schemas import RequestModel, ResponseModel
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
