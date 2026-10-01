"""Server-side sessions with opaque bearer tokens.

Only the SHA-256 of a token is stored, so a database leak does not yield
usable tokens. Sessions have an absolute lifetime and a sliding idle timeout;
disabling a person invalidates all their sessions immediately.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.identity.tables import persons, sessions
from arada.kernel.config import Settings
from arada.kernel.context import Principal, RequestMeta
from arada.kernel.errors import Unauthenticated
from arada.kernel.ids import uuid7

TOKEN_BYTES = 32
_TOUCH_INTERVAL = timedelta(seconds=30)


def now_utc() -> datetime:
    return datetime.now(UTC)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


@dataclass(frozen=True, slots=True)
class IssuedSession:
    session_id: UUID
    token: str
    expires_at: datetime
    mfa_verified: bool


async def issue(
    conn: AsyncConnection,
    settings: Settings,
    meta: RequestMeta,
    *,
    person_id: UUID,
    mfa_verified: bool,
    not_after: datetime | None = None,
) -> IssuedSession:
    """Create a session. ``not_after`` caps its absolute expiry (rotation)."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = now_utc()
    expires_at = now + timedelta(hours=settings.session_absolute_timeout_hours)
    if not_after is not None:
        expires_at = min(expires_at, not_after)
    idle = min(now + timedelta(minutes=settings.session_idle_timeout_minutes), expires_at)
    session_id = uuid7()
    await conn.execute(
        insert(sessions).values(
            id=session_id,
            person_id=person_id,
            token_hash=hash_token(token),
            created_at=now,
            last_seen_at=now,
            idle_expires_at=idle,
            expires_at=expires_at,
            mfa_verified_at=now if mfa_verified else None,
            ip=meta.ip,
            user_agent=meta.user_agent,
        )
    )
    return IssuedSession(session_id, token, expires_at, mfa_verified)


async def authenticate(conn: AsyncConnection, settings: Settings, token: str) -> Principal:
    """Resolve a bearer token to a principal or raise ``Unauthenticated``.

    Every failure mode (unknown, revoked, expired, idle, disabled person)
    produces the same error so callers cannot probe token states.
    """
    row = (
        await conn.execute(
            select(
                sessions.c.id,
                sessions.c.person_id,
                sessions.c.last_seen_at,
                sessions.c.idle_expires_at,
                sessions.c.expires_at,
                sessions.c.mfa_verified_at,
                sessions.c.revoked_at,
                persons.c.status,
            )
            .join(persons, persons.c.id == sessions.c.person_id)
            .where(sessions.c.token_hash == hash_token(token))
        )
    ).first()
    now = now_utc()
    if (
        row is None
        or row.revoked_at is not None
        or row.status != "active"
        or now >= row.expires_at
        or now >= row.idle_expires_at
    ):
        raise Unauthenticated()

    if now - row.last_seen_at >= _TOUCH_INTERVAL:
        new_idle = min(
            now + timedelta(minutes=settings.session_idle_timeout_minutes), row.expires_at
        )
        await conn.execute(
            update(sessions)
            .where(sessions.c.id == row.id)
            .values(last_seen_at=now, idle_expires_at=new_idle)
        )
    return Principal(
        person_id=row.person_id, session_id=row.id, mfa_verified_at=row.mfa_verified_at
    )


async def rotate(
    conn: AsyncConnection,
    settings: Settings,
    meta: RequestMeta,
    principal: Principal,
    *,
    mfa_verified: bool,
    reason: str,
) -> IssuedSession:
    """Replace the caller's session with a new token on a privilege change.

    A token is never upgraded in place: the old session is revoked and a new
    one issued in the same transaction, so a token observed before the change
    (logs, a shared device, a fixation attempt) never gains the new
    privileges. The new session keeps the old one's absolute expiry, so
    rotation never extends a session's lifetime.
    """
    not_after: datetime | None = (
        await conn.execute(
            update(sessions)
            .where(and_(sessions.c.id == principal.session_id, sessions.c.revoked_at.is_(None)))
            .values(revoked_at=now_utc(), revoked_reason=reason)
            .returning(sessions.c.expires_at)
        )
    ).scalar_one_or_none()
    if not_after is None:  # revoked concurrently (for example a logout)
        raise Unauthenticated()
    return await issue(
        conn,
        settings,
        meta,
        person_id=principal.person_id,
        mfa_verified=mfa_verified,
        not_after=not_after,
    )


async def revoke(conn: AsyncConnection, session_id: UUID, reason: str) -> None:
    await conn.execute(
        update(sessions)
        .where(and_(sessions.c.id == session_id, sessions.c.revoked_at.is_(None)))
        .values(revoked_at=now_utc(), revoked_reason=reason)
    )


async def revoke_all_for_person(conn: AsyncConnection, person_id: UUID, reason: str) -> None:
    await conn.execute(
        update(sessions)
        .where(and_(sessions.c.person_id == person_id, sessions.c.revoked_at.is_(None)))
        .values(revoked_at=now_utc(), revoked_reason=reason)
    )
