"""Kernel unit tests: ids, tracing, configuration, crypto, log redaction."""

from __future__ import annotations

import base64
import json
import secrets
import time

import pytest
from pydantic import ValidationError

from arada.kernel.config import Environment, Settings
from arada.kernel.crypto import DecryptionError, Keyring, aad_for
from arada.kernel.ids import uuid7
from arada.kernel.logging import REDACTED, redact_processor
from arada.kernel.tracing import new_span, parse_traceparent

KEK = base64.b64encode(secrets.token_bytes(32)).decode()
# Built at runtime so no token-shaped literal ever sits in the repository.
FAKE_BOT_TOKEN = "123456789:" + secrets.token_urlsafe(26)[:35]
DSN = "postgresql+asyncpg://u:p@localhost/db"


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": DSN,
        "database_platform_reader_url": DSN,
        "kek_base64": KEK,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------- ids
def test_uuid7_has_version_and_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_uuid7_is_monotonic_within_and_across_milliseconds() -> None:
    ids = [uuid7() for _ in range(5000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_uuid7_embeds_current_time() -> None:
    before = int(time.time() * 1000)
    ms = uuid7().int >> 80
    assert before - 5 <= ms <= int(time.time() * 1000) + 5


# --------------------------------------------------------------- tracing
def test_traceparent_continues_valid_parent() -> None:
    parent = parse_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
    assert parent is not None
    span = new_span(parent)
    assert span.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert span.span_id != parent.span_id
    assert span.header().startswith("00-4bf92f3577b34da6a3ce929d0e0e4736-")


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "garbage",
        "00-00000000000000000000000000000000-00f067aa0ba902b7-01",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01",
        "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
    ],
)
def test_invalid_traceparent_starts_new_trace(value: str | None) -> None:
    assert parse_traceparent(value) is None
    span = new_span(None)
    assert len(span.trace_id) == 32


# --------------------------------------------------------------- config
def test_secrets_are_hidden_in_repr() -> None:
    settings = make_settings()
    rendered = repr(settings) + str(settings.model_dump())
    assert "u:p@" not in rendered
    assert KEK not in rendered


def test_kek_must_be_32_bytes() -> None:
    with pytest.raises(ValidationError):
        make_settings(kek_base64=base64.b64encode(b"short").decode())


def test_production_rejects_unsafe_configuration() -> None:
    with pytest.raises(ValidationError) as exc:
        make_settings(
            environment=Environment.PRODUCTION,
            require_mfa_for_privileged_scopes=False,
            expose_api_docs=True,
        )
    message = str(exc.value)
    assert "require_mfa_for_privileged_scopes" in message
    assert "root_domain must be set" in message


def test_root_domain_is_configuration_and_normalised() -> None:
    assert make_settings().root_domain is None  # TBD (ADR-026)
    assert make_settings(root_domain=" Example.COM. ").root_domain == "example.com"


# --------------------------------------------------------------- crypto
def test_envelope_encryption_round_trip_and_binding() -> None:
    ring = Keyring({1: secrets.token_bytes(32)}, 1)
    aad = aad_for("control.totp_factors", "row-1", None, "totp_secret")
    sealed = ring.seal(b"super-secret", aad=aad)
    assert sealed.ciphertext != b"super-secret"
    assert ring.open(sealed, aad=aad) == b"super-secret"
    # Moving the ciphertext to another row or tenant must fail.
    with pytest.raises(DecryptionError):
        ring.open(sealed, aad=aad_for("control.totp_factors", "row-2", None, "totp_secret"))
    with pytest.raises(DecryptionError):
        ring.open(sealed, aad=aad_for("control.totp_factors", "row-1", "tenant-b", "totp_secret"))


def test_keyring_rotation_keeps_old_ciphertexts_readable() -> None:
    old, new = secrets.token_bytes(32), secrets.token_bytes(32)
    aad = b"x"
    sealed_v1 = Keyring({1: old}, 1).seal(b"v1", aad=aad)
    rotated = Keyring({1: old, 2: new}, 2)
    assert rotated.open(sealed_v1, aad=aad) == b"v1"
    assert rotated.seal(b"v2", aad=aad).kek_version == 2


# --------------------------------------------------------------- log redaction
def test_redaction_removes_secret_keys_and_token_shaped_values() -> None:
    event = {
        "event": "login with Bearer abcdefghijklmnopqrstuvwxyz0123",
        "password": "hunter2hunter2",
        "access_token": "tok",
        "nested": {"api_key": "k", "note": FAKE_BOT_TOKEN},
        "dsn": "postgresql+asyncpg://arada_app:pw@db/arada",
        "hash": "$argon2id$v=19$m=65536,t=3,p=4$abc$def",
        "safe": "value",
    }
    out = redact_processor(None, "info", dict(event))
    dumped = json.dumps(out)
    for secret in (
        "hunter2hunter2",
        "abcdefghijklmnopqrstuvwxyz0123",
        FAKE_BOT_TOKEN,
        "$argon2id",
        ":pw@",
    ):
        assert secret not in dumped
    assert out["password"] == REDACTED
    assert out["safe"] == "value"
