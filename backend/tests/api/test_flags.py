"""Gate 8: platform/vertical/tenant feature configuration."""

from __future__ import annotations

import httpx

from arada.kernel.db import Database
from tests.support import Persona, audit_rows
from tests.world import World


async def features(
    client: httpx.AsyncClient, persona: Persona, slug: str
) -> dict[str, tuple[bool, str]]:
    response = await client.get(f"/v1/t/{slug}/features", headers=persona.headers)
    assert response.status_code == 200, response.text
    return {f["key"]: (f["enabled"], f["source"]) for f in response.json()}


async def put_override(
    client: httpx.AsyncClient, admin: Persona, key: str, **body: object
) -> httpx.Response:
    return await client.put(
        f"/v1/platform/feature-flags/{key}/overrides", headers=admin.headers, json=body
    )


async def clear(
    client: httpx.AsyncClient, admin: Persona, key: str, **body: object
) -> httpx.Response:
    return await client.post(
        f"/v1/platform/feature-flags/{key}/overrides:clear", headers=admin.headers, json=body
    )


async def test_blueprint_defaults_then_overrides_per_tenant(
    client: httpx.AsyncClient, super_admin: Persona, world: World, db: Database
) -> None:
    a, b = world.a, world.b
    # Phones 1.0.0 declares reviews: true, delivery: false.
    initial = await features(client, a.staff, a.slug)
    assert initial["reviews"] == (True, "blueprint")
    assert initial["delivery"] == (False, "blueprint")
    assert initial["ai"] == (False, "default")

    # Tenant-level: only A changes.
    assert (
        await put_override(
            client, super_admin, "ai", scope_type="tenant", tenant=a.slug, enabled=True
        )
    ).status_code == 204
    assert (await features(client, a.staff, a.slug))["ai"] == (True, "tenant")
    assert (await features(client, b.staff, b.slug))["ai"] == (False, "default")

    # Vertical-level reaches B (A's tenant override still wins for A).
    assert (
        await put_override(
            client, super_admin, "ai", scope_type="vertical", vertical=world.vertical, enabled=False
        )
    ).status_code == 204
    assert (await features(client, a.staff, a.slug))["ai"] == (True, "tenant")
    assert (await features(client, b.staff, b.slug))["ai"] == (False, "vertical")

    # Platform kill switch beats everything, then is lifted.
    assert (
        await put_override(
            client,
            super_admin,
            "reviews",
            scope_type="platform",
            enabled=False,
            enforced=True,
            reason="incident",
        )
    ).status_code == 204
    assert (await features(client, a.staff, a.slug))["reviews"] == (False, "platform_enforced")
    assert (await clear(client, super_admin, "reviews", scope_type="platform")).status_code == 204
    assert (await features(client, a.staff, a.slug))["reviews"] == (True, "blueprint")

    for body in (
        {"scope_type": "tenant", "tenant": a.slug},
        {"scope_type": "vertical", "vertical": world.vertical},
    ):
        assert (await clear(client, super_admin, "ai", **body)).status_code == 204

    rows = await audit_rows(db, action="feature_flag.override_set", resource_id="ai")
    assert any(str(r.tenant_id) == a.id for r in rows), "tenant override is in A's audit trail"


async def test_flag_management_is_platform_only_and_validated(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> None:
    owner = world.a.owner
    assert (
        await client.get("/v1/platform/feature-flags", headers=owner.headers)
    ).status_code == 403
    assert (
        await put_override(
            client, owner, "ai", scope_type="tenant", tenant=world.a.slug, enabled=True
        )
    ).status_code == 403
    listed = await client.get("/v1/platform/feature-flags", headers=super_admin.headers)
    assert {
        "ai",
        "delivery",
        "reviews",
        "coupons",
        "loyalty",
        "advertising",
        "advanced_analytics",
    } <= {f["key"] for f in listed.json()}
    # Enforcement is platform-only; targets must match the scope; unknown flags 404.
    assert (
        await put_override(
            client,
            super_admin,
            "ai",
            scope_type="tenant",
            tenant=world.a.slug,
            enabled=True,
            enforced=True,
        )
    ).status_code == 422
    assert (
        await put_override(client, super_admin, "ai", scope_type="tenant", enabled=True)
    ).status_code == 422
    assert (
        await put_override(client, super_admin, "nope", scope_type="platform", enabled=True)
    ).status_code == 404
