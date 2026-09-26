"""Identity use cases: create persons, log in, log out, enrol TOTP.

Authentication only: this module establishes *who* someone is. What they
may do is decided by ``arada.rbac`` against a ``Scope``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.audit import service as audit
from arada.identity import passwords, sessions, totp
from arada.identity.tables import identities, password_credentials, persons
from arada.kernel.config import Settings
from arada.kernel.context import Principal, RequestMeta
from arada.kernel.crypto import Keyring
from arada.kernel.db import Database
from arada.kernel.errors import Conflict, MfaRequired, Unauthenticated, ValidationFailed
from arada.kernel.ids import uuid7

INVALID_CREDENTIALS = "invalid credentials"


@dataclass(frozen=True, slots=True)
class PersonSummary:
    id: UUID
    display_name: str
    status: str
    username: str | None
    totp: str  # none | pending | confirmed


def _validate_display_name(display_name: str) -> str:
    cleaned = " ".join(display_name.split())
    if not 1 <= len(cleaned) <= 120:
        raise ValidationFailed(errors={"display_name": ["must be 1-120 characters"]})
    return cleaned


async def create_person_with_password(
    conn: AsyncConnection,
    meta: RequestMeta,
    *,
    actor_person_id: UUID | None,
    audit_tenant_id: UUID | None,
    username: str,
    password: str,
    display_name: str,
) -> UUID:
    """Create a person with a password identity. Callers authorise first."""
    uname = passwords.normalise_username(username)
    passwords.validate_username(uname)
    name = _validate_display_name(display_name)
    password_hash = await passwords.hash_password(password)

    person_id, identity_id = uuid7(), uuid7()
    try:
        async with conn.begin_nested():
            await conn.execute(insert(persons).values(id=person_id, display_name=name))
            await conn.execute(
                insert(identities).values(
                    id=identity_id, person_id=person_id, provider="password", subject=uname
                )
            )
    except IntegrityError as exc:
        raise Conflict("username is not available") from exc
    await conn.execute(
        insert(password_credentials).values(identity_id=identity_id, password_hash=password_hash)
    )
    await audit.record(
        conn,
        meta,
        actor_person_id=actor_person_id,
        tenant_id=audit_tenant_id,
        action="identity.person_created",
        resource_type="person",
        resource_id=person_id,
        after={"username": uname, "display_name": name},
    )
    return person_id


async def login(
    db: Database,
    settings: Settings,
    keyring: Keyring,
    meta: RequestMeta,
    *,
    username: str,
    password: str,
    totp_code: str | None,
) -> sessions.IssuedSession:
    uname = passwords.normalise_username(username)
    async with db.transaction() as conn:
        row = (
            await conn.execute(
                select(
                    identities.c.id.label("identity_id"),
                    identities.c.person_id,
                    password_credentials.c.password_hash,
                    password_credentials.c.locked_until,
                    persons.c.status,
                )
                .join(password_credentials, password_credentials.c.identity_id == identities.c.id)
                .join(persons, persons.c.id == identities.c.person_id)
                .where(and_(identities.c.provider == "password", identities.c.subject == uname))
            )
        ).first()
        factor = await totp.status(conn, row.person_id) if row else "none"

    now = sessions.now_utc()
    locked = bool(row and row.locked_until and row.locked_until > now)
    password_ok = await passwords.verify_password(
        row.password_hash if row is not None and not locked else None, password
    )

    if row is None or locked or not password_ok or row.status != "active":
        async with db.transaction() as conn:
            if row is not None and not locked and not password_ok:
                await _count_failure(conn, settings, meta, row.identity_id, row.person_id)
            await audit.record(
                conn,
                meta,
                actor_person_id=row.person_id if row else None,
                tenant_id=None,
                action="auth.login_failed",
                resource_type="identity",
                resource_id=row.identity_id if row else None,
                outcome="failure",
                reason="locked" if locked else ("disabled" if row and password_ok else None),
                after={"username": uname} if passwords.USERNAME.match(uname) else None,
            )
        raise Unauthenticated(INVALID_CREDENTIALS)

    rehash = passwords.needs_rehash(row.password_hash)
    new_hash = await passwords.hash_password(password) if rehash else None

    mfa_verified = False
    totp_failed = False
    async with db.transaction() as conn:
        if factor == "confirmed":
            if not totp_code:
                raise MfaRequired("a TOTP code is required for this account")
            if await totp.verify(
                conn, keyring, person_id=row.person_id, code=totp_code, require_confirmed=True
            ):
                mfa_verified = True
            else:
                totp_failed = True
                await _count_failure(conn, settings, meta, row.identity_id, row.person_id)
                await audit.record(
                    conn,
                    meta,
                    actor_person_id=row.person_id,
                    tenant_id=None,
                    action="auth.login_failed",
                    resource_type="identity",
                    resource_id=row.identity_id,
                    outcome="failure",
                    reason="invalid second factor",
                )
        if not totp_failed:
            values: dict[str, object] = {"failed_attempts": 0, "locked_until": None}
            if new_hash:
                values["password_hash"] = new_hash
            await conn.execute(
                update(password_credentials)
                .where(password_credentials.c.identity_id == row.identity_id)
                .values(**values)
            )
            issued = await sessions.issue(
                conn, settings, meta, person_id=row.person_id, mfa_verified=mfa_verified
            )
            await audit.record(
                conn,
                meta,
                actor_person_id=row.person_id,
                tenant_id=None,
                action="auth.login_succeeded",
                resource_type="session",
                resource_id=issued.session_id,
                after={"mfa_verified": mfa_verified},
            )
    if totp_failed:
        raise Unauthenticated(INVALID_CREDENTIALS)
    return issued


async def _count_failure(
    conn: AsyncConnection,
    settings: Settings,
    meta: RequestMeta,
    identity_id: UUID,
    person_id: UUID,
) -> None:
    """Atomically count a failed attempt; lock the account at the threshold."""
    failures = (
        await conn.execute(
            update(password_credentials)
            .where(password_credentials.c.identity_id == identity_id)
            .values(failed_attempts=password_credentials.c.failed_attempts + 1)
            .returning(password_credentials.c.failed_attempts)
        )
    ).scalar_one()
    if failures >= settings.login_max_failures:
        await conn.execute(
            update(password_credentials)
            .where(password_credentials.c.identity_id == identity_id)
            .values(
                failed_attempts=0,
                locked_until=sessions.now_utc() + timedelta(minutes=settings.login_lockout_minutes),
            )
        )
        await audit.record(
            conn,
            meta,
            actor_person_id=person_id,
            tenant_id=None,
            action="auth.account_locked",
            resource_type="identity",
            resource_id=identity_id,
            outcome="failure",
            reason=f"{failures} consecutive failures",
        )


async def logout(db: Database, meta: RequestMeta, principal: Principal) -> None:
    async with db.transaction(person_id=principal.person_id) as conn:
        await sessions.revoke(conn, principal.session_id, "logout")
        await audit.record(
            conn,
            meta,
            actor_person_id=principal.person_id,
            tenant_id=None,
            action="auth.logout",
            resource_type="session",
            resource_id=principal.session_id,
        )


async def summary(conn: AsyncConnection, person_id: UUID) -> PersonSummary:
    row = (
        await conn.execute(
            select(persons.c.id, persons.c.display_name, persons.c.status, identities.c.subject)
            .outerjoin(
                identities,
                and_(identities.c.person_id == persons.c.id, identities.c.provider == "password"),
            )
            .where(persons.c.id == person_id)
        )
    ).first()
    if row is None:
        raise Unauthenticated()
    return PersonSummary(
        id=row.id,
        display_name=row.display_name,
        status=row.status,
        username=row.subject,
        totp=await totp.status(conn, person_id),
    )


async def begin_totp_enrolment(
    db: Database, settings: Settings, keyring: Keyring, meta: RequestMeta, principal: Principal
) -> totp.Enrolment:
    async with db.transaction(person_id=principal.person_id) as conn:
        me = await summary(conn, principal.person_id)
        enrolment = await totp.begin_enrolment(
            conn,
            keyring,
            person_id=principal.person_id,
            account=me.username or str(principal.person_id),
            issuer=settings.totp_issuer,
        )
        await audit.record(
            conn,
            meta,
            actor_person_id=principal.person_id,
            tenant_id=None,
            action="mfa.totp_enrolment_started",
            resource_type="person",
            resource_id=principal.person_id,
        )
    return enrolment


async def confirm_totp(
    db: Database, keyring: Keyring, meta: RequestMeta, principal: Principal, code: str
) -> None:
    ok = False
    async with db.transaction(person_id=principal.person_id) as conn:
        if await totp.status(conn, principal.person_id) != "pending":
            raise Conflict("no pending TOTP enrolment")
        ok = await totp.verify(
            conn, keyring, person_id=principal.person_id, code=code, require_confirmed=False
        )
        if ok:
            await totp.confirm(conn, principal.person_id)
            # The session that proved possession of the factor is now verified.
            await sessions.mark_mfa_verified(conn, principal.session_id)
            await audit.record(
                conn,
                meta,
                actor_person_id=principal.person_id,
                tenant_id=None,
                action="mfa.totp_confirmed",
                resource_type="person",
                resource_id=principal.person_id,
            )
    if not ok:
        raise ValidationFailed(errors={"code": ["invalid or expired code"]})
