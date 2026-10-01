"""Database access with explicit transaction boundaries and tenant context.

Two runtime pools exist (06_DATABASE_MODEL.md §2):

* ``app``: role ``arada_app`` (NOBYPASSRLS). All request handling uses it.
  Tenant context is set with ``set_config(..., is_local => true)`` inside each
  transaction, so a pooled connection can never carry a previous request's
  tenant. With no tenant context, RLS returns zero rows (fail closed).
* ``reader``: role ``arada_platform_reader`` (BYPASSRLS, read-only). Only
  platform-wide reads that have already been authorised use it.

The owner role is never used at runtime; only migrations hold it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from arada.kernel.config import Settings

_SET_CONTEXT = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true), "
    "set_config('app.person_id', :person_id, true)"
)


RESTRICT_VIOLATION = "23001"


def sqlstate(exc: DBAPIError) -> str | None:
    """The PostgreSQL SQLSTATE behind a driver error, if there is one."""
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(
        getattr(orig, "__cause__", None), "sqlstate", None
    )


async def set_context(
    conn: AsyncConnection, *, tenant_id: UUID | None, person_id: UUID | None
) -> None:
    """Set (or change) the RLS context for the current transaction only."""
    await conn.execute(
        _SET_CONTEXT,
        {
            "tenant_id": str(tenant_id) if tenant_id else "",
            "person_id": str(person_id) if person_id else "",
        },
    )


def _engine(
    url: str, *, pool_size: int, max_overflow: int, app_name: str, timeout_ms: int
) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "server_settings": {
                "application_name": app_name,
                "statement_timeout": str(timeout_ms),
                "idle_in_transaction_session_timeout": str(timeout_ms * 2),
            }
        },
    )


class Database:
    def __init__(self, settings: Settings, *, app_name: str = "arada-api") -> None:
        self.app: AsyncEngine = _engine(
            settings.database_url.get_secret_value(),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            app_name=app_name,
            timeout_ms=settings.db_statement_timeout_ms,
        )
        self.reader: AsyncEngine = _engine(
            settings.database_platform_reader_url.get_secret_value(),
            pool_size=2,
            max_overflow=2,
            app_name=f"{app_name}-reader",
            timeout_ms=settings.db_statement_timeout_ms,
        )

    @asynccontextmanager
    async def transaction(
        self, *, tenant_id: UUID | None = None, person_id: UUID | None = None
    ) -> AsyncIterator[AsyncConnection]:
        """One unit of work. Commits on success, rolls back on any exception."""
        async with self.app.begin() as conn:
            await set_context(conn, tenant_id=tenant_id, person_id=person_id)
            yield conn

    @asynccontextmanager
    async def platform_read(self) -> AsyncIterator[AsyncConnection]:
        """Read-only, RLS-bypassing connection for authorised platform reads."""
        async with self.reader.begin() as conn:
            yield conn

    async def ping(self) -> bool:
        async with self.app.connect() as conn:
            value: int = (await conn.execute(text("SELECT 1"))).scalar_one()
            return bool(value == 1)

    async def dispose(self) -> None:
        await self.app.dispose()
        await self.reader.dispose()
