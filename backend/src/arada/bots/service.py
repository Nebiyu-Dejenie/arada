"""Merchant-owned Telegram bots (bring-your-own; owner decision D3).

Platform-level administration (``bots.manage``, an MFA-gated platform
permission) binds one bot to one tenant. The admin supplies the bot id and the
token (decision D6): the bot id is **never** parsed from the token, because
Telegram does not document the token format (assumption A9). A wrong bot id
fails closed: every login for that tenant fails the Ed25519 check. No call is
made to Telegram here; outbound Bot API calls are a Phase 2 non-goal.

The token is envelope-encrypted with associated data bound to the row and the
tenant (ADR-017), is decrypted only in memory to check a login's HMAC, and is
never returned, logged or audited.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.audit import service as audit
from arada.bots.tables import telegram_bots, telegram_init_data_uses
from arada.customers import sessions as customer_sessions
from arada.kernel.config import Settings
from arada.kernel.crypto import Keyring, Sealed, aad_for
from arada.kernel.errors import Conflict, NotFound, ValidationFailed
from arada.kernel.ids import uuid7
from arada.kernel.scope import Scope
from arada.tenancy import service as tenancy

MAX_BOT_ID = 2**53 - 1
# Replay rows are pruned by the database clock, but freshness is judged by the
# application clock. A row must outlive every moment its initData could still
# pass freshness, or pruning would reopen a fresh reuse window.
REPLAY_PRUNE_MARGIN = timedelta(minutes=5)
# The docs show the token only by example, so only its shape as an opaque
# printable credential is checked: no whitespace, bounded length.
_TOKEN = re.compile(r"[\x21-\x7e]{16,256}")


@dataclass(frozen=True, slots=True)
class BotStatus:
    tenant_id: UUID
    telegram_bot_id: int
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LoginBot:
    """What a login needs. The token never appears in ``repr`` (logs, tracebacks)."""

    telegram_bot_id: int
    token: str = field(repr=False)


def _aad(row_id: UUID, tenant_id: UUID) -> bytes:
    return aad_for("telegram_bots", str(row_id), str(tenant_id), "bot_token")


def _validate(bot_id: int, token: str) -> None:
    problems: dict[str, list[str]] = {}
    if not 0 < bot_id <= MAX_BOT_ID:
        problems["bot_id"] = ["must be a positive integer below 2^53"]
    if not _TOKEN.fullmatch(token):
        problems["bot_token"] = ["must be 16-256 printable characters without spaces"]
    if problems:
        raise ValidationFailed(errors=problems)


async def _active(conn: AsyncConnection) -> BotStatus | None:
    row = (
        await conn.execute(
            select(
                telegram_bots.c.tenant_id,
                telegram_bots.c.telegram_bot_id,
                telegram_bots.c.status,
                telegram_bots.c.created_at,
            ).where(telegram_bots.c.status == "active")
        )
    ).first()
    return BotStatus(*row) if row else None


async def _disable_active(conn: AsyncConnection) -> int | None:
    previous: int | None = (
        await conn.execute(
            update(telegram_bots)
            .where(telegram_bots.c.status == "active")
            .values(status="disabled", disabled_at=datetime.now(UTC))
            .returning(telegram_bots.c.telegram_bot_id)
        )
    ).scalar_one_or_none()
    return previous


async def register(
    scope: Scope, keyring: Keyring, *, tenant_id: UUID, bot_id: int, token: str
) -> BotStatus:
    """Bind (or replace) the tenant's bot. Replacing revokes customer sessions."""
    scope.require("bots.manage")
    _validate(bot_id, token)
    tenant = await tenancy.enter_tenant(scope, tenant_id)
    if tenant.status == "archived":
        raise NotFound("tenant not found")
    previous = await _disable_active(scope.conn)
    revoked = await customer_sessions.revoke_all_in_tenant(scope.conn, "bot replaced")
    row_id = uuid7()
    sealed = keyring.seal(token.encode(), aad=_aad(row_id, tenant_id))
    try:
        async with scope.conn.begin_nested():
            await scope.conn.execute(
                insert(telegram_bots).values(
                    id=row_id,
                    tenant_id=tenant_id,
                    telegram_bot_id=bot_id,
                    token_ciphertext=sealed.ciphertext,
                    token_nonce=sealed.nonce,
                    wrapped_dek=sealed.wrapped_dek,
                    dek_nonce=sealed.dek_nonce,
                    kek_version=sealed.kek_version,
                    created_by=scope.actor_person_id,
                )
            )
    except IntegrityError as exc:
        raise Conflict("this bot is already bound to another tenant") from exc
    await audit.record_in(
        scope,
        action="telegram.bot_registered",
        resource_type="telegram_bot",
        resource_id=row_id,
        before={"telegram_bot_id": previous} if previous is not None else None,
        after={"telegram_bot_id": bot_id, "customer_sessions_revoked": revoked},
    )
    status = await _active(scope.conn)
    if status is None:
        raise RuntimeError("the bot just registered is not active")
    return status


