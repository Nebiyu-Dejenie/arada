"""TOTP second factor (RFC 6238).

The shared secret is envelope-encrypted with AAD bound to the factor row.
Each accepted time step is recorded so a code cannot be replayed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

import pyotp
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.identity.tables import totp_factors
from arada.kernel.crypto import Keyring, Sealed, aad_for
from arada.kernel.errors import Conflict, NotFound
from arada.kernel.ids import uuid7

_PURPOSE = "totp_secret"
_TABLE = "control.totp_factors"
_STEP = 30
_WINDOW = 1  # accept the previous/next step for clock drift


@dataclass(frozen=True, slots=True)
class Enrolment:
    secret: str
    provisioning_uri: str


def _aad(factor_id: UUID) -> bytes:
    return aad_for(_TABLE, str(factor_id), None, _PURPOSE)


async def status(conn: AsyncConnection, person_id: UUID) -> str:
    row = (
        await conn.execute(
            select(totp_factors.c.confirmed_at).where(totp_factors.c.person_id == person_id)
        )
    ).first()
    if row is None:
        return "none"
    return "confirmed" if row.confirmed_at is not None else "pending"


async def begin_enrolment(
    conn: AsyncConnection, keyring: Keyring, *, person_id: UUID, account: str, issuer: str
) -> Enrolment:
    existing = await status(conn, person_id)
    if existing == "confirmed":
        raise Conflict("a confirmed TOTP factor already exists")
    if existing == "pending":
        await conn.execute(delete(totp_factors).where(totp_factors.c.person_id == person_id))
    secret = pyotp.random_base32()
    factor_id = uuid7()
    sealed = keyring.seal(secret.encode(), aad=_aad(factor_id))
    await conn.execute(
        insert(totp_factors).values(
            person_id=person_id,
            id=factor_id,
            secret_ciphertext=sealed.ciphertext,
            secret_nonce=sealed.nonce,
            wrapped_dek=sealed.wrapped_dek,
            dek_nonce=sealed.dek_nonce,
            kek_version=sealed.kek_version,
        )
    )
    uri = pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)
    return Enrolment(secret=secret, provisioning_uri=uri)


async def verify(
    conn: AsyncConnection,
    keyring: Keyring,
    *,
    person_id: UUID,
    code: str,
    require_confirmed: bool,
    now: float | None = None,
) -> bool:
    """Verify ``code`` and consume its time step. Locks the factor row."""
    row = (
        await conn.execute(
            select(totp_factors).where(totp_factors.c.person_id == person_id).with_for_update()
        )
    ).first()
    if row is None:
        raise NotFound("no TOTP factor")
    if require_confirmed and row.confirmed_at is None:
        return False
    if not (code.isdigit() and len(code) == 6):
        return False
    secret = keyring.open(
        Sealed(
            row.secret_ciphertext, row.secret_nonce, row.wrapped_dek, row.dek_nonce, row.kek_version
        ),
        aad=_aad(row.id),
    ).decode()
    totp = pyotp.TOTP(secret)
    current = now if now is not None else time.time()
    step_now = int(current // _STEP)
    for offset in range(-_WINDOW, _WINDOW + 1):
        step = step_now + offset
        if totp.at(step * _STEP) == code:
            if row.last_used_step is not None and step <= row.last_used_step:
                return False  # replayed or older code
            await conn.execute(
                update(totp_factors)
                .where(totp_factors.c.person_id == person_id)
                .values(last_used_step=step)
            )
            return True
    return False


async def confirm(conn: AsyncConnection, person_id: UUID) -> None:
    await conn.execute(
        update(totp_factors)
        .where(totp_factors.c.person_id == person_id)
        .values(confirmed_at=func.now())
    )
