"""Tenant context never survives a pooled connection (ADR-002, kernel/db.py).

``Database.transaction`` sets the tenant context with
``set_config(..., is_local => true)`` at the start of every transaction, so
the value dies with the transaction. These tests do not take that on trust:
they run two tenants' transactions interleaved on a deliberately tiny pool,
so every connection is reused for both tenants, and fail some of them part
way through (application exceptions, database errors, RLS violations).
"""

from __future__ import annotations

import asyncio
import random
import uuid
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.kernel.config import Settings
from arada.kernel.db import Database, set_context
from arada.kernel.ids import uuid7
from tests.world import TenantWorld, World

POOL = 2
TABLES = (
    "audit_events",
    "domains",
    "feature_flag_overrides",
    "merchant_profiles",
    "tenant_blueprint_assignments",
    "tenant_invitation_roles",
    "tenant_invitations",
    "tenant_membership_roles",
    "tenant_memberships",
)
VISIBLE_TENANTS = " UNION ".join(
    f"SELECT tenant_id FROM control.{t} WHERE tenant_id IS NOT NULL" for t in TABLES
)
ROLLED_BACK = "must-roll-back"


class Abort(Exception):
    """An application error in the middle of a transaction."""


@dataclass(frozen=True)
class Seen:
    pid: int
    tenant: uuid.UUID | None
    context_at_start: str
    context_at_end: str
    visible: frozenset[uuid.UUID]
    own_profile: bool


@pytest.fixture
async def tiny_pool(settings: Settings) -> AsyncIterator[Database]:
    db = Database(
        settings.model_copy(update={"db_pool_size": POOL, "db_max_overflow": 0}),
        app_name="arada-tests-pool",
    )
    yield db
    await db.dispose()


async def _context(conn: AsyncConnection) -> str:
    value: str | None = (
        await conn.execute(text("SELECT current_setting('app.tenant_id', true)"))
    ).scalar_one()
    return str(value or "")


