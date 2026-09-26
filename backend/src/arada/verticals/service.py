"""Verticals: the business categories blueprints and merchants belong to."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.audit import service as audit
from arada.kernel.errors import Conflict, NotFound, ValidationFailed
from arada.kernel.ids import uuid7
from arada.kernel.scope import Scope
from arada.verticals.tables import verticals

KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


@dataclass(frozen=True, slots=True)
class Vertical:
    id: UUID
    key: str
    name_en: str
    name_am: str | None
    status: str


_COLS = (
    verticals.c.id,
    verticals.c.key,
    verticals.c.name_en,
    verticals.c.name_am,
    verticals.c.status,
)


async def create(scope: Scope, *, key: str, name_en: str, name_am: str | None) -> Vertical:
    scope.require("verticals.manage")
    if not KEY.match(key):
        raise ValidationFailed(errors={"key": ["lowercase letters, digits and '_' (2-40)"]})
    vertical_id = uuid7()
    try:
        async with scope.conn.begin_nested():
            await scope.conn.execute(
                insert(verticals).values(
                    id=vertical_id,
                    key=key,
                    name_en=name_en,
                    name_am=name_am,
                    created_by=scope.actor_person_id,
                )
            )
    except IntegrityError as exc:
        raise Conflict("a vertical with this key already exists") from exc
    await audit.record_in(
        scope,
        action="vertical.created",
        resource_type="vertical",
        resource_id=vertical_id,
        after={"key": key, "name_en": name_en, "name_am": name_am},
    )
    return Vertical(vertical_id, key, name_en, name_am, "active")


async def list_visible(scope: Scope) -> list[Vertical]:
    """Platform readers see all verticals; vertical admins see their own."""
    query = select(*_COLS).order_by(verticals.c.key)
    if "blueprints.read" not in scope.grants.platform:
        visible = [
            vid for vid, perms in scope.grants.vertical.items() if "blueprints.read" in perms
        ]
        if not visible:
            scope.require("blueprints.read")  # raises Forbidden / MFA step-up
        query = query.where(verticals.c.id.in_(visible))
    return [Vertical(*row) for row in (await scope.conn.execute(query)).all()]


async def get_by_key(conn: AsyncConnection, key: str) -> Vertical:
    row = (await conn.execute(select(*_COLS).where(verticals.c.key == key))).first()
    if row is None:
        raise NotFound("vertical not found")
    return Vertical(*row)


async def get(conn: AsyncConnection, vertical_id: UUID) -> Vertical:
    row = (await conn.execute(select(*_COLS).where(verticals.c.id == vertical_id))).first()
    if row is None:
        raise NotFound("vertical not found")
    return Vertical(*row)
