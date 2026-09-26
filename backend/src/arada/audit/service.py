"""Audit trail (Permanent Command §23, Master Directive §87).

Audit rows are written in the **same transaction** as the change they
describe, so an action and its audit record commit or roll back together.
Values are sanitised before storage: keys that look secret are replaced, and
nothing but JSON-safe primitives is kept.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.audit.tables import audit_events
from arada.kernel.context import RequestMeta
from arada.kernel.db import Database
from arada.kernel.errors import Forbidden
from arada.kernel.ids import uuid7
from arada.kernel.scope import Scope

Outcome = Literal["success", "failure", "denied"]
REDACTED = "[REDACTED]"
_SECRET_KEYS = re.compile(
    r"(pass(word|wd)?|secret|token|hash|totp|otp|credential|api_?key|private_?key|kek|dek|nonce)",
    re.IGNORECASE,
)
MAX_PAGE = 200


def sanitise(value: Any) -> Any:
    """Make a value JSON-safe and strip anything that looks like a secret."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return sanitise(value.value)
    if isinstance(value, Mapping):
        return {
            str(k): (REDACTED if _SECRET_KEYS.search(str(k)) else sanitise(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [sanitise(v) for v in value]
    return str(value)


async def record(
    conn: AsyncConnection,
    meta: RequestMeta,
    *,
    actor_person_id: UUID | None,
    tenant_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: str | UUID | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    reason: str | None = None,
    outcome: Outcome = "success",
) -> UUID:
    event_id = uuid7()
    await conn.execute(
        insert(audit_events).values(
            id=event_id,
            occurred_at=func.now(),
            actor_type="person" if actor_person_id else "system",
            actor_person_id=actor_person_id,
            tenant_id=tenant_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            outcome=outcome,
            source=meta.source,
            request_id=meta.request_id,
            trace_id=meta.trace_id,
            ip=meta.ip,
            user_agent=meta.user_agent,
            reason=reason,
            before=sanitise(before) if before is not None else None,
            after=sanitise(after) if after is not None else None,
        )
    )
    return event_id


async def record_in(
    scope: Scope,
    *,
    action: str,
    resource_type: str,
    resource_id: str | UUID | None = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    reason: str | None = None,
    tenant_id: UUID | None = None,
) -> UUID:
    """Record an event for the scope's actor, defaulting to the scope's tenant."""
    return await record(
        scope.conn,
        scope.meta,
        actor_person_id=scope.actor_person_id,
        tenant_id=tenant_id
        if tenant_id is not None
        else (scope.tenant.id if scope.tenant else None),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before=before,
        after=after,
        reason=reason,
    )


@dataclass(frozen=True, slots=True)
class AuditEvent:
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


_COLUMNS = (
    audit_events.c.id,
    audit_events.c.occurred_at,
    audit_events.c.actor_type,
    audit_events.c.actor_person_id,
    audit_events.c.tenant_id,
    audit_events.c.action,
    audit_events.c.resource_type,
    audit_events.c.resource_id,
    audit_events.c.outcome,
    audit_events.c.source,
    audit_events.c.request_id,
    audit_events.c.trace_id,
    audit_events.c.reason,
    audit_events.c.before,
    audit_events.c.after,
)


def _page(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE))


async def list_for_tenant(
    scope: Scope, *, limit: int = 50, before: UUID | None = None
) -> list[AuditEvent]:
    """Tenant audit log. RLS guarantees only this tenant's rows are visible."""
    scope.require("audit.read")
    query = select(*_COLUMNS).order_by(audit_events.c.id.desc()).limit(_page(limit))
    if before is not None:
        query = query.where(audit_events.c.id < before)
    rows = (await scope.conn.execute(query)).all()
    return [AuditEvent(*row) for row in rows]


async def list_platform(
    scope: Scope,
    db: Database,
    *,
    tenant_id: UUID | None = None,
    action: str | None = None,
    limit: int = 50,
    before: UUID | None = None,
) -> list[AuditEvent]:
    """Platform-wide audit log, read through the RLS-bypassing reader role.

    Authorised first (platform ``audit.read``), then read on the reader pool.
    """
    if "audit.read" not in scope.grants.platform:
        scope.require("audit.read")  # raises the right error (403 / MFA step-up)
        raise Forbidden("platform audit requires a platform-scoped role")
    query = select(*_COLUMNS).order_by(audit_events.c.id.desc()).limit(_page(limit))
    if tenant_id is not None:
        query = query.where(audit_events.c.tenant_id == tenant_id)
    if action is not None:
        query = query.where(audit_events.c.action == action)
    if before is not None:
        query = query.where(audit_events.c.id < before)
    async with db.platform_read() as conn:
        rows = (await conn.execute(query)).all()
    return [AuditEvent(*row) for row in rows]
