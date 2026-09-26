"""Tenants (merchants): creation, lifecycle, profile, blueprint pin, domains.

A merchant is a tenant: the isolation boundary for every tenant-owned row.
Platform operations that act on a tenant switch the transaction into that
tenant's context first, so its RLS-protected rows and its audit events can
only ever be written for that tenant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.audit import service as audit
from arada.blueprints import service as blueprints
from arada.blueprints.tables import blueprint_versions
from arada.blueprints.tables import blueprints as blueprint_table
from arada.kernel.config import Settings
from arada.kernel.context import TenantRef, bind_tenant
from arada.kernel.db import set_context
from arada.kernel.errors import Conflict, NotFound, PreconditionFailed, ValidationFailed
from arada.kernel.ids import uuid7
from arada.kernel.scope import Scope
from arada.tenancy import members
from arada.tenancy.tables import (
    domains,
    merchant_profiles,
    tenant_blueprint_assignments,
    tenants,
)
from arada.verticals import service as verticals
from arada.verticals.tables import verticals as vertical_table

SLUG = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")
RESERVED_SLUGS = frozenset(
    {
        "www", "app", "api", "admin", "finance", "ops", "status", "merchant", "media", "static",
        "cdn", "assets", "auth", "login", "sso", "id", "account", "billing", "pay", "payments",
        "agent", "sms", "mail", "smtp", "imap", "mx", "ns", "help", "support", "docs", "blog",
        "shop", "store", "dev", "staging", "test", "internal", "root", "platform", "arada",
    }
)  # fmt: skip
RESERVED_PREFIXES = ("stg-", "dev-", "test-", "admin-", "finance-", "api-", "ops-")
AUDIT_ACTIONS = {
    "activate": "tenant.activated",
    "suspend": "tenant.suspended",
    "reactivate": "tenant.reactivated",
    "archive": "tenant.archived",
}
HOSTNAME = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

# action -> (permission, allowed source statuses, target status)
TRANSITIONS: dict[str, tuple[str, frozenset[str], str]] = {
    "activate": ("tenants.suspend", frozenset({"draft"}), "active"),
    "suspend": ("tenants.suspend", frozenset({"active"}), "suspended"),
    "reactivate": ("tenants.suspend", frozenset({"suspended"}), "active"),
    "archive": ("tenants.archive", frozenset({"draft", "suspended"}), "archived"),
}


@dataclass(frozen=True, slots=True)
class Profile:
    display_name: str
    tagline: str | None
    description: str | None
    brand_primary_color: str | None
    brand_accent_color: str | None
    contact_email: str | None
    contact_phone: str | None
    version: int


@dataclass(frozen=True, slots=True)
class TenantDetail:
    id: UUID
    slug: str
    display_name: str
    status: str
    vertical_id: UUID
    vertical_key: str
    blueprint_id: UUID
    blueprint_key: str
    blueprint_version_id: UUID
    blueprint_version: str
    isolation_tier: str
    currency: str
    default_locale: str
    timezone: str
    created_at: datetime
    version: int
    profile: Profile | None = None


def validate_slug(slug: str) -> None:
    if (
        not SLUG.match(slug)
        or "--" in slug
        or slug in RESERVED_SLUGS
        or slug.startswith(RESERVED_PREFIXES)
    ):
        raise ValidationFailed(
            errors={"slug": ["3-32 chars, lowercase letters/digits/hyphens, not reserved"]}
        )


def _ref(row: Any) -> TenantRef:
    return TenantRef(id=row.id, slug=row.slug, vertical_id=row.vertical_id, status=row.status)


async def resolve_by_slug(conn: AsyncConnection, slug: str) -> TenantRef | None:
    """Trusted server-side resolution. Archived tenants no longer exist to callers."""
    if not SLUG.match(slug):
        return None
    row = (
        await conn.execute(
            select(tenants.c.id, tenants.c.slug, tenants.c.vertical_id, tenants.c.status).where(
                and_(tenants.c.slug == slug, tenants.c.status != "archived")
            )
        )
    ).first()
    return _ref(row) if row else None


async def resolve_by_host(conn: AsyncConnection, host: str) -> TenantRef | None:
    """Host header -> tenant, through the domains table only (never client input)."""
    hostname = host.strip().lower().split(":", 1)[0].rstrip(".")
    if not HOSTNAME.match(hostname) or len(hostname) > 253:
        return None
    row = (
        await conn.execute(
            select(tenants.c.id, tenants.c.slug, tenants.c.vertical_id, tenants.c.status)
            .join(domains, domains.c.tenant_id == tenants.c.id)
            .where(
                and_(
                    domains.c.hostname == hostname,
                    domains.c.status == "active",
                    domains.c.kind == "storefront",
                    tenants.c.status.in_(("active",)),
                )
            )
        )
    ).first()
    return _ref(row) if row else None


async def enter_tenant(scope: Scope, tenant_id: UUID) -> TenantRef:
    """Switch a platform scope into one tenant's context (RLS + audit)."""
    row = (
        await scope.conn.execute(
            select(tenants.c.id, tenants.c.slug, tenants.c.vertical_id, tenants.c.status).where(
                tenants.c.id == tenant_id
            )
        )
    ).first()
    if row is None:
        raise NotFound("tenant not found")
    ref = _ref(row)
    await set_context(scope.conn, tenant_id=ref.id, person_id=scope.actor_person_id)
    scope.tenant = ref
    bind_tenant(ref.id)
    return ref


