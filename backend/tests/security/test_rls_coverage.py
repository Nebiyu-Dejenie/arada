"""Row-level security at the SQL layer, table by table (ADR-002, ADR-034).

Everything here runs as the runtime role ``arada_app`` on a raw connection,
with no service code in between: these are the guarantees that hold even if
application code has a tenant bug. Test transactions are always rolled back.

The first test is the RLS policy lint: it reads the live catalogue, so a new
table with a ``tenant_id`` column fails CI until it is under forced RLS with
tenant-context policies. (Convention: every tenant-owned table names its
tenant column ``tenant_id``.)
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import asyncpg
import httpx
import pytest

from arada.kernel.ids import uuid7
from tests.support import Persona
from tests.world import World

TENANT_TABLES = (
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
# Tables where arada_app holds UPDATE / DELETE at all (others: denied by grant).
UPDATABLE = {
    "domains",
    "feature_flag_overrides",
    "merchant_profiles",
    "tenant_invitations",
    "tenant_memberships",
}
DELETABLE = {"feature_flag_overrides", "tenant_membership_roles"}


@asynccontextmanager
async def rolled_back(conn: asyncpg.Connection) -> AsyncIterator[None]:
    tx = conn.transaction()
    await tx.start()
    try:
        yield
    finally:
        await tx.rollback()


async def ctx(conn: asyncpg.Connection, tenant: str | uuid.UUID | None) -> None:
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant or ""))


@dataclass(frozen=True)
class Rows:
    a_invitation: uuid.UUID
    b_invitation: uuid.UUID
    a_host: str
    b_host: str


@pytest.fixture(scope="module")
async def rows(client: httpx.AsyncClient, super_admin: Persona, world: World) -> Rows:
    """Committed rows for both tenants in every tenant table, via the API."""
    hosts: dict[str, str] = {}
    invitations: dict[str, uuid.UUID] = {}
    for key, tenant in (("a", world.a), ("b", world.b)):
        hosts[key] = f"rls-{tenant.slug}.localhost"
        added = await client.post(
            f"/v1/platform/tenants/{tenant.id}/domains",
            headers=super_admin.headers,
            json={"hostname": hosts[key]},
        )
        assert added.status_code == 201, added.text
        override = await client.put(
            "/v1/platform/feature-flags/loyalty/overrides",
            headers=super_admin.headers,
            json={"scope_type": "tenant", "tenant": tenant.slug, "enabled": True},
        )
        assert override.status_code == 204, override.text
        invited = await client.post(
            f"/v1/t/{tenant.slug}/invitations",
            headers=tenant.admin.headers,
            json={"roles": ["TENANT_STAFF"]},
        )
        assert invited.status_code == 201, invited.text
        invitations[key] = uuid.UUID(invited.json()["id"])
    return Rows(invitations["a"], invitations["b"], hosts["a"], hosts["b"])


# ----------------------------------------------------------------- RLS lint
async def test_every_table_with_a_tenant_id_is_under_forced_rls(
    app_conn: asyncpg.Connection,
) -> None:
    tables = await app_conn.fetch(
        """
        SELECT c.relname, c.relrowsecurity AS rls, c.relforcerowsecurity AS forced
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
        WHERE n.nspname = 'control' AND c.relkind IN ('r', 'p')
        """
    )
    assert {t["relname"] for t in tables} == set(TENANT_TABLES), (
        "a table gained or lost a tenant_id column: update TENANT_TABLES and its RLS tests"
    )
    unprotected = [t["relname"] for t in tables if not (t["rls"] and t["forced"])]
    assert unprotected == [], f"tenant tables without FORCE ROW LEVEL SECURITY: {unprotected}"

    policies = await app_conn.fetch(
        """
        SELECT c.relname, p.polname, p.polcmd::text AS polcmd,
               ARRAY(SELECT r.rolname FROM pg_roles r WHERE r.oid = ANY (p.polroles)) AS roles,
               pg_get_expr(p.polqual, p.polrelid) AS using_expr,
               pg_get_expr(p.polwithcheck, p.polrelid) AS check_expr
        FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid
        WHERE c.relname = ANY ($1::text[])
        """,
        list(TENANT_TABLES),
    )
    app_policies: dict[str, list[Any]] = {}
    for p in policies:
        if p["roles"] == ["arada_app"]:
            app_policies.setdefault(p["relname"], []).append(p)
            # Every runtime-role policy is keyed on the transaction's tenant context.
            for expr in (p["using_expr"], p["check_expr"]):
                assert expr is None or "current_tenant_id()" in expr, (p["polname"], expr)
        else:
            # The only other policies: read-only, for the NOLOGIN resolver role.
            assert p["roles"] == ["arada_resolver"], p["polname"]
            assert p["polcmd"] == "r", f"{p['polname']} lets the resolver do more than SELECT"
    missing = sorted(set(TENANT_TABLES) - app_policies.keys())
    assert missing == [], f"tenant tables with no arada_app policy (they deny all): {missing}"
    for table, table_policies in app_policies.items():
        commands = {p["polcmd"] for p in table_policies}
        assert "*" in commands or "r" in commands, f"{table}: no SELECT policy"
        writes = [p for p in table_policies if p["polcmd"] in {"*", "a", "w"}]
        assert all(p["check_expr"] for p in writes), f"{table}: a write policy lacks WITH CHECK"


async def test_runtime_role_cannot_bypass_rls(app_conn: asyncpg.Connection) -> None:
    role = await app_conn.fetchrow(
        "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
        "FROM pg_roles WHERE rolname = 'arada_app'"
    )
    assert role is not None
    assert dict(role) == {
        "rolsuper": False,
        "rolbypassrls": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
    }
    owned = await app_conn.fetchval(
        "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'control' AND c.relowner = 'arada_app'::regrole"
    )
    assert owned == 0, "the runtime role owns a table (owners are exempt without FORCE)"
    memberships = await app_conn.fetch(
        "SELECT roleid::regrole::text AS role FROM pg_auth_members "
        "WHERE member = 'arada_app'::regrole"
    )
    assert memberships == [], "the runtime role can assume another role"
    resolver = await app_conn.fetchval(
        "SELECT rolcanlogin FROM pg_roles WHERE rolname = 'arada_resolver'"
    )
    assert resolver is False


# ------------------------------------------------------------- reads, per table
@pytest.mark.parametrize("table", TENANT_TABLES)
async def test_tenant_a_reads_only_its_own_rows(
    app_conn: asyncpg.Connection, world: World, rows: Rows, table: str
) -> None:
    async with rolled_back(app_conn):
        await ctx(app_conn, world.a.id)
        seen = {
            str(r["tenant_id"])
            for r in await app_conn.fetch(
                f"SELECT DISTINCT tenant_id FROM control.{table} WHERE tenant_id IS NOT NULL"
            )
        }
        assert seen == {world.a.id}
        targeted = await app_conn.fetchval(
            f"SELECT count(*) FROM control.{table} WHERE tenant_id = $1", uuid.UUID(world.b.id)
        )
        assert targeted == 0, "B's rows are invisible even when asked for by id"

        await ctx(app_conn, None)
        assert (
            await app_conn.fetchval(
                f"SELECT count(*) FROM control.{table} WHERE tenant_id IS NOT NULL"
            )
            == 0
        ), "no tenant context: no tenant rows (fail closed)"


# ------------------------------------------------------------ writes, per table
def _insert_into_b(world: World, rows: Rows) -> dict[str, tuple[str, tuple[Any, ...]]]:
    b = uuid.UUID(world.b.id)
    return {
        "audit_events": (
            "INSERT INTO control.audit_events (id, tenant_id, actor_type, action, "
            "resource_type, source) VALUES ($1, $2, 'system', 'probe.forged', 'probe', 'system')",
            (uuid7(), b),
        ),
        "domains": (
            "INSERT INTO control.domains (id, tenant_id, hostname, kind) "
            "VALUES ($1, $2, $3, 'storefront')",
            (uuid7(), b, f"evil-{secrets.token_hex(4)}.localhost"),
        ),
        "feature_flag_overrides": (
            "INSERT INTO control.feature_flag_overrides (id, flag_key, scope_type, tenant_id, "
            "enabled) VALUES ($1, 'coupons', 'tenant', $2, true)",
            (uuid7(), b),
        ),
        "merchant_profiles": (
            "INSERT INTO control.merchant_profiles (tenant_id, display_name) VALUES ($1, 'pwned')",
            (b,),
        ),
        "tenant_blueprint_assignments": (
            "INSERT INTO control.tenant_blueprint_assignments "
            "(id, tenant_id, blueprint_version_id) VALUES ($1, $2, $3)",
            (uuid7(), b, uuid.UUID(world.versions["1.1.0"])),
        ),
        "tenant_invitation_roles": (
            "INSERT INTO control.tenant_invitation_roles (tenant_id, invitation_id, role_key) "
            "VALUES ($1, $2, 'TENANT_OWNER')",
            (b, rows.b_invitation),
        ),
        "tenant_invitations": (
            "INSERT INTO control.tenant_invitations (id, tenant_id, token_hash, expires_at) "
            "VALUES ($1, $2, $3, now() + interval '1 hour')",
            (uuid7(), b, secrets.token_bytes(32)),
        ),
        "tenant_membership_roles": (
            "INSERT INTO control.tenant_membership_roles (tenant_id, membership_id, role_key) "
            "VALUES ($1, $2, 'TENANT_OWNER')",
            (b, uuid.UUID(world.b.memberships[world.b.staff.username])),
        ),
        "tenant_memberships": (
            "INSERT INTO control.tenant_memberships (id, tenant_id, person_id) VALUES ($1, $2, $3)",
            (uuid7(), b, uuid.UUID(str(world.a.admin.person_id))),
        ),
    }


@pytest.mark.parametrize("table", TENANT_TABLES)
async def test_tenant_a_cannot_write_tenant_b_rows(
    app_conn: asyncpg.Connection, world: World, rows: Rows, table: str
) -> None:
    a, b = uuid.UUID(world.a.id), uuid.UUID(world.b.id)
    sql, args = _insert_into_b(world, rows)[table]

    # INSERT a row owned by B: refused by the policy's WITH CHECK.
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        async with rolled_back(app_conn):
            await ctx(app_conn, a)
            await app_conn.execute(sql, *args)

    # UPDATE / DELETE B's rows: they do not exist for A (or the grant is absent).
    for statement, allowed in (
        (f"UPDATE control.{table} SET tenant_id = tenant_id WHERE tenant_id = $1", UPDATABLE),
        (f"DELETE FROM control.{table} WHERE tenant_id = $1", DELETABLE),
    ):
        async with rolled_back(app_conn):
            await ctx(app_conn, a)
            if table in allowed:
                assert (await app_conn.execute(statement, b)).endswith(" 0"), statement
            else:
                with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
                    await app_conn.execute(statement, b)

    # Moving one of A's own rows into B: refused by WITH CHECK.
    if table in UPDATABLE:
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            async with rolled_back(app_conn):
                await ctx(app_conn, a)
                await app_conn.execute(
                    f"UPDATE control.{table} SET tenant_id = $2 WHERE tenant_id = $1", a, b
                )


# ------------------------------------------------------ table-specific rules
async def test_tenant_invitation_roles_are_isolated_at_sql_level(
    app_conn: asyncpg.Connection, world: World, rows: Rows
) -> None:
    a = uuid.UUID(world.a.id)
    async with rolled_back(app_conn):
        await ctx(app_conn, a)
        visible = {
            (r["tenant_id"], r["invitation_id"])
            for r in await app_conn.fetch(
                "SELECT tenant_id, invitation_id FROM control.tenant_invitation_roles"
            )
        }
        assert (a, rows.a_invitation) in visible
        assert all(t == a for t, _ in visible)
        assert not any(i == rows.b_invitation for _, i in visible)
        assert (
            await app_conn.fetchval(
                "SELECT count(*) FROM control.tenant_invitation_roles WHERE invitation_id = $1",
                rows.b_invitation,
            )
            == 0
        )
    # Labelled as A's own row but pointing at B's invitation: the composite key
    # (tenant_id, invitation_id) has no such parent, so it cannot exist.
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        async with rolled_back(app_conn):
            await ctx(app_conn, a)
            await app_conn.execute(
                "INSERT INTO control.tenant_invitation_roles (tenant_id, invitation_id, role_key) "
                "VALUES ($1, $2, 'TENANT_OWNER')",
                a,
                rows.b_invitation,
            )
    # Adding a role to B's invitation from A: refused by RLS.
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        async with rolled_back(app_conn):
            await ctx(app_conn, a)
            await app_conn.execute(
                "INSERT INTO control.tenant_invitation_roles (tenant_id, invitation_id, role_key) "
                "VALUES ($1, $2, 'TENANT_OWNER')",
                uuid.UUID(world.b.id),
                rows.b_invitation,
            )
    # Rewriting or deleting role rows: no grant at all.
    for statement in (
        "UPDATE control.tenant_invitation_roles SET role_key = 'TENANT_OWNER'",
        "DELETE FROM control.tenant_invitation_roles",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="permission denied"):
            async with rolled_back(app_conn):
                await ctx(app_conn, a)
                await app_conn.execute(statement)


async def test_flag_overrides_global_rows_are_shared_but_only_writable_outside_tenants(
    app_conn: asyncpg.Connection, world: World, rows: Rows
) -> None:
    a, b = uuid.UUID(world.a.id), uuid.UUID(world.b.id)
    async with rolled_back(app_conn):
        # Outside any tenant: a platform override can be written.
        await ctx(app_conn, None)
        await app_conn.execute(
            "INSERT INTO control.feature_flag_overrides (id, flag_key, scope_type, enabled) "
            "VALUES ($1, 'subscriptions', 'platform', true)",
            uuid7(),
        )
        # Inside A: global rows and A's rows are visible; B's never.
        await ctx(app_conn, a)
        seen = await app_conn.fetch(
            "SELECT flag_key, scope_type, tenant_id FROM control.feature_flag_overrides"
        )
        assert ("subscriptions", "platform", None) in {tuple(r) for r in seen}
        assert {r["tenant_id"] for r in seen} <= {None, a}
        assert a in {r["tenant_id"] for r in seen}
        # ...but tenant-context code cannot change platform configuration.
        assert (
            await app_conn.execute(
                "UPDATE control.feature_flag_overrides SET enabled = false "
                "WHERE scope_type = 'platform'"
            )
            == "UPDATE 0"
        )
        assert (
            await app_conn.execute(
                "DELETE FROM control.feature_flag_overrides WHERE scope_type = 'platform'"
            )
            == "DELETE 0"
        )
        # Outside any tenant, a tenant's override is readable by no one.
        await ctx(app_conn, None)
        assert (
            await app_conn.fetchval(
                "SELECT count(*) FROM control.feature_flag_overrides WHERE tenant_id = ANY($1)",
                [a, b],
            )
            == 0
        )
    for context, statement, args in (
        (
            a,
            "INSERT INTO control.feature_flag_overrides (id, flag_key, scope_type, enabled) "
            "VALUES ($1, 'advertising', 'platform', true)",
            (uuid7(),),
        ),
        (
            None,
            "INSERT INTO control.feature_flag_overrides (id, flag_key, scope_type, tenant_id, "
            "enabled) VALUES ($1, 'coupons', 'tenant', $2, true)",
            (uuid7(), a),
        ),
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
            async with rolled_back(app_conn):
                await ctx(app_conn, context)
                await app_conn.execute(statement, *args)


async def test_domains_resolve_only_through_the_host_resolver(
    app_conn: asyncpg.Connection, world: World, rows: Rows
) -> None:
    async with rolled_back(app_conn):
        await ctx(app_conn, None)
        assert await app_conn.fetchval("SELECT count(*) FROM control.domains") == 0
        resolve = "SELECT control.resolve_storefront_host($1)"
        assert str(await app_conn.fetchval(resolve, rows.a_host)) == world.a.id
        assert str(await app_conn.fetchval(resolve, rows.b_host)) == world.b.id
        assert await app_conn.fetchval(resolve, "nobody.localhost") is None
        assert await app_conn.fetchval(resolve, "%") is None, "exact match only, no patterns"
    # Platform-kind domains have no tenant, so the runtime role cannot create them.
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        async with rolled_back(app_conn):
            await ctx(app_conn, None)
            await app_conn.execute(
                "INSERT INTO control.domains (id, hostname, kind) VALUES ($1, $2, 'platform')",
                uuid7(),
                f"platform-{secrets.token_hex(4)}.localhost",
            )
