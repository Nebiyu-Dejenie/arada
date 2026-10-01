from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request, Response
from pydantic import Field

from arada.api.auth import CurrentPrincipal
from arada.api.deps import Meta, container_of
from arada.api.schemas import RequestModel, ResponseModel
from arada.identity import service as identity

router = APIRouter(prefix="/v1", tags=["authentication"])


class LoginIn(RequestModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, max_length=12)


class SessionOut(ResponseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105  (a token type, not a secret)
    expires_at: datetime
    mfa_verified: bool


class TotpEnrolmentOut(ResponseModel):
    secret: str
    provisioning_uri: str


class TotpConfirmIn(RequestModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


@router.post("/auth/login", response_model=SessionOut, summary="Password (+TOTP) login")
async def login(body: LoginIn, request: Request, meta: Meta) -> SessionOut:
    c = container_of(request)
    issued = await identity.login(
        c.db,
        c.settings,
        c.keyring,
        meta,
        username=body.username,
        password=body.password,
        totp_code=body.totp_code,
    )
    return SessionOut(
        access_token=issued.token, expires_at=issued.expires_at, mfa_verified=issued.mfa_verified
    )


@router.post("/auth/logout", status_code=204, summary="Revoke the current session")
async def logout(principal: CurrentPrincipal, request: Request, meta: Meta) -> Response:
    await identity.logout(container_of(request).db, meta, principal)
    return Response(status_code=204)


@router.post("/me/mfa/totp", response_model=TotpEnrolmentOut, summary="Begin TOTP enrolment")
async def begin_totp(principal: CurrentPrincipal, request: Request, meta: Meta) -> TotpEnrolmentOut:
    c = container_of(request)
    enrolment = await identity.begin_totp_enrolment(c.db, c.settings, c.keyring, meta, principal)
    return TotpEnrolmentOut(secret=enrolment.secret, provisioning_uri=enrolment.provisioning_uri)


@router.post(
    "/me/mfa/totp/confirm",
    response_model=SessionOut,
    summary="Confirm TOTP enrolment",
    description=(
        "Confirms the pending factor and rotates the session: the calling token "
        "is revoked and a new, MFA-verified token is returned in its place. The "
        "new session keeps the old one's absolute expiry."
    ),
)
async def confirm_totp(
    body: TotpConfirmIn, principal: CurrentPrincipal, request: Request, meta: Meta
) -> SessionOut:
    c = container_of(request)
    issued = await identity.confirm_totp(c.db, c.settings, c.keyring, meta, principal, body.code)
    return SessionOut(
        access_token=issued.token, expires_at=issued.expires_at, mfa_verified=issued.mfa_verified
    )
