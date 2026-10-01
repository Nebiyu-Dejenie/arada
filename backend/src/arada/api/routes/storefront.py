"""Storefront customer authentication (Phase 2; ADR-012, ADR-036).

Every route here is served on a merchant's own host. The tenant is resolved
from ``Host`` server-side; no request field, header or query parameter can
name a tenant. Customer tokens are accepted only by these routes, and staff
tokens never are.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from arada.access.customer import customer_scope
from arada.api.auth import bearer_token
from arada.api.deps import Meta, container_of
from arada.api.schemas import ResponseModel
from arada.audit import service as audit
from arada.customers import service as customers
from arada.customers import sessions as customer_sessions
from arada.customers import telegram_login

router = APIRouter(prefix="/v1/storefront", tags=["storefront"])


class TelegramAuthIn(BaseModel):
    """The raw ``Telegram.WebApp.initData`` string, exactly as received.

    Not a ``RequestModel``: whitespace stripping and NUL rejection would alter
    or pre-judge authentication data. The validator alone decides, and every
    rejection is the same 401. ``initDataUnsafe`` is never accepted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    init_data: str


class CustomerSessionOut(BaseModel):
    access_token: str
    expires_at: datetime


class CustomerMeOut(ResponseModel):
    customer_id: UUID
    tenant_slug: str
    display_name: str
    first_seen_at: datetime


def _host(request: Request) -> str:
    return request.headers.get("host", "")


@router.post(
    "/auth/telegram",
    response_model=CustomerSessionOut,
    summary="Customer login with Telegram Mini App initData",
    responses={401: {"description": "Telegram authentication failed (one generic answer)"}},
)
async def telegram_auth(body: TelegramAuthIn, request: Request, meta: Meta) -> CustomerSessionOut:
    c = container_of(request)
    issued = await telegram_login.login(
        c.db, c.settings, c.keyring, meta, host=_host(request), init_data=body.init_data
    )
    return CustomerSessionOut(access_token=issued.token, expires_at=issued.expires_at)


@router.get("/me", response_model=CustomerMeOut, summary="The authenticated customer")
async def me(request: Request, meta: Meta) -> CustomerMeOut:
    c = container_of(request)
    token = bearer_token(request)
    async with customer_scope(c.db, c.settings, meta, host=_host(request), token=token) as scope:
        profile = await customers.own_profile(scope)
        slug = scope.tenant.slug
    return CustomerMeOut(
        customer_id=profile.customer_id,
        tenant_slug=slug,
        display_name=profile.display_name,
        first_seen_at=profile.first_seen_at,
    )


@router.post("/auth/logout", status_code=204, summary="End the customer session")
async def logout(request: Request, meta: Meta) -> Response:
    c = container_of(request)
    token = bearer_token(request)
    async with customer_scope(c.db, c.settings, meta, host=_host(request), token=token) as scope:
        await customer_sessions.revoke(scope.conn, scope.principal.session_id, "logout")
        await audit.record(
            scope.conn,
            meta,
            actor_person_id=scope.principal.person_id,
            tenant_id=scope.tenant.id,
            action="auth.customer_logout",
            resource_type="customer",
            resource_id=scope.principal.customer_id,
        )
    return Response(status_code=204)