async def create_tenant(
    scope: Scope,
    settings: Settings,
    *,
    slug: str,
    display_name: str,
    vertical_key: str,
    blueprint_version_id: UUID,
) -> tuple[TenantDetail, members.Invitation]:
    vertical = await verticals.get_by_key(scope.conn, vertical_key)
    scope.require("tenants.create", vertical_id=vertical.id)
    validate_slug(slug)
    version = await blueprints.version_summary(scope.conn, blueprint_version_id)
    if version.vertical_id != vertical.id:
        raise ValidationFailed(errors={"blueprint_version_id": ["belongs to another vertical"]})
    if version.status != "published":
        raise ValidationFailed(errors={"blueprint_version_id": ["must be a published version"]})

    tenant_id = uuid7()
    try:
        async with scope.conn.begin_nested():
            await scope.conn.execute(
                insert(tenants).values(
                    id=tenant_id,
                    slug=slug,
                    display_name=display_name,
                    vertical_id=vertical.id,
                    blueprint_version_id=blueprint_version_id,
                    created_by=scope.actor_person_id,
                )
            )
    except IntegrityError as exc:
        raise Conflict("this slug is not available") from exc

    await enter_tenant(scope, tenant_id)
    await scope.conn.execute(
        insert(merchant_profiles).values(
            tenant_id=tenant_id, display_name=display_name, updated_by=scope.actor_person_id
        )
    )
    await scope.conn.execute(
        insert(tenant_blueprint_assignments).values(
            id=uuid7(),
            tenant_id=tenant_id,
            blueprint_version_id=blueprint_version_id,
            assigned_by=scope.actor_person_id,
            reason="initial assignment at creation",
        )
    )
    owner_invitation = await members.issue_invitation(
        scope, roles=["TENANT_OWNER"], ttl_hours=settings.invitation_ttl_hours
    )
    await audit.record_in(
        scope,
        action="tenant.created",
        resource_type="tenant",
        resource_id=tenant_id,
        after={
            "slug": slug,
            "display_name": display_name,
            "vertical": vertical_key,
            "blueprint_version_id": blueprint_version_id,
            "blueprint_version": version.version,
            "status": "draft",
        },
    )
    return await detail(scope.conn, tenant_id, with_profile=True), owner_invitation


async def detail(conn: AsyncConnection, tenant_id: UUID, *, with_profile: bool) -> TenantDetail:
    vt = vertical_table
    row = (
        await conn.execute(
            select(
                tenants,
                vt.c.key.label("vertical_key"),
                blueprint_table.c.id.label("blueprint_id"),
                blueprint_table.c.key.label("blueprint_key"),
                blueprint_versions.c.version_major,
                blueprint_versions.c.version_minor,
                blueprint_versions.c.version_patch,
            )
            .join(vt, vt.c.id == tenants.c.vertical_id)
            .join(blueprint_versions, blueprint_versions.c.id == tenants.c.blueprint_version_id)
            .join(blueprint_table, blueprint_table.c.id == blueprint_versions.c.blueprint_id)
            .where(tenants.c.id == tenant_id)
        )
    ).first()
    if row is None:
        raise NotFound("tenant not found")
    profile = await _profile(conn, tenant_id) if with_profile else None
    return TenantDetail(
        id=row.id,
        slug=row.slug,
        display_name=row.display_name,
        status=row.status,
        vertical_id=row.vertical_id,
        vertical_key=row.vertical_key,
        blueprint_id=row.blueprint_id,
        blueprint_key=row.blueprint_key,
        blueprint_version_id=row.blueprint_version_id,
        blueprint_version=f"{row.version_major}.{row.version_minor}.{row.version_patch}",
        isolation_tier=row.isolation_tier,
        currency=row.currency,
        default_locale=row.default_locale,
        timezone=row.timezone,
        created_at=row.created_at,
        version=row.version,
        profile=profile,
    )


