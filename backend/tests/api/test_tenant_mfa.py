"""Privileged tenant roles need an MFA-verified session (09_SECURITY.md §3, ADR-035).

TENANT_OWNER, TENANT_ADMIN and TENANT_FINANCE hold the money, staff and
security permissions of a merchant; their permissions are withheld until the
session has proven a second factor. TENANT_MANAGER and TENANT_STAFF work
with a password-only session.
"""

from __future__ import annotations

import httpx

from arada.kernel.db import Database
from tests.support import Persona, enrol_totp, login, make_person
from tests.world import World, accept_as_new, create_tenant, invite

MFA_REQUIRED = "urn:arada:problem:mfa-required-for-scope"


def _step_up(response: httpx.Response) -> bool:
    return response.status_code == 403 and response.json()["type"] == MFA_REQUIRED


async def test_owner_admin_and_finance_need_an_mfa_verified_session(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> None:
    _, slug, owner_token = await create_tenant(
        client, super_admin, world.vertical, world.versions["1.0.0"], "mfa-"
    )
    owner = await accept_as_new(client, owner_token)  # password-only session
    assert _step_up(await client.get(f"/v1/t/{slug}", headers=owner.headers))
    assert _step_up(
        await client.post(
            f"/v1/t/{slug}/invitations", headers=owner.headers, json={"roles": ["TENANT_STAFF"]}
        )
    )
    await enrol_totp(client, owner)
    assert (await client.get(f"/v1/t/{slug}", headers=owner.headers)).status_code == 200

    for role, probe in (("TENANT_ADMIN", "/staff"), ("TENANT_FINANCE", "/audit-events")):
        member = await accept_as_new(client, await invite(client, owner, slug, [role]))
        assert _step_up(await client.get(f"/v1/t/{slug}", headers=member.headers)), role
        assert _step_up(await client.get(f"/v1/t/{slug}{probe}", headers=member.headers)), role
        await enrol_totp(client, member)
        assert (await client.get(f"/v1/t/{slug}", headers=member.headers)).status_code == 200
        assert (
            await client.get(f"/v1/t/{slug}{probe}", headers=member.headers)
        ).status_code == 200, role

    # A later password + TOTP login is MFA-verified from the start.
    await login(client, owner)
    assert (await client.get(f"/v1/t/{slug}/staff", headers=owner.headers)).status_code == 200


async def test_manager_and_staff_work_without_mfa(client: httpx.AsyncClient, world: World) -> None:
    owner, slug = world.a.owner, world.a.slug
    manager = await accept_as_new(client, await invite(client, owner, slug, ["TENANT_MANAGER"]))
    staff = await accept_as_new(client, await invite(client, owner, slug, ["TENANT_STAFF"]))
    for persona in (manager, staff):
        assert (await client.get(f"/v1/t/{slug}", headers=persona.headers)).status_code == 200
    assert (await client.get(f"/v1/t/{slug}/staff", headers=manager.headers)).status_code == 200
    # Staff lack staff.read altogether: a plain 403, not an MFA step-up.
    denied = await client.get(f"/v1/t/{slug}/staff", headers=staff.headers)
    assert denied.status_code == 403
    assert denied.json()["type"] != MFA_REQUIRED


async def test_without_mfa_only_the_non_privileged_roles_count(
    client: httpx.AsyncClient, world: World
) -> None:
    """Staff + Admin, password-only: staff rights work, admin rights are withheld."""
    owner, slug = world.a.owner, world.a.slug
    both = await accept_as_new(
        client, await invite(client, owner, slug, ["TENANT_STAFF", "TENANT_ADMIN"])
    )
    current = await client.get(f"/v1/t/{slug}", headers=both.headers)
    assert current.status_code == 200  # tenants.read comes from TENANT_STAFF too
    etag = current.headers["etag"]
    assert _step_up(await client.get(f"/v1/t/{slug}/staff", headers=both.headers))
    assert _step_up(
        await client.patch(
            f"/v1/t/{slug}/profile",
            headers={**both.headers, "If-Match": etag},
            json={"tagline": "not without MFA"},
        )
    )
    await enrol_totp(client, both)
    assert (await client.get(f"/v1/t/{slug}/staff", headers=both.headers)).status_code == 200


async def test_step_up_never_reveals_a_tenant_to_non_members(
    client: httpx.AsyncClient, world: World, db: Database
) -> None:
    outsider = await make_person(db)
    await login(client, outsider)  # password-only, like an unverified owner
    for path in ("", "/staff", "/audit-events"):
        response = await client.get(f"/v1/t/{world.b.slug}{path}", headers=outsider.headers)
        assert response.status_code == 404, path
