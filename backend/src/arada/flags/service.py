"""Feature flag management and per-tenant evaluation (Permanent Command §29)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.audit import service as audit
from arada.blueprints.tables import blueprint_versions
from arada.flags.evaluation import FlagValue, Override, evaluate
from arada.flags.tables import feature_flag_overrides, feature_flags
from arada.kernel.errors import NotFound, ValidationFailed
from arada.kernel.ids import uuid7
from arada.kernel.scope import Scope
from arada.tenancy import service as tenancy
from arada.tenancy.tables import tenants
from arada.verticals import service as verticals

OV = feature_flag_overrides.c


@dataclass(frozen=True, slots=True)
class FlagInfo:
    key: str
    description: str
    default_enabled: bool
    allowed_scopes: tuple[str, ...]
    overrides: tuple[dict[str, Any], ...]


async def _flag(conn: AsyncConnection, key: str) -> Any:
    row = (await conn.execute(select(feature_flags).where(feature_flags.c.key == key))).first()
    if row is None:
        raise NotFound("feature flag not found")
    return row


async def list_flags(scope: Scope) -> list[FlagInfo]:
    scope.require("flags.manage")
    flags = (await scope.conn.execute(select(feature_flags).order_by(feature_flags.c.key))).all()
    overrides = (
        await scope.conn.execute(select(feature_flag_overrides).order_by(OV.flag_key))
    ).all()
    by_flag: dict[str, list[dict[str, Any]]] = {}
    for o in overrides:
        by_flag.setdefault(o.flag_key, []).append(
            {
                "scope_type": o.scope_type,
                "vertical_id": o.vertical_id,
                "tenant_id": o.tenant_id,
                "enabled": o.enabled,
                "enforced": o.enforced,
                "reason": o.reason,
            }
        )
    return [
        FlagInfo(
            f.key,
            f.description,
            f.default_enabled,
            tuple(f.allowed_scopes),
            tuple(by_flag.get(f.key, [])),
        )
        for f in flags
    ]


async def _target(
    scope: Scope, scope_type: str, vertical_key: str | None, tenant_slug: str | None
) -> tuple[UUID | None, UUID | None]:
    if scope_type == "platform":
        if vertical_key or tenant_slug:
            raise ValidationFailed(errors={"scope_type": ["platform overrides take no target"]})
        return None, None
    if scope_type == "vertical":
        if not vertical_key or tenant_slug:
            raise ValidationFailed(
                errors={"vertical": ["vertical overrides need exactly a vertical"]}
            )
        return (await verticals.get_by_key(scope.conn, vertical_key)).id, None
    if not tenant_slug or vertical_key:
        raise ValidationFailed(errors={"tenant": ["tenant overrides need exactly a tenant"]})
    ref = await tenancy.resolve_by_slug(scope.conn, tenant_slug)
    if ref is None:
        raise NotFound("tenant not found")
    await tenancy.enter_tenant(scope, ref.id)  # audit lands in the tenant's trail
    return None, ref.id


def _match(scope_type: str, vertical_id: UUID | None, tenant_id: UUID | None) -> Any:
    return and_(
        OV.scope_type == scope_type,
        OV.vertical_id.is_(None) if vertical_id is None else OV.vertical_id == vertical_id,
        OV.tenant_id.is_(None) if tenant_id is None else OV.tenant_id == tenant_id,
    )


async def set_override(
    scope: Scope,
    *,
    key: str,
    scope_type: str,
    vertical_key: str | None,
    tenant_slug: str | None,
    enabled: bool,
    enforced: bool,
    reason: str | None,
) -> None:
    scope.require("flags.manage")
    flag = await _flag(scope.conn, key)
    if scope_type not in flag.allowed_scopes:
        raise ValidationFailed(
            errors={"scope_type": [f"{key} cannot be overridden at {scope_type}"]}
        )
    if enforced and scope_type != "platform":
        raise ValidationFailed(errors={"enforced": ["only platform overrides can be enforced"]})
    vertical_id, tenant_id = await _target(scope, scope_type, vertical_key, tenant_slug)
    before = (
        await scope.conn.execute(
            select(OV.enabled, OV.enforced).where(
                and_(OV.flag_key == key, _match(scope_type, vertical_id, tenant_id))
            )
        )
    ).first()
    index = {
        "platform": [OV.flag_key],
        "vertical": [OV.flag_key, OV.vertical_id],
        "tenant": [OV.flag_key, OV.tenant_id],
    }
    stmt = pg_insert(feature_flag_overrides).values(
        id=uuid7(),
        flag_key=key,
        scope_type=scope_type,
        vertical_id=vertical_id,
        tenant_id=tenant_id,
        enabled=enabled,
        enforced=enforced,
        reason=reason,
        updated_by=scope.actor_person_id,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=index[scope_type],
        index_where=OV.scope_type == scope_type,
        set_={
            "enabled": enabled,
            "enforced": enforced,
            "reason": reason,
            "updated_at": func.now(),
            "updated_by": scope.actor_person_id,
        },
    )
    await scope.conn.execute(stmt)
    await audit.record_in(
        scope,
        action="feature_flag.override_set",
        resource_type="feature_flag",
        resource_id=key,
        before={"enabled": before.enabled, "enforced": before.enforced} if before else None,
        after={
            "scope_type": scope_type,
            "vertical": vertical_key,
            "tenant": tenant_slug,
            "enabled": enabled,
            "enforced": enforced,
        },
        reason=reason,
    )


async def clear_override(
    scope: Scope, *, key: str, scope_type: str, vertical_key: str | None, tenant_slug: str | None
) -> None:
    scope.require("flags.manage")
    await _flag(scope.conn, key)
    vertical_id, tenant_id = await _target(scope, scope_type, vertical_key, tenant_slug)
    result = await scope.conn.execute(
        delete(feature_flag_overrides).where(
            and_(OV.flag_key == key, _match(scope_type, vertical_id, tenant_id))
        )
    )
    if not result.rowcount:
        raise NotFound("override not found")
    await audit.record_in(
        scope,
        action="feature_flag.override_cleared",
        resource_type="feature_flag",
        resource_id=key,
        before={"scope_type": scope_type, "vertical": vertical_key, "tenant": tenant_slug},
    )


async def effective_for_tenant(conn: AsyncConnection, tenant_id: UUID) -> dict[str, FlagValue]:
    """Evaluate every flag for one tenant (no authorisation: callers check)."""
    tenant = (
        await conn.execute(
            select(tenants.c.vertical_id, blueprint_versions.c.definition)
            .join(blueprint_versions, blueprint_versions.c.id == tenants.c.blueprint_version_id)
            .where(tenants.c.id == tenant_id)
        )
    ).first()
    if tenant is None:
        raise NotFound("tenant not found")
    blueprint_features: dict[str, bool] = tenant.definition.get("features", {})
    flags = (await conn.execute(select(feature_flags))).all()
    overrides = (
        await conn.execute(
            select(feature_flag_overrides).where(
                (OV.scope_type == "platform")
                | ((OV.scope_type == "vertical") & (OV.vertical_id == tenant.vertical_id))
                | ((OV.scope_type == "tenant") & (OV.tenant_id == tenant_id))
            )
        )
    ).all()
    found: dict[tuple[str, str], Override] = {
        (o.flag_key, o.scope_type): Override(o.enabled, o.enforced) for o in overrides
    }
    return {
        f.key: evaluate(
            f.key,
            default=f.default_enabled,
            platform=found.get((f.key, "platform")),
            vertical=found.get((f.key, "vertical")),
            tenant=found.get((f.key, "tenant")),
            blueprint_default=blueprint_features.get(f.key),
        )
        for f in flags
    }


async def for_scope(scope: Scope) -> dict[str, FlagValue]:
    scope.require("tenants.read")
    return await effective_for_tenant(scope.conn, scope.tenant_ref.id)
