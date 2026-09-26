"""Audit trail guarantees enforced by PostgreSQL itself (Gate 7, DB layer)."""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from arada.audit.service import sanitise
from arada.kernel.ids import uuid7
from tests.conftest import PgEnv

INSERT = """
INSERT INTO control.audit_events
  (id, actor_type, tenant_id, action, resource_type, source)
VALUES ($1, 'system', $2, 'test.event', 'test', 'system')
"""


async def _in_context(conn: asyncpg.Connection, tenant: uuid.UUID | None) -> None:
    await conn.execute(
        "SELECT set_config('app.tenant_id', $1, true)", str(tenant) if tenant else ""
    )


async def test_app_role_cannot_update_or_delete_audit(app_conn: asyncpg.Connection) -> None:
    async with app_conn.transaction():
        await app_conn.execute(INSERT, uuid7(), None)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("UPDATE control.audit_events SET reason = 'x'")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("DELETE FROM control.audit_events")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("TRUNCATE control.audit_events")


async def test_owner_and_superuser_cannot_tamper_with_audit(
    app_conn: asyncpg.Connection, owner_conn: asyncpg.Connection, pg_env: PgEnv, test_database: str
) -> None:
    await app_conn.execute(INSERT, uuid7(), None)

    # Forced RLS has no policy for the owner: it cannot even insert or see rows,
    # so UPDATE/DELETE touch nothing, and TRUNCATE is stopped by the trigger.
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await owner_conn.execute(INSERT, uuid7(), None)
    assert await owner_conn.execute("UPDATE control.audit_events SET reason = 'x'") == "UPDATE 0"
    assert await owner_conn.execute("DELETE FROM control.audit_events") == "DELETE 0"
    with pytest.raises(asyncpg.RestrictViolationError):
        await owner_conn.execute("TRUNCATE control.audit_events")

    # A superuser bypasses RLS entirely; the append-only triggers still hold.
    superuser = await asyncpg.connect(pg_env.superuser_dsn(test_database))
    try:
        for statement in (
            "UPDATE control.audit_events SET reason = 'tamper'",
            "DELETE FROM control.audit_events",
            "TRUNCATE control.audit_events",
        ):
            with pytest.raises(asyncpg.RestrictViolationError):
                await superuser.execute(statement)
    finally:
        await superuser.close()


async def test_tenant_context_limits_audit_reads_and_writes(
    app_conn: asyncpg.Connection, pg_env: PgEnv, test_database: str
) -> None:
    tenant_a, tenant_b = uuid7(), uuid7()
    marker = uuid7()

    # Written legitimately, each in its own tenant context.
    for tenant in (tenant_a, tenant_b):
        async with app_conn.transaction():
            await _in_context(app_conn, tenant)
            await app_conn.execute(INSERT, uuid7(), tenant)

    # In tenant A's context: writing B's event is rejected by RLS.
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app_conn.transaction():
            await _in_context(app_conn, tenant_a)
            await app_conn.execute(INSERT, marker, tenant_b)

    # ...and A sees only A (not B, not platform events).
    async with app_conn.transaction():
        await _in_context(app_conn, tenant_a)
        tenants = {
            r["tenant_id"]
            for r in await app_conn.fetch("SELECT tenant_id FROM control.audit_events")
        }
    assert tenants == {tenant_a}

    # With no tenant context the app role sees nothing (fail closed) and may
    # only write platform events.
    async with app_conn.transaction():
        await _in_context(app_conn, None)
        assert await app_conn.fetchval("SELECT count(*) FROM control.audit_events") == 0
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app_conn.transaction():
            await _in_context(app_conn, None)
            await app_conn.execute(INSERT, uuid7(), tenant_a)

    # The platform reader sees everything, and cannot write.
    reader = await asyncpg.connect(
        f"postgresql://arada_platform_reader:{pg_env.passwords.reader}"
        f"@{pg_env.host}:{pg_env.port}/{test_database}"
    )
    try:
        seen = {
            r["tenant_id"] for r in await reader.fetch("SELECT tenant_id FROM control.audit_events")
        }
        assert {tenant_a, tenant_b} <= seen
        with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
            await reader.execute(INSERT, uuid7(), None)
    finally:
        await reader.close()


async def test_action_format_is_enforced(app_conn: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await app_conn.execute(
            "INSERT INTO control.audit_events (id, actor_type, action, resource_type, source) "
            "VALUES ($1, 'system', 'DROP TABLE', 'x', 'system')",
            uuid7(),
        )


def test_sanitise_strips_secrets_and_normalises_types() -> None:
    raw = {
        "username": "alice",
        "password": "hunter2hunter2",
        "password_hash": "$argon2id$...",
        "nested": {"totp_secret": "JBSWY3DPEHPK3PXP", "ok": 1},
        "id": uuid.UUID("01890000-0000-7000-8000-000000000000"),
    }
    clean = sanitise(raw)
    assert clean["password"] == "[REDACTED]"
    assert clean["password_hash"] == "[REDACTED]"
    assert clean["nested"]["totp_secret"] == "[REDACTED]"
    assert clean["nested"]["ok"] == 1
    assert clean["id"] == "01890000-0000-7000-8000-000000000000"
