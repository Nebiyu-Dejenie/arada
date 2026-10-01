"""Customers: a person as seen by one tenant (ADR-024, 02_TENANCY.md §6).

A person who shops at two merchants has two customer rows, one per tenant,
and neither merchant can see the other's (FORCE RLS). Customers are created
only by a successful channel login; there is no API to create one directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.customers.tables import customers
from arada.identity.tables import persons
from arada.kernel.errors import Unauthenticated
from arada.kernel.ids import uuid7
from arada.kernel.scope import CustomerScope


@dataclass(frozen=True, slots=True)
class CustomerProfile:
    customer_id: UUID
    display_name: str
    first_seen_at: datetime


async def find_or_create(
    conn: AsyncConnection, *, tenant_id: UUID, person_id: UUID
) -> tuple[UUID, bool]:
    """The person's customer row in ``tenant_id`` (inside that tenant's context).

    Concurrent first logins converge on one row: the unique key settles it.
    """
    created: UUID | None = (
        await conn.execute(
            pg_insert(customers)
            .values(id=uuid7(), tenant_id=tenant_id, person_id=person_id)
            .on_conflict_do_nothing(index_elements=["tenant_id", "person_id"])
            .returning(customers.c.id)
        )
    ).scalar_one_or_none()
    if created is not None:
        return created, True
    existing: UUID = (
        await conn.execute(
            select(customers.c.id).where(
                and_(customers.c.tenant_id == tenant_id, customers.c.person_id == person_id)
            )
        )
    ).scalar_one()
    return existing, False


async def own_profile(scope: CustomerScope) -> CustomerProfile:
    """The calling customer's own record, and nothing else."""
    row = (
        await scope.conn.execute(
            select(customers.c.id, customers.c.first_seen_at, persons.c.display_name)
            .join(persons, persons.c.id == customers.c.person_id)
            .where(
                and_(
                    customers.c.tenant_id == scope.tenant.id,
                    customers.c.id == scope.principal.customer_id,
                    customers.c.person_id == scope.principal.person_id,
                )
            )
        )
    ).first()
    if row is None:
        raise Unauthenticated()
    return CustomerProfile(
        customer_id=row.id, display_name=row.display_name, first_seen_at=row.first_seen_at
    )
