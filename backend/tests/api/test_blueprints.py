"""Gate 6: blueprint/version foundation through the API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import yaml

from arada.kernel.db import Database
from tests.support import Persona, audit_rows, enrol_totp, login, make_person, unique

SEEDS = Path(__file__).resolve().parents[3] / "blueprints" / "phones"


def seed(version: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((SEEDS / f"{version}.yaml").read_text())
    return data


async def make_blueprint(client: httpx.AsyncClient, admin: Persona) -> tuple[str, str]:
    vertical = unique("phones_")
    r = await client.post(
        "/v1/platform/verticals", headers=admin.headers, json={"key": vertical, "name_en": "Phones"}
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/v1/platform/blueprints",
        headers=admin.headers,
        json={"vertical": vertical, "key": "retail", "name_en": "Retail phones"},
    )
    assert r.status_code == 201, r.text
    return vertical, r.json()["id"]


async def draft(
    client: httpx.AsyncClient,
    admin: Persona,
    blueprint_id: str,
    version: str,
    definition: dict[str, Any],
) -> httpx.Response:
    return await client.post(
        f"/v1/platform/blueprints/{blueprint_id}/versions",
        headers=admin.headers,
        json={"version": version, "definition": definition},
    )


async def publish(
    client: httpx.AsyncClient, admin: Persona, blueprint_id: str, version_id: str
) -> httpx.Response:
    return await client.post(
        f"/v1/platform/blueprints/{blueprint_id}/versions/{version_id}:publish",
        headers=admin.headers,
    )


async def test_versioned_blueprint_lifecycle(
    client: httpx.AsyncClient, super_admin: Persona, db: Database
) -> None:
    _, bp = await make_blueprint(client, super_admin)

    v1 = await draft(client, super_admin, bp, "1.0.0", seed("1.0.0"))
    assert v1.status_code == 201
    assert v1.json()["status"] == "draft"
    p1 = await publish(client, super_admin, bp, v1.json()["id"])
    assert p1.status_code == 200, p1.text
    assert p1.json()["change_level"] == "initial"
    assert len(p1.json()["content_hash"]) == 64

    v11 = await draft(client, super_admin, bp, "1.1.0", seed("1.1.0"))
    assert (await publish(client, super_admin, bp, v11.json()["id"])).json()[
        "change_level"
    ] == "minor"

    # A breaking change disguised as a minor bump is refused...
    disguised = await draft(client, super_admin, bp, "1.2.0", seed("2.0.0"))
    refused = await publish(client, super_admin, bp, disguised.json()["id"])
    assert refused.status_code == 409
    assert "major change" in refused.json()["detail"]
    # ...and accepted when declared honestly.
    v2 = await draft(client, super_admin, bp, "2.0.0", seed("2.0.0"))
    assert (await publish(client, super_admin, bp, v2.json()["id"])).json()[
        "change_level"
    ] == "major"

    versions = await client.get(
        f"/v1/platform/blueprints/{bp}/versions", headers=super_admin.headers
    )
    listed = {(v["version"], v["status"]) for v in versions.json()}
    assert {
        ("1.0.0", "published"),
        ("1.1.0", "published"),
        ("2.0.0", "published"),
        ("1.2.0", "draft"),
    } <= listed

    published = await audit_rows(
        db, action="blueprint.version_published", resource_id=v2.json()["id"]
    )
    assert published[0].after["change_level"] == "major"
    assert published[0].after["changes"]


async def test_version_rules(client: httpx.AsyncClient, super_admin: Persona) -> None:
    _, bp = await make_blueprint(client, super_admin)
    v1 = await draft(client, super_admin, bp, "1.0.0", seed("1.0.0"))
    await publish(client, super_admin, bp, v1.json()["id"])
    # Not greater than the published version.
    assert (await draft(client, super_admin, bp, "0.9.0", seed("1.0.0"))).status_code == 422
    # Same content as the published version.
    same = await draft(client, super_admin, bp, "1.0.1", seed("1.0.0"))
    assert (await publish(client, super_admin, bp, same.json()["id"])).status_code == 409
    # Invalid definitions never become drafts.
    bad = await draft(client, super_admin, bp, "1.1.0", {"schema_version": 1, "entities": {}})
    assert bad.status_code == 422
    assert bad.json()["errors"]
    # Publishing twice / editing a published version.
    assert (await publish(client, super_admin, bp, v1.json()["id"])).status_code == 409
    edit = await client.put(
        f"/v1/platform/blueprints/{bp}/versions/{v1.json()['id']}/definition",
        headers={**super_admin.headers, "If-Match": '"1"'},
        json={"definition": seed("1.1.0")},
    )
    assert edit.status_code == 409


async def test_draft_updates_use_optimistic_concurrency(
    client: httpx.AsyncClient, super_admin: Persona
) -> None:
    _, bp = await make_blueprint(client, super_admin)
    created = await draft(client, super_admin, bp, "1.0.0", seed("1.0.0"))
    url = f"/v1/platform/blueprints/{bp}/versions/{created.json()['id']}/definition"
    body = {"definition": seed("1.1.0")}
    assert (await client.put(url, headers=super_admin.headers, json=body)).status_code == 428
    ok = await client.put(
        url, headers={**super_admin.headers, "If-Match": created.headers["etag"]}, json=body
    )
    assert ok.status_code == 200
    assert ok.headers["etag"] == '"2"'
    stale = await client.put(url, headers={**super_admin.headers, "If-Match": '"1"'}, json=body)
    assert stale.status_code == 412


async def test_vertical_admins_are_confined_to_their_vertical(
    client: httpx.AsyncClient, super_admin: Persona, db: Database
) -> None:
    mine, bp_mine = await make_blueprint(client, super_admin)
    _, bp_other = await make_blueprint(client, super_admin)
    admin = await make_person(db)
    r = await client.post(
        "/v1/platform/role-grants",
        headers=super_admin.headers,
        json={"person_id": str(admin.person_id), "role": "VERTICAL_ADMIN", "vertical": mine},
    )
    assert r.status_code == 204
    await login(client, admin)
    await enrol_totp(client, admin)

    created = await draft(client, admin, bp_mine, "1.0.0", seed("1.0.0"))
    assert created.status_code == 201
    assert (await publish(client, admin, bp_mine, created.json()["id"])).status_code == 200
    # The other vertical's blueprint does not exist as far as they can tell.
    assert (await draft(client, admin, bp_other, "1.0.0", seed("1.0.0"))).status_code == 404
    assert (
        await client.get(f"/v1/platform/blueprints/{bp_other}/versions", headers=admin.headers)
    ).status_code == 404
    visible = {
        b["id"] for b in (await client.get("/v1/platform/blueprints", headers=admin.headers)).json()
    }
    assert bp_mine in visible
    assert bp_other not in visible


async def test_ordinary_person_cannot_touch_blueprints(
    client: httpx.AsyncClient, super_admin: Persona, db: Database
) -> None:
    _, bp = await make_blueprint(client, super_admin)
    nobody = await make_person(db)
    await login(client, nobody)
    assert (await client.get("/v1/platform/blueprints", headers=nobody.headers)).status_code == 403
    assert (await draft(client, nobody, bp, "1.0.0", seed("1.0.0"))).status_code == 404