async def status_of(scope: Scope, tenant_id: UUID) -> BotStatus:
    scope.require("bots.manage")
    await tenancy.enter_tenant(scope, tenant_id)
    status = await _active(scope.conn)
    if status is None:
        raise NotFound("no active bot")
    return status


async def disable(scope: Scope, tenant_id: UUID) -> None:
    """Unbind the tenant's bot: logins stop and customer sessions are revoked."""
    scope.require("bots.manage")
    await tenancy.enter_tenant(scope, tenant_id)
    previous = await _disable_active(scope.conn)
    if previous is None:
        raise NotFound("no active bot")
    revoked = await customer_sessions.revoke_all_in_tenant(scope.conn, "bot disabled")
    await audit.record_in(
        scope,
        action="telegram.bot_disabled",
        resource_type="telegram_bot",
        before={"telegram_bot_id": previous},
        after={"customer_sessions_revoked": revoked},
    )


async def active_bot_for_login(conn: AsyncConnection, keyring: Keyring) -> LoginBot | None:
    """The context tenant's active bot, with its token decrypted in memory."""
    row = (
        await conn.execute(
            select(
                telegram_bots.c.id,
                telegram_bots.c.tenant_id,
                telegram_bots.c.telegram_bot_id,
                telegram_bots.c.token_ciphertext,
                telegram_bots.c.token_nonce,
                telegram_bots.c.wrapped_dek,
                telegram_bots.c.dek_nonce,
                telegram_bots.c.kek_version,
            ).where(telegram_bots.c.status == "active")
        )
    ).first()
    if row is None:
        return None
    sealed = Sealed(
        row.token_ciphertext, row.token_nonce, row.wrapped_dek, row.dek_nonce, row.kek_version
    )
    token = keyring.open(sealed, aad=_aad(row.id, row.tenant_id)).decode()
    return LoginBot(telegram_bot_id=row.telegram_bot_id, token=token)


async def record_init_data_use(
    conn: AsyncConnection,
    settings: Settings,
    *,
    tenant_id: UUID,
    init_data_hash: bytes,
    auth_date: datetime,
) -> bool:
    """Count one session bootstrap from this ``initData``; False if it is a replay.

    The first use opens a window. Later uses (Mini App reloads) are allowed
    only within ``telegram_init_data_reuse_window_seconds`` of the first and up
    to ``telegram_init_data_max_uses`` in total (PHASE_2_PLAN.md §9). The row
    lock taken by ``ON CONFLICT DO UPDATE`` serialises concurrent uses.
    """
    digest = hashlib.sha256(init_data_hash).digest()
    window = timedelta(seconds=settings.telegram_init_data_reuse_window_seconds)
    expires_at = (
        auth_date
        + timedelta(seconds=settings.telegram_init_data_max_age_seconds)
        + timedelta(seconds=settings.telegram_init_data_future_skew_seconds)
        + REPLAY_PRUNE_MARGIN
    )
    # Opportunistic pruning; RLS confines it to this tenant's expired rows. The
    # database clock is used throughout, because first_used_at is set by it.
    await conn.execute(
        delete(telegram_init_data_uses).where(telegram_init_data_uses.c.expires_at < func.now())
    )
    existing = telegram_init_data_uses.c
    stmt = (
        pg_insert(telegram_init_data_uses)
        .values(tenant_id=tenant_id, hash_digest=digest, use_count=1, expires_at=expires_at)
        .on_conflict_do_update(
            index_elements=["tenant_id", "hash_digest"],
            set_={"use_count": existing.use_count + 1},
            where=and_(
                existing.first_used_at > func.now() - window,
                existing.use_count < settings.telegram_init_data_max_uses,
            ),
        )
        .returning(existing.use_count)
    )
    accepted = (await conn.execute(stmt)).scalar_one_or_none()
    return accepted is not None
