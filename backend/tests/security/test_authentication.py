"""Authentication bypass: every protected operation refuses anonymous callers."""

from __future__ import annotations

import re

import httpx
import pytest
from fastapi import FastAPI

from arada.kernel.db import Database
from tests.support import Persona, api_operations, enrol_totp, login, make_person, unique
from tests.world import World

PUBLIC = {
    ("GET", "/healthz"),
    ("GET", "/readyz"),
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/invitations:accept"),
    ("GET", "/v1/storefront/merchant"),
}
DUMMY = {
    "tenant_slug": "shop-x",
    "blueprint_id": "01890000-0000-7000-8000-000000000001",
    "version_id": "01890000-0000-7000-8000-000000000002",
    "tenant_id": "01890000-0000-7000-8000-000000000003",
    "membership_id": "01890000-0000-7000-8000-000000000004",
    "invitation_id": "01890000-0000-7000-8000-000000000005",
    "key": "ai",
    "action": "publish",
}


def protected(app: FastAPI) -> list[tuple[str, str]]:
    ops = [op for op in api_operations(app) if op not in PUBLIC]
    assert len(ops) >= 30, f"suspiciously few protected operations: {len(ops)}"
    return ops


def fill(path: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: DUMMY[m.group(1)], path)


async def test_public_surface_is_exactly_what_we_intend(app: FastAPI) -> None:
    public = {op for op in api_operations(app) if op in PUBLIC}
    assert public == PUBLIC


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Bearer",
        "Bearer short",
        "Basic dXNlcjpwYXNz",
        "Bearer " + "A" * 43,  # well-formed but unknown token
        "Bearer " + "A" * 500,  # oversized
        "bearer\t" + "A" * 43,
    ],
)
async def test_every_protected_operation_rejects_missing_or_bad_tokens(
    client: httpx.AsyncClient, app: FastAPI, authorization: str | None
) -> None:
    headers = {"authorization": authorization} if authorization is not None else {}
    for method, path in protected(app):
        response = await client.request(method, fill(path), headers=headers, json={})
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        assert response.headers["content-type"] == "application/problem+json"


async def test_tokens_are_not_accepted_from_query_strings(
    client: httpx.AsyncClient, world: World
) -> None:
    token = world.a.owner.token
    response = await client.get("/v1/me", params={"access_token": token, "token": token})
    assert response.status_code == 401


async def test_revoked_session_cannot_be_reused(client: httpx.AsyncClient, world: World) -> None:
    persona = world.b.staff
    old = persona.token
    await login(client, persona)  # fresh session for the rest of the suite
    fresh = persona.token
    assert old != fresh
    persona.token = old
    assert (await client.post("/v1/auth/logout", headers=persona.headers)).status_code == 204
    assert (await client.get("/v1/me", headers=persona.headers)).status_code == 401
    persona.token = fresh
    assert (await client.get("/v1/me", headers=persona.headers)).status_code == 200


async def test_pre_mfa_token_never_gains_privileged_access(
    client: httpx.AsyncClient, super_admin: Persona, db: Database
) -> None:
    """Session fixation / upgrade-in-place: the token that existed before MFA
    was proven must not become a privileged token afterwards."""
    mo = await make_person(db)
    granted = await client.post(
        "/v1/platform/role-grants",
        headers=super_admin.headers,
        json={"person_id": str(mo.person_id), "role": "SUPER_ADMIN"},
    )
    assert granted.status_code == 204
    pre_mfa = {"Authorization": f"Bearer {await login(client, mo)}"}
    body = {"key": unique("v_"), "name_en": "Fixation"}
    denied = await client.post("/v1/platform/verticals", headers=pre_mfa, json=body)
    assert denied.status_code == 403
    assert denied.json()["type"] == "urn:arada:problem:mfa-required-for-scope"

    await enrol_totp(client, mo)

    for method, path, payload in (
        ("POST", "/v1/platform/verticals", body),
        ("GET", "/v1/platform/verticals", None),
        ("GET", "/v1/me", None),
    ):
        stale = await client.request(method, path, headers=pre_mfa, json=payload)
        assert stale.status_code == 401, f"{method} {path} with the pre-MFA token"
    fresh = await client.post("/v1/platform/verticals", headers=mo.headers, json=body)
    assert fresh.status_code == 201
    # Clean up the extra SUPER_ADMIN (others remain, so the guard allows it).
    revoked = await client.post(
        "/v1/platform/role-grants:revoke",
        headers=super_admin.headers,
        json={"person_id": str(mo.person_id), "role": "SUPER_ADMIN"},
    )
    assert revoked.status_code == 204
