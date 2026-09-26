"""Gate 3: identities, authentication, sessions and TOTP work correctly."""

from __future__ import annotations

import hashlib

import asyncpg
import httpx
import pytest

from arada.identity.service import create_person_with_password
from arada.kernel.db import Database
from arada.kernel.errors import Conflict
from tests.conftest import PgEnv
from tests.support import (
    DEFAULT_PASSWORD,
    SYSTEM_META,
    audit_rows,
    enrol_totp,
    login,
    make_person,
    unique,
)


async def test_login_me_logout_cycle(client: httpx.AsyncClient, db: Database) -> None:
    alice = await make_person(db)
    await login(client, alice)
    me = await client.get("/v1/me", headers=alice.headers)
    assert me.status_code == 200
    body = me.json()
    assert body["person_id"] == str(alice.person_id)
    assert body["username"] == alice.username
    assert body["mfa"] == {"totp": "none", "session_verified": False}

    assert (await client.post("/v1/auth/logout", headers=alice.headers)).status_code == 204
    assert (await client.get("/v1/me", headers=alice.headers)).status_code == 401


async def test_usernames_are_normalised_and_unique(db: Database) -> None:
    name = unique("Mixed")
    person = await make_person(db, username=name)
    assert person.username == name.lower()
    with pytest.raises(Conflict):
        async with db.transaction() as conn:
            await create_person_with_password(
                conn,
                SYSTEM_META,
                actor_person_id=None,
                audit_tenant_id=None,
                username=name.upper(),
                password=DEFAULT_PASSWORD,
                display_name="Duplicate",
            )


async def test_unknown_user_and_wrong_password_are_indistinguishable(
    client: httpx.AsyncClient, db: Database
) -> None:
    bob = await make_person(db)
    wrong = await client.post(
        "/v1/auth/login", json={"username": bob.username, "password": "wrong password!!"}
    )
    unknown = await client.post(
        "/v1/auth/login", json={"username": unique("nobody"), "password": "wrong password!!"}
    )
    assert wrong.status_code == unknown.status_code == 401

    def strip(r: httpx.Response) -> dict[str, object]:
        return {k: v for k, v in r.json().items() if k != "request_id"}

    assert strip(wrong) == strip(unknown)


async def test_account_locks_after_repeated_failures(
    client: httpx.AsyncClient, db: Database
) -> None:
    carol = await make_person(db)
    for _ in range(10):
        r = await client.post(
            "/v1/auth/login", json={"username": carol.username, "password": "not the password"}
        )
        assert r.status_code == 401
    # Even the correct password is refused while locked.
    locked = await client.post(
        "/v1/auth/login", json={"username": carol.username, "password": carol.password}
    )
    assert locked.status_code == 401
    assert await audit_rows(db, action="auth.account_locked", actor_person_id=carol.person_id)


async def test_totp_enrolment_and_login(client: httpx.AsyncClient, db: Database) -> None:
    dave = await make_person(db)
    await login(client, dave)
    await enrol_totp(client, dave)
    me = (await client.get("/v1/me", headers=dave.headers)).json()
    assert me["mfa"] == {"totp": "confirmed", "session_verified": True}

    no_code = await client.post(
        "/v1/auth/login", json={"username": dave.username, "password": dave.password}
    )
    assert no_code.status_code == 401
    assert no_code.json()["type"] == "urn:arada:problem:mfa-required"

    bad_code = await client.post(
        "/v1/auth/login",
        json={"username": dave.username, "password": dave.password, "totp_code": "000000"},
    )
    assert bad_code.status_code == 401

    code = dave.next_totp()
    ok = await client.post(
        "/v1/auth/login",
        json={"username": dave.username, "password": dave.password, "totp_code": code},
    )
    assert ok.status_code == 200
    assert ok.json()["mfa_verified"] is True

    replay = await client.post(
        "/v1/auth/login",
        json={"username": dave.username, "password": dave.password, "totp_code": code},
    )
    assert replay.status_code == 401, "a TOTP code must not be accepted twice"


async def test_secrets_never_stored_in_clear(
    client: httpx.AsyncClient, db: Database, pg_env: PgEnv, test_database: str
) -> None:
    erin = await make_person(db)
    token = await login(client, erin)
    await enrol_totp(client, erin)
    assert erin.totp_secret is not None

    conn = await asyncpg.connect(pg_env.superuser_dsn(test_database))
    try:
        cred = await conn.fetchrow(
            "SELECT pc.password_hash FROM control.password_credentials pc "
            "JOIN control.identities i ON i.id = pc.identity_id WHERE i.person_id = $1",
            erin.person_id,
        )
        assert cred is not None
        assert cred["password_hash"].startswith("$argon2id$")
        assert erin.password not in cred["password_hash"]

        factor = await conn.fetchrow(
            "SELECT secret_ciphertext FROM control.totp_factors WHERE person_id = $1",
            erin.person_id,
        )
        assert factor is not None
        assert erin.totp_secret.encode() not in bytes(factor["secret_ciphertext"])

        hashes = [
            bytes(r["token_hash"])
            for r in await conn.fetch(
                "SELECT token_hash FROM control.sessions WHERE person_id = $1", erin.person_id
            )
        ]
        assert hashlib.sha256(token.encode()).digest() in hashes
        assert token.encode() not in b"".join(hashes)
    finally:
        await conn.close()


async def test_expired_and_disabled_sessions_are_rejected(
    client: httpx.AsyncClient, db: Database, pg_env: PgEnv, test_database: str
) -> None:
    frank, grace = await make_person(db), await make_person(db)
    await login(client, frank)
    await login(client, grace)
    conn = await asyncpg.connect(pg_env.superuser_dsn(test_database))
    try:
        await conn.execute(
            "UPDATE control.sessions SET idle_expires_at = now() - interval '1 second' "
            "WHERE person_id = $1",
            frank.person_id,
        )
        await conn.execute(
            "UPDATE control.persons SET status = 'disabled' WHERE id = $1", grace.person_id
        )
    finally:
        await conn.close()
    assert (await client.get("/v1/me", headers=frank.headers)).status_code == 401
    assert (await client.get("/v1/me", headers=grace.headers)).status_code == 401


async def test_login_audit_is_correlated(client: httpx.AsyncClient, db: Database) -> None:
    heidi = await make_person(db)
    response = await client.post(
        "/v1/auth/login", json={"username": heidi.username, "password": heidi.password}
    )
    rows = await audit_rows(db, action="auth.login_succeeded", actor_person_id=heidi.person_id)
    assert len(rows) == 1
    assert rows[0].request_id == response.headers["x-request-id"]
    assert rows[0].trace_id == response.headers["traceparent"].split("-")[1]
    assert rows[0].source == "api"
    assert rows[0].tenant_id is None
