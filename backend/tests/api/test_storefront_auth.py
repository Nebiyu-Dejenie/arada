"""Customer login with Telegram: identity mapping, sessions, bots, audit (Phase 2)."""

from __future__ import annotations

import asyncio
import secrets
import uuid
from collections.abc import AsyncIterator

import asyncpg
import httpx
import pytest

from arada.kernel.db import Database
from tests.conftest import PgEnv
from tests.storefront import Storefront, new_customer, open_storefront, telegram_login
from tests.support import Persona, audit_rows, enrol_totp, login, make_person
from tests.telegram_kit import Signer, fake_bot
from tests.world import TenantWorld, World, build_tenant


@pytest.fixture
async def superuser(pg_env: PgEnv, test_database: str) -> AsyncIterator[asyncpg.Connection]:
    """Test-only inspection and time travel (expiry); never how the app connects."""
    conn = await asyncpg.connect(pg_env.superuser_dsn(test_database))
    yield conn
    await conn.close()


async def fresh(
    client: httpx.AsyncClient, root: Persona, world: World, prefix: str
) -> tuple[TenantWorld, Storefront]:
    tenant = await build_tenant(client, root, world.vertical, world.versions["1.0.0"], prefix)
    return tenant, await open_storefront(client, root, tenant.id, tenant.slug)


def telegram_user(name: str = "Abebe", last: str | None = None) -> dict[str, object]:
    user: dict[str, object] = {"id": secrets.randbelow(10**12) + 1, "first_name": name}
    if last is not None:
        user["last_name"] = last
    return user


