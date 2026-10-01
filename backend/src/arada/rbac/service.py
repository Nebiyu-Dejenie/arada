"""Authorisation data: effective grants and platform/vertical role assignment.

Grants are computed from the database on every request, so a revoked role
stops working immediately. Privileged (platform and vertical) grants are
withheld until the session is MFA-verified when policy requires it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

from sqlalchemy import and_, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.audit import service as audit
from arada.identity.tables import persons
from arada.kernel.config import Settings
from arada.kernel.context import Principal
from arada.kernel.db import RESTRICT_VIOLATION, sqlstate
from arada.kernel.errors import Conflict, NotFound, ValidationFailed
from arada.kernel.scope import Grants, Scope
from arada.rbac.catalogue import MFA_REQUIRED_TENANT_ROLES, PLATFORM_ROLES, VERTICAL_ROLES
from arada.rbac.tables import (
    platform_role_assignments,
    role_permissions,
    roles,
    vertical_role_assignments,
)
from arada.tenancy.tables import tenant_membership_roles, tenant_memberships
from arada.verticals import service as verticals_service
from arada.verticals.tables import verticals


def mfa_satisfied(settings: Settings, principal: Principal) -> bool:
    return principal.mfa_verified or not settings.require_mfa_for_privileged_scopes


def tenant_mfa_satisfied(settings: Settings, principal: Principal) -> bool:
    return principal.mfa_verified or not settings.require_mfa_for_privileged_tenant_roles


async def load_privileged_grants(conn: AsyncConnection, person_id: UUID, *, mfa_ok: bool) -> Grants:
    platform: frozenset[str] = frozenset(
        (
            await conn.execute(
                select(role_permissions.c.permission_key)
                .join(
                    platform_role_assignments,
                    platform_role_assignments.c.role_key == role_permissions.c.role_key,
                )
                .where(platform_role_assignments.c.person_id == person_id)
            )
        ).scalars()
    )
    vertical_rows = (
        await conn.execute(
            select(vertical_role_assignments.c.vertical_id, role_permissions.c.permission_key)
            .join(
                vertical_role_assignments,
                vertical_role_assignments.c.role_key == role_permissions.c.role_key,
            )
            .where(vertical_role_assignments.c.person_id == person_id)
        )
    ).all()
    by_vertical: dict[UUID, set[str]] = defaultdict(set)
    for vertical_id, permission in vertical_rows:
        by_vertical[vertical_id].add(permission)
    vertical = MappingProxyType({k: frozenset(v) for k, v in by_vertical.items()})

    if mfa_ok:
        return Grants(platform=platform, vertical=vertical)
    withheld = platform.union(*vertical.values()) if vertical else platform
    return Grants(withheld_for_mfa=frozenset(withheld))


@dataclass(frozen=True, slots=True)
class RoleInfo:
    key: str
    scope_type: str
    description: str
    permissions: tuple[str, ...]


async def catalogue(conn: AsyncConnection, scope_type: str | None = None) -> list[RoleInfo]:
    query = (
        select(
            roles.c.key,
            roles.c.scope_type,
            roles.c.description,
            func.array_agg(role_permissions.c.permission_key).label("perms"),
        )
        .join(role_permissions, role_permissions.c.role_key == roles.c.key)
        .group_by(roles.c.key)
        .order_by(roles.c.scope_type, roles.c.key)
    )
    if scope_type is not None:
        query = query.where(roles.c.scope_type == scope_type)
    rows = (await conn.execute(query)).all()
    return [RoleInfo(r.key, r.scope_type, r.description, tuple(sorted(r.perms))) for r in rows]


async def _require_person(conn: AsyncConnection, person_id: UUID) -> None:
    exists = (
        await conn.execute(select(persons.c.id).where(persons.c.id == person_id))
    ).scalar_one_or_none()
    if exists is None:
        raise NotFound("person not found")


async def grant_role(
    scope: Scope, *, person_id: UUID, role: str, vertical_key: str | None = None
) -> None:
    scope.require("roles.manage")
    await _require_person(scope.conn, person_id)
    if role in PLATFORM_ROLES:
        if vertical_key is not None:
            raise ValidationFailed(errors={"vertical": ["platform roles take no vertical"]})
        stmt = (
            pg_insert(platform_role_assignments)
            .values(person_id=person_id, role_key=role, granted_by=scope.actor_person_id)
            .on_conflict_do_nothing()
        )
        target = {"role": role}
    elif role in VERTICAL_ROLES:
        if vertical_key is None:
            raise ValidationFailed(errors={"vertical": ["vertical roles need a vertical"]})
        vertical = await verticals_service.get_by_key(scope.conn, vertical_key)
        stmt = (
            pg_insert(vertical_role_assignments)
            .values(
                person_id=person_id,
                vertical_id=vertical.id,
                role_key=role,
                granted_by=scope.actor_person_id,
            )
            .on_conflict_do_nothing()
        )
        target = {"role": role, "vertical": vertical_key}
    else:
        raise ValidationFailed(errors={"role": ["not a platform or vertical role"]})
    result = await scope.conn.execute(stmt)
    if result.rowcount:
        await audit.record_in(
            scope,
            action="rbac.role_granted",
            resource_type="person",
            resource_id=person_id,
            after=target,
        )


async def revoke_role(
    scope: Scope, *, person_id: UUID, role: str, vertical_key: str | None = None
) -> None:
    scope.require("roles.manage")
    if role in PLATFORM_ROLES:
        # The last SUPER_ADMIN is guarded by the database itself (migration
        # 0008): a trigger serialises concurrent revocations and refuses the
        # one that would leave none. The refusal aborts this transaction, so
        # nothing (deletion or audit) is committed.
        stmt = delete(platform_role_assignments).where(
            and_(
                platform_role_assignments.c.person_id == person_id,
                platform_role_assignments.c.role_key == role,
            )
        )
        target = {"role": role}
    elif role in VERTICAL_ROLES:
        if vertical_key is None:
            raise ValidationFailed(errors={"vertical": ["vertical roles need a vertical"]})
        vertical = await verticals_service.get_by_key(scope.conn, vertical_key)
        stmt = delete(vertical_role_assignments).where(
            and_(
                vertical_role_assignments.c.person_id == person_id,
                vertical_role_assignments.c.vertical_id == vertical.id,
                vertical_role_assignments.c.role_key == role,
            )
        )
        target = {"role": role, "vertical": vertical_key}
    else:
        raise ValidationFailed(errors={"role": ["not a platform or vertical role"]})
    try:
        result = await scope.conn.execute(stmt)
    except IntegrityError as exc:
        if role == "SUPER_ADMIN" and sqlstate(exc) == RESTRICT_VIOLATION:
            raise Conflict("cannot revoke the last SUPER_ADMIN") from exc
        raise
    if not result.rowcount:
        raise NotFound("role assignment not found")
    await audit.record_in(
        scope,
        action="rbac.role_revoked",
        resource_type="person",
        resource_id=person_id,
        before=target,
    )


async def privileged_roles_of(conn: AsyncConnection, person_id: UUID) -> dict[str, list[str]]:
    platform: list[str] = sorted(
        (
            await conn.execute(
                select(platform_role_assignments.c.role_key).where(
                    platform_role_assignments.c.person_id == person_id
                )
            )
        ).scalars()
    )
    rows = (
        await conn.execute(
            select(vertical_role_assignments.c.role_key, verticals.c.key)
            .join(verticals, verticals.c.id == vertical_role_assignments.c.vertical_id)
            .where(vertical_role_assignments.c.person_id == person_id)
        )
    ).all()
    return {"platform": platform, "vertical": sorted(f"{role}@{key}" for role, key in rows)}


async def any_super_admin(conn: AsyncConnection) -> bool:
    return (
        await conn.execute(
            select(func.count()).where(platform_role_assignments.c.role_key == "SUPER_ADMIN")
        )
    ).scalar_one() > 0


async def assign_super_admin_unchecked(conn: AsyncConnection, person_id: UUID) -> None:
    """Bootstrap only (CLI, first run). Never reachable from the API."""
    await conn.execute(
        insert(platform_role_assignments).values(person_id=person_id, role_key="SUPER_ADMIN")
    )


async def load_tenant_grants(
    conn: AsyncConnection, person_id: UUID, *, mfa_ok: bool
) -> tuple[frozenset[str], frozenset[str]]:
    """Permissions from the person's roles in the *current* tenant.

    Returns ``(usable, withheld_for_mfa)``. Without an MFA-verified session,
    permissions that only come from ``MFA_REQUIRED_TENANT_ROLES`` are withheld;
    permissions also held through another role stay usable.

    Runs inside a tenant context: RLS restricts the membership tables to that
    tenant, so this can never return another tenant's grants.
    """
    rows = (
        await conn.execute(
            select(tenant_membership_roles.c.role_key, role_permissions.c.permission_key)
            .select_from(tenant_membership_roles)
            .join(
                tenant_memberships,
                and_(
                    tenant_memberships.c.tenant_id == tenant_membership_roles.c.tenant_id,
                    tenant_memberships.c.id == tenant_membership_roles.c.membership_id,
                ),
            )
            .join(
                role_permissions,
                role_permissions.c.role_key == tenant_membership_roles.c.role_key,
            )
            .where(
                and_(
                    tenant_memberships.c.person_id == person_id,
                    tenant_memberships.c.status == "active",
                )
            )
        )
    ).all()
    usable = frozenset(p for r, p in rows if mfa_ok or r not in MFA_REQUIRED_TENANT_ROLES)
    return usable, frozenset(p for _, p in rows) - usable
