"""Idempotent creation of the database roles (06_DATABASE_MODEL.md §2).

Run once per cluster/database with a superuser DSN, before migrations. It is
the only code that ever uses superuser credentials. Every statement is a
constant or is built server-side with ``format(%I, %L)``, so no value from the
environment is ever spliced into SQL text by Python.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg

# role -> (create statement, alter statement). Attributes are deliberately
# explicit so a drifted role is corrected on every run.
_ROLE_DDL: dict[str, tuple[str, str]] = {
    "arada_owner": (
        "CREATE ROLE arada_owner WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS",
        "ALTER ROLE arada_owner WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS",
    ),
    "arada_app": (
        "CREATE ROLE arada_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS",
        "ALTER ROLE arada_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS",
    ),
    "arada_platform_reader": (
        "CREATE ROLE arada_platform_reader "
        "WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS",
        "ALTER ROLE arada_platform_reader WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS",
    ),
    # Owns the narrow SECURITY DEFINER resolver functions; cannot log in.
    "arada_resolver": (
        "CREATE ROLE arada_resolver WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS",
        "ALTER ROLE arada_resolver WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS",
    ),
}

_LOGIN_ROLES = ("arada_owner", "arada_app", "arada_platform_reader")


@dataclass(frozen=True, slots=True)
class RolePasswords:
    owner: str
    app: str
    reader: str

    def for_role(self, role: str) -> str:
        return {
            "arada_owner": self.owner,
            "arada_app": self.app,
            "arada_platform_reader": self.reader,
        }[role]


async def _exec_formatted(conn: asyncpg.Connection, template: str, *args: str) -> None:
    """Build a utility statement server-side with format() and execute it."""
    statement = await conn.fetchval(template, *args)
    await conn.execute(statement)


async def bootstrap_roles(superuser_dsn: str, database: str, passwords: RolePasswords) -> None:
    for value in (passwords.owner, passwords.app, passwords.reader):
        if len(value) < 16:
            raise ValueError("database role passwords must be at least 16 characters")

    conn = await asyncpg.connect(superuser_dsn)
    try:
        for role, (create_sql, alter_sql) in _ROLE_DDL.items():
            exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
            await conn.execute(alter_sql if exists else create_sql)
        for role in _LOGIN_ROLES:
            await _exec_formatted(
                conn,
                "SELECT format('ALTER ROLE %I WITH PASSWORD %L', $1::text, $2::text)",
                role,
                passwords.for_role(role),
            )
        await conn.execute(
            "ALTER ROLE arada_platform_reader SET default_transaction_read_only = on"
        )
        # Migrations (run as arada_owner) must be able to hand function
        # ownership to arada_resolver.
        await conn.execute("GRANT arada_resolver TO arada_owner")

        await _exec_formatted(
            conn, "SELECT format('ALTER DATABASE %I OWNER TO arada_owner', $1::text)", database
        )
        await _exec_formatted(
            conn, "SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', $1::text)", database
        )
        await _exec_formatted(
            conn,
            "SELECT format('GRANT CONNECT ON DATABASE %I "
            "TO arada_app, arada_platform_reader', $1::text)",
            database,
        )
    finally:
        await conn.close()
