"""Telegram Mini App authentication: the negative suite (Phase 2, owner's list 1-18).

Every failed login must produce the *same* 401 problem document, whatever the
cause, and the cause must reach the logs only as a reason code. Customer and
staff credentials must never be usable as each other, and a customer session
must be useless at any host but its own tenant's.
"""

from __future__ import annotations

import ast
import asyncio
import io
import json
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from arada.kernel.config import Settings
from arada.kernel.logging import configure_logging
from arada.main import create_app
from tests.storefront import Customer, Storefront, new_customer, open_storefront, telegram_login
from tests.support import Persona, api_operations
from tests.telegram_kit import Signer, encode, fake_bot, hmac_hex, login_widget_hash
from tests.world import World, build_tenant

SRC = Path(__file__).resolve().parents[2] / "src" / "arada"
GENERIC = {
    "type": "urn:arada:problem:telegram-auth-failed",
    "title": "Telegram authentication failed",
    "status": 401,
}


def assert_generic_401(response: httpx.Response) -> None:
    assert response.status_code == 401, response.text
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert set(body) == {"type", "title", "status", "instance", "request_id"}, body
    assert {k: body[k] for k in GENERIC} == GENERIC


@pytest.fixture
def logs(settings: Settings) -> Iterator[io.StringIO]:
    """Everything the application logs, through the real redacting pipeline."""
    buffer = io.StringIO()
    configure_logging("DEBUG", "json", stream=buffer)
    yield buffer
    configure_logging(settings.log_level, settings.log_format)


def reasons(buffer: io.StringIO) -> list[str]:
    found = []
    for line in buffer.getvalue().splitlines():
        record = json.loads(line)
        if record.get("event") == "telegram.auth_failed":
            found.append(record["reason"])
    return found


# ------------------------------------------------------------- 1-11: bad initData
async def test_every_rejection_is_the_same_generic_401_with_a_logged_reason(
    client: httpx.AsyncClient,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
    logs: io.StringIO,
) -> None:
    sf, other = storefronts
    now = int(time.time())

    def signed(**kwargs: Any) -> dict[str, str]:
        return telegram_signer.fields(bot_id=sf.bot_id, bot_token=sf.bot_token, **kwargs)

    forged = signed()  # 1. forged: valid HMAC (attacker holds the token), wrong signer
    forged["signature"] = Signer().signature(forged, sf.bot_id)
    forged["hash"] = hmac_hex(forged, sf.bot_token)
    bad_hmac = signed()  # 3. invalid HMAC
    bad_hmac["hash"] = "0" * 64
    bad_signature = signed()  # 4. invalid Ed25519 (well-formed, wrong bytes)
    bad_signature["signature"] = "A" * 86
    bad_signature["hash"] = hmac_hex(bad_signature, sf.bot_token)
    missing_signature = signed()  # 10. missing required field
    del missing_signature["signature"]
    widget = {"id": "7", "first_name": "A", "auth_date": str(now)}  # 11. Login Widget
    widget["hash"] = login_widget_hash(widget, sf.bot_token)

    cases: list[tuple[str, str, str]] = [
        ("forged", encode(forged), "bad_signature"),
        ("malformed", "user=%zz&hash=1", "malformed"),  # 2.
        ("invalid HMAC", encode(bad_hmac), "bad_hash"),
        ("invalid Ed25519", encode(bad_signature), "bad_signature"),
        ("expired", encode(signed(auth_date=now - 7200)), "stale"),  # 5.
        ("future", encode(signed(auth_date=now + 3600)), "future"),
        ("missing signature", encode(missing_signature), "malformed"),
        ("login widget", encode(widget), "malformed"),
        ("oidc id_token", "eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJ4In0.c2ln", "malformed"),
        ("empty (keyboard launch)", "", "malformed"),
        # 7. cross-tenant: tenant B's genuine initData presented at tenant A's host.
        ("cross-tenant", other.init_data(telegram_signer), "bad_hash"),
    ]
    for label, raw, _ in cases:
        response = await telegram_login(client, sf.host, raw)
        assert_generic_401(response)
        assert response.json()["type"] == GENERIC["type"], label
    assert reasons(logs) == [reason for _, _, reason in cases]


