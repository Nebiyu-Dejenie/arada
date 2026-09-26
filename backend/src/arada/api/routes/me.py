from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel

from arada.api.auth import CurrentPrincipal
from arada.api.deps import container_of
from arada.api.schemas import ResponseModel
from arada.identity import service as identity
from arada.rbac import service as rbac

router = APIRouter(prefix="/v1", tags=["me"])


class MfaOut(BaseModel):
    totp: str
    session_verified: bool


class RolesOut(BaseModel):
    platform: list[str]
    vertical: list[str]


class MeOut(ResponseModel):
    person_id: UUID
    display_name: str
    username: str | None
    mfa: MfaOut
    roles: RolesOut


@router.get("/me", response_model=MeOut, summary="The authenticated person")
async def me(principal: CurrentPrincipal, request: Request) -> MeOut:
    async with container_of(request).db.transaction(person_id=principal.person_id) as conn:
        person = await identity.summary(conn, principal.person_id)
        privileged = await rbac.privileged_roles_of(conn, principal.person_id)
    return MeOut(
        person_id=person.id,
        display_name=person.display_name,
        username=person.username,
        mfa=MfaOut(totp=person.totp, session_verified=principal.mfa_verified),
        roles=RolesOut(**privileged),
    )
