"""Telegram identities: ``identities(provider='telegram', subject=<user id>)``.

Identity mapping only (ADR-024): this finds or creates the global person for
an already-verified Telegram user id. It takes plain values, never the raw
``initData``, and grants nothing. A Telegram identity is its own person: it is
never linked to an existing staff account here (linking needs verified proof
of both identities, ADR-024).

Only the Telegram user id (as the identity subject) and a display name are
stored. Username, photo and language are not.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.audit import service as audit
from arada.identity.tables import identities, persons
from arada.kernel.context import RequestMeta
from arada.kernel.ids import uuid7

PROVIDER = "telegram"
MAX_DISPLAY_NAME = 120


@dataclass(frozen=True, slots=True)
class TelegramPerson:
    person_id: UUID
    status: str
    created: bool


def display_name(first_name: str, last_name: str | None) -> str:
    """A storable display name: no control characters, collapsed spaces, ≤120."""
    joined = f"{first_name} {last_name or ''}"
    visible = "".join(c for c in joined if unicodedata.category(c) != "Cc")
    cleaned = " ".join(visible.split())[:MAX_DISPLAY_NAME].strip()
    return cleaned or "Telegram user"


async def _find(conn: AsyncConnection, subject: str) -> TelegramPerson | None:
    row = (
        await conn.execute(
            select(persons.c.id, persons.c.status)
            .join(identities, identities.c.person_id == persons.c.id)
            .where(and_(identities.c.provider == PROVIDER, identities.c.subject == subject))
        )
    ).first()
    return TelegramPerson(row.id, row.status, created=False) if row else None


async def find_or_create_person(
    conn: AsyncConnection,
    meta: RequestMeta,
    *,
    telegram_user_id: int,
    name: str,
    audit_tenant_id: UUID | None,
) -> TelegramPerson:
    """The person behind a verified Telegram user id, created on first sight.

    Concurrent first logins of the same user converge on one person: the
    unique ``(provider, subject)`` key decides, and the loser reads the winner.
    """
    if telegram_user_id <= 0:
        raise ValueError("telegram user ids are positive")
    subject = str(telegram_user_id)
    found = await _find(conn, subject)
    if found is not None:
        return found
    person_id = uuid7()
    try:
        async with conn.begin_nested():
            await conn.execute(insert(persons).values(id=person_id, display_name=name))
            await conn.execute(
                insert(identities).values(
                    id=uuid7(), person_id=person_id, provider=PROVIDER, subject=subject
                )
            )
    except IntegrityError:
        winner = await _find(conn, subject)
        if winner is None:
            raise
        return winner
    await audit.record(
        conn,
        meta,
        actor_person_id=person_id,
        tenant_id=audit_tenant_id,
        action="identity.person_created",
        resource_type="person",
        resource_id=person_id,
        after={"provider": PROVIDER},
    )
    return TelegramPerson(person_id, "active", created=True)