async def test_replayed_init_data_is_refused_after_the_use_cap(
    client: httpx.AsyncClient,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
    settings: Settings,
    logs: io.StringIO,
) -> None:
    """6. Replay: concurrent reuse of one initData never exceeds the cap."""
    sf, _ = storefronts
    raw = sf.init_data(telegram_signer)
    cap = settings.telegram_init_data_max_uses
    results = await asyncio.gather(*(telegram_login(client, sf.host, raw) for _ in range(cap + 10)))
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200] * cap + [401] * 10
    for response in results:
        if response.status_code == 401:
            assert_generic_401(response)
    assert reasons(logs) == ["replayed"] * 10


async def test_wrong_registered_bot_id_fails_closed(
    client: httpx.AsyncClient, super_admin: Persona, world: World, telegram_signer: Signer
) -> None:
    """8. The admin typed the wrong bot id: no login can succeed, none is forged."""
    tenant = await build_tenant(client, super_admin, world.vertical, world.versions["1.0.0"], "w-")
    sf = await open_storefront(client, super_admin, tenant.id, tenant.slug)
    real_bot_id = sf.bot_id
    rebound = await client.put(
        f"/v1/platform/tenants/{tenant.id}/telegram-bot",
        headers=super_admin.headers,
        json={"bot_id": real_bot_id + 1, "bot_token": sf.bot_token},
    )
    assert rebound.status_code == 200
    # Telegram signs for the real bot id; the tenant is registered with another.
    genuine = telegram_signer.init_data(bot_id=real_bot_id, bot_token=sf.bot_token)
    assert_generic_401(await telegram_login(client, sf.host, genuine))


async def test_signature_from_the_other_telegram_environment_is_refused(
    client: httpx.AsyncClient, storefronts: tuple[Storefront, Storefront], logs: io.StringIO
) -> None:
    """9. Data signed under another environment's key (another Signer) fails."""
    sf, _ = storefronts
    other_environment = Signer()
    raw = sf.init_data(other_environment)
    assert_generic_401(await telegram_login(client, sf.host, raw))
    assert reasons(logs) == ["bad_signature"]


def test_production_refuses_the_test_key_and_any_mismatch(settings: Settings) -> None:
    """9. Environment separation is enforced at startup, not by convention."""
    test_key = "40055058a4ee38156a06562e52eece92a771bcd8346a8c4615cb7376eddf72ec"
    production_key = "e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d"
    base = {
        **settings.model_dump(),
        "environment": "production",
        "expose_api_docs": False,
        "root_domain": "example.test",
        "log_format": "json",
    }
    refused: list[dict[str, Any]] = [
        {"telegram_environment": "production", "telegram_public_key_hex": test_key},
        {"telegram_environment": "test", "telegram_public_key_hex": test_key},
        {"telegram_environment": "production", "telegram_public_key_hex": None},
        {"telegram_environment": "production", "telegram_public_key_hex": Signer().public_hex},
    ]
    for overrides in refused:
        with pytest.raises(ValueError):
            Settings(**{**base, **overrides})
    Settings(
        **{**base, "telegram_environment": "production", "telegram_public_key_hex": production_key}
    )
    # Outside production a known key must still match its environment.
    with pytest.raises(ValueError):
        Settings(**{**settings.model_dump(), "telegram_public_key_hex": production_key})


