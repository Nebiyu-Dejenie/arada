"""Telegram Mini App ``initData`` validation (ADR-012).

Implements **only** the Mini App mechanism, as verified against the official
documentation on 2026-10-01 (``docs/reports/PHASE_2_PLAN.md`` §5, §14):

* <https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app>
* <https://core.telegram.org/bots/webapps#validating-data-for-third-party-use>
* <https://core.telegram.org/bots/webapps#webappinitdata>

It is deliberately *not* the legacy Login Widget (secret key ``SHA256(token)``)
and *not* Telegram Login / OpenID Connect (JWT ID tokens checked against JWKS).
Those are different mechanisms with different derivations and never apply to
Mini App data.

Both checks are required on every call:

1. **HMAC-SHA-256.** ``secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)``.
   ``hash`` must equal the HMAC of the data-check-string: every received field
   except ``hash`` (so ``signature`` and unknown fields are included), sorted
   alphabetically, as ``key=<value>``, joined with ``\\n``.
2. **Ed25519.** ``signature`` (base64url, padding optional) must verify over
   ``"<bot_id>:WebAppData\\n"`` followed by every received field except ``hash``
   and ``signature``, sorted and joined the same way, under the configured
   Telegram public key. This binds the data to one bot and cannot be forged by
   anyone who merely holds the bot token.

Then ``auth_date`` freshness is checked. The maximum age and the future skew
are our policy: Telegram defines neither.

**Assumption A8 (not stated by Telegram).** The query string is decoded once,
as ``application/x-www-form-urlencoded`` (``+`` is a space, ``%XX`` is a byte),
the decoded bytes must be UTF-8, and both data-check-strings use the decoded
values verbatim, hashed and signed over their UTF-8 bytes. Nothing else is
normalised: no trimming, no Unicode normalisation, no JSON re-serialisation.
This is confirmed only by the owner's live test-environment sample.
A decoded value may not contain a line feed, the data-check-string separator
(otherwise the signed string has more than one parse).

Every failure raises ``InitDataRejected`` with a machine reason for logs and
metrics. Callers must show clients one generic answer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

Reason = Literal[
    "malformed",
    "bad_hash",
    "bad_signature",
    "stale",
    "future",
]

MAX_INIT_DATA_BYTES = 4096
MAX_FIELDS = 64
MAX_TELEGRAM_USER_ID = 2**53 - 1  # "at most 52 significant bits" (WebAppUser.id)
HMAC_KEY_CONSTANT = b"WebAppData"
_SEPARATOR = "\n"  # joins the data-check-string; never allowed inside a value

_KEY = re.compile(r"[A-Za-z0-9_]{1,64}")
# Raw query-string characters: unreserved, sub-delims used by encoders, and
# percent escapes. Anything else (including NUL, spaces, newlines) is malformed.
_RAW = re.compile(r"[A-Za-z0-9\-._~!$'()*+,;=:@/?&%]*")
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_HEX64 = re.compile(r"[0-9A-Fa-f]{64}")
# A 64-byte signature is 86 base64url characters, or 88 with "==" padding.
_SIGNATURE = re.compile(r"[A-Za-z0-9_-]{86}(==)?")


class InitDataRejected(Exception):
    """``initData`` failed validation. ``reason`` is for logs, never clients."""

    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


@dataclass(frozen=True, slots=True)
class TelegramUser:
    """The fields of ``WebAppUser`` that ARADA uses. Nothing else is kept."""

    id: int
    first_name: str
    last_name: str | None
    language_code: str | None


@dataclass(frozen=True, slots=True)
class VerifiedInitData:
    user: TelegramUser
    auth_date: datetime
    hash: bytes  # the 32-byte HMAC; unique per initData, used for replay control


def _decode_component(component: str) -> str:
    """One form-urlencoded component -> text (A8). Strict: no lossy decoding."""
    if _BAD_ESCAPE.search(component):
        raise InitDataRejected("malformed")
    raw = bytearray()
    i = 0
    plain = component.replace("+", " ")
    while i < len(plain):
        char = plain[i]
        if char == "%":
            raw.append(int(plain[i + 1 : i + 3], 16))
            i += 3
        else:
            raw.extend(char.encode("ascii"))
            i += 1
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InitDataRejected("malformed") from exc


def parse(raw: str) -> dict[str, str]:
    """Decode the raw ``initData`` query string into its fields, strictly.

    Every field is kept, known or not: unknown fields are covered by the hash
    and the signature, so dropping one would break verification.
    """
    if not raw or len(raw) > MAX_INIT_DATA_BYTES or not _RAW.fullmatch(raw):
        raise InitDataRejected("malformed")
    pairs = raw.split("&")
    if len(pairs) > MAX_FIELDS:
        raise InitDataRejected("malformed")
    fields: dict[str, str] = {}
    for pair in pairs:
        key_part, sep, value_part = pair.partition("=")
        if not sep:
            raise InitDataRejected("malformed")
        key = _decode_component(key_part)
        if not _KEY.fullmatch(key) or key in fields:
            raise InitDataRejected("malformed")
        value = _decode_component(value_part)
        # The data-check-strings join fields with a line feed, so a value that
        # contains one makes the signed string ambiguous: its holder could move
        # field boundaries (even make ``user`` someone else) without changing a
        # signed byte. Refusing it keeps the parse injective. (Deep audit F1.)
        if _SEPARATOR in value:
            raise InitDataRejected("malformed")
        fields[key] = value
    return fields


def data_check_string(fields: dict[str, str], *, exclude: frozenset[str]) -> str:
    """Received fields minus ``exclude``, sorted by key, ``key=value``, ``\\n``-joined."""
    return "\n".join(f"{k}={fields[k]}" for k in sorted(fields) if k not in exclude)


def hmac_secret_key(bot_token: str) -> bytes:
    """Mini App secret key: HMAC-SHA-256 of the token, keyed with ``WebAppData``."""
    return hmac.new(HMAC_KEY_CONSTANT, bot_token.encode("utf-8"), hashlib.sha256).digest()


def expected_hash(fields: dict[str, str], bot_token: str) -> bytes:
    dcs = data_check_string(fields, exclude=frozenset({"hash"}))
    return hmac.new(hmac_secret_key(bot_token), dcs.encode("utf-8"), hashlib.sha256).digest()


def signed_message(fields: dict[str, str], bot_id: int) -> bytes:
    """The Ed25519 message: ``<bot_id>:WebAppData\\n`` + fields minus hash, signature."""
    dcs = data_check_string(fields, exclude=frozenset({"hash", "signature"}))
    return f"{bot_id}:WebAppData\n{dcs}".encode()


def decode_signature(value: str) -> bytes:
    if not _SIGNATURE.fullmatch(value):
        raise InitDataRejected("malformed")
    unpadded = value.rstrip("=")
    signature = base64.urlsafe_b64decode(unpadded + "==")
    if len(signature) != 64:
        raise InitDataRejected("malformed")
    return signature


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_name: str) -> Any:
    raise ValueError("non-standard JSON constant")


def _optional_text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InitDataRejected("malformed")
    return value


def parse_user(value: str) -> TelegramUser:
    """The ``user`` field (WebAppUser, JSON-serialised). Only ``user`` is identity."""
    try:
        data = json.loads(
            value, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant
        )
    except ValueError as exc:
        raise InitDataRejected("malformed") from exc
    if not isinstance(data, dict):
        raise InitDataRejected("malformed")
    user_id = data.get("id")
    if (
        not isinstance(user_id, int)
        or isinstance(user_id, bool)
        or not 0 < user_id <= MAX_TELEGRAM_USER_ID
    ):
        raise InitDataRejected("malformed")
    first_name = data.get("first_name")
    if not isinstance(first_name, str) or not first_name.strip():
        raise InitDataRejected("malformed")
    # "is_bot: Returns in the receiver field only" (WebAppUser): a bot claim in
    # ``user`` is not a documented case, so it is refused defensively.
    if data.get("is_bot") not in (None, False):
        raise InitDataRejected("malformed")
    return TelegramUser(
        id=user_id,
        first_name=first_name,
        last_name=_optional_text(data, "last_name"),
        language_code=_optional_text(data, "language_code"),
    )


def verify(
    raw: str,
    *,
    bot_id: int,
    bot_token: str,
    public_key: Ed25519PublicKey,
    now: datetime,
    max_age: timedelta,
    future_skew: timedelta,
) -> VerifiedInitData:
    """Validate raw ``initData`` for one bot. Raises ``InitDataRejected``.

    Order: structure, HMAC, Ed25519, then content and freshness, so a forged
    request is always counted as forged whatever else is wrong with it.
    """
    fields = parse(raw)
    for required in ("hash", "signature", "auth_date", "user"):
        if required not in fields:
            raise InitDataRejected("malformed")
    if not _HEX64.fullmatch(fields["hash"]):
        raise InitDataRejected("malformed")
    received_hash = bytes.fromhex(fields["hash"])  # letter case is not specified
    signature = decode_signature(fields["signature"])

    if not hmac.compare_digest(received_hash, expected_hash(fields, bot_token)):
        raise InitDataRejected("bad_hash")
    try:
        public_key.verify(signature, signed_message(fields, bot_id))
    except InvalidSignature as exc:
        raise InitDataRejected("bad_signature") from exc

    auth_date_text = fields["auth_date"]
    if not auth_date_text.isascii() or not auth_date_text.isdigit() or len(auth_date_text) > 12:
        raise InitDataRejected("malformed")
    try:
        auth_date = datetime.fromtimestamp(int(auth_date_text), tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:  # beyond year 9999
        raise InitDataRejected("malformed") from exc
    user = parse_user(fields["user"])
    if auth_date > now + future_skew:
        raise InitDataRejected("future")
    if now - auth_date > max_age:
        raise InitDataRejected("stale")
    return VerifiedInitData(user=user, auth_date=auth_date, hash=received_hash)
