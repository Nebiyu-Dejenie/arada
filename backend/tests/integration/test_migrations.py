"""Gate 2: migrations build a valid schema from zero, reversibly, without drift."""

from __future__ import annotations

import asyncio
import secrets

import asyncpg
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from arada.cli import _alembic_config
from arada.schema import metadata
from tests.conftest import PgEnv, create_migrated_database, drop_database


async def test_schema_builds_from_zero_and_round_trips(pg_env: PgEnv) -> None:
    """upgrade head -> downgrade base -> upgrade head on a brand-new database."""
    name = f"arada_mig_{secrets.token_hex(4)}"
    await create_migrated_database(pg_env, name)
    try:
        cfg = _alembic_config(pg_env.url("arada_owner", pg_env.passwords.owner, name))
        await asyncio.to_thread(command.downgrade, cfg, "base")
        conn = await asyncpg.connect(pg_env.superuser_dsn(name))
        try:
            leftover = await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'control'"
            )
            assert leftover == []
        finally:
            await conn.close()
        await asyncio.to_thread(command.upgrade, cfg, "head")
    finally:
        await drop_database(pg_env, name)


async def test_code_table_declarations_match_migrated_schema(
    pg_env: PgEnv, test_database: str
) -> None:
    """The SQLAlchemy declarations used for queries must match the real schema."""
    engine = create_async_engine(pg_env.url("arada_owner", pg_env.passwords.owner, test_database))

    def _diff(sync_conn: Connection) -> list[object]:
        ctx = MigrationContext.configure(
            sync_conn, opts={"compare_type": True, "include_schemas": True}
        )
        relevant = []
        for change in compare_metadata(ctx, metadata):
            items = change if isinstance(change, list) else [change]
            for item in items:
                kind = item[0]
                # Column-level drift is what breaks queries; indexes, constraints
                # and RLS are verified behaviourally by the integration tests.
                if kind in {
                    "add_table",
                    "remove_table",
                    "add_column",
                    "remove_column",
                    "modify_type",
                    "modify_nullable",
                }:
                    if kind == "remove_table" and getattr(item[1], "name", "") == "alembic_version":
                        continue
                    relevant.append(item)
        return relevant

    try:
        async with engine.connect() as conn:
            drift = await conn.run_sync(_diff)
    finally:
        await engine.dispose()
    assert drift == [], f"schema drift between code and migrations: {drift}"


async def test_runtime_role_cannot_run_ddl(app_conn: asyncpg.Connection) -> None:
    import pytest

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("CREATE TABLE control.evil (id int)")
