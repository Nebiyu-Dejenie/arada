"""Builds Mini App ``initData`` the way Telegram documents it, for tests only.

A throwaway Ed25519 key pair stands in for Telegram's key, and bot tokens are
random fakes. Nothing here is a real credential, and no real ``initData`` or
personal data is ever committed (PHASE_2_PLAN.md §4). These vectors prove the
validator matches *our reading* of the spec; conformance with Telegram itself
is proven only by the owner's live test-environment sample.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def fake_bot() -> tuple[int, str]:
    """A random bot id and a random token. Never a real bot."""
    bot_id = secrets.randbelow(9 * 10**9) + 10**9
    return bot_id, f"{bot_id}:{secrets.token_urlsafe(26)}"


def public_hex(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes_raw().hex()


@dataclass
class Signer:
    """Signs like Telegram: HMAC with the bot token, Ed25519 with ``key``."""

    key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)

    @property
    def public_hex(self) -> str:
        return public_hex(self.key)

    def fields(
        self,
        *,
        bot_id: int,
        bot_token: str,
        user: dict[str, Any] | None = None,
        auth_date: int | None = None,
        extra: dict[str, str] | None = None,
        signature_padding: bool = False,
    ) -> dict[str, str]:
        """Decoded fields with a valid ``signature`` and ``hash``."""
        values: dict[str, str] = {
            "auth_date": str(int(time.time()) if auth_date is None else auth_date),
            "query_id": "AAH" + secrets.token_urlsafe(12),
            "user": json.dumps(
                user or {"id": secrets.randbelow(10**10) + 1, "first_name": "Abebe"},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        values.update(extra or {})
        values["signature"] = self.signature(values, bot_id, padding=signature_padding)
        values["hash"] = hmac_hex(values, bot_token)
        return values

    def signature(self, values: dict[str, str], bot_id: int, *, padding: bool = False) -> str:
        message = f"{bot_id}:WebAppData\n" + dcs(values, {"hash", "signature"})
        encoded = base64.urlsafe_b64encode(self.key.sign(message.encode())).decode()
        return encoded if padding else encoded.rstrip("=")

    def init_data(self, **kwargs: Any) -> str:
        return encode(self.fields(**kwargs))


def dcs(values: dict[str, str], exclude: set[str]) -> str:
    return "\n".join(f"{k}={values[k]}" for k in sorted(values) if k not in exclude)


def hmac_hex(values: dict[str, str], bot_token: str, *, key_constant: bytes = b"WebAppData") -> str:
    secret = hmac.new(key_constant, bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, dcs(values, {"hash"}).encode(), hashlib.sha256).hexdigest()


def login_widget_hash(values: dict[str, str], bot_token: str) -> str:
    """The legacy Login Widget derivation (secret = SHA256(token)): never valid here."""
    secret = hashlib.sha256(bot_token.encode()).digest()
    return hmac.new(secret, dcs(values, {"hash"}).encode(), hashlib.sha256).hexdigest()


def encode(values: dict[str, str], *, plus_for_space: bool = False) -> str:
    """Percent-encode like ``encodeURIComponent`` (or form style with ``+``)."""
    parts = []
    for key, value in values.items():
        encoded = quote(value, safe="")
        if plus_for_space:
            encoded = encoded.replace("%20", "+")
        parts.append(f"{key}={encoded}")
    return "&".join(parts)
