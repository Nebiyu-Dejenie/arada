"""A two-merchant world built only through the public API.

Super Admin -> vertical -> Phones blueprint (1.0.0, 1.1.0) -> tenants A and B.
Each tenant's owner joins through the owner invitation (self-registration),
then invites an Admin and a Staff member who register the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from tests.support import DEFAULT_PASSWORD, Persona, login, unique

SEEDS = Path(__file__).resolve().parents[2] / "blueprints" / "phones"


def seed(version: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((SEEDS / f"{version}.yaml").read_text())
    return data


@dataclass
class TenantWorld:
    id: str
    slug: str
    owner: Persona
    admin: Persona
    staff: Persona
    memberships: dict[str, str] = field(default_factory=dict)  # persona username -> membership id


@dataclass
class World:
    vertical: str
    blueprint_id: str
    versions: dict[str, str]
    a: TenantWorld
    b: TenantWorld


async def _ok(response: httpx.Response, status: int = 200) -> Any:
    assert response.status_code == status, (
        f"{response.request.method} {response.request.url}: {response.text}"
    )
    return response.json() if response.content else None


async def accept_as_new(client: httpx.AsyncClient, token: str) -> Persona:
    username = unique("u")
    body = {
        "token": token,
        "new_account": {
            "username": username,
            "password": DEFAULT_PASSWORD,
            "display_name": username.title(),
        },
    }
    membership = await _ok(await client.post("/v1/invitations:accept", json=body))
    persona = Persona(
        person_id=membership["membership_id"], username=username, password=DEFAULT_PASSWORD
    )
    await login(client, persona)
    me = await _ok(await client.get("/v1/me", headers=persona.headers))
    persona.person_id = me["person_id"]
    return persona


async def invite(client: httpx.AsyncClient, inviter: Persona, slug: str, roles: list[str]) -> str:
    created = await _ok(
        await client.post(
            f"/v1/t/{slug}/invitations", headers=inviter.headers, json={"roles": roles}
        ),
        201,
    )
    token: str = created["token"]
    return token


async def create_tenant(
    client: httpx.AsyncClient, root: Persona, vertical: str, version_id: str, prefix: str
) -> tuple[str, str, str]:
    slug = unique(prefix)
    created = await _ok(
        await client.post(
            "/v1/platform/tenants",
            headers=root.headers,
            json={
                "slug": slug,
                "display_name": f"{prefix.upper()} Phones",
                "vertical": vertical,
                "blueprint_version_id": version_id,
            },
        ),
        201,
    )
    return created["tenant"]["id"], slug, created["owner_invitation"]["token"]


async def build_tenant(
    client: httpx.AsyncClient, root: Persona, vertical: str, version_id: str, prefix: str
) -> TenantWorld:
    tenant_id, slug, owner_token = await create_tenant(client, root, vertical, version_id, prefix)
    owner = await accept_as_new(client, owner_token)
    admin = await accept_as_new(client, await invite(client, owner, slug, ["TENANT_ADMIN"]))
    staff = await accept_as_new(client, await invite(client, admin, slug, ["TENANT_STAFF"]))
    await _ok(await client.post(f"/v1/platform/tenants/{tenant_id}:activate", headers=root.headers))
    world = TenantWorld(id=tenant_id, slug=slug, owner=owner, admin=admin, staff=staff)
    for member in await _ok(await client.get(f"/v1/t/{slug}/staff", headers=owner.headers)):
        world.memberships[member["username"]] = member["membership_id"]
    return world


async def build_world(client: httpx.AsyncClient, root: Persona) -> World:
    vertical = unique("phones_")
    await _ok(
        await client.post(
            "/v1/platform/verticals",
            headers=root.headers,
            json={"key": vertical, "name_en": "Phones"},
        ),
        201,
    )
    bp = await _ok(
        await client.post(
            "/v1/platform/blueprints",
            headers=root.headers,
            json={"vertical": vertical, "key": "retail", "name_en": "Retail phones"},
        ),
        201,
    )
    versions: dict[str, str] = {}
    for version in ("1.0.0", "1.1.0"):
        draft = await _ok(
            await client.post(
                f"/v1/platform/blueprints/{bp['id']}/versions",
                headers=root.headers,
                json={"version": version, "definition": seed(version)},
            ),
            201,
        )
        await _ok(
            await client.post(
                f"/v1/platform/blueprints/{bp['id']}/versions/{draft['id']}:publish",
                headers=root.headers,
            )
        )
        versions[version] = draft["id"]
    a = await build_tenant(client, root, vertical, versions["1.0.0"], "shop-a-")
    b = await build_tenant(client, root, vertical, versions["1.0.0"], "shop-b-")
    return World(vertical=vertical, blueprint_id=bp["id"], versions=versions, a=a, b=b)
