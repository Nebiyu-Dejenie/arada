"""Customer sessions: opaque, server-side, bound to one tenant and customer (ADR-036).

Same mechanics as staff sessions (ADR-029): a random token, only its SHA-256
stored, a sliding idle timeout under an absolute lifetime, immediate
revocation. The difference is the binding: ``customer_sessions`` is under
FORCE RLS, and every function here runs inside the tenant context resolved
from the request host. A token issued by tenant A is therefore invisible at
tenant B's host: the database itself refuses to find it.

Customer tokens and staff tokens live in different tables and are checked by
different code, so neither can ever be used as the other.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.customers.tables import customer_sessions, customers
from arada.identity.tables import persons
from arada.kernel.config import Settings
from arada.kernel.context import CustomerPrincipal, RequestMeta
from arada.kernel.errors import Unauthenticated
from arada.kernel.ids import uuid7

TOKEN_BYTES = 32
_TOUCH_INTERVAL = timedelta(seconds=30)


def now_utc() -> datetime:
    return datetime.now(UTC)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


@dataclass(frozen=True, slots=True)
class IssuedCustomerSession:
    session_id: UUID
    customer_id: UUID
    expires_at: datetime
    token: str = field(repr=False)


async def _context_tenant(conn: AsyncConnection) -> UUID:
    tenant_id: UUID | None = (
        await conn.execute(select(func.control.current_tenant_id()))
    ).scalar_one_or_none()
    if tenant_id is None:
        raise RuntimeError("customer sessions are only handled inside a tenant context")
    return tenant_id


async def issue(
    conn: AsyncConnection,
    settings: Settings,
    meta: RequestMeta,
    *,
    tenant_id: UUID,
    customer_id: UUID,
) -> IssuedCustomerSession:
    if await _context_tenant(conn) != tenant_id:
        raise RuntimeError("tenant context does not match the session's tenant")
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = now_utc()
    expires_at = now + timedelta(hours=settings.customer_session_absolute_timeout_hours)
    idle = min(now + timedelta(minutes=settings.customer_session_idle_timeout_minutes), expires_at)
    session_id = uuid7()
    await conn.execute(
        insert(customer_sessions).values(
            id=session_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            token_hash=hash_token(token),
            created_at=now,
            last_seen_at=now,
            idle_expires_at=idle,
            expires_at=expires_at,
            ip=meta.ip,
            user_agent=meta.user_agent,
        )
    )
    return IssuedCustomerSession(session_id, customer_id, expires_at, token)


async def authenticate(
    conn: AsyncConnection, settings: Settings, *, tenant_id: UUID, token: str
) -> CustomerPrincipal:
    """Resolve a customer token inside ``tenant_id``'s context, or raise.

    Every failure (unknown, other tenant, revoked, expired, idle, disabled
    person) is the same ``Unauthenticated``, so token states cannot be probed.
    """
    if await _context_tenant(conn) != tenant_id:
        raise RuntimeError("tenant context does not match the request's tenant")
    row = (
        await conn.execute(
            select(
                customer_sessions.c.id,
                customer_sessions.c.tenant_id,
                customer_sessions.c.customer_id,
                customer_sessions.c.last_seen_at,
                customer_sessions.c.idle_expires_at,
                customer_sessions.c.expires_at,
                customer_sessions.c.revoked_at,
                customers.c.person_id,
                persons.c.status,
            )
            .join(
                customers,
                and_(
                    customers.c.tenant_id == customer_sessions.c.tenant_id,
                    customers.c.id == customer_sessions.c.customer_id,
                ),
            )
            .join(persons, persons.c.id == customers.c.person_id)
            .where(customer_sessions.c.token_hash == hash_token(token))
        )
    ).first()
    now = now_utc()
    if (
        row is None
        or row.tenant_id != tenant_id  # RLS already guarantees this; belt and braces
        or row.revoked_at is not None
        or row.status != "active"
        or now >= row.expires_at
        or now >= row.idle_expires_at
    ):
        raise Unauthenticated()
    if now - row.last_seen_at >= _TOUCH_INTERVAL:
        new_idle = min(
            now + timedelta(minutes=settings.customer_session_idle_timeout_minutes),
            row.expires_at,
        )
        await conn.execute(
            update(customer_sessions)
            .where(customer_sessions.c.id == row.id)
            .values(last_seen_at=now, idle_expires_at=new_idle)
        )
    return CustomerPrincipal(
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        person_id=row.person_id,
        session_id=row.id,
    )


async def revoke(conn: AsyncConnection, session_id: UUID, reason: str) -> None:
    await conn.execute(
        update(customer_sessions)
        .where(and_(customer_sessions.c.id == session_id, customer_sessions.c.revoked_at.is_(None)))
        .values(revoked_at=now_utc(), revoked_reason=reason)
    )


async def revoke_all_in_tenant(conn: AsyncConnection, reason: str) -> int:
    """Revoke every live session of the context tenant (RLS limits the reach)."""
    await _context_tenant(conn)
    result = await conn.execute(
        update(customer_sessions)
        .where(customer_sessions.c.revoked_at.is_(None))
        .values(revoked_at=now_utc(), revoked_reason=reason)
    )
    return int(result.rowcount or 0)
