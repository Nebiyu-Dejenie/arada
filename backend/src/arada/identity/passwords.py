"""Password hashing (argon2id) and policy.

Hashing is CPU-bound, so callers run it on a worker thread and never block
the event loop. A fixed dummy hash is verified for unknown usernames so the
response time does not reveal whether an account exists.
"""

from __future__ import annotations

import asyncio
import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from arada.kernel.errors import ValidationFailed

MIN_LENGTH = 12
MAX_LENGTH = 256  # bounds hashing cost of attacker-supplied input
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")

_hasher = PasswordHasher()  # argon2id, RFC 9106 low-memory profile defaults
_DUMMY_HASH = _hasher.hash("arada-dummy-password-for-timing-equalisation")


def normalise_username(raw: str) -> str:
    return raw.strip().lower()


def validate_username(username: str) -> None:
    if not USERNAME.match(username):
        raise ValidationFailed(
            errors={"username": ["3-64 chars: lowercase letters, digits, '.', '_' or '-'"]}
        )


def validate_password(password: str) -> None:
    if not MIN_LENGTH <= len(password) <= MAX_LENGTH:
        raise ValidationFailed(
            errors={"password": [f"must be {MIN_LENGTH}-{MAX_LENGTH} characters"]}
        )


async def hash_password(password: str) -> str:
    validate_password(password)
    return await asyncio.to_thread(_hasher.hash, password)


def _verify(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


async def verify_password(stored_hash: str | None, password: str) -> bool:
    """Constant-shape verification: always performs one argon2 verification."""
    if len(password) > MAX_LENGTH:
        password = password[:MAX_LENGTH]
    if stored_hash is None:
        await asyncio.to_thread(_verify, _DUMMY_HASH, password)
        return False
    return await asyncio.to_thread(_verify, stored_hash, password)


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)