def test_staging_accepts_only_telegrams_published_keys(settings: Settings) -> None:
    """9. Only development and automated tests may use a throwaway key (there is
    no Telegram private key to sign test vectors with). Staging, like
    production, must use a key Telegram publishes, matching its environment."""
    test_key = "40055058a4ee38156a06562e52eece92a771bcd8346a8c4615cb7376eddf72ec"
    production_key = "e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d"
    base = {**settings.model_dump(), "environment": "staging"}
    for overrides in (
        {"telegram_environment": "test", "telegram_public_key_hex": Signer().public_hex},
        {"telegram_environment": "production", "telegram_public_key_hex": test_key},
    ):
        with pytest.raises(ValueError, match="telegram"):
            Settings(**{**base, **overrides})
    Settings(**{**base, "telegram_environment": "test", "telegram_public_key_hex": test_key})
    Settings(
        **{**base, "telegram_environment": "production", "telegram_public_key_hex": production_key}
    )
    Settings(**{**base, "telegram_public_key_hex": None})  # unconfigured: logins fail closed


async def test_unknown_host_and_unbound_tenant(
    client: httpx.AsyncClient,
    super_admin: Persona,
    world: World,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
    logs: io.StringIO,
) -> None:
    sf, _ = storefronts
    raw = sf.init_data(telegram_signer)
    unknown = await telegram_login(client, "nobody.localhost", raw)
    assert unknown.status_code == 404
    # A tenant with a host but no bot: the generic 401.
    tenant = await build_tenant(client, super_admin, world.vertical, world.versions["1.0.0"], "n-")
    host = f"nobot-{tenant.slug}.localhost"
    added = await client.post(
        f"/v1/platform/tenants/{tenant.id}/domains",
        headers=super_admin.headers,
        json={"hostname": host},
    )
    assert added.status_code == 201
    assert_generic_401(await telegram_login(client, host, raw))
    assert reasons(logs) == ["no_bot"]


async def test_client_supplied_tenant_hints_never_choose_the_tenant(
    client: httpx.AsyncClient,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
) -> None:
    a, b = storefronts
    # B's genuine data plus every hint pointing at B, sent to A's host: refused.
    response = await client.post(
        "/v1/storefront/auth/telegram",
        headers={"Host": a.host, "X-Tenant-ID": b.tenant_id, "X-Forwarded-Host": b.host},
        params={"tenant_id": b.tenant_id, "tenant": b.slug},
        json={"init_data": b.init_data(telegram_signer)},
    )
    assert_generic_401(response)
    # A tenant field in the body is rejected outright (mass assignment).
    smuggled = await telegram_login(
        client, a.host, a.init_data(telegram_signer), tenant_id=b.tenant_id
    )
    assert smuggled.status_code == 422
    # With hints for B but A's own data at A's host, the session is A's.
    customer = await new_customer(client, a, telegram_signer)
    me = await client.get(
        "/v1/storefront/me", headers={**customer.headers, "X-Tenant-ID": b.tenant_id}
    )
    assert me.status_code == 200
    assert me.json()["tenant_slug"] == a.slug


# ------------------------------------------- 12-15: sessions and credential types
async def test_customer_routes_refuse_missing_bad_and_foreign_tokens(
    client: httpx.AsyncClient,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
    world: World,
) -> None:
    """12, 14, 15."""
    a, b = storefronts
    customer = await new_customer(client, a, telegram_signer)
    attempts = {
        "no token": {"Host": a.host},
        "bad token": {"Host": a.host, "Authorization": "Bearer " + "x" * 43},
        "staff owner token": {"Host": a.host, **world.a.owner.headers},  # 14.
        "staff admin token": {"Host": a.host, **world.a.admin.headers},
        "A's token at B": {**customer.headers, "Host": b.host},  # 15.
        "A's token at unknown host": {**customer.headers, "Host": "nobody.localhost"},
    }
    for label, headers in attempts.items():
        for method, path in (("GET", "/v1/storefront/me"), ("POST", "/v1/storefront/auth/logout")):
            response = await client.request(method, path, headers=headers)
            assert response.status_code == 401, (label, path, response.status_code)
    # Still valid at its own host: the foreign attempts revoked nothing.
    assert (await client.get("/v1/storefront/me", headers=customer.headers)).status_code == 200


