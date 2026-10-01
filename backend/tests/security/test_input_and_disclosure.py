"""Mass assignment, SQL injection, error disclosure and secret leakage."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from arada.kernel.config import Environment, Settings
from arada.main import create_app
from tests.conftest import PgEnv
from tests.storefront import TELEGRAM_PRODUCTION_PUBLIC_KEY
from tests.support import DEFAULT_PASSWORD, Persona
from tests.world import World

SRC = Path(__file__).resolve().parents[2] / "src" / "arada"


# --------------------------------------------------------------- mass assignment
def _resolve(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref:
        resolved: dict[str, Any] = components[ref.rsplit("/", 1)[-1]]
        return resolved
    return schema


def test_every_request_body_forbids_unknown_fields(app: FastAPI) -> None:
    spec = app.openapi()
    components = spec["components"]["schemas"]
    checked = 0
    for path, item in spec["paths"].items():
        for method, op in item.items():
            body = op.get("requestBody", {}).get("content", {}).get("application/json")
            if not body:
                continue
            schema = _resolve(body["schema"], components)
            for candidate in schema.get("anyOf", [schema]):
                candidate = _resolve(candidate, components)
                if candidate.get("type") == "null":
                    continue
                checked += 1
                assert candidate.get("additionalProperties") is False, f"{method.upper()} {path}"
    assert checked >= 15


# --------------------------------------------------------------- SQL injection
PAYLOADS = [
    "' OR '1'='1",
    "x'; DROP TABLE control.tenants; --",
    "1) UNION SELECT password_hash FROM control.password_credentials --",
    "\\x00",
    "shop-a' --",
    "%' OR tenant_id IS NOT NULL --",
    "ሳምሰንግ",
]


async def test_injection_payloads_are_inert(
    client: httpx.AsyncClient, super_admin: Persona, world: World, pg_env: PgEnv, test_database: str
) -> None:
    root = super_admin.headers
    for payload in PAYLOADS:
        responses = [
            await client.get(f"/v1/t/{payload}", headers=world.a.admin.headers),
            await client.get("/v1/platform/persons", headers=root, params={"username": payload}),
            await client.get("/v1/platform/tenants", headers=root, params={"vertical": payload}),
            await client.get("/v1/platform/audit-events", headers=root, params={"action": payload}),
            await client.post(
                "/v1/auth/login", json={"username": payload, "password": payload + "x" * 12}
            ),
            await client.get(
                "/v1/storefront/merchant",
                headers={"host": payload.encode("ascii", "ignore").decode() or "x"},
            ),
        ]
        for r in responses:
            assert r.status_code in {200, 401, 403, 404, 422}, (
                f"{payload!r}: {r.request.url} -> {r.status_code}"
            )
            body = r.json() if r.headers.get("content-type", "").endswith("json") else {}
            # The problem "instance" legitimately echoes the requested path (the
            # attacker's own input); nothing else may reflect or leak data.
            rest = str(
                {k: v for k, v in body.items() if k != "instance"}
                if isinstance(body, dict)
                else body
            )
            assert "$argon2" not in r.text
            assert "password_hash" not in rest
            assert "syntax error" not in r.text.lower()
        etag = (await client.get(f"/v1/t/{world.a.slug}", headers=world.a.admin.headers)).headers[
            "etag"
        ]
        patched = await client.patch(
            f"/v1/t/{world.a.slug}/profile",
            headers={**world.a.admin.headers, "If-Match": etag},
            json={"tagline": payload[:160]},
        )
        assert patched.status_code in {200, 422}
        if patched.status_code == 200:
            assert patched.json()["tagline"] == payload[:160], "stored verbatim, never executed"

    conn = await asyncpg.connect(pg_env.superuser_dsn(test_database))
    try:
        assert await conn.fetchval("SELECT to_regclass('control.tenants') IS NOT NULL")
        assert await conn.fetchval("SELECT count(*) FROM control.tenants") >= 2
    finally:
        await conn.close()


async def test_nul_bytes_are_rejected_not_crashing(client: httpx.AsyncClient, world: World) -> None:
    etag = (await client.get(f"/v1/t/{world.a.slug}", headers=world.a.admin.headers)).headers[
        "etag"
    ]
    response = await client.patch(
        f"/v1/t/{world.a.slug}/profile",
        headers={**world.a.admin.headers, "If-Match": etag},
        json={"tagline": "evil\u0000tail"},
    )
    assert response.status_code == 422
    login = await client.post("/v1/auth/login", json={"username": "a\u0000b", "password": "x" * 20})
    assert login.status_code in {401, 422}


def test_no_sql_is_built_by_string_formatting() -> None:
    """All SQL uses bound parameters; f-strings and .format() never build SQL."""
    pattern = re.compile(
        r"(text|execute|exec_driver_sql|fetch\w*)\(\s*f[\"']|"
        r"(SELECT|INSERT|UPDATE|DELETE)[^\"'\n]*[\"']\s*(%|\.format\()",
        re.IGNORECASE,
    )
    offenders = [
        f"{p.relative_to(SRC)}:{n}"
        for p in SRC.rglob("*.py")
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


# --------------------------------------------------------------- error disclosure
@pytest.fixture
async def crashing_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("internal detail: dsn=postgresql://arada_app:hunter2@db/arada")

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


async def test_unhandled_errors_disclose_nothing(crashing_client: httpx.AsyncClient) -> None:
    response = await crashing_client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["type"] == "urn:arada:problem:internal-error"
    assert body["request_id"]
    for leak in ("internal detail", "hunter2", "Traceback", "RuntimeError", "postgresql://"):
        assert leak not in response.text


async def test_validation_errors_never_echo_input(client: httpx.AsyncClient) -> None:
    secret = "my-real-password-" + "z" * 300  # too long: rejected by validation
    response = await client.post("/v1/auth/login", json={"username": "someone", "password": secret})
    assert response.status_code == 422
    assert secret[:20] not in response.text


async def test_api_docs_are_off_in_production(settings: Settings) -> None:
    prod = Settings(
        **{
            **settings.model_dump(),
            "environment": Environment.PRODUCTION,
            "expose_api_docs": False,
            "root_domain": "example.test",
            "log_format": "json",
            "telegram_environment": "production",
            "telegram_public_key_hex": TELEGRAM_PRODUCTION_PUBLIC_KEY,
        }
    )
    app = create_app(prod)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            for path in ("/openapi.json", "/docs"):
                assert (await c.get(path)).status_code == 404


# --------------------------------------------------------------- secret leakage
async def test_responses_never_carry_credentials(
    client: httpx.AsyncClient, super_admin: Persona, world: World
) -> None:
    root = super_admin.headers
    urls = [
        "/v1/me",
        f"/v1/t/{world.a.slug}",
        f"/v1/t/{world.a.slug}/staff",
        f"/v1/t/{world.a.slug}/audit-events",
        f"/v1/platform/persons?username={world.a.owner.username}",
        "/v1/platform/audit-events",
        "/v1/platform/tenants",
    ]
    for url in urls:
        text = (await client.get(url, headers=root)).text
        assert "$argon2" not in text, url
        assert DEFAULT_PASSWORD not in text, url
        assert (super_admin.totp_secret or "unset") not in text, url
        for persona in (world.a.owner, world.a.admin):
            assert persona.token is not None
            assert persona.token not in text, url


def test_openapi_exposes_no_secret_fields(app: FastAPI) -> None:
    schema = str(app.openapi()["components"]["schemas"])
    for field in ("password_hash", "token_hash", "secret_ciphertext", "wrapped_dek", "kek"):
        assert field not in schema


async def test_logs_never_contain_passwords_or_tokens(
    client: httpx.AsyncClient, world: World, capfd: pytest.CaptureFixture[str]
) -> None:
    persona = world.a.staff
    await client.post(
        "/v1/auth/login",
        json={"username": persona.username, "password": "wrong-" + DEFAULT_PASSWORD},
    )
    await client.get("/v1/me", headers=persona.headers)
    await client.post(
        "/v1/auth/login", json={"username": persona.username, "password": persona.password}
    )
    out, err = capfd.readouterr()
    logs = out + err
    assert "http.request" in logs or logs == "", "request logging is expected on stdout"
    assert DEFAULT_PASSWORD not in logs
    assert persona.token is not None
    assert persona.token not in logs


def test_repository_contains_no_committed_secrets() -> None:
    root = SRC.parents[2]
    patterns = [
        re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),  # Telegram bot token
        re.compile(r"postgres(ql)?(\+\w+)?://[a-z_]+:[0-9a-f]{20,}@"),  # generated DB password
        re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ]
    tracked = [
        p
        for p in root.rglob("*")
        if p.is_file()
        and ".git" not in p.parts
        and ".venv" not in p.parts
        and "node_modules" not in p.parts
        and p.name != ".env"
        and p.suffix
        in {".py", ".toml", ".yaml", ".yml", ".md", ".sh", ".ini", ".example", ".json", ""}
    ]
    hits = [
        str(p.relative_to(root))
        for p in tracked
        for pat in patterns
        if pat.search(p.read_text(errors="ignore"))
    ]
    assert hits == []
