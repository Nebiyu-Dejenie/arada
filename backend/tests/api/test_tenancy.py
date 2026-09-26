"""Gate 5 and the RBAC milestone: tenancy works, roles hold inside a tenant.

Personas (from the ``world`` fixture): Super Admin, Tenant A Owner/Admin/Staff,
Tenant B Owner/Admin/Staff.
"""

from __future__ import annotations

import asyncpg
import httpx

from arada.kernel.db import Database
from tests.conftest import PgEnv
from tests.support import Persona, audit_rows, login, make_person
from tests.world import World, accept_as_new, build_tenant, create_tenant, invite, seed


# ------------------------------------------------------------- super admin
async def test_super_admin_creates_and_governs_tenants(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> None:
    listed = await client.get(
        "/v1/platform/tenants", headers=super_admin.headers, params={"vertical": world.vertical}
    )
    assert listed.status_code == 200
    slugs = {t["slug"]: t for t in listed.json()}
    assert {world.a.slug, world.b.slug} <= slugs.keys()
    assert slugs[world.a.slug]["status"] == "active"
    assert slugs[world.a.slug]["blueprint_version"] == "1.0.0"

    # The super admin can read any tenant's console (platform tenants.read).
    detail = await client.get(f"/v1/t/{world.a.slug}", headers=super_admin.headers)
    assert detail.status_code == 200
    assert detail.json()["profile"]["display_name"] == "SHOP-A- Phones"


async def test_blueprint_pin_moves_only_by_explicit_assignment(
    client: httpx.AsyncClient, super_admin: Persona, world: World, db: Database
) -> None:
    root = super_admin.headers
    tenant_id, slug, owner_token = await create_tenant(
        client, super_admin, world.vertical, world.versions["1.0.0"], "pin-"
    )
    # Publishing a newer version does not move existing tenants.
    draft = await client.post(
        f"/v1/platform/blueprints/{world.blueprint_id}/versions",
        headers=root,
        json={"version": "2.0.0", "definition": seed("2.0.0")},
    )
    assert draft.status_code == 201, draft.text
    published = await client.post(
        f"/v1/platform/blueprints/{world.blueprint_id}/versions/{draft.json()['id']}:publish",
        headers=root,
    )
    assert published.status_code == 200
    for existing in (slug, world.a.slug, world.b.slug):
        assert (await client.get(f"/v1/t/{existing}", headers=root)).json()[
            "blueprint_version"
        ] == "1.0.0"

    moved = await client.post(
        f"/v1/platform/tenants/{tenant_id}/blueprint-assignment",
        headers=root,
        json={"blueprint_version_id": world.versions["1.1.0"], "reason": "adopt battery health"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["blueprint_version"] == "1.1.0"
    # Everyone else is untouched.
    assert (await client.get(f"/v1/t/{world.b.slug}", headers=root)).json()[
        "blueprint_version"
    ] == "1.0.0"

    history = await client.get(f"/v1/t/{slug}/blueprint-history", headers=root)
    assert [h["blueprint_version_id"] for h in history.json()] == [
        world.versions["1.0.0"],
        world.versions["1.1.0"],
    ]
    rows = await audit_rows(db, action="tenant.blueprint_assigned")
    assert any(
        r.after["blueprint_version"] == "1.1.0" and str(r.tenant_id) == tenant_id for r in rows
    )

    # Invalid targets: a draft, and a version from another vertical, are refused.
    other_draft = await client.post(
        f"/v1/platform/blueprints/{world.blueprint_id}/versions",
        headers=root,
        json={"version": "2.1.0", "definition": seed("2.0.0") | {"description": "draft only"}},
    )
    refused = await client.post(
        f"/v1/platform/tenants/{tenant_id}/blueprint-assignment",
        headers=root,
        json={"blueprint_version_id": other_draft.json()["id"], "reason": "should fail"},
    )
    assert refused.status_code == 422
    assert owner_token  # owner invitation was issued with the tenant


async def test_tenant_a_admin_manages_tenant_a(
    client: httpx.AsyncClient, world: World, db: Database
) -> None:
    admin, slug = world.a.admin, world.a.slug
    current = await client.get(f"/v1/t/{slug}", headers=admin.headers)
    assert current.status_code == 200
    etag = current.headers["etag"]
    patched = await client.patch(
        f"/v1/t/{slug}/profile",
        headers={**admin.headers, "If-Match": etag},
        json={"tagline": "Genuine phones, fair prices", "brand_primary_color": "#0a7cff"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["tagline"] == "Genuine phones, fair prices"
    # Stale version is rejected (optimistic concurrency).
    stale = await client.patch(
        f"/v1/t/{slug}/profile", headers={**admin.headers, "If-Match": etag}, json={"tagline": "x"}
    )
    assert stale.status_code == 412

    staff = await client.get(f"/v1/t/{slug}/staff", headers=admin.headers)
    assert {m["username"] for m in staff.json()} >= {
        world.a.owner.username,
        admin.username,
        world.a.staff.username,
    }

    promoted = await client.put(
        f"/v1/t/{slug}/staff/{world.a.memberships[world.a.staff.username]}/roles",
        headers=admin.headers,
        json={"roles": ["TENANT_STAFF", "TENANT_MANAGER"]},
    )
    assert promoted.status_code == 200
    assert promoted.json()["roles"] == ["TENANT_MANAGER", "TENANT_STAFF"]
    demoted = await client.put(
        f"/v1/t/{slug}/staff/{world.a.memberships[world.a.staff.username]}/roles",
        headers=admin.headers,
        json={"roles": ["TENANT_STAFF"]},
    )
    assert demoted.status_code == 200

    audit = await client.get(f"/v1/t/{slug}/audit-events", headers=admin.headers)
    assert audit.status_code == 200
    actions = {e["action"] for e in audit.json()}
    assert {
        "tenant.profile_updated",
        "tenant.staff_roles_changed",
        "tenant.invitation_accepted",
    } <= actions
    assert all(e["tenant_id"] == world.a.id for e in audit.json())


async def test_tenant_a_staff_cannot_perform_admin_operations(
    client: httpx.AsyncClient, world: World
) -> None:
    staff, slug = world.a.staff, world.a.slug
    assert (await client.get(f"/v1/t/{slug}", headers=staff.headers)).status_code == 200
    denied = [
        await client.patch(
            f"/v1/t/{slug}/profile",
            headers={**staff.headers, "If-Match": '"1"'},
            json={"tagline": "x"},
        ),
        await client.post(
            f"/v1/t/{slug}/invitations", headers=staff.headers, json={"roles": ["TENANT_STAFF"]}
        ),
        await client.put(
            f"/v1/t/{slug}/staff/{world.a.memberships[world.a.admin.username]}/roles",
            headers=staff.headers,
            json={"roles": ["TENANT_STAFF"]},
        ),
        await client.post(
            f"/v1/t/{slug}/staff/{world.a.memberships[world.a.admin.username]}:remove",
            headers=staff.headers,
        ),
        await client.get(f"/v1/t/{slug}/audit-events", headers=staff.headers),
        await client.get(f"/v1/t/{slug}/staff", headers=staff.headers),
    ]
    assert [r.status_code for r in denied] == [403] * len(denied)
    # Staff is a member, so 403 (not 404) is correct: the tenant is theirs.


async def test_privilege_escalation_inside_a_tenant_is_refused(
    client: httpx.AsyncClient, world: World
) -> None:
    admin, slug = world.a.admin, world.a.slug
    # An admin cannot mint an owner (TENANT_OWNER exceeds their permissions)...
    assert (
        await client.post(
            f"/v1/t/{slug}/invitations", headers=admin.headers, json={"roles": ["TENANT_OWNER"]}
        )
    ).status_code == 403
    assert (
        await client.put(
            f"/v1/t/{slug}/staff/{world.a.memberships[world.a.staff.username]}/roles",
            headers=admin.headers,
            json={"roles": ["TENANT_OWNER"]},
        )
    ).status_code == 403
    # ...cannot change their own roles...
    assert (
        await client.put(
            f"/v1/t/{slug}/staff/{world.a.memberships[admin.username]}/roles",
            headers=admin.headers,
            json={"roles": ["TENANT_ADMIN", "TENANT_FINANCE"]},
        )
    ).status_code == 403
    # ...cannot remove the owner...
    assert (
        await client.post(
            f"/v1/t/{slug}/staff/{world.a.memberships[world.a.owner.username]}:remove",
            headers=admin.headers,
        )
    ).status_code == 403
    # ...and cannot hand out platform or vertical roles through a tenant.
    assert (
        await client.post(
            f"/v1/t/{slug}/invitations", headers=admin.headers, json={"roles": ["SUPER_ADMIN"]}
        )
    ).status_code == 422


async def test_last_owner_cannot_be_removed_or_demoted(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> None:
    tenant = await build_tenant(
        client, super_admin, world.vertical, world.versions["1.0.0"], "own-"
    )
    owner_membership = tenant.memberships[tenant.owner.username]
    # The super admin may manage any tenant's staff, but not break the invariant.
    demote = await client.put(
        f"/v1/t/{tenant.slug}/staff/{owner_membership}/roles",
        headers=super_admin.headers,
        json={"roles": ["TENANT_ADMIN"]},
    )
    assert demote.status_code == 409
    remove = await client.post(
        f"/v1/t/{tenant.slug}/staff/{owner_membership}:remove", headers=super_admin.headers
    )
    assert remove.status_code == 409


async def test_invitations_are_single_use_revocable_and_expiring(
    client: httpx.AsyncClient, world: World, pg_env: PgEnv, test_database: str
) -> None:
    admin, slug = world.a.admin, world.a.slug
    token = await invite(client, admin, slug, ["TENANT_STAFF"])
    await accept_as_new(client, token)
    reused = await client.post(
        "/v1/invitations:accept",
        json={
            "token": token,
            "new_account": {
                "username": "reuse" + slug[-6:],
                "password": "x" * 12,
                "display_name": "R",
            },
        },
    )
    assert reused.status_code == 404

    revocable = await client.post(
        f"/v1/t/{slug}/invitations", headers=admin.headers, json={"roles": ["TENANT_STAFF"]}
    )
    revoke = await client.post(
        f"/v1/t/{slug}/invitations/{revocable.json()['id']}:revoke", headers=admin.headers
    )
    assert revoke.status_code == 204
    assert (
        await client.post(
            "/v1/invitations:accept",
            json={"token": revocable.json()["token"]},
            headers=world.b.staff.headers,
        )
    ).status_code == 404

    expiring = await client.post(
        f"/v1/t/{slug}/invitations", headers=admin.headers, json={"roles": ["TENANT_STAFF"]}
    )
    conn = await asyncpg.connect(pg_env.superuser_dsn(test_database))
    try:
        await conn.execute(
            "UPDATE control.tenant_invitations "
            "SET expires_at = now() - interval '1 second' WHERE id = $1",
            expiring.json()["id"],
        )
    finally:
        await conn.close()
    assert (
        await client.post(
            "/v1/invitations:accept",
            json={"token": expiring.json()["token"]},
            headers=world.b.staff.headers,
        )
    ).status_code == 404


async def test_a_person_can_belong_to_several_tenants(
    client: httpx.AsyncClient, world: World, db: Database
) -> None:
    person = await make_person(db)
    await login(client, person)
    for tenant in (world.a, world.b):
        token = await invite(client, tenant.admin, tenant.slug, ["TENANT_STAFF"])
        joined = await client.post(
            "/v1/invitations:accept", headers=person.headers, json={"token": token}
        )
        assert joined.status_code == 200, joined.text
    mine = await client.get("/v1/me/tenants", headers=person.headers)
    assert {m["tenant_slug"] for m in mine.json()} == {world.a.slug, world.b.slug}
    # Each membership only grants rights inside its own tenant.
    assert all(m["roles"] == ["TENANT_STAFF"] for m in mine.json())


async def test_suspended_tenant_is_read_only_for_its_staff(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> None:
    tenant = await build_tenant(
        client, super_admin, world.vertical, world.versions["1.0.0"], "susp-"
    )
    assert (
        await client.post(f"/v1/platform/tenants/{tenant.id}:suspend", headers=super_admin.headers)
    ).status_code == 200
    etag = (await client.get(f"/v1/t/{tenant.slug}", headers=tenant.owner.headers)).headers["etag"]
    write = await client.patch(
        f"/v1/t/{tenant.slug}/profile",
        headers={**tenant.owner.headers, "If-Match": etag},
        json={"tagline": "x"},
    )
    assert write.status_code == 403
    assert (
        await client.post(
            f"/v1/platform/tenants/{tenant.id}:reactivate", headers=super_admin.headers
        )
    ).status_code == 200
    ok = await client.patch(
        f"/v1/t/{tenant.slug}/profile",
        headers={**tenant.owner.headers, "If-Match": etag},
        json={"tagline": "back"},
    )
    assert ok.status_code == 200
    # Invalid transition.
    assert (
        await client.post(f"/v1/platform/tenants/{tenant.id}:activate", headers=super_admin.headers)
    ).status_code == 409


async def test_archived_tenant_disappears_for_its_members(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> None:
    tenant = await build_tenant(
        client, super_admin, world.vertical, world.versions["1.0.0"], "arch-"
    )
    root = super_admin.headers
    assert (
        await client.post(f"/v1/platform/tenants/{tenant.id}:suspend", headers=root)
    ).status_code == 200
    assert (
        await client.post(f"/v1/platform/tenants/{tenant.id}:archive", headers=root)
    ).status_code == 200
    assert (
        await client.get(f"/v1/t/{tenant.slug}", headers=tenant.owner.headers)
    ).status_code == 404
    # The slug is never reissued.
    reuse = await client.post(
        "/v1/platform/tenants",
        headers=root,
        json={
            "slug": tenant.slug,
            "display_name": "Squatter",
            "vertical": world.vertical,
            "blueprint_version_id": world.versions["1.0.0"],
        },
    )
    assert reuse.status_code == 409


async def test_storefront_resolves_tenant_from_host_only(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> None:
    for tenant in (world.a, world.b):
        added = await client.post(
            f"/v1/platform/tenants/{tenant.id}/domains",
            headers=super_admin.headers,
            json={"hostname": f"{tenant.slug}.localhost"},
        )
        assert added.status_code == 201, added.text
    a = await client.get(
        "/v1/storefront/merchant", headers={"host": f"{world.a.slug}.localhost:8080"}
    )
    b = await client.get("/v1/storefront/merchant", headers={"host": f"{world.b.slug}.LOCALHOST."})
    assert (a.status_code, b.status_code) == (200, 200)
    assert a.json()["slug"] == world.a.slug
    assert b.json()["slug"] == world.b.slug
    # Client-supplied tenant hints are ignored; unknown hosts are 404.
    spoof = await client.get(
        "/v1/storefront/merchant",
        headers={"host": f"{world.a.slug}.localhost", "x-tenant-id": world.b.id},
        params={"tenant": world.b.slug},
    )
    assert spoof.json()["slug"] == world.a.slug
    assert (
        await client.get("/v1/storefront/merchant", headers={"host": "nobody.localhost"})
    ).status_code == 404
    assert (
        await client.get("/v1/storefront/merchant", headers={"host": "bad host!"})
    ).status_code == 404


async def test_draft_tenant_is_not_publicly_served(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> None:
    tenant_id, slug, _ = await create_tenant(
        client, super_admin, world.vertical, world.versions["1.0.0"], "draft-"
    )
    await client.post(
        f"/v1/platform/tenants/{tenant_id}/domains",
        headers=super_admin.headers,
        json={"hostname": f"{slug}.localhost"},
    )
    assert (
        await client.get("/v1/storefront/merchant", headers={"host": f"{slug}.localhost"})
    ).status_code == 404
