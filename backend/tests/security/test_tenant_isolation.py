"""Tenant A -> Tenant B: every attack must fail and leak nothing (Gates 5, 9).

The route test enumerates the *live* application's tenant-scoped routes, so a
new tenant route without isolation coverage fails this suite by construction.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from arada.kernel.ids import uuid7
from tests.conftest import PgEnv
from tests.support import Persona, api_operations
from tests.world import World

# One valid request per tenant-scoped route, so the response reflects
# authorisation, never input validation. A new route must be added here.
SAMPLE_BODIES: dict[tuple[str, str], dict[str, Any] | None] = {
    ("GET", "/v1/t/{tenant_slug}"): None,
    ("PATCH", "/v1/t/{tenant_slug}/profile"): {"tagline": "pwned by A"},
    ("GET", "/v1/t/{tenant_slug}/blueprint-history"): None,
    ("GET", "/v1/t/{tenant_slug}/staff"): None,
    ("POST", "/v1/t/{tenant_slug}/invitations"): {"roles": ["TENANT_STAFF"]},
    ("POST", "/v1/t/{tenant_slug}/invitations/{invitation_id}:revoke"): None,
    ("PUT", "/v1/t/{tenant_slug}/staff/{membership_id}/roles"): {"roles": ["TENANT_ADMIN"]},
    ("POST", "/v1/t/{tenant_slug}/staff/{membership_id}:remove"): None,
    ("GET", "/v1/t/{tenant_slug}/audit-events"): None,
    ("GET", "/v1/t/{tenant_slug}/features"): None,
}


def tenant_routes(app: FastAPI) -> list[tuple[str, str]]:
    return [(m, p) for m, p in api_operations(app) if p.startswith("/v1/t/{tenant_slug}")]


def test_every_tenant_route_is_covered(app: FastAPI) -> None:
    """Exact correspondence: no uncovered live route, no stale sample."""
    live = set(tenant_routes(app))
    assert len(live) >= 9, f"suspiciously few tenant routes enumerated: {sorted(live)}"
    assert live == SAMPLE_BODIES.keys(), (
        f"uncovered: {sorted(live - SAMPLE_BODIES.keys())}; "
        f"stale: {sorted(SAMPLE_BODIES.keys() - live)}"
    )


async def _victim_ids(client: httpx.AsyncClient, world: World) -> dict[str, str]:
    """Real identifiers that belong to tenant B."""
    invitation = await client.post(
        f"/v1/t/{world.b.slug}/invitations",
        headers=world.b.admin.headers,
        json={"roles": ["TENANT_STAFF"]},
    )
    assert invitation.status_code == 201
    return {
        "tenant_slug": world.b.slug,
        "membership_id": world.b.memberships[world.b.staff.username],
        "invitation_id": invitation.json()["id"],
    }


def _fill(path: str, values: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], path)


async def _snapshot_b(client: httpx.AsyncClient, world: World) -> tuple[Any, ...]:
    headers = world.b.owner.headers
    tenant = (await client.get(f"/v1/t/{world.b.slug}", headers=headers)).json()
    staff = (await client.get(f"/v1/t/{world.b.slug}/staff", headers=headers)).json()
    return (
        tenant["profile"],
        sorted((m["membership_id"], tuple(m["roles"]), m["status"]) for m in staff),
    )


@pytest.mark.parametrize("attacker", ["admin", "staff", "owner"])
async def test_tenant_a_cannot_reach_tenant_b_through_any_route(
    client: httpx.AsyncClient, app: FastAPI, world: World, attacker: str
) -> None:
    persona: Persona = getattr(world.a, attacker)
    victim = await _victim_ids(client, world)
    before = await _snapshot_b(client, world)
    attempted = 0
    for method, path in tenant_routes(app):
        attempted += 1
        url = _fill(path, victim)
        body = SAMPLE_BODIES[(method, path)]
        headers = {**persona.headers, "If-Match": '"1"'}
        response = await client.request(method, url, headers=headers, json=body)
        assert response.status_code == 404, f"{attacker} {method} {url} -> {response.status_code}"
        # Nothing from B is echoed back.
        assert world.b.slug not in response.text.replace(url, "")
    assert attempted == len(SAMPLE_BODIES), "not every tenant route was attacked"
    assert await _snapshot_b(client, world) == before, "tenant B changed during the attack"


async def test_ids_from_tenant_b_are_invisible_inside_tenant_a(
    client: httpx.AsyncClient, world: World
) -> None:
    """IDOR: A's own URL, B's object ids."""
    admin, slug = world.a.admin, world.a.slug
    victim = await _victim_ids(client, world)
    attempts = [
        await client.put(
            f"/v1/t/{slug}/staff/{victim['membership_id']}/roles",
            headers=admin.headers,
            json={"roles": ["TENANT_STAFF"]},
        ),
        await client.post(
            f"/v1/t/{slug}/staff/{victim['membership_id']}:remove", headers=admin.headers
        ),
        await client.post(
            f"/v1/t/{slug}/invitations/{victim['invitation_id']}:revoke", headers=admin.headers
        ),
        await client.put(
            f"/v1/t/{slug}/staff/{uuid7()}/roles",
            headers=admin.headers,
            json={"roles": ["TENANT_STAFF"]},
        ),
    ]
    assert [r.status_code for r in attempts] == [404, 404, 404, 404]


async def test_client_supplied_tenant_hints_are_ignored(
    client: httpx.AsyncClient, world: World
) -> None:
    admin = world.a.admin
    response = await client.get(
        f"/v1/t/{world.a.slug}",
        headers={**admin.headers, "X-Tenant-ID": world.b.id, "X-Tenant-Slug": world.b.slug},
        params={"tenant_id": world.b.id, "tenant": world.b.slug},
    )
    assert response.status_code == 200
    assert response.json()["id"] == world.a.id
    # Mass assignment: tenant_id / status / vertical in a body are rejected.
    etag = response.headers["etag"]
    for field in (
        {"tenant_id": world.b.id},
        {"status": "active"},
        {"vertical_id": str(uuid.uuid4())},
        {"version": 99},
    ):
        smuggled = await client.patch(
            f"/v1/t/{world.a.slug}/profile",
            headers={**admin.headers, "If-Match": etag},
            json={"tagline": "x", **field},
        )
        assert smuggled.status_code == 422, field


async def test_tenant_roles_grant_nothing_on_the_platform(
    client: httpx.AsyncClient, world: World
) -> None:
    owner = world.a.owner
    attempts = [
        await client.get("/v1/platform/tenants", headers=owner.headers),
        await client.get("/v1/platform/audit-events", headers=owner.headers),
        await client.post(f"/v1/platform/tenants/{world.b.id}:suspend", headers=owner.headers),
        await client.post(f"/v1/platform/tenants/{world.a.id}:suspend", headers=owner.headers),
        await client.post(
            "/v1/platform/role-grants",
            headers=owner.headers,
            json={"person_id": str(owner.person_id), "role": "SUPER_ADMIN"},
        ),
        await client.post(
            "/v1/platform/verticals", headers=owner.headers, json={"key": "evil", "name_en": "E"}
        ),
    ]
    assert [r.status_code for r in attempts] == [403] * len(attempts)


async def test_audit_of_b_never_shows_a(client: httpx.AsyncClient, world: World) -> None:
    events = (
        await client.get(f"/v1/t/{world.b.slug}/audit-events", headers=world.b.owner.headers)
    ).json()
    assert events
    assert all(e["tenant_id"] == world.b.id for e in events)
    a_people = {
        str(world.a.owner.person_id),
        str(world.a.admin.person_id),
        str(world.a.staff.person_id),
    }
    assert not a_people & {e["actor_person_id"] for e in events}


async def test_memberships_list_only_the_callers_own(
    client: httpx.AsyncClient, world: World
) -> None:
    mine = (await client.get("/v1/me/tenants", headers=world.a.staff.headers)).json()
    assert [m["tenant_slug"] for m in mine] == [world.a.slug]


# ----------------------------------------------------------------- database layer
async def _ctx(conn: asyncpg.Connection, tenant: str | None) -> None:
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant or "")


@pytest.mark.parametrize(
    "table",
    ["merchant_profiles", "tenant_memberships", "tenant_membership_roles", "tenant_invitations"],
)
async def test_rls_confines_reads_to_the_context_tenant(
    app_conn: asyncpg.Connection, world: World, table: str
) -> None:
    async with app_conn.transaction():
        await _ctx(app_conn, world.a.id)
        seen = {
            str(r["tenant_id"])
            for r in await app_conn.fetch(f"SELECT tenant_id FROM control.{table}")
        }
    assert seen == {world.a.id}
    async with app_conn.transaction():
        await _ctx(app_conn, None)
        assert await app_conn.fetchval(f"SELECT count(*) FROM control.{table}") == 0


async def test_rls_blocks_writes_into_another_tenant(
    app_conn: asyncpg.Connection, world: World
) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app_conn.transaction():
            await _ctx(app_conn, world.a.id)
            await app_conn.execute(
                "INSERT INTO control.tenant_memberships (id, tenant_id, person_id) "
                "VALUES ($1, $2, $3)",
                uuid7(),
                uuid.UUID(world.b.id),
                uuid.UUID(str(world.a.admin.person_id)),
            )
    async with app_conn.transaction():
        await _ctx(app_conn, world.a.id)
        updated = await app_conn.execute(
            "UPDATE control.merchant_profiles SET tagline = 'pwned' WHERE tenant_id = $1",
            uuid.UUID(world.b.id),
        )
    assert updated == "UPDATE 0"


async def test_composite_keys_forbid_cross_tenant_references(
    world: World, pg_env: PgEnv, test_database: str
) -> None:
    """Even with RLS bypassed (superuser), a role row cannot point across tenants."""
    conn = await asyncpg.connect(pg_env.superuser_dsn(test_database))
    try:
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO control.tenant_membership_roles (tenant_id, membership_id, role_key) "
                "VALUES ($1, $2, 'TENANT_OWNER')",
                uuid.UUID(world.a.id),
                uuid.UUID(world.b.memberships[world.b.staff.username]),
            )
    finally:
        await conn.close()


async def test_resolver_functions_reveal_only_what_they_must(
    app_conn: asyncpg.Connection, world: World
) -> None:
    async with app_conn.transaction():
        await app_conn.execute(
            "SELECT set_config('app.person_id', $1, true)", str(world.a.staff.person_id)
        )
        rows = await app_conn.fetch("SELECT tenant_id FROM control.memberships_of_current_person()")
    assert {str(r["tenant_id"]) for r in rows} == {world.a.id}
    assert (
        await app_conn.fetchval("SELECT control.resolve_invitation(sha256('guess'::bytea))") is None
    )
    # The resolver role cannot be assumed by the application.
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("SET ROLE arada_resolver")
