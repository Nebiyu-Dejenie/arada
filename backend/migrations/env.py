"""Alembic environment: migrations run as ``arada_owner`` only."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from arada.schema import metadata

config = context.config
target_metadata = metadata


def _owner_url() -> str:
    url = config.attributes.get("owner_url") or os.environ.get("ARADA_DATABASE_OWNER_URL")
    if not url:
        raise RuntimeError("ARADA_DATABASE_OWNER_URL is not set; migrations run as arada_owner")
    return str(url)


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        transaction_per_migration=True,
        compare_type=True,
    )
    with context.begin_transaction():
        # Fail fast instead of queueing behind long-held locks in production.
        connection.exec_driver_sql("SET lock_timeout = '5s'")
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_owner_url())
    try:
        async with engine.connect() as conn:
            await conn.run_sync(_run)
            await conn.commit()
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("offline SQL generation is not supported; run against a database")

existing = config.attributes.get("connection")
if existing is not None:
    _run(existing)
else:
    asyncio.run(_run_async())