async def _transaction(
    db: Database, n: int, tenant: uuid.UUID, other: uuid.UUID, seen: list[Seen]
) -> str:
    """One unit of work for ``tenant``; every fifth one fails in a different way."""
    failure = ("ok", "ok", "app-error", "db-error", "rls-violation")[n % 5]
    async with db.transaction(tenant_id=tenant, person_id=None) as conn:
        pid: int = (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        start = await _context(conn)
        await asyncio.sleep(random.random() / 500)  # let other transactions interleave
        visible: frozenset[uuid.UUID] = frozenset(
            (await conn.execute(text(VISIBLE_TENANTS))).scalars()
        )
        own: int = (
            await conn.execute(
                text("SELECT count(*) FROM control.merchant_profiles WHERE tenant_id = :t"),
                {"t": tenant},
            )
        ).scalar_one()
        await asyncio.sleep(random.random() / 500)
        seen.append(Seen(pid, tenant, start, await _context(conn), visible, own == 1))
        if failure == "ok":
            return failure
        # Write first, then fail: the write must never become visible.
        await conn.execute(
            text("UPDATE control.merchant_profiles SET tagline = :t WHERE tenant_id = :id"),
            {"t": f"{ROLLED_BACK}-{n}", "id": tenant},
        )
        if failure == "app-error":
            raise Abort(n)
        if failure == "db-error":
            await conn.execute(text("SELECT 1 / 0"))
        await conn.execute(  # rls-violation: a row for the other tenant
            text(
                "INSERT INTO control.tenant_memberships (id, tenant_id, person_id) "
                "SELECT :id, :other, person_id FROM control.tenant_memberships LIMIT 1"
            ),
            {"id": uuid7(), "other": other},
        )
    raise AssertionError("unreachable: every failure path raises")


async def _no_tenant(db: Database, seen: list[Seen]) -> None:
    """A platform-style transaction (no tenant) squeezed in between tenant ones."""
    async with db.transaction(tenant_id=None, person_id=None) as conn:
        pid: int = (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        start = await _context(conn)
        await asyncio.sleep(random.random() / 500)
        visible: frozenset[uuid.UUID] = frozenset(
            (await conn.execute(text(VISIBLE_TENANTS))).scalars()
        )
        seen.append(Seen(pid, None, start, await _context(conn), visible, own_profile=False))


async def test_interleaved_tenants_on_reused_connections_never_cross(
    tiny_pool: Database, world: World
) -> None:
    a, b = uuid.UUID(world.a.id), uuid.UUID(world.b.id)
    seen: list[Seen] = []
    jobs: list[Coroutine[Any, Any, object]] = [
        _transaction(tiny_pool, n, *((a, b) if n % 2 == 0 else (b, a)), seen) for n in range(400)
    ]
    for n in range(100):
        jobs.insert(n * 5, _no_tenant(tiny_pool, seen))
    # Three times as many transactions in flight as connections: every
    # connection is contended and switches tenants constantly, while no
    # waiter comes near the pool's checkout timeout on a slow machine.
    in_flight = asyncio.Semaphore(3 * POOL)

    async def bounded(job: Coroutine[Any, Any, object]) -> object:
        async with in_flight:
            return await job

    outcomes = await asyncio.gather(*(bounded(j) for j in jobs), return_exceptions=True)

    failures = [type(o).__name__ for o in outcomes if isinstance(o, BaseException)]
    unexpected = set(failures) - {"Abort", "DBAPIError", "ProgrammingError"}
    assert not unexpected, f"unexpected failures: {sorted(unexpected)}"
    assert failures.count("Abort") == 80
    assert sum(isinstance(o, DBAPIError) for o in outcomes) == 160  # 1/0 and RLS violations
    assert not [o for o in outcomes if isinstance(o, AssertionError)]
    assert len(seen) == 500

    for s in seen:
        if s.tenant is None:  # no context at all: nothing stale, no tenant rows
            assert s.context_at_start == s.context_at_end == "", s
            assert s.visible == frozenset(), s
            continue
        assert s.context_at_start == s.context_at_end == str(s.tenant), s
        assert s.visible == {s.tenant}, f"{s.tenant} saw {s.visible}"
        assert s.own_profile, s
    # The pool really was reused, and for both tenants on the same connection.
    pids = {s.pid for s in seen}
    assert len(pids) <= POOL
    assert any({s.tenant for s in seen if s.pid == pid} >= {a, b, None} for pid in pids)

    # Nothing written by a failed transaction survived.
    async with tiny_pool.transaction(tenant_id=a) as conn:
        tagline_a: str = (
            await conn.execute(text("SELECT coalesce(tagline, '') FROM control.merchant_profiles"))
        ).scalar_one()
    async with tiny_pool.transaction(tenant_id=b) as conn:
        tagline_b: str = (
            await conn.execute(text("SELECT coalesce(tagline, '') FROM control.merchant_profiles"))
        ).scalar_one()
    assert ROLLED_BACK not in tagline_a
    assert ROLLED_BACK not in tagline_b


async def test_a_checked_out_connection_carries_no_tenant_context(
    tiny_pool: Database, world: World
) -> None:
    a, b = uuid.UUID(world.a.id), uuid.UUID(world.b.id)
    used: dict[int, set[uuid.UUID]] = {}

    async def hold(tenant: uuid.UUID, fail: bool) -> None:
        async with tiny_pool.transaction(tenant_id=tenant) as conn:
            pid: int = (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            used.setdefault(pid, set()).add(tenant)
            await asyncio.sleep(0.05)  # both connections are checked out together
            if fail:
                raise Abort(tenant)

    for fail_a, fail_b in ((True, False), (False, True), (True, True), (False, False)):
        await asyncio.gather(hold(a, fail_a), hold(b, fail_b), return_exceptions=True)
        await asyncio.gather(hold(b, fail_a), hold(a, fail_b), return_exceptions=True)
    assert len(used) == POOL
    assert all(tenants == {a, b} for tenants in used.values()), used

    # Hold every pooled connection at once, straight from the pool, without
    # going through Database.transaction (so nothing sets a context).
    raw = [await tiny_pool.app.connect() for _ in range(POOL)]
    try:
        for conn in raw:
            assert (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one() in used
            assert await _context(conn) == ""
            assert (await conn.execute(text(VISIBLE_TENANTS))).all() == []
            await conn.rollback()
    finally:
        for conn in raw:
            await conn.close()


async def test_tenant_context_is_transaction_local(tiny_pool: Database, world: World) -> None:
    a, b = uuid.UUID(world.a.id), uuid.UUID(world.b.id)
    async with tiny_pool.app.connect() as conn:
        await conn.begin()
        await set_context(conn, tenant_id=a, person_id=None)
        assert await _context(conn) == str(a)
        await conn.commit()
        assert await _context(conn) == "", "a committed transaction's context leaked"
        await conn.rollback()

        await conn.begin()
        await set_context(conn, tenant_id=b, person_id=None)
        await conn.rollback()
        assert await _context(conn) == "", "a rolled-back transaction's context leaked"
        await conn.rollback()

        # A context switch inside a savepoint that rolls back is undone too.
        await conn.begin()
        await set_context(conn, tenant_id=a, person_id=None)
        nested = await conn.begin_nested()
        await set_context(conn, tenant_id=b, person_id=None)
        await nested.rollback()
        assert await _context(conn) == str(a)
        await conn.rollback()


async def test_concurrent_api_requests_from_two_tenants_never_cross(
    client: httpx.AsyncClient, world: World
) -> None:
    """Through the whole HTTP stack, on the application's own pool (5 + 5)."""

    async def as_tenant(tenant: TenantWorld, n: int) -> tuple[TenantWorld, str, httpx.Response]:
        path = (
            "",
            "/staff",
            "/audit-events",
            "/blueprint-history",
            "/features",
            "/profile",  # stale If-Match: 412 after the transaction opened (rolled back)
        )[n % 6]
        url = f"/v1/t/{tenant.slug}{path}"
        if path == "/profile":
            response = await client.patch(
                url,
                headers={**tenant.admin.headers, "If-Match": '"0"'},
                json={"tagline": ROLLED_BACK},
            )
        else:
            response = await client.get(url, headers=tenant.owner.headers)
        return tenant, path, response

    # Twice the application pool (5 + 5) in flight: connections are shared
    # and reused across tenants without any request queueing for the pool's
    # full 30 s checkout timeout on a slow machine.
    in_flight = asyncio.Semaphore(20)

    async def bounded(tenant: TenantWorld, n: int) -> tuple[TenantWorld, str, httpx.Response]:
        async with in_flight:
            return await as_tenant(tenant, n)

    results = await asyncio.gather(
        *(bounded(world.a if n % 2 == 0 else world.b, n) for n in range(120))
    )
    members = {
        world.a.slug: {world.a.owner.username, world.a.admin.username, world.a.staff.username},
        world.b.slug: {world.b.owner.username, world.b.admin.username, world.b.staff.username},
    }
    for tenant, path, response in results:
        other = world.b if tenant is world.a else world.a
        if path == "/profile":
            assert response.status_code == 412, response.text
            continue
        assert response.status_code == 200, (path, response.text)
        assert other.id not in response.text
        assert other.slug not in response.text
        body = response.json()
        if path == "":
            assert body["id"] == tenant.id
        elif path == "/staff":
            assert members[tenant.slug] <= {m["username"] for m in body}
            assert not members[other.slug] & {m["username"] for m in body}
        elif path == "/audit-events":
            assert {e["tenant_id"] for e in body} == {tenant.id}
        elif path == "/blueprint-history":
            assert {h["tenant_id"] for h in body} == {tenant.id}
