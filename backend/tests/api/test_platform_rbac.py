"""Gate 4 (platform/vertical scope): roles and permissions enforced server-side."""

from __future__ import annotations

import httpx
import pytest

from arada.kernel.config import Settings
from arada.kernel.db import Database
from arada.kernel.errors import Conflict
from arada.rbac import service as rbac
from arada.rbac.bootstrap import bootstrap_super_admin
from tests.support import (
    DEFAULT_PASSWORD,
    Persona,
    audit_rows,
    enrol_totp,
    login,
    make_person,
    unique,
)
from tests.world import World


async def _grant(
    client: httpx.AsyncClient,
    admin: Persona,
    person: Persona,
    role: str,
    vertical: str | None = None,
) -> httpx.Response:
    body = {"person_id": str(person.person_id), "role": role}
    if vertical:
        body["vertical"] = vertical
    return await client.post("/v1/platform/role-grants", headers=admin.headers, json=body)


async def _create_vertical(client: httpx.AsyncClient, admin: Persona, key: str) -> httpx.Response:
    return await client.post(
        "/v1/platform/verticals", headers=admin.headers, json={"key": key, "name_en": key.title()}
    )


async def test_bootstrap_runs_only_once(settings: Settings, super_admin: Persona) -> None:
    with pytest.raises(Conflict):
        await bootstrap_super_admin(settings, unique("again"), "Second", DEFAULT_PASSWORD)


async def test_super_admin_can_run_platform_operations(
    client: httpx.AsyncClient, super_admin: Persona, db: Database
) -> None:
    key = unique("v_")
    created = await _create_vertical(client, super_admin, key)
    assert created.status_code == 201, created.text
    listed = await client.get("/v1/platform/verticals", headers=super_admin.headers)
    assert key in {v["key"] for v in listed.json()}
    rows = await audit_rows(db, action="vertical.created", resource_id=created.json()["id"])
    assert rows[0].actor_person_id == super_admin.person_id
    assert rows[0].request_id == created.headers["x-request-id"]


async def test_privileged_roles_require_an_mfa_verified_session(
    client: httpx.AsyncClient, super_admin: Persona, db: Database
) -> None:
    second = await make_person(db)
    assert (await _grant(client, super_admin, second, "SUPER_ADMIN")).status_code == 204
    await login(client, second)  # password only: session not MFA-verified
    denied = await _create_vertical(client, second, unique("v_"))
    assert denied.status_code == 403
    assert denied.json()["type"] == "urn:arada:problem:mfa-required-for-scope"
    await enrol_totp(client, second)  # proves the factor in this session
    assert (await _create_vertical(client, second, unique("v_"))).status_code == 201


async def test_ordinary_person_is_forbidden_platform_operations(
    client: httpx.AsyncClient, db: Database
) -> None:
    nobody = await make_person(db)
    await login(client, nobody)
    assert (await _create_vertical(client, nobody, unique("v_"))).status_code == 403
    assert (await client.get("/v1/platform/verticals", headers=nobody.headers)).status_code == 403
    lookup = await client.get(
        "/v1/platform/persons", headers=nobody.headers, params={"username": nobody.username}
    )
    assert lookup.status_code == 403


async def test_platform_admin_cannot_grant_roles(
    client: httpx.AsyncClient, super_admin: Persona, db: Database
) -> None:
    admin, target = await make_person(db), await make_person(db)
    assert (await _grant(client, super_admin, admin, "PLATFORM_ADMIN")).status_code == 204
    await login(client, admin)
    await enrol_totp(client, admin)
    assert (await _create_vertical(client, admin, unique("v_"))).status_code == 201
    # Privilege escalation attempt: PLATFORM_ADMIN lacks roles.manage.
    assert (await _grant(client, admin, target, "SUPER_ADMIN")).status_code == 403
    assert (await _grant(client, admin, admin, "SUPER_ADMIN")).status_code == 403


async def test_vertical_admin_sees_only_their_vertical(
    client: httpx.AsyncClient, super_admin: Persona, db: Database
) -> None:
    phones, cars = unique("phones_"), unique("cars_")
    for key in (phones, cars):
        assert (await _create_vertical(client, super_admin, key)).status_code == 201
    carol = await make_person(db)
    assert (await _grant(client, super_admin, carol, "VERTICAL_ADMIN", phones)).status_code == 204
    await login(client, carol)
    await enrol_totp(client, carol)
    visible = {
        v["key"] for v in (await client.get("/v1/platform/verticals", headers=carol.headers)).json()
    }
    assert visible == {phones}
    # A vertical admin is not a platform admin.
    assert (await _create_vertical(client, carol, unique("v_"))).status_code == 403
    me = (await client.get("/v1/me", headers=carol.headers)).json()
    assert me["roles"] == {"platform": [], "vertical": [f"VERTICAL_ADMIN@{phones}"]}