async def test_customer_tokens_are_refused_by_every_staff_operation(
    client: httpx.AsyncClient,
    app: FastAPI,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
) -> None:
    """13. OpenAPI-driven: every non-storefront operation, with a live customer token."""
    a, _ = storefronts
    customer = await new_customer(client, a, telegram_signer)
    values = {
        "tenant_slug": a.slug,
        "tenant_id": a.tenant_id,
        "blueprint_id": "01890000-0000-7000-8000-000000000001",
        "version_id": "01890000-0000-7000-8000-000000000002",
        "membership_id": "01890000-0000-7000-8000-000000000004",
        "invitation_id": "01890000-0000-7000-8000-000000000005",
        "key": "ai",
        "action": "publish",
    }
    public = {
        ("GET", "/healthz"),
        ("GET", "/readyz"),
        ("POST", "/v1/auth/login"),
        ("POST", "/v1/invitations:accept"),
        ("GET", "/v1/storefront/merchant"),
        ("POST", "/v1/storefront/auth/telegram"),
    }
    staff_operations = [
        (m, p)
        for m, p in api_operations(app)
        if (m, p) not in public and not p.startswith("/v1/storefront/")
    ]
    assert len(staff_operations) >= 30
    for method, path in staff_operations:
        url = re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], path)
        for host in (a.host, "testserver"):
            headers = {"Authorization": f"Bearer {customer.token}", "Host": host}
            response = await client.request(method, url, headers=headers, json={})
            assert response.status_code == 401, f"{method} {url} @ {host} -> {response.status_code}"
    assert (await client.get("/v1/storefront/me", headers=customer.headers)).status_code == 200


async def test_customer_authentication_grants_no_business_permission(
    client: httpx.AsyncClient,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
) -> None:
    """8 (owner's architecture rule): a customer session only proves identity."""
    a, _ = storefronts
    customer = await new_customer(client, a, telegram_signer)
    for path in (f"/v1/t/{a.slug}", f"/v1/t/{a.slug}/staff", "/v1/me", "/v1/me/tenants"):
        response = await client.get(path, headers=customer.headers)
        assert response.status_code == 401, path


# ----------------------------------------------- 16-18: logs and initDataUnsafe
async def test_raw_init_data_bot_tokens_and_personal_data_never_reach_the_logs(
    client: httpx.AsyncClient,
    super_admin: Persona,
    world: World,
    telegram_signer: Signer,
    logs: io.StringIO,
) -> None:
    """16, 17."""
    tenant = await build_tenant(client, super_admin, world.vertical, world.versions["1.0.0"], "l-")
    sf = await open_storefront(client, super_admin, tenant.id, tenant.slug)  # PUT with token
    user = {"id": 5550001234, "first_name": "Selamawit", "last_name": "Tesfaye"}
    fields = telegram_signer.fields(bot_id=sf.bot_id, bot_token=sf.bot_token, user=user)
    raw = encode(fields)
    ok = await telegram_login(client, sf.host, raw)
    assert ok.status_code == 200
    tampered = dict(fields, auth_date=str(int(time.time()) - 5))
    assert_generic_401(await telegram_login(client, sf.host, encode(tampered)))
    status = await client.get(
        f"/v1/platform/tenants/{tenant.id}/telegram-bot", headers=super_admin.headers
    )
    assert status.status_code == 200

    text = logs.getvalue()
    assert "telegram.auth_succeeded" in text
    assert "telegram.auth_failed" in text
    secret_secret = sf.bot_token.split(":", 1)[1]
    for needle in (
        raw,
        fields["hash"],
        fields["signature"],
        fields["query_id"],
        sf.bot_token,
        secret_secret,
        "Selamawit",
        "Tesfaye",
        "5550001234",
        ok.json()["access_token"],
    ):
        assert needle not in text, f"leaked into logs: {needle[:12]}…"
    # ...nor into any response the platform admin sees.
    assert sf.bot_token not in status.text
    assert secret_secret not in status.text


