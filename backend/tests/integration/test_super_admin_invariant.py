"""The platform always keeps at least one SUPER_ADMIN (ADR-033, migration 0008).

These tests need to control how many SUPER_ADMINs exist in the whole
database, so they run on their own freshly migrated database instead of the
shared session one (where other tests grant SUPER_ADMIN freely).

Every revocation here goes through the real service path
(``platform_scope`` -> ``rbac.revoke_role``) or, for the database backstop,
through raw connections as the runtime role ``arada_app``.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg
import pytest

from arada.access.scopes import platform_scope
from arada.audit import service as audit
from arada.kernel.config import Environment, Settings
from arada.kernel.context import Principal, RequestMeta
from arada.kernel.db import Database
from arada.kernel.errors import Conflict, Forbidden
from arada.kernel.ids import uuid7
from arada.rbac import service as rbac
from tests.conftest import PgEnv, create_migrated_database, drop_database

META = RequestMeta(request_id="super-admin-invariant", trace_id="0" * 31 + "2", source="system")


@dataclass
class Isolated:
    name: str
    pg: PgEnv
    settings: Settings
    db: Database

    async def superuser(self) -> asyncpg.Connection:
        return await asyncpg.connect(self.pg.superuser_dsn(self.name))

    async def app_role(self) -> asyncpg.Connection:
        return await asyncpg.connect(
            f"postgresql://arada_app:{self.pg.passwords.app}"
            f"@{self.pg.host}:{self.pg.port}/{self.name}"
        )


@pytest.fixture(scope="module")
async def iso(pg_env: PgEnv) -> AsyncIterator[Isolated]:
    name = f"arada_sa_{secrets.token_hex(4)}"
    await create_migrated_database(pg_env, name)
    settings = Settings(
        environment=Environment.TEST,
        database_url=pg_env.url("arada_app", pg_env.passwords.app, name),
        database_platform_reader_url=pg_env.url(
            "arada_platform_reader", pg_env.passwords.reader, name
        ),
        kek_base64=pg_env.kek_base64,
        log_level="WARNING",
        require_mfa_for_privileged_scopes=True,
    )
    db = Database(settings, app_name="arada-tests-sa")
    try:
        yield Isolated(name, pg_env, settings, db)
    finally:
        await db.dispose()
        await drop_database(pg_env, name)


async def exactly(iso: Isolated, n: int) -> list[UUID]:
    """Make exactly ``n`` SUPER_ADMINs exist (new people); return them."""
    people = [uuid7() for _ in range(n)]
    su = await iso.superuser()
    try:
        async with su.transaction():
            for person in people:
                await su.execute(
                    "INSERT INTO control.persons (id, display_name) VALUES ($1, 'sa test')", person
                )
                await su.execute(
                    "INSERT INTO control.platform_role_assignments (person_id, role_key) "
                    "VALUES ($1, 'SUPER_ADMIN')",
                    person,
                )
            # Allowed by the guard: the new ones remain.
            await su.execute(
                "DELETE FROM control.platform_role_assignments "
                "WHERE role_key = 'SUPER_ADMIN' AND NOT person_id = ANY($1::uuid[])",
                people,
            )
    finally:
        await su.close()
    return people


async def super_admins(iso: Isolated) -> set[UUID]:
    su = await iso.superuser()
    try:
        rows = await su.fetch(
            "SELECT person_id FROM control.platform_role_assignments WHERE role_key = 'SUPER_ADMIN'"
        )
    finally:
        await su.close()
    return {r["person_id"] for r in rows}


async def revocation_events(iso: Isolated, target: UUID) -> int:
    su = await iso.superuser()
    try:
        count: int = await su.fetchval(
            "SELECT count(*) FROM control.audit_events "
            "WHERE action = 'rbac.role_revoked' AND resource_id = $1",
            str(target),
        )
    finally:
        await su.close()
    return count


def mfa_session(person: UUID) -> Principal:
    return Principal(person_id=person, session_id=uuid7(), mfa_verified_at=datetime.now(UTC))


async def revoke(iso: Isolated, actor: UUID, target: UUID) -> None:
    async with platform_scope(iso.db, iso.settings, META, mfa_session(actor)) as scope:
        await rbac.revoke_role(scope, person_id=target, role="SUPER_ADMIN")


async def blocked_on_advisory_lock(iso: Isolated) -> int:
    """Wait (up to 5 s) until a backend of this database waits on an advisory lock."""
    su = await iso.superuser()
    waiting = 0
    try:
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(5):
                while not waiting:
                    waiting = await su.fetchval(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = $1 "
                        "AND wait_event_type = 'Lock' AND wait_event = 'advisory'",
                        iso.name,
                    )
                    await asyncio.sleep(0.02)
    finally:
        await su.close()
    return waiting


# ------------------------------------------------------------------ service path
async def test_a_super_admin_can_be_revoked_when_another_remains(iso: Isolated) -> None:
    actor, target = await exactly(iso, 2)
    await revoke(iso, actor, target)
    assert await super_admins(iso) == {actor}
    assert await revocation_events(iso, target) == 1


async def test_the_last_super_admin_cannot_be_revoked(iso: Isolated) -> None:
    (only,) = await exactly(iso, 1)
    with pytest.raises(Conflict, match="last SUPER_ADMIN"):
        await revoke(iso, only, only)  # not even by themselves
    assert await super_admins(iso) == {only}
    assert await revocation_events(iso, only) == 0


async def test_revocation_and_its_audit_event_commit_atomically(
    iso: Isolated, monkeypatch: pytest.MonkeyPatch
) -> None:
    actor, target = await exactly(iso, 2)

    async def audit_fails(*_: Any, **__: Any) -> None:
        raise RuntimeError("audit store unavailable")

    # The DELETE succeeds, then the audit write fails: nothing may be committed.
    monkeypatch.setattr(audit, "record_in", audit_fails)
    with pytest.raises(RuntimeError, match="audit store unavailable"):
        await revoke(iso, actor, target)
    monkeypatch.undo()
    assert await super_admins(iso) == {actor, target}
    assert await revocation_events(iso, target) == 0

    await revoke(iso, actor, target)
    assert await super_admins(iso) == {actor}
    assert await revocation_events(iso, target) == 1


async def test_overlapping_revocations_cannot_remove_the_last_super_admin(
    iso: Isolated,
) -> None:
    """Deterministic interleaving: X revokes Y and holds its transaction open;
    Y (still a SUPER_ADMIN in its own snapshot) revokes X meanwhile."""
    x, y = await exactly(iso, 2)
    first_deleted, release_first = asyncio.Event(), asyncio.Event()

    async def first() -> None:
        async with platform_scope(iso.db, iso.settings, META, mfa_session(x)) as scope:
            await rbac.revoke_role(scope, person_id=y, role="SUPER_ADMIN")
            first_deleted.set()
            await release_first.wait()  # keep the transaction and its lock open

    one = asyncio.create_task(first())
    deleted = asyncio.create_task(first_deleted.wait())
    await asyncio.wait({one, deleted}, return_when=asyncio.FIRST_COMPLETED)
    if one.done():  # the first revocation failed: surface its error, never hang
        deleted.cancel()
        one.result()
    two = asyncio.create_task(revoke(iso, y, x))
    try:
        assert await blocked_on_advisory_lock(iso) == 1, "the second revocation was not serialised"
        assert not two.done()
    finally:
        release_first.set()
    await one
    with pytest.raises(Conflict, match="last SUPER_ADMIN"):
        await two
    assert await super_admins(iso) == {x}
    assert await revocation_events(iso, y) == 1
    assert await revocation_events(iso, x) == 0


async def test_racing_revocations_always_leave_one_super_admin(iso: Isolated) -> None:
    """Free-running races: every pair of mutual revocations, many times."""
    for _ in range(15):
        x, y = await exactly(iso, 2)
        results = await asyncio.gather(revoke(iso, x, y), revoke(iso, y, x), return_exceptions=True)
        # One wins. The other is refused by the guard, or (if it started after
        # the winner committed) because its actor is no longer a SUPER_ADMIN.
        assert [r for r in results if r is None] == [None], results
        assert all(isinstance(r, Conflict | Forbidden) for r in results if r is not None)
        assert len(await super_admins(iso)) == 1


# ------------------------------------------------------- database backstop
async def test_the_database_refuses_to_remove_the_last_super_admin(iso: Isolated) -> None:
    await exactly(iso, 2)
    conn = await iso.app_role()
    try:
        with pytest.raises(asyncpg.RestrictViolationError, match="at least one SUPER_ADMIN"):
            await conn.execute(
                "DELETE FROM control.platform_role_assignments WHERE role_key = 'SUPER_ADMIN'"
            )
    finally:
        await conn.close()
    assert len(await super_admins(iso)) == 2


async def test_overlapping_raw_deletes_are_serialised_by_the_database(iso: Isolated) -> None:
    """No service code at all: two runtime-role sessions delete different rows."""
    x, y = await exactly(iso, 2)
    c1, c2 = await iso.app_role(), await iso.app_role()
    try:
        t1 = c1.transaction()
        await t1.start()
        await c1.execute("DELETE FROM control.platform_role_assignments WHERE person_id = $1", x)

        async def second() -> None:
            async with c2.transaction():
                await c2.execute(
                    "DELETE FROM control.platform_role_assignments WHERE person_id = $1", y
                )

        two = asyncio.create_task(second())
        try:
            assert await blocked_on_advisory_lock(iso) == 1
        finally:
            await t1.commit()
        with pytest.raises(asyncpg.RestrictViolationError):
            await two
    finally:
        await c1.close()
        await c2.close()
    assert await super_admins(iso) == {y}


async def test_repeatable_read_cannot_remove_a_super_admin(iso: Isolated) -> None:
    """A REPEATABLE READ snapshot predates the lock, so the check would be stale."""
    x, _ = await exactly(iso, 2)
    conn = await iso.app_role()
    try:
        with pytest.raises(asyncpg.RestrictViolationError, match="READ COMMITTED"):
            async with conn.transaction(isolation="repeatable_read"):
                await conn.execute(
                    "DELETE FROM control.platform_role_assignments WHERE person_id = $1", x
                )
    finally:
        await conn.close()
    assert len(await super_admins(iso)) == 2


async def test_other_platform_roles_are_not_constrained(iso: Isolated) -> None:
    (admin,) = await exactly(iso, 1)
    su = await iso.superuser()
    try:
        await su.execute(
            "INSERT INTO control.platform_role_assignments (person_id, role_key) "
            "VALUES ($1, 'PLATFORM_ADMIN')",
            admin,
        )
    finally:
        await su.close()
    conn = await iso.app_role()
    try:
        deleted = await conn.execute(
            "DELETE FROM control.platform_role_assignments WHERE role_key = 'PLATFORM_ADMIN'"
        )
        assert deleted == "DELETE 1"
    finally:
        await conn.close()
