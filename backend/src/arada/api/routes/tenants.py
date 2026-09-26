"""Tenancy API: platform tenant management, tenant console, invitations.

Every tenant-scoped route lives under ``/v1/t/{tenant_slug}``; the tenant is
resolved server-side and authorised per request. There is no route that
accepts a tenant id from the client as an authorisation input.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import Field

from arada.api.auth import CurrentPrincipal, OptionalPrincipal
from arada.api.deps import container_of, platform, request_meta, tenant
from arada.api.schemas import RequestModel, ResponseModel
from arada.audit import service as audit
from arada.kernel.errors import NotFound, PreconditionFailed, PreconditionRequired
from arada.tenancy import members
from arada.tenancy import service as tenancy

router = APIRouter(prefix="/v1", tags=["tenancy"])

SLUG = r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$"
ROLE = r"^[A-Z][A-Z_]{2,39}$"


# ---------------------------------------------------------------- schemas
class TenantIn(RequestModel):
    slug: str = Field(pattern=SLUG)
    display_name: str = Field(min_length=1, max_length=120)
    vertical: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    blueprint_version_id: UUID


class ProfileOut(ResponseModel):
    display_name: str
    tagline: str | None
    description: str | None
    brand_primary_color: str | None
    brand_accent_color: str | None
    contact_email: str | None
    contact_phone: str | None
    version: int


class TenantOut(ResponseModel):
    id: UUID
    slug: str
    display_name: str
    status: str
    vertical_key: str
    blueprint_key: str
    blueprint_version_id: UUID
    blueprint_version: str
    isolation_tier: str
    currency: str
    default_locale: str
    timezone: str
    created_at: datetime
    version: int
    profile: ProfileOut | None = None


class InvitationOut(ResponseModel):
    id: UUID
    token: str = Field(description="Shown once. Deliver it to the invitee out of band.")
    expires_at: datetime
    roles: list[str]


class TenantCreatedOut(ResponseModel):
    tenant: TenantOut
    owner_invitation: InvitationOut


class LifecycleIn(RequestModel):
    reason: str | None = Field(default=None, max_length=500)


class BlueprintAssignmentIn(RequestModel):
    blueprint_version_id: UUID
    reason: str = Field(min_length=3, max_length=500)


class DomainIn(RequestModel):
    hostname: str = Field(min_length=4, max_length=253)


class ProfilePatch(RequestModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    tagline: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    brand_primary_color: str | None = Field(default=None, pattern=r"^#[0-9a-f]{6}$")
    brand_accent_color: str | None = Field(default=None, pattern=r"^#[0-9a-f]{6}$")
    contact_email: str | None = Field(default=None, max_length=254)
    contact_phone: str | None = Field(default=None, pattern=r"^\+[1-9][0-9]{6,14}$")


class InviteIn(RequestModel):
    roles: list[str] = Field(min_length=1, max_length=10)
    ttl_hours: int | None = Field(default=None, ge=1, le=720)


class RolesIn(RequestModel):
    roles: list[str] = Field(min_length=1, max_length=10)


class StaffOut(ResponseModel):
    membership_id: UUID
    person_id: UUID
    display_name: str
    username: str | None
    status: str
    roles: list[str]


class NewAccountIn(RequestModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class AcceptIn(RequestModel):
    token: str = Field(min_length=20, max_length=200)
    new_account: NewAccountIn | None = None


class MembershipOut(ResponseModel):
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    membership_id: UUID
    roles: list[str]


class AuditEventOut(ResponseModel):
    id: UUID
    occurred_at: datetime
    actor_type: str
    actor_person_id: UUID | None
    tenant_id: UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    source: str
    request_id: str | None
    trace_id: str | None
    reason: str | None
    before: Any
    after: Any


class PublicMerchantOut(ResponseModel):
    slug: str
    display_name: str
    tagline: str | None
    description: str | None
    brand_primary_color: str | None
    brand_accent_color: str | None


def _tenant_out(t: tenancy.TenantDetail) -> TenantOut:
    data = asdict(t)
    return TenantOut.model_validate(data)


def _invitation_out(i: members.Invitation) -> InvitationOut:
    return InvitationOut(id=i.id, token=i.token, expires_at=i.expires_at, roles=list(i.roles))


def _staff_out(m: members.StaffMember) -> StaffOut:
    return StaffOut(**{**asdict(m), "roles": list(m.roles)})


def _if_match(value: str | None) -> int:
    if value is None:
        raise PreconditionRequired()
    stripped = value.strip().removeprefix("W/").strip('"')
    if not stripped.isdigit():
        raise PreconditionFailed()
    return int(stripped)


# ---------------------------------------------------------------- platform
@router.post(
    "/platform/tenants", response_model=TenantCreatedOut, status_code=201, tags=["platform"]
)
async def create_tenant(
    body: TenantIn, principal: CurrentPrincipal, request: Request
) -> TenantCreatedOut:
    """Create a merchant tenant pinned to a published blueprint version.

    Returns a one-time owner invitation token; the owner joins by accepting it.
    """
    async with platform(request, principal) as scope:
        detail, invitation = await tenancy.create_tenant(
            scope,
            container_of(request).settings,
            slug=body.slug,
            display_name=body.display_name,
            vertical_key=body.vertical,
            blueprint_version_id=body.blueprint_version_id,
        )
    return TenantCreatedOut(
        tenant=_tenant_out(detail), owner_invitation=_invitation_out(invitation)
    )


@router.get("/platform/tenants", response_model=list[TenantOut], tags=["platform"])
async def list_tenants(
    principal: CurrentPrincipal,
    request: Request,
    vertical: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9_]{1,39}$"),
    status: Literal["draft", "active", "suspended", "archived"] | None = None,
) -> list[TenantOut]:
    async with platform(request, principal) as scope:
        items = await tenancy.list_tenants(scope, vertical_key=vertical, status=status)
    return [_tenant_out(t) for t in items]


@router.post("/platform/tenants/{tenant_id}:{action}", response_model=TenantOut, tags=["platform"])
async def lifecycle(
    tenant_id: UUID,
    action: Literal["activate", "suspend", "reactivate", "archive"],
    principal: CurrentPrincipal,
    request: Request,
    body: LifecycleIn | None = None,
) -> TenantOut:
    async with platform(request, principal) as scope:
        detail = await tenancy.change_status(
            scope, tenant_id, action, body.reason if body else None
        )
    return _tenant_out(detail)


@router.post(
    "/platform/tenants/{tenant_id}/blueprint-assignment",
    response_model=TenantOut,
    tags=["platform"],
)
async def assign_blueprint(
    tenant_id: UUID, body: BlueprintAssignmentIn, principal: CurrentPrincipal, request: Request
) -> TenantOut:
    async with platform(request, principal) as scope:
        detail = await tenancy.assign_blueprint(
            scope, tenant_id, body.blueprint_version_id, body.reason
        )
    return _tenant_out(detail)


@router.post("/platform/tenants/{tenant_id}/domains", status_code=201, tags=["platform"])
async def add_domain(
    tenant_id: UUID, body: DomainIn, principal: CurrentPrincipal, request: Request
) -> dict[str, str]:
    async with platform(request, principal) as scope:
        domain_id = await tenancy.add_domain(scope, tenant_id, body.hostname)
    return {"id": str(domain_id)}


@router.get("/platform/audit-events", response_model=list[AuditEventOut], tags=["platform"])
async def platform_audit(
    principal: CurrentPrincipal,
    request: Request,
    tenant_id: UUID | None = None,
    action: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9_.]{2,79}$"),
    limit: int = Query(default=50, ge=1, le=200),
    before: UUID | None = None,
) -> list[AuditEventOut]:
    async with platform(request, principal) as scope:
        events = await audit.list_platform(
            scope,
            container_of(request).db,
            tenant_id=tenant_id,
            action=action,
            limit=limit,
            before=before,
        )
    return [AuditEventOut.model_validate(asdict(e)) for e in events]


# ---------------------------------------------------------------- me / invitations
@router.get("/me/tenants", response_model=list[MembershipOut], tags=["me"])
async def my_tenants(principal: CurrentPrincipal, request: Request) -> list[MembershipOut]:
    async with container_of(request).db.transaction(person_id=principal.person_id) as conn:
        items = await members.memberships_of(conn, principal.person_id)
    return [MembershipOut(**{**asdict(m), "roles": list(m.roles)}) for m in items]


@router.post("/invitations:accept", response_model=MembershipOut, tags=["me"])
async def accept_invitation(
    body: AcceptIn, principal: OptionalPrincipal, request: Request
) -> MembershipOut:
    new_account = (
        members.NewAccount(
            username=body.new_account.username,
            password=body.new_account.password,
            display_name=body.new_account.display_name,
        )
        if body.new_account
        else None
    )
    membership = await members.accept_invitation(
        container_of(request).db,
        request_meta(request),
        token=body.token,
        principal=principal,
        new_account=new_account,
    )
    return MembershipOut(**{**asdict(membership), "roles": list(membership.roles)})


# ---------------------------------------------------------------- tenant console
@router.get("/t/{tenant_slug}", response_model=TenantOut, tags=["tenant"])
async def get_tenant(
    tenant_slug: str, principal: CurrentPrincipal, request: Request, response: Response
) -> TenantOut:
    async with tenant(request, principal, tenant_slug) as scope:
        detail = await tenancy.get_for_scope(scope)
    if detail.profile:
        response.headers["ETag"] = f'"{detail.profile.version}"'
    return _tenant_out(detail)


@router.patch("/t/{tenant_slug}/profile", response_model=ProfileOut, tags=["tenant"])
async def update_profile(
    tenant_slug: str,
    body: ProfilePatch,
    principal: CurrentPrincipal,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None),
) -> ProfileOut:
    expected = _if_match(if_match)
    changes = body.model_dump(exclude_unset=True)
    async with tenant(request, principal, tenant_slug) as scope:
        profile = await tenancy.update_profile(scope, changes, expected_version=expected)
    response.headers["ETag"] = f'"{profile.version}"'
    return ProfileOut.model_validate(asdict(profile))


@router.get("/t/{tenant_slug}/blueprint-history", tags=["tenant"])
async def blueprint_history(
    tenant_slug: str, principal: CurrentPrincipal, request: Request
) -> list[dict[str, Any]]:
    async with tenant(request, principal, tenant_slug) as scope:
        rows = await tenancy.blueprint_history(scope)
    return [{k: (str(v) if v is not None else None) for k, v in r.items()} for r in rows]


@router.get("/t/{tenant_slug}/staff", response_model=list[StaffOut], tags=["tenant"])
async def list_staff(
    tenant_slug: str, principal: CurrentPrincipal, request: Request
) -> list[StaffOut]:
    async with tenant(request, principal, tenant_slug) as scope:
        staff = await members.list_staff(scope)
    return [_staff_out(m) for m in staff]


@router.post(
    "/t/{tenant_slug}/invitations", response_model=InvitationOut, status_code=201, tags=["tenant"]
)
async def invite(
    tenant_slug: str, body: InviteIn, principal: CurrentPrincipal, request: Request
) -> InvitationOut:
    async with tenant(request, principal, tenant_slug) as scope:
        invitation = await members.invite(
            scope, container_of(request).settings, roles=body.roles, ttl_hours=body.ttl_hours
        )
    return _invitation_out(invitation)


@router.post(
    "/t/{tenant_slug}/invitations/{invitation_id}:revoke", status_code=204, tags=["tenant"]
)
async def revoke_invitation(
    tenant_slug: str, invitation_id: UUID, principal: CurrentPrincipal, request: Request
) -> Response:
    async with tenant(request, principal, tenant_slug) as scope:
        await members.revoke_invitation(scope, invitation_id)
    return Response(status_code=204)


@router.put(
    "/t/{tenant_slug}/staff/{membership_id}/roles", response_model=StaffOut, tags=["tenant"]
)
async def set_roles(
    tenant_slug: str,
    membership_id: UUID,
    body: RolesIn,
    principal: CurrentPrincipal,
    request: Request,
) -> StaffOut:
    async with tenant(request, principal, tenant_slug) as scope:
        member = await members.set_roles(scope, membership_id, body.roles)
    return _staff_out(member)


@router.post("/t/{tenant_slug}/staff/{membership_id}:remove", status_code=204, tags=["tenant"])
async def remove_staff(
    tenant_slug: str, membership_id: UUID, principal: CurrentPrincipal, request: Request
) -> Response:
    async with tenant(request, principal, tenant_slug) as scope:
        await members.remove(scope, membership_id)
    return Response(status_code=204)


@router.get("/t/{tenant_slug}/audit-events", response_model=list[AuditEventOut], tags=["tenant"])
async def tenant_audit(
    tenant_slug: str,
    principal: CurrentPrincipal,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    before: UUID | None = None,
) -> list[AuditEventOut]:
    async with tenant(request, principal, tenant_slug) as scope:
        events = await audit.list_for_tenant(scope, limit=limit, before=before)
    return [AuditEventOut.model_validate(asdict(e)) for e in events]


# ---------------------------------------------------------------- storefront (public)
@router.get("/storefront/merchant", response_model=PublicMerchantOut, tags=["storefront"])
async def storefront_merchant(request: Request) -> PublicMerchantOut:
    """Public merchant identity, resolved from the Host header via the domains
    table. The client cannot name a tenant; only the hostname selects it."""
    host = request.headers.get("host", "")
    async with container_of(request).db.transaction() as conn:
        ref = await tenancy.resolve_by_host(conn, host)
        if ref is None:
            raise NotFound("unknown host")
        profile = await tenancy.public_profile(conn, ref)
    if profile is None:
        raise NotFound("unknown host")
    return PublicMerchantOut(
        slug=ref.slug,
        display_name=profile.display_name,
        tagline=profile.tagline,
        description=profile.description,
        brand_primary_color=profile.brand_primary_color,
        brand_accent_color=profile.brand_accent_color,
    )
