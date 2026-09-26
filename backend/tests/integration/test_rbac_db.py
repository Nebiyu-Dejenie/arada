"""RBAC integrity enforced by the database, and code/DB catalogue parity."""

from __future__ import annotations

import asyncpg
import pytest

from arada.kernel.ids import uuid7
from arada.rbac.catalogue import PERMISSIONS, ROLES


async def test_database_catalogue_matches_code(owner_conn: asyncpg.Connection) -> None:
    db_perms = {
        r["key"]: tuple(r["scopes"])
        for r in await owner_conn.fetch("SELECT key, scopes FROM control.permissions")
    }
    assert db_perms == PERMISSIONS

    db_roles = {
        r["key"]: r["scope_type"]
        for r in await owner_conn.fetch("SELECT key, scope_type FROM control.roles")
    }
    assert db_roles == {k: r.scope for k, r in ROLES.items()}

    db_grants: dict[str, set[str]] = {}
    for r in await owner_conn.fetch(
        "SELECT role_key, permission_key FROM control.role_permissions"
    ):
        db_grants.setdefault(r["role_key"], set()).add(r["permission_key"])
    assert db_grants == {k: set(r.permissions) for k, r in ROLES.items()}


async def test_role_cannot_hold_permission_outside_its_scope(
    owner_conn: asyncpg.Connection,
) -> None:
    # products.publish is tenant-only; a platform role must not hold it.
    with pytest.raises(asyncpg.CheckViolationError):
        await owner_conn.execute(
            "INSERT INTO control.role_permissions VALUES ('SUPER_ADMIN', 'products.publish')"
        )


async def test_assignment_tables_accept_only_roles_of_their_scope(
    owner_conn: asyncpg.Connection,
) -> None:
    person = uuid7()
    await owner_conn.execute(
        "INSERT INTO control.persons (id, display_name) VALUES ($1, 'scope test')", person
    )
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await owner_conn.execute(
            "INSERT INTO control.platform_role_assignments (person_id, role_key) "
            "VALUES ($1, 'TENANT_OWNER')",
            person,
        )
    with pytest.raises(asyncpg.CheckViolationError):
        await owner_conn.execute(
            "INSERT INTO control.platform_role_assignments (person_id, role_key, scope_type) "
            "VALUES ($1, 'TENANT_OWNER', 'tenant')",
            person,
        )


async def test_runtime_role_cannot_rewrite_the_catalogue(app_conn: asyncpg.Connection) -> None:
    for statement in (
        "INSERT INTO control.role_permissions VALUES ('TENANT_STAFF', 'staff.manage')",
        "UPDATE control.roles SET scope_type = 'platform' WHERE key = 'TENANT_OWNER'",
        "DELETE FROM control.role_permissions",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.execute(statement)
