"""Test helpers: personas, logins, TOTP codes, audit reads."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
import pyotp
from sqlalchemy import select

from arada.audit.tables import audit_events
from arada.identity.service import create_person_with_password
from arada.kernel.context import RequestMeta
from arada.kernel.db import Database

DEFAULT_PASSWORD = "correct horse battery staple"
SYSTEM_META = RequestMeta(request_id="test-setup", trace_id="0" * 31 + "1", source="system")


def unique(prefix: str) -> str:
    return f"{prefix}{secrets.token_hex(4)}"


@dataclass
class Persona:
    person_id: UUID
    username: str
    password: str
    totp_secret: str | None = None
    token: str | None = None
    _last_step: int = field(default=-1, repr=False)

    def next_totp(self) -> str:
        """A valid code for a step not yet used (replay protection is real)."""
        assert self.totp_secret is not None
        step = max(int(time.time() // 30), self._last_step + 1)
        self._last_step = step
        return pyotp.TOTP(self.totp_secret).at(step * 30)

    @property
    def headers(self) -> dict[str, str]:
        assert self.token is not None
        return {"Authorization": f"Bearer {self.token}"}


async def make_person(
    db: Database, *, username: str | None = None, password: str = DEFAULT_PASSWORD
) -> Persona:
    uname = username or unique("user")
    async with db.transaction() as conn:
        person_id = await create_person_with_password(
            conn,
            SYSTEM_META,
            actor_person_id=None,
            audit_tenant_id=None,
            username=uname,
            password=password,
            display_name=uname.title(),
        )
    return Persona(person_id=person_id, username=uname.lower(), password=password)


async def login(client: httpx.AsyncClient, persona: Persona, *, with_totp: bool = True) -> str:
    body: dict[str, Any] = {"username": persona.username, "password": persona.password}
    if with_totp and persona.totp_secret:
        body["totp_code"] = persona.next_totp()
    response = await client.post("/v1/auth/login", json=body)
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    persona.token = token
    return token


async def enrol_totp(client: httpx.AsyncClient, persona: Persona) -> None:
    """Enrol and confirm TOTP; the persona switches to the rotated, MFA-verified token."""
    started = await client.post("/v1/me/mfa/totp", headers=persona.headers)
    assert started.status_code == 200, started.text
    persona.totp_secret = started.json()["secret"]
    confirmed = await client.post(
        "/v1/me/mfa/totp/confirm", headers=persona.headers, json={"code": persona.next_totp()}
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["mfa_verified"] is True
    persona.token = confirmed.json()["access_token"]


async def audit_rows(db: Database, **filters: Any) -> list[Any]:
    query = select(audit_events).order_by(audit_events.c.id)
    for key, value in filters.items():
        query = query.where(getattr(audit_events.c, key) == value)
    async with db.platform_read() as conn:
        return list((await conn.execute(query)).all())


def api_operations(app: Any) -> list[tuple[str, str]]:
    """Every (METHOD, path) the application serves, from its OpenAPI schema.

    ``app.routes`` is not a reliable inventory: FastAPI >= 0.141 nests included
    routers instead of flattening them, which once made route-enumerating
    security tests pass vacuously. The OpenAPI document is the public contract
    of what is served, so tests enumerate that.
    """
    operations = [
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert operations, "route enumeration returned nothing"
    return sorted(operations)
