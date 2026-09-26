"""Gate 7: important administrative actions are auditable, completely and safely."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from arada.kernel.db import Database
from tests.support import DEFAULT_PASSWORD, Persona, audit_rows
from tests.world import World, seed

# action -> expected scope of the event
EXPECTED = {
    "rbac.super_admin_bootstrapped": "platform",
    "auth.login_succeeded": "platform",
    "mfa.totp_confirmed": "platform",
    "vertical.created": "platform",
    "blueprint.created": "platform",
    "blueprint.version_drafted": "platform",
    "blueprint.version_published": "platform",
    "tenant.created": "tenant",
    "tenant.invitation_created": "tenant",
    "identity.person_created": "either",  # platform (CLI/helpers) or tenant (invitation)
    "tenant.invitation_accepted": "tenant",
    "tenant.activated": "tenant",
}


async def test_administrative_actions_leave_complete_records(
    world: World, db: Database, super_admin: Persona
) -> None:
    rows = await audit_rows(db)
    by_action: dict[str, list[Any]] = {}
    for r in rows:
        by_action.setdefault(r.action, []).append(r)
    missing = sorted(set(EXPECTED) - by_action.keys())
    assert not missing, f"no audit record for: {missing}"

    for action, scope in EXPECTED.items():
        for r in by_action[action]:
            assert r.occurred_at is not None, action
            assert r.resource_type
            assert r.action == action
            assert r.source in {"api", "cli"}, action
            assert r.request_id, f"{action} is not correlated"
            assert r.trace_id, f"{action} is not correlated"
            if scope == "tenant":
                assert r.tenant_id is not None, f"{action} lost its tenant"
            if r.source == "api" and action != "identity.person_created":
                assert r.actor_person_id is not None, f"{action} has no actor"

    via_invitation = [r for r in by_action["identity.person_created"] if r.source == "api"]
    assert via_invitation
    assert all(r.tenant_id is not None for r in via_invitation), "self-registration lost its tenant"

    bootstrap = by_action["rbac.super_admin_bootstrapped"][0]
    assert bootstrap.source == "cli"
    created_a = [r for r in by_action["tenant.created"] if str(r.tenant_id) == world.a.id]
    assert created_a[0].actor_person_id == super_admin.person_id
    assert created_a[0].after["slug"] == world.a.slug


async def test_audit_never_contains_secrets(world: World, db: Database) -> None:
    dump = json.dumps([dict(r._mapping) for r in await audit_rows(db)], default=str)
    assert DEFAULT_PASSWORD not in dump
    assert not re.search(r"\$argon2", dump)
    for persona in (world.a.owner, world.a.admin, world.b.staff):
        assert persona.token is not None
        assert persona.token not in dump


async def test_failed_operations_leave_no_success_record(
    client: httpx.AsyncClient, super_admin: Persona, world: World, db: Database
) -> None:
    disguised = await client.post(
        f"/v1/platform/blueprints/{world.blueprint_id}/versions",
        headers=super_admin.headers,
        json={"version": "1.1.1", "definition": seed("2.0.0")},
    )
    assert disguised.status_code == 201
    refused = await client.post(
        f"/v1/platform/blueprints/{world.blueprint_id}/versions/{disguised.json()['id']}:publish",
        headers=super_admin.headers,
    )
    assert refused.status_code == 409
    assert (
        await audit_rows(
            db, action="blueprint.version_published", resource_id=disguised.json()["id"]
        )
        == []
    )


async def test_platform_audit_spans_tenants_for_platform_roles_only(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> None:
    for tenant in (world.a, world.b):
        page = await client.get(
            "/v1/platform/audit-events",
            headers=super_admin.headers,
            params={"tenant_id": tenant.id},
        )
        assert page.status_code == 200
        assert page.json()
        assert {e["tenant_id"] for e in page.json()} == {tenant.id}
    assert (
        await client.get("/v1/platform/audit-events", headers=world.a.owner.headers)
    ).status_code == 403
