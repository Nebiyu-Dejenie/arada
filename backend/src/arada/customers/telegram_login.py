"""Customer login with Telegram Mini App ``initData`` (ADR-012, ADR-036).

The approved order, each step its own layer:

1. **Tenant resolution.** The tenant comes from the request ``Host`` through
   the domains resolver. Nothing the client sends names a tenant.
2. **Bot binding.** That tenant's own active bot (FORCE RLS, tenant context).
3. **Authentication.** ``arada.telegram.miniapp.verify``: HMAC with the
   tenant's token and Ed25519 over the tenant's bot id, then freshness.
4. **Replay window.** Our policy, recorded per tenant.
5. **Identity mapping.** ``identities('telegram', <user id>)`` → person.
6. **Customer.** The person's customer row in this tenant.
7. **Session.** An opaque session bound to this tenant and customer.

Authentication grants no business permission; what a customer may do is
decided by the business functions that receive a ``CustomerScope``.

Every failure, whatever its cause, becomes the same ``TelegramAuthFailed``
(401) for the client. The cause is logged as a low-cardinality ``reason``;
raw ``initData``, tokens, hashes, signatures, Telegram user ids and names are
never logged. Failures are not written to the audit trail: an unauthenticated
endpoint must not let anyone generate database writes (register B4).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from arada.audit import service as audit
from arada.bots import service as bots
from arada.customers import service as customers
from arada.customers import sessions as customer_sessions
from arada.identity import telegram as telegram_identity
from arada.kernel.config import Settings
from arada.kernel.context import RequestMeta, bind_tenant, bind_user
from arada.kernel.crypto import Keyring
from arada.kernel.db import Database, set_context
from arada.kernel.errors import AppError, NotFound
from arada.kernel.logging import get_logger
from arada.telegram import miniapp
from arada.tenancy import service as tenancy

log = get_logger("arada.auth.telegram")


class TelegramAuthFailed(AppError):
    """The single answer to every failed Telegram login (owner decision D5)."""

    status = 401
    code = "telegram-auth-failed"
    title = "Telegram authentication failed"


class _Refused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _public_key(settings: Settings) -> Ed25519PublicKey:
    if settings.telegram_public_key_hex is None:
        raise _Refused("not_configured")
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(settings.telegram_public_key_hex))


async def login(
    db: Database,
    settings: Settings,
    keyring: Keyring,
    meta: RequestMeta,
    *,
    host: str,
    init_data: str,
) -> customer_sessions.IssuedCustomerSession:
    try:
        async with db.transaction() as conn:
            tenant = await tenancy.resolve_by_host(conn, host)
            if tenant is None:
                raise NotFound("unknown host")
            await set_context(conn, tenant_id=tenant.id, person_id=None)
            bind_tenant(tenant.id)

            bot = await bots.active_bot_for_login(conn, keyring)
            if bot is None:
                raise _Refused("no_bot")
            verified = miniapp.verify(
                init_data,
                bot_id=bot.telegram_bot_id,
                bot_token=bot.token,
                public_key=_public_key(settings),
                now=datetime.now(UTC),
                max_age=timedelta(seconds=settings.telegram_init_data_max_age_seconds),
                future_skew=timedelta(seconds=settings.telegram_init_data_future_skew_seconds),
            )
            if not await bots.record_init_data_use(
                conn,
                settings,
                tenant_id=tenant.id,
                init_data_hash=verified.hash,
                auth_date=verified.auth_date,
            ):
                raise _Refused("replayed")

            person = await telegram_identity.find_or_create_person(
                conn,
                meta,
                telegram_user_id=verified.user.id,
                name=telegram_identity.display_name(
                    verified.user.first_name, verified.user.last_name
                ),
                audit_tenant_id=tenant.id,
            )
            if person.status != "active":
                raise _Refused("user_rejected")
            await set_context(conn, tenant_id=tenant.id, person_id=person.person_id)
            bind_user(person.person_id)

            customer_id, created = await customers.find_or_create(
                conn, tenant_id=tenant.id, person_id=person.person_id
            )
            if created:
                await audit.record(
                    conn,
                    meta,
                    actor_person_id=person.person_id,
                    tenant_id=tenant.id,
                    action="customer.created",
                    resource_type="customer",
                    resource_id=customer_id,
                    after={"channel": "telegram"},
                )
            issued = await customer_sessions.issue(
                conn, settings, meta, tenant_id=tenant.id, customer_id=customer_id
            )
            await audit.record(
                conn,
                meta,
                actor_person_id=person.person_id,
                tenant_id=tenant.id,
                action="auth.customer_login",
                resource_type="customer",
                resource_id=customer_id,
                after={"channel": "telegram", "session_id": issued.session_id},
            )
    except miniapp.InitDataRejected as exc:
        log.warning("telegram.auth_failed", reason=exc.reason)
        raise TelegramAuthFailed() from None
    except _Refused as exc:
        log.warning("telegram.auth_failed", reason=exc.reason)
        raise TelegramAuthFailed() from None
    log.info("telegram.auth_succeeded", customer_id=str(issued.customer_id))
    return issued