async def test_login_creates_a_customer_and_a_session_bound_to_the_host(
    client: httpx.AsyncClient, storefronts: tuple[Storefront, Storefront], telegram_signer: Signer
) -> None:
    a, _ = storefronts
    user = telegram_user("አበበ", "በቀለ")
    response = await telegram_login(client, a.host, a.init_data(telegram_signer, user=user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"access_token", "expires_at"}
    me = await client.get(
        "/v1/storefront/me",
        headers={"Host": a.host, "Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["tenant_slug"] == a.slug
    assert me.json()["display_name"] == "አበበ በቀለ"
    assert set(me.json()) == {"customer_id", "tenant_slug", "display_name", "first_seen_at"}


async def test_returning_user_keeps_one_customer_and_gets_a_new_session(
    client: httpx.AsyncClient, storefronts: tuple[Storefront, Storefront], telegram_signer: Signer
) -> None:
    a, _ = storefronts
    user = telegram_user()
    first = await new_customer(client, a, telegram_signer, user=user)
    second = await new_customer(client, a, telegram_signer, user=user)
    assert first.token != second.token
    ids = [
        (await client.get("/v1/storefront/me", headers=c.headers)).json()["customer_id"]
        for c in (first, second)
    ]
    assert ids[0] == ids[1]


async def test_one_person_two_merchants_two_unlinked_customers(
    client: httpx.AsyncClient,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
    superuser: asyncpg.Connection,
) -> None:
    a, b = storefronts
    user = telegram_user("Hana")
    at_a = await new_customer(client, a, telegram_signer, user=user)
    at_b = await new_customer(client, b, telegram_signer, user=user)
    id_a = (await client.get("/v1/storefront/me", headers=at_a.headers)).json()["customer_id"]
    id_b = (await client.get("/v1/storefront/me", headers=at_b.headers)).json()["customer_id"]
    assert id_a != id_b
    rows = await superuser.fetch(
        "SELECT c.tenant_id, c.person_id FROM commerce.customers c "
        "JOIN control.identities i ON i.person_id = c.person_id "
        "WHERE i.provider = 'telegram' AND i.subject = $1",
        str(user["id"]),
    )
    assert {str(r["tenant_id"]) for r in rows} == {a.tenant_id, b.tenant_id}
    assert len({r["person_id"] for r in rows}) == 1, "one global person"


async def test_concurrent_first_logins_converge_on_one_person_and_customer(
    client: httpx.AsyncClient,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
    superuser: asyncpg.Connection,
) -> None:
    a, _ = storefronts
    user = telegram_user("Race")
    responses = await asyncio.gather(
        *(telegram_login(client, a.host, a.init_data(telegram_signer, user=user)) for _ in range(8))
    )
    assert [r.status_code for r in responses] == [200] * 8
    identities = await superuser.fetchval(
        "SELECT count(*) FROM control.identities WHERE provider = 'telegram' AND subject = $1",
        str(user["id"]),
    )
    customers = await superuser.fetchval(
        "SELECT count(*) FROM commerce.customers c JOIN control.identities i "
        "ON i.person_id = c.person_id WHERE i.provider = 'telegram' AND i.subject = $1",
        str(user["id"]),
    )
    assert (identities, customers) == (1, 1)


async def test_reloads_within_the_window_work_and_stop_when_it_closes(
    client: httpx.AsyncClient,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
    superuser: asyncpg.Connection,
) -> None:
    a, _ = storefronts
    raw = a.init_data(telegram_signer)
    assert (await telegram_login(client, a.host, raw)).status_code == 200
    assert (await telegram_login(client, a.host, raw)).status_code == 200  # a Mini App reload
    await superuser.execute(
        "UPDATE control.telegram_init_data_uses SET first_used_at = now() - interval '11 minutes' "
        "WHERE tenant_id = $1 AND first_used_at > now() - interval '1 minute'",
        uuid.UUID(a.tenant_id),
    )
    assert (await telegram_login(client, a.host, raw)).status_code == 401
    # Fresh initData from the same user is unaffected.
    assert (await telegram_login(client, a.host, a.init_data(telegram_signer))).status_code == 200


async def test_expired_idle_and_disabled_sessions_are_refused(
    client: httpx.AsyncClient,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
    superuser: asyncpg.Connection,
) -> None:
    a, _ = storefronts
    sessions = [await new_customer(client, a, telegram_signer) for _ in range(3)]
    absolute, idle, disabled = sessions
    for customer in sessions:
        assert (await client.get("/v1/storefront/me", headers=customer.headers)).status_code == 200

    async def session_of(token: str) -> uuid.UUID:
        value: uuid.UUID = await superuser.fetchval(
            "SELECT id FROM control.customer_sessions WHERE token_hash = sha256($1::bytea)",
            token.encode(),
        )
        return value

    await superuser.execute(
        "UPDATE control.customer_sessions SET expires_at = now() - interval '1 second', "
        "idle_expires_at = now() - interval '1 second', created_at = now() - interval '1 day' "
        "WHERE id = $1",
        await session_of(absolute.token),
    )
    await superuser.execute(
        "UPDATE control.customer_sessions SET idle_expires_at = now() - interval '1 second' "
        "WHERE id = $1",
        await session_of(idle.token),
    )
    await superuser.execute(
        "UPDATE control.persons SET status = 'disabled' WHERE id = ("
        "SELECT c.person_id FROM control.customer_sessions s JOIN commerce.customers c "
        "ON c.tenant_id = s.tenant_id AND c.id = s.customer_id WHERE s.id = $1)",
        await session_of(disabled.token),
    )
    for customer in sessions:
        assert (await client.get("/v1/storefront/me", headers=customer.headers)).status_code == 401


async def test_a_disabled_person_cannot_log_in(
    client: httpx.AsyncClient,
    storefronts: tuple[Storefront, Storefront],
    telegram_signer: Signer,
    superuser: asyncpg.Connection,
) -> None:
    a, _ = storefronts
    user = telegram_user("Blocked")
    await new_customer(client, a, telegram_signer, user=user)
    await superuser.execute(
        "UPDATE control.persons SET status = 'disabled' WHERE id = ("
        "SELECT person_id FROM control.identities WHERE provider = 'telegram' AND subject = $1)",
        str(user["id"]),
    )
    response = await telegram_login(client, a.host, a.init_data(telegram_signer, user=user))
    assert response.status_code == 401


async def test_replacing_or_disabling_the_bot_revokes_customer_sessions(
    client: httpx.AsyncClient, super_admin: Persona, world: World, telegram_signer: Signer
) -> None:
    tenant, sf = await fresh(client, super_admin, world, "r-")
    customer = await new_customer(client, sf, telegram_signer)
    old_data = sf.init_data(telegram_signer)
    new_id, new_token = fake_bot()
    replaced = await client.put(
        f"/v1/platform/tenants/{tenant.id}/telegram-bot",
        headers=super_admin.headers,
        json={"bot_id": new_id, "bot_token": new_token},
    )
    assert replaced.status_code == 200
    assert (await client.get("/v1/storefront/me", headers=customer.headers)).status_code == 401
    # The old bot's data no longer authenticates; the new bot's does.
    assert (await telegram_login(client, sf.host, old_data)).status_code == 401
    sf.bot_id, sf.bot_token = new_id, new_token
    customer = await new_customer(client, sf, telegram_signer)

    disabled = await client.delete(
        f"/v1/platform/tenants/{tenant.id}/telegram-bot", headers=super_admin.headers
    )
    assert disabled.status_code == 204
    assert (await client.get("/v1/storefront/me", headers=customer.headers)).status_code == 401
    assert (await telegram_login(client, sf.host, sf.init_data(telegram_signer))).status_code == 401
    status = await client.get(
        f"/v1/platform/tenants/{tenant.id}/telegram-bot", headers=super_admin.headers
    )
    assert status.status_code == 404
    again = await client.delete(
        f"/v1/platform/tenants/{tenant.id}/telegram-bot", headers=super_admin.headers
    )
    assert again.status_code == 404


async def test_a_suspended_tenant_stops_logins_and_sessions(
    client: httpx.AsyncClient, super_admin: Persona, world: World, telegram_signer: Signer
) -> None:
    tenant, sf = await fresh(client, super_admin, world, "s-")
    customer = await new_customer(client, sf, telegram_signer)
    suspended = await client.post(
        f"/v1/platform/tenants/{tenant.id}:suspend", headers=super_admin.headers
    )
    assert suspended.status_code == 200, suspended.text
    assert (await client.get("/v1/storefront/me", headers=customer.headers)).status_code == 401
    login_attempt = await telegram_login(client, sf.host, sf.init_data(telegram_signer))
    assert login_attempt.status_code == 404  # the host no longer resolves to a merchant


async def test_bot_binding_is_platform_only_mfa_gated_and_validated(
    client: httpx.AsyncClient, super_admin: Persona, world: World, db: Database
) -> None:
    tenant = await build_tenant(client, super_admin, world.vertical, world.versions["1.0.0"], "p-")
    url = f"/v1/platform/tenants/{tenant.id}/telegram-bot"
    bot_id, token = fake_bot()
    body = {"bot_id": bot_id, "bot_token": token}

    assert (await client.put(url, json=body)).status_code == 401
    for persona in (tenant.owner, tenant.admin, tenant.staff):  # tenant roles: no bots.manage
        assert (await client.put(url, headers=persona.headers, json=body)).status_code == 403
    operator = await make_person(db)
    granted = await client.post(
        "/v1/platform/role-grants",
        headers=super_admin.headers,
        json={"person_id": str(operator.person_id), "role": "PLATFORM_ADMIN"},
    )
    assert granted.status_code == 204
    await login(client, operator)  # password only
    step_up = await client.put(url, headers=operator.headers, json=body)
    assert step_up.status_code == 403
    assert step_up.json()["type"] == "urn:arada:problem:mfa-required-for-scope"
    await enrol_totp(client, operator)

    for bad in (
        {"bot_id": 0, "bot_token": token},
        {"bot_id": 2**53, "bot_token": token},
        {"bot_id": bot_id, "bot_token": "short"},
        {"bot_id": bot_id, "bot_token": "has a space in it, so no"},
        {"bot_id": bot_id},
        {**body, "tenant_id": world.a.id},
    ):
        assert (await client.put(url, headers=operator.headers, json=bad)).status_code == 422, bad
    missing = f"/v1/platform/tenants/{uuid.uuid4()}/telegram-bot"
    assert (await client.put(missing, headers=operator.headers, json=body)).status_code == 404

    bound = await client.put(url, headers=operator.headers, json=body)
    assert bound.status_code == 200
    assert bound.json() == {
        "tenant_id": tenant.id,
        "bot_id": bot_id,
        "status": "active",
        "registered_at": bound.json()["registered_at"],
    }
    # The same active bot cannot serve a second merchant.
    other = await build_tenant(client, super_admin, world.vertical, world.versions["1.0.0"], "q-")
    clash = await client.put(
        f"/v1/platform/tenants/{other.id}/telegram-bot", headers=operator.headers, json=body
    )
    assert clash.status_code == 409
    events = await audit_rows(db, action="telegram.bot_registered", tenant_id=uuid.UUID(tenant.id))
    assert len(events) == 1
    assert events[0].actor_person_id == operator.person_id
    assert events[0].request_id == bound.headers["x-request-id"]


async def test_logins_are_audited_inside_the_tenant_with_correlation_ids(
    client: httpx.AsyncClient,
    super_admin: Persona,
    world: World,
    telegram_signer: Signer,
    db: Database,
) -> None:
    tenant, sf = await fresh(client, super_admin, world, "u-")
    response = await telegram_login(client, sf.host, sf.init_data(telegram_signer))
    assert response.status_code == 200
    request_id = response.headers["x-request-id"]
    events = await audit_rows(db, tenant_id=uuid.UUID(tenant.id), request_id=request_id)
    assert [e.action for e in events] == [
        "identity.person_created",
        "customer.created",
        "auth.customer_login",
    ]
    assert len({e.actor_person_id for e in events}) == 1
    assert all(e.trace_id and e.source == "api" for e in events)
    assert "access_token" not in str([e.after for e in events])
    # The merchant sees its own customers' logins; the other merchant does not.
    own = await client.get(f"/v1/t/{tenant.slug}/audit-events", headers=tenant.owner.headers)
    assert request_id in own.text
    other = await client.get(f"/v1/t/{world.b.slug}/audit-events", headers=world.b.owner.headers)
    assert request_id not in other.text
    # Failed attempts write nothing (no database writes for unauthenticated callers).
    failed = await telegram_login(client, sf.host, "user=%7B%7D")
    assert failed.status_code == 401
    assert await audit_rows(db, request_id=failed.headers["x-request-id"]) == []
