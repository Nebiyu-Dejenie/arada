"""Tenant membership: staff, invitations, and tenant-scoped role assignment.

Privilege-escalation rules (10_RBAC.md §4):

* A tenant-level grantor may only grant a role whose permissions are a subset
  of their own effective tenant permissions (a TENANT_ADMIN cannot mint a
  TENANT_OWNER), and may not change their own roles.
* Platform/vertical administrators holding ``staff.manage`` for the tenant's
  vertical may grant any tenant role.
* A tenant always keeps at least one active TENANT_OWNER.

Invitations are the only way a person joins a tenant: the token is shown
once, stored as a SHA-256 hash, single-use and expiring.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.audit import service as audit
from arada.identity.service import create_person_with_password
from arada.identity.tables import identities, persons
from arada.kernel.config import Settings
from arada.kernel.context import Principal, RequestMeta
from arada.kernel.db import Database, set_context
from arada.kernel.errors import (
    Conflict,
    Forbidden,
    NotFound,
    Unauthenticated,
    ValidationFailed,
)
from arada.kernel.ids import uuid7
from arada.kernel.scope import Scope
from arada.rbac.tables import role_permissions, roles
from arada.tenancy.tables import (
    tenant_invitation_roles,
    tenant_invitations,
    tenant_membership_roles,
    tenant_memberships,
    tenants,
)

OWNER = "TENANT_OWNER"


@dataclass(frozen=True, slots=True)
class Invitation:
    id: UUID
    token: str
    expires_at: datetime
    roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StaffMember:
    membership_id: UUID
    person_id: UUID
    display_name: str
    username: str | None
    status: str
    roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Membership:
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    membership_id: UUID
    roles: tuple[str, ...]


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


async def _lock_staff(scope: Scope) -> None:
    """Serialise staff mutations per tenant (last-owner checks stay correct)."""
    await scope.conn.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"staff:{scope.tenant_ref.id}", 0)))
    )


async def _role_permissions(conn: AsyncConnection, role: str) -> frozenset[str]:
    scope_type: str | None = (
        await conn.execute(select(roles.c.scope_type).where(roles.c.key == role))
    ).scalar_one_or_none()
    if scope_type != "tenant":
        raise ValidationFailed(errors={"roles": [f"{role} is not a tenant role"]})
    return frozenset(
        (
            await conn.execute(
                select(role_permissions.c.permission_key).where(role_permissions.c.role_key == role)
            )
        ).scalars()
    )


async def _check_grantable(scope: Scope, requested: set[str]) -> None:
    privileged = scope.grants.privileged("staff.manage", scope.tenant_ref.vertical_id)
    for role in sorted(requested):
        perms = await _role_permissions(scope.conn, role)
        if not privileged and not perms <= scope.grants.tenant:
            raise Forbidden(f"you cannot grant {role}: it exceeds your own permissions")


def _normalise_roles(requested: list[str]) -> set[str]:
    wanted = set(requested)
    if not wanted:
        raise ValidationFailed(errors={"roles": ["at least one role is required"]})
    return wanted


async def issue_invitation(scope: Scope, *, roles: list[str], ttl_hours: int) -> Invitation:
    """Create an invitation. Callers authorise (and check grantability) first."""
    wanted = _normalise_roles(roles)
    for role in wanted:
        await _role_permissions(scope.conn, role)  # validates tenant-scope roles
    token = secrets.token_urlsafe(32)
    invitation_id = uuid7()
    expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)
    await scope.conn.execute(
        insert(tenant_invitations).values(
            id=invitation_id,
            tenant_id=scope.tenant_ref.id,
            token_hash=_hash(token),
            created_by=scope.actor_person_id,
            expires_at=expires_at,
        )
    )
    await scope.conn.execute(
        insert(tenant_invitation_roles),
        [
            {"tenant_id": scope.tenant_ref.id, "invitation_id": invitation_id, "role_key": r}
            for r in sorted(wanted)
        ],
    )
    await audit.record_in(
        scope,
        action="tenant.invitation_created",
        resource_type="invitation",
        resource_id=invitation_id,
        after={"roles": sorted(wanted), "expires_at": expires_at},
    )
    return Invitation(invitation_id, token, expires_at, tuple(sorted(wanted)))


async def invite(
    scope: Scope, settings: Settings, *, roles: list[str], ttl_hours: int | None
) -> Invitation:
    scope.require("staff.manage", write=True)
    wanted = _normalise_roles(roles)
    await _check_grantable(scope, wanted)
    ttl = min(ttl_hours or settings.invitation_ttl_hours, settings.invitation_ttl_hours)
    return await issue_invitation(scope, roles=sorted(wanted), ttl_hours=ttl)


async def revoke_invitation(scope: Scope, invitation_id: UUID) -> None:
    scope.require("staff.manage", write=True)
    result = await scope.conn.execute(
        update(tenant_invitations)
        .where(
            and_(
                tenant_invitations.c.id == invitation_id,
                tenant_invitations.c.accepted_at.is_(None),
                tenant_invitations.c.revoked_at.is_(None),
            )
        )
        .values(revoked_at=func.now())
    )
    if result.rowcount != 1:
        raise NotFound("open invitation not found")
    await audit.record_in(
        scope,
        action="tenant.invitation_revoked",
        resource_type="invitation",
        resource_id=invitation_id,
    )


@dataclass(frozen=True, slots=True)
class NewAccount:
    username: str
    password: str
    display_name: str


async def accept_invitation(
    db: Database,
    meta: RequestMeta,
    *,
    token: str,
    principal: Principal | None,
    new_account: NewAccount | None,
) -> Membership:
    token_hash = _hash(token)
    async with db.transaction(person_id=principal.person_id if principal else None) as conn:
        # Narrow cross-tenant lookup: token hash -> tenant, nothing else.
        tenant_id: UUID | None = (
            await conn.execute(select(func.control.resolve_invitation(token_hash)))
        ).scalar_one_or_none()
        if tenant_id is None:
            raise NotFound("invitation not found, expired or already used")
        await set_context(
            conn, tenant_id=tenant_id, person_id=principal.person_id if principal else None
        )
        invitation = (
            await conn.execute(
                select(tenant_invitations)
                .where(tenant_invitations.c.token_hash == token_hash)
                .with_for_update()
            )
        ).first()
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or invitation.expires_at <= datetime.now(UTC)
        ):
            raise NotFound("invitation not found, expired or already used")
        tenant = (
            await conn.execute(
                select(tenants.c.slug, tenants.c.display_name, tenants.c.status).where(
                    tenants.c.id == tenant_id
                )
            )
        ).first()
        if tenant is None or tenant.status == "archived":
            raise NotFound("invitation not found, expired or already used")

        if principal is not None:
            if new_account is not None:
                raise ValidationFailed(errors={"new_account": ["already authenticated"]})
            person_id = principal.person_id
        else:
            if new_account is None:
                raise Unauthenticated("log in, or provide new_account to register")
            person_id = await create_person_with_password(
                conn,
                meta,
                actor_person_id=None,
                audit_tenant_id=tenant_id,
                username=new_account.username,
                password=new_account.password,
                display_name=new_account.display_name,
            )
            await set_context(conn, tenant_id=tenant_id, person_id=person_id)

        existing = (
            await conn.execute(
                select(tenant_memberships.c.id, tenant_memberships.c.status).where(
                    tenant_memberships.c.person_id == person_id
                )
            )
        ).first()
        if existing is None:
            membership_id = uuid7()
            await conn.execute(
                insert(tenant_memberships).values(
                    id=membership_id,
                    tenant_id=tenant_id,
                    person_id=person_id,
                    created_by=invitation.created_by,
                )
            )
        else:
            membership_id = existing.id
            if existing.status != "active":
                await conn.execute(
                    update(tenant_memberships)
                    .where(tenant_memberships.c.id == membership_id)
                    .values(status="active", updated_at=func.now())
                )
        invited_roles: list[str] = sorted(
            (
                await conn.execute(
                    select(tenant_invitation_roles.c.role_key).where(
                        tenant_invitation_roles.c.invitation_id == invitation.id
                    )
                )
            ).scalars()
        )
        await conn.execute(
            pg_insert(tenant_membership_roles)
            .values(
                [
                    {
                        "tenant_id": tenant_id,
                        "membership_id": membership_id,
                        "role_key": role,
                        "granted_by": invitation.created_by,
                    }
                    for role in invited_roles
                ]
            )
            .on_conflict_do_nothing()
        )
        await conn.execute(
            update(tenant_invitations)
            .where(tenant_invitations.c.id == invitation.id)
            .values(accepted_at=func.now(), accepted_by=person_id)
        )
        await audit.record(
            conn,
            meta,
            actor_person_id=person_id,
            tenant_id=tenant_id,
            action="tenant.invitation_accepted",
            resource_type="membership",
            resource_id=membership_id,
            after={"invitation_id": invitation.id, "roles": invited_roles},
        )
        all_roles = await _roles_of(conn, membership_id)
    return Membership(tenant_id, tenant.slug, tenant.display_name, membership_id, all_roles)


async def _roles_of(conn: AsyncConnection, membership_id: UUID) -> tuple[str, ...]:
    return tuple(
        sorted(
            (
                await conn.execute(
                    select(tenant_membership_roles.c.role_key).where(
                        tenant_membership_roles.c.membership_id == membership_id
                    )
                )
            ).scalars()
        )
    )


async def list_staff(scope: Scope) -> list[StaffMember]:
    scope.require("staff.read")
    rows = (
        await scope.conn.execute(
            select(
                tenant_memberships.c.id,
                tenant_memberships.c.person_id,
                persons.c.display_name,
                identities.c.subject,
                tenant_memberships.c.status,
                func.coalesce(
                    func.array_agg(tenant_membership_roles.c.role_key).filter(
                        tenant_membership_roles.c.role_key.is_not(None)
                    ),
                    [],
                ).label("roles"),
            )
            .join(persons, persons.c.id == tenant_memberships.c.person_id)
            .outerjoin(
                identities,
                and_(identities.c.person_id == persons.c.id, identities.c.provider == "password"),
            )
            .outerjoin(
                tenant_membership_roles,
                and_(
                    tenant_membership_roles.c.tenant_id == tenant_memberships.c.tenant_id,
                    tenant_membership_roles.c.membership_id == tenant_memberships.c.id,
                ),
            )
            .group_by(tenant_memberships.c.id, persons.c.display_name, identities.c.subject)
            .order_by(tenant_memberships.c.created_at)
        )
    ).all()
    return [
        StaffMember(r.id, r.person_id, r.display_name, r.subject, r.status, tuple(sorted(r.roles)))
        for r in rows
    ]


async def _locked_membership(scope: Scope, membership_id: UUID) -> tuple[UUID, str]:
    row = (
        await scope.conn.execute(
            select(tenant_memberships.c.person_id, tenant_memberships.c.status)
            .where(tenant_memberships.c.id == membership_id)
            .with_for_update()
        )
    ).first()
    if row is None:  # includes every other tenant's membership (RLS)
        raise NotFound("staff member not found")
    return row.person_id, row.status


async def _other_active_owners(scope: Scope, membership_id: UUID) -> int:
    return (
        await scope.conn.execute(
            select(func.count())
            .select_from(tenant_membership_roles)
            .join(
                tenant_memberships,
                and_(
                    tenant_memberships.c.tenant_id == tenant_membership_roles.c.tenant_id,
                    tenant_memberships.c.id == tenant_membership_roles.c.membership_id,
                ),
            )
            .where(
                and_(
                    tenant_membership_roles.c.role_key == OWNER,
                    tenant_memberships.c.status == "active",
                    tenant_memberships.c.id != membership_id,
                )
            )
        )
    ).scalar_one()


def _guard_self(scope: Scope, person_id: UUID) -> None:
    if person_id == scope.actor_person_id and not scope.grants.privileged(
        "staff.manage", scope.tenant_ref.vertical_id
    ):
        raise Forbidden("you cannot change your own roles or membership")


async def set_roles(scope: Scope, membership_id: UUID, requested: list[str]) -> StaffMember:
    scope.require("staff.manage", write=True)
    wanted = _normalise_roles(requested)
    await _lock_staff(scope)
    person_id, status = await _locked_membership(scope, membership_id)
    if status != "active":
        raise Conflict("staff member is not active")
    _guard_self(scope, person_id)
    current = set(await _roles_of(scope.conn, membership_id))
    await _check_grantable(scope, (wanted - current) | (current - wanted))
    if (
        OWNER in current
        and OWNER not in wanted
        and await _other_active_owners(scope, membership_id) == 0
    ):
        raise Conflict("a tenant must keep at least one owner")
    if current - wanted:
        await scope.conn.execute(
            delete(tenant_membership_roles).where(
                and_(
                    tenant_membership_roles.c.membership_id == membership_id,
                    tenant_membership_roles.c.role_key.in_(sorted(current - wanted)),
                )
            )
        )
    if wanted - current:
        await scope.conn.execute(
            insert(tenant_membership_roles),
            [
                {
                    "tenant_id": scope.tenant_ref.id,
                    "membership_id": membership_id,
                    "role_key": role,
                    "granted_by": scope.actor_person_id,
                }
                for role in sorted(wanted - current)
            ],
        )
    await audit.record_in(
        scope,
        action="tenant.staff_roles_changed",
        resource_type="membership",
        resource_id=membership_id,
        before={"roles": sorted(current)},
        after={"roles": sorted(wanted)},
    )
    staff = {m.membership_id: m for m in await list_staff(scope)}
    return staff[membership_id]


async def remove(scope: Scope, membership_id: UUID) -> None:
    scope.require("staff.manage", write=True)
    await _lock_staff(scope)
    person_id, status = await _locked_membership(scope, membership_id)
    if status != "active":
        raise Conflict("staff member is not active")
    _guard_self(scope, person_id)
    current = set(await _roles_of(scope.conn, membership_id))
    await _check_grantable(scope, current)
    if OWNER in current and await _other_active_owners(scope, membership_id) == 0:
        raise Conflict("a tenant must keep at least one owner")
    await scope.conn.execute(
        delete(tenant_membership_roles).where(
            tenant_membership_roles.c.membership_id == membership_id
        )
    )
    await scope.conn.execute(
        update(tenant_memberships)
        .where(tenant_memberships.c.id == membership_id)
        .values(status="removed", updated_at=func.now())
    )
    await audit.record_in(
        scope,
        action="tenant.staff_removed",
        resource_type="membership",
        resource_id=membership_id,
        before={"roles": sorted(current)},
    )


async def memberships_of(conn: AsyncConnection, person_id: UUID) -> list[Membership]:
    """All active memberships of a person, via the narrow resolver function."""
    await set_context(conn, tenant_id=None, person_id=person_id)
    rows = (
        await conn.execute(
            text("SELECT tenant_id, membership_id FROM control.memberships_of_current_person()")
        )
    ).all()
    result: list[Membership] = []
    for tenant_id, membership_id in rows:
        tenant = (
            await conn.execute(
                select(tenants.c.slug, tenants.c.display_name, tenants.c.status).where(
                    tenants.c.id == tenant_id
                )
            )
        ).first()
        if tenant is None or tenant.status == "archived":
            continue
        await set_context(conn, tenant_id=tenant_id, person_id=person_id)
        result.append(
            Membership(
                tenant_id,
                tenant.slug,
                tenant.display_name,
                membership_id,
                await _roles_of(conn, membership_id),
            )
        )
    await set_context(conn, tenant_id=None, person_id=person_id)
    return result