async def test_platform_admin_revocation_is_immediate(
    client: httpx.AsyncClient, super_admin: Persona, db: Database
) -> None:
    """(Renamed: this test never covered SUPER_ADMIN. That is now
    ``test_super_admin_revocation_is_immediate_and_audited`` below, plus the
    last-SUPER_ADMIN and concurrency tests in
    ``tests/integration/test_super_admin_invariant.py``.)"""
    dave = await make_person(db)
    assert (await _grant(client, super_admin, dave, "PLATFORM_ADMIN")).status_code == 204
    await login(client, dave)
    await enrol_totp(client, dave)
    assert (await _create_vertical(client, dave, unique("v_"))).status_code == 201
    revoked = await client.post(
        "/v1/platform/role-grants:revoke",
        headers=super_admin.headers,
        json={"person_id": str(dave.person_id), "role": "PLATFORM_ADMIN"},
    )
    assert revoked.status_code == 204
    # Same session, very next request: the role is gone.
    assert (await _create_vertical(client, dave, unique("v_"))).status_code == 403
    assert await audit_rows(db, action="rbac.role_revoked", resource_id=str(dave.person_id))


async def _revoke(
    client: httpx.AsyncClient, actor: Persona, target: Persona, role: str = "SUPER_ADMIN"
) -> httpx.Response:
    return await client.post(
        "/v1/platform/role-grants:revoke",
        headers=actor.headers,
        json={"person_id": str(target.person_id), "role": role},
    )


async def _platform_roles(db: Database, person: Persona) -> list[str]:
    async with db.transaction() as conn:
        return (await rbac.privileged_roles_of(conn, person.person_id))["platform"]


async def test_super_admin_revocation_is_immediate_and_audited(
    client: httpx.AsyncClient, super_admin: Persona, db: Database
) -> None:
    ivan = await make_person(db)
    assert (await _grant(client, super_admin, ivan, "SUPER_ADMIN")).status_code == 204
    await login(client, ivan)
    await enrol_totp(client, ivan)
    assert (await _create_vertical(client, ivan, unique("v_"))).status_code == 201

    revoked = await _revoke(client, super_admin, ivan)
    assert revoked.status_code == 204, revoked.text
    # Same session, very next request: the role and its permissions are gone.
    assert (await _create_vertical(client, ivan, unique("v_"))).status_code == 403
    assert (await _grant(client, ivan, ivan, "SUPER_ADMIN")).status_code == 403
    me = (await client.get("/v1/me", headers=ivan.headers)).json()
    assert me["roles"]["platform"] == []
    # Revoking again: nothing left to revoke.
    assert (await _revoke(client, super_admin, ivan)).status_code == 404

    (event,) = await audit_rows(db, action="rbac.role_revoked", resource_id=str(ivan.person_id))
    assert event.actor_person_id == super_admin.person_id
    assert event.before == {"role": "SUPER_ADMIN"}
    assert event.request_id == revoked.headers["x-request-id"]


async def test_only_mfa_verified_role_managers_can_revoke_a_super_admin(
    client: httpx.AsyncClient, super_admin: Persona, db: Database, world: World
) -> None:
    target = await make_person(db)
    assert (await _grant(client, super_admin, target, "SUPER_ADMIN")).status_code == 204

    platform_admin = await make_person(db)
    assert (await _grant(client, super_admin, platform_admin, "PLATFORM_ADMIN")).status_code == 204
    await login(client, platform_admin)
    await enrol_totp(client, platform_admin)
    unverified_super = await make_person(db)
    assert (await _grant(client, super_admin, unverified_super, "SUPER_ADMIN")).status_code == 204
    await login(client, unverified_super)  # password only
    nobody = await make_person(db)
    await login(client, nobody)

    assert (await _revoke(client, platform_admin, target)).status_code == 403
    assert (await _revoke(client, world.a.owner, target)).status_code == 403
    assert (await _revoke(client, nobody, target)).status_code == 403
    step_up = await _revoke(client, unverified_super, target)
    assert step_up.status_code == 403
    assert step_up.json()["type"] == "urn:arada:problem:mfa-required-for-scope"
    anonymous = await client.post(
        "/v1/platform/role-grants:revoke",
        json={"person_id": str(target.person_id), "role": "SUPER_ADMIN"},
    )
    assert anonymous.status_code == 401

    assert await _platform_roles(db, target) == ["SUPER_ADMIN"]
    assert not await audit_rows(db, action="rbac.role_revoked", resource_id=str(target.person_id))


async def test_role_grants_are_validated(
    client: httpx.AsyncClient, super_admin: Persona, db: Database
) -> None:
    erin = await make_person(db)
    assert (await _grant(client, super_admin, erin, "TENANT_OWNER")).status_code == 422
    assert (await _grant(client, super_admin, erin, "VERTICAL_ADMIN")).status_code == 422
    assert (await _grant(client, super_admin, erin, "NOT_A_ROLE")).status_code == 422
    ghost = Persona(person_id=erin.person_id.__class__(int=1), username="ghost", password="x")
    assert (await _grant(client, super_admin, ghost, "PLATFORM_ADMIN")).status_code == 404


async def test_role_catalogue_is_published(client: httpx.AsyncClient, db: Database) -> None:
    fred = await make_person(db)
    await login(client, fred)
    tenant_roles = await client.get(
        "/v1/roles", headers=fred.headers, params={"scope_type": "tenant"}
    )
    keys = {r["key"] for r in tenant_roles.json()}
    assert {"TENANT_OWNER", "TENANT_ADMIN", "TENANT_STAFF"} <= keys
    assert all(r["scope_type"] == "tenant" for r in tenant_roles.json())