async def _profile(conn: AsyncConnection, tenant_id: UUID) -> Profile | None:
    """RLS-protected: only readable inside this tenant's context."""
    row = (
        await conn.execute(
            select(
                merchant_profiles.c.display_name,
                merchant_profiles.c.tagline,
                merchant_profiles.c.description,
                merchant_profiles.c.brand_primary_color,
                merchant_profiles.c.brand_accent_color,
                merchant_profiles.c.contact_email,
                merchant_profiles.c.contact_phone,
                merchant_profiles.c.version,
            ).where(merchant_profiles.c.tenant_id == tenant_id)
        )
    ).first()
    return Profile(*row) if row else None


async def get_for_scope(scope: Scope) -> TenantDetail:
    scope.require("tenants.read")
    return await detail(scope.conn, scope.tenant_ref.id, with_profile=True)


PROFILE_FIELDS = frozenset(
    {
        "display_name", "tagline", "description", "brand_primary_color", "brand_accent_color",
        "contact_email", "contact_phone",
    }
)  # fmt: skip


async def update_profile(
    scope: Scope, changes: dict[str, Any], *, expected_version: int
) -> Profile:
    scope.require("tenants.manage", write=True)
    unknown = set(changes) - PROFILE_FIELDS
    if unknown:  # defence in depth behind the API's extra="forbid"
        raise ValidationFailed(errors={k: ["not an editable field"] for k in unknown})
    if not changes:
        raise ValidationFailed(errors={"body": ["nothing to update"]})
    before = await _profile(scope.conn, scope.tenant_ref.id)
    if before is None:
        raise NotFound("profile not found")
    result = await scope.conn.execute(
        update(merchant_profiles)
        .where(
            and_(
                merchant_profiles.c.tenant_id == scope.tenant_ref.id,
                merchant_profiles.c.version == expected_version,
            )
        )
        .values(
            **changes,
            version=merchant_profiles.c.version + 1,
            updated_at=func.now(),
            updated_by=scope.actor_person_id,
        )
    )
    if result.rowcount != 1:
        raise PreconditionFailed()
    after = await _profile(scope.conn, scope.tenant_ref.id)
    if after is None:
        raise NotFound("profile not found")
    await audit.record_in(
        scope,
        action="tenant.profile_updated",
        resource_type="merchant_profile",
        resource_id=scope.tenant_ref.id,
        before={k: getattr(before, k) for k in changes},
        after={k: getattr(after, k) for k in changes},
    )
    return after


async def list_tenants(
    scope: Scope, *, vertical_key: str | None = None, status: str | None = None
) -> list[TenantDetail]:
    query = select(tenants.c.id).order_by(tenants.c.slug)
    if vertical_key is not None:
        vertical = await verticals.get_by_key(scope.conn, vertical_key)
        scope.require("tenants.read", vertical_id=vertical.id)
        query = query.where(tenants.c.vertical_id == vertical.id)
    elif "tenants.read" not in scope.grants.platform:
        visible = [v for v, perms in scope.grants.vertical.items() if "tenants.read" in perms]
        if not visible:
            scope.require("tenants.read")
        query = query.where(tenants.c.vertical_id.in_(visible))
    if status is not None:
        query = query.where(tenants.c.status == status)
    ids: list[UUID] = list((await scope.conn.execute(query)).scalars().all())
    return [await detail(scope.conn, tid, with_profile=False) for tid in ids]