async def test_bot_token_is_never_returned_or_audited(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> None:
    """17. Responses and the audit trail carry the bot id, never the token."""
    tenant = await build_tenant(client, super_admin, world.vertical, world.versions["1.0.0"], "t-")
    bot_id, token = fake_bot()
    put = await client.put(
        f"/v1/platform/tenants/{tenant.id}/telegram-bot",
        headers=super_admin.headers,
        json={"bot_id": bot_id, "bot_token": token},
    )
    assert put.status_code == 200
    assert set(put.json()) == {"tenant_id", "bot_id", "status", "registered_at"}
    events = await client.get(
        "/v1/platform/audit-events",
        headers=super_admin.headers,
        params={"tenant_id": tenant.id, "action": "telegram.bot_registered"},
    )
    assert events.status_code == 200
    assert len(events.json()) == 1
    for text in (put.text, events.text):
        assert token not in text
        assert token.split(":", 1)[1] not in text
    assert events.json()[0]["after"]["telegram_bot_id"] == bot_id


def _code_mentions(tree: ast.AST) -> Iterator[str]:
    """Every identifier, attribute, argument and non-docstring string in a module."""
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, ast.arg | ast.keyword):
            yield node.arg or ""
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            yield node.value


def test_init_data_unsafe_is_never_used_by_server_code() -> None:
    """18 / AUTH-4: no server code reads, names or accepts ``initDataUnsafe``.

    AST-based, so it sees identifiers, attributes, parameters, keyword
    arguments, dictionary keys and string literals, but not the docstrings
    that document the rule.
    """
    pattern = re.compile(r"init_?data_?unsafe", re.IGNORECASE)
    checked = 0
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        checked += 1
        for mention in _code_mentions(ast.parse(path.read_text(), filename=str(path))):
            if pattern.search(mention):
                offenders.append(f"{path.relative_to(SRC)}: {mention!r}")
    assert checked > 50
    assert offenders == []
    # The check is not vacuous: it finds a planted use.
    planted = ast.parse(
        'def f(d):\n    """initDataUnsafe is documented."""\n    return d["initDataUnsafe"]'
    )
    assert [m for m in _code_mentions(planted) if pattern.search(m)] == ["initDataUnsafe"]


def test_login_body_accepts_only_the_raw_init_data_string(app: FastAPI) -> None:
    """The endpoint's schema has one field: the raw string. No parsed user object."""
    schema = app.openapi()["components"]["schemas"]["TelegramAuthIn"]
    assert set(schema["properties"]) == {"init_data"}
    assert schema["properties"]["init_data"]["type"] == "string"
    assert schema.get("additionalProperties") is False


async def test_a_logged_out_session_is_dead_everywhere(
    client: httpx.AsyncClient, storefronts: tuple[Storefront, Storefront], telegram_signer: Signer
) -> None:
    a, _ = storefronts
    customer: Customer = await new_customer(client, a, telegram_signer)
    second: Customer = await new_customer(client, a, telegram_signer)
    assert (
        await client.post("/v1/storefront/auth/logout", headers=customer.headers)
    ).status_code == 204
    assert (await client.get("/v1/storefront/me", headers=customer.headers)).status_code == 401
    assert (
        await client.post("/v1/storefront/auth/logout", headers=customer.headers)
    ).status_code == 401
    assert (await client.get("/v1/storefront/me", headers=second.headers)).status_code == 200


async def test_without_a_configured_key_every_login_fails_closed(
    settings: Settings,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
    logs: io.StringIO,
) -> None:
    unconfigured = Settings(**{**settings.model_dump(), "telegram_public_key_hex": None})
    application = create_app(unconfigured)
    configure_logging("DEBUG", "json", stream=logs)  # create_app reconfigures logging
    sf, _ = storefronts
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            assert_generic_401(await telegram_login(c, sf.host, sf.init_data(telegram_signer)))
    assert reasons(logs) == ["not_configured"]
