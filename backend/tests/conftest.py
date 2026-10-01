"""Test harness.

Database tests run against a real PostgreSQL (no mocks for the database):
each session creates a fresh database, bootstraps the roles exactly as
production does, applies every migration from zero, and drops the database
afterwards. Connection details come from the environment or the repo-root
``.env`` written by ``scripts/init-env.sh``.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import httpx
import pytest
from alembic import command
from fastapi import FastAPI

from arada.cli import _alembic_config
from arada.kernel.config import Environment, Settings
from arada.kernel.db import Database
from arada.main import create_app
from arada.ops.db_bootstrap import RolePasswords, bootstrap_roles
from arada.rbac.bootstrap import bootstrap_super_admin
from tests.storefront import Storefront, open_storefront
from tests.support import DEFAULT_PASSWORD, Persona, enrol_totp, login, unique
from tests.telegram_kit import Signer
from tests.world import World, build_world

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    path = REPO_ROOT / ".env"
    if path.exists():
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


_DOTENV = _read_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or _DOTENV.get(name) or default


@dataclass(frozen=True)
class PgEnv:
    host: str
    port: str
    superuser_password: str
    passwords: RolePasswords
    kek_base64: str

    def superuser_dsn(self, database: str = "postgres") -> str:
        return f"postgresql://postgres:{self.superuser_password}@{self.host}:{self.port}/{database}"

    def url(self, role: str, password: str, database: str) -> str:
        return f"postgresql+asyncpg://{role}:{password}@{self.host}:{self.port}/{database}"


@pytest.fixture(scope="session")
def pg_env() -> PgEnv:
    required = {
        "ARADA_PG_SUPERUSER_PASSWORD": _env("ARADA_PG_SUPERUSER_PASSWORD"),
        "ARADA_DB_OWNER_PASSWORD": _env("ARADA_DB_OWNER_PASSWORD"),
        "ARADA_DB_APP_PASSWORD": _env("ARADA_DB_APP_PASSWORD"),
        "ARADA_DB_READER_PASSWORD": _env("ARADA_DB_READER_PASSWORD"),
        "ARADA_KEK_BASE64": _env("ARADA_KEK_BASE64"),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        pytest.fail(
            "database tests need PostgreSQL: run ./scripts/init-env.sh && docker compose up -d "
            f"postgres (missing: {', '.join(missing)})",
            pytrace=False,
        )
    return PgEnv(
        host=_env("ARADA_PG_HOST", "127.0.0.1") or "127.0.0.1",
        port=_env("ARADA_PG_PORT", "55432") or "55432",
        superuser_password=required["ARADA_PG_SUPERUSER_PASSWORD"] or "",
        passwords=RolePasswords(
            owner=required["ARADA_DB_OWNER_PASSWORD"] or "",
            app=required["ARADA_DB_APP_PASSWORD"] or "",
            reader=required["ARADA_DB_READER_PASSWORD"] or "",
        ),
        kek_base64=required["ARADA_KEK_BASE64"] or "",
    )


async def create_migrated_database(pg: PgEnv, name: str) -> None:
    conn = await asyncpg.connect(pg.superuser_dsn())
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()
    await bootstrap_roles(pg.superuser_dsn(), name, pg.passwords)
    owner_url = pg.url("arada_owner", pg.passwords.owner, name)
    # env.py calls asyncio.run(); run it on a worker thread with its own loop.
    await asyncio.to_thread(command.upgrade, _alembic_config(owner_url), "head")


async def drop_database(pg: PgEnv, name: str) -> None:
    conn = await asyncpg.connect(pg.superuser_dsn())
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", name
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
async def test_database(pg_env: PgEnv) -> AsyncIterator[str]:
    name = f"arada_test_{secrets.token_hex(4)}"
    await create_migrated_database(pg_env, name)
    yield name
    if not os.environ.get("ARADA_TEST_KEEP_DB"):
        await drop_database(pg_env, name)


@pytest.fixture(scope="session")
def telegram_signer() -> Signer:
    """A throwaway key standing in for Telegram's test-environment key."""
    return Signer()


@pytest.fixture(scope="session")
def settings(pg_env: PgEnv, test_database: str, telegram_signer: Signer) -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url=pg_env.url("arada_app", pg_env.passwords.app, test_database),
        database_platform_reader_url=pg_env.url(
            "arada_platform_reader", pg_env.passwords.reader, test_database
        ),
        database_owner_url=pg_env.url("arada_owner", pg_env.passwords.owner, test_database),
        kek_base64=pg_env.kek_base64,
        log_format="console",
        log_level="WARNING",
        require_mfa_for_privileged_scopes=True,
        telegram_environment="test",
        telegram_public_key_hex=telegram_signer.public_hex,
    )


@pytest.fixture(scope="session")
async def db(settings: Settings) -> AsyncIterator[Database]:
    database = Database(settings, app_name="arada-tests")
    yield database
    await database.dispose()


@pytest.fixture(scope="session")
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture(scope="session")
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def owner_conn(pg_env: PgEnv, test_database: str) -> AsyncIterator[asyncpg.Connection]:
    """Direct connection as the schema owner, for DB-level guarantee tests."""
    conn = await asyncpg.connect(
        f"postgresql://arada_owner:{pg_env.passwords.owner}@{pg_env.host}:{pg_env.port}/{test_database}"
    )
    yield conn
    await conn.close()


@pytest.fixture
async def app_conn(pg_env: PgEnv, test_database: str) -> AsyncIterator[asyncpg.Connection]:
    """Direct connection as the runtime application role (RLS enforced)."""
    conn = await asyncpg.connect(
        f"postgresql://arada_app:{pg_env.passwords.app}@{pg_env.host}:{pg_env.port}/{test_database}"
    )
    yield conn
    await conn.close()


@pytest.fixture(scope="session")
async def super_admin(settings: Settings, client: httpx.AsyncClient) -> Persona:
    """The platform owner, bootstrapped exactly as the CLI does, with TOTP."""
    username = unique("root")
    person_id = await bootstrap_super_admin(settings, username, "Platform Owner", DEFAULT_PASSWORD)
    persona = Persona(person_id=person_id, username=username, password=DEFAULT_PASSWORD)
    await login(client, persona)
    await enrol_totp(client, persona)
    return persona


@pytest.fixture(scope="session")
async def world(client: httpx.AsyncClient, super_admin: Persona) -> World:
    """Two merchants (A, B) with Owner, Admin and Staff each, built via the API."""
    return await build_world(client, super_admin)


@pytest.fixture(scope="session")
async def storefronts(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> tuple[Storefront, Storefront]:
    """A host and an own bot for tenants A and B. Bound once: re-binding a bot
    revokes customer sessions, so tests that replace bots use fresh tenants."""
    a = await open_storefront(client, super_admin, world.a.id, world.a.slug)
    b = await open_storefront(client, super_admin, world.b.id, world.b.slug)
    return a, b