async def change_status(
    scope: Scope, tenant_id: UUID, action: str, reason: str | None
) -> TenantDetail:
    if action not in TRANSITIONS:
        raise ValidationFailed(errors={"action": ["unknown lifecycle action"]})
    permission, sources, target = TRANSITIONS[action]
    tenant = await enter_tenant(scope, tenant_id)
    scope.require(permission, vertical_id=tenant.vertical_id)
    result = await scope.conn.execute(
        update(tenants)
        .where(and_(tenants.c.id == tenant_id, tenants.c.status.in_(sources)))
        .values(status=target, updated_at=func.now(), version=tenants.c.version + 1)
    )
    if result.rowcount != 1:
        raise Conflict(f"cannot {action} a tenant in status {tenant.status}")
    await audit.record_in(
        scope,
        action=AUDIT_ACTIONS[action],
        resource_type="tenant",
        resource_id=tenant_id,
        before={"status": tenant.status},
        after={"status": target},
        reason=reason,
    )
    return await detail(scope.conn, tenant_id, with_profile=False)


async def assign_blueprint(
    scope: Scope, tenant_id: UUID, blueprint_version_id: UUID, reason: str
) -> TenantDetail:
    """Explicitly move a tenant to another published version (never implicit).

    Phase 1 has no blueprint-bound tenant data yet, so the pin moves without a
    data migration; from Phase 3 this goes through migration plans (ADR-006).
    """
    tenant = await enter_tenant(scope, tenant_id)
    scope.require("blueprints.migrate", vertical_id=tenant.vertical_id)
    if tenant.status == "archived":
        raise NotFound("tenant not found")
    current: UUID = (
        await scope.conn.execute(
            select(tenants.c.blueprint_version_id)
            .where(tenants.c.id == tenant_id)
            .with_for_update()
        )
    ).scalar_one()
    target = await blueprints.version_summary(scope.conn, blueprint_version_id)
    if target.vertical_id != tenant.vertical_id:
        raise ValidationFailed(errors={"blueprint_version_id": ["belongs to another vertical"]})
    if target.status != "published":
        raise ValidationFailed(errors={"blueprint_version_id": ["must be a published version"]})
    if current == blueprint_version_id:
        raise Conflict("tenant is already pinned to this version")
    previous = await blueprints.version_summary(scope.conn, current)
    await scope.conn.execute(
        update(tenants)
        .where(tenants.c.id == tenant_id)
        .values(
            blueprint_version_id=blueprint_version_id,
            updated_at=func.now(),
            version=tenants.c.version + 1,
        )
    )
    await scope.conn.execute(
        insert(tenant_blueprint_assignments).values(
            id=uuid7(),
            tenant_id=tenant_id,
            blueprint_version_id=blueprint_version_id,
            previous_blueprint_version_id=current,
            assigned_by=scope.actor_person_id,
            reason=reason,
        )
    )
    await audit.record_in(
        scope,
        action="tenant.blueprint_assigned",
        resource_type="tenant",
        resource_id=tenant_id,
        before={"blueprint_version_id": current, "blueprint_version": previous.version},
        after={"blueprint_version_id": blueprint_version_id, "blueprint_version": target.version},
        reason=reason,
    )
    return await detail(scope.conn, tenant_id, with_profile=False)


async def blueprint_history(scope: Scope) -> list[dict[str, Any]]:
    scope.require("blueprints.read")
    rows = (
        await scope.conn.execute(
            select(tenant_blueprint_assignments)
            .where(tenant_blueprint_assignments.c.tenant_id == scope.tenant_ref.id)
            .order_by(tenant_blueprint_assignments.c.assigned_at)
        )
    ).all()
    return [dict(r._mapping) for r in rows]


async def add_domain(scope: Scope, tenant_id: UUID, hostname: str) -> UUID:
    scope.require("domains.manage")
    host = hostname.strip().lower().rstrip(".")
    if not HOSTNAME.match(host):
        raise ValidationFailed(errors={"hostname": ["not a valid lowercase hostname"]})
    await enter_tenant(scope, tenant_id)
    domain_id = uuid7()
    try:
        async with scope.conn.begin_nested():
            await scope.conn.execute(
                insert(domains).values(
                    id=domain_id,
                    tenant_id=tenant_id,
                    hostname=host,
                    kind="storefront",
                    created_by=scope.actor_person_id,
                )
            )
    except IntegrityError as exc:
        raise Conflict("hostname already in use") from exc
    await audit.record_in(
        scope, action="tenant.domain_added", resource_type="domain", resource_id=domain_id,
        after={"hostname": host},
    )  # fmt: skip
    return domain_id


async def public_profile(conn: AsyncConnection, tenant: TenantRef) -> Profile | None:
    await set_context(conn, tenant_id=tenant.id, person_id=None)
    return await _profile(conn, tenant.id)
