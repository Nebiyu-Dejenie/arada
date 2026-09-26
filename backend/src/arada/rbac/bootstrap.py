"""First-run bootstrap of the platform owner (CLI only, never via the API)."""

from __future__ import annotations

import secrets
from uuid import UUID

from arada.audit import service as audit
from arada.identity.service import create_person_with_password
from arada.kernel.config import Settings
from arada.kernel.context import RequestMeta
from arada.kernel.db import Database
from arada.kernel.errors import Conflict
from arada.rbac import service as rbac


async def bootstrap_super_admin(
    settings: Settings, username: str, display_name: str, password: str
) -> UUID:
    """Create the first SUPER_ADMIN. Refuses if one already exists.

    The new account must enrol TOTP before any platform permission becomes
    usable (privileged scopes require an MFA-verified session).
    """
    meta = RequestMeta(
        request_id=secrets.token_hex(16), trace_id=secrets.token_hex(16), source="cli"
    )
    db = Database(settings, app_name="arada-cli")
    try:
        async with db.transaction() as conn:
            # Serialise concurrent bootstraps on a transaction-scoped advisory lock.
            await conn.exec_driver_sql("SELECT pg_advisory_xact_lock(4242001)")
            if await rbac.any_super_admin(conn):
                raise Conflict("a SUPER_ADMIN already exists; use the API to grant roles")
            person_id = await create_person_with_password(
                conn,
                meta,
                actor_person_id=None,
                audit_tenant_id=None,
                username=username,
                password=password,
                display_name=display_name,
            )
            await rbac.assign_super_admin_unchecked(conn, person_id)
            await audit.record(
                conn,
                meta,
                actor_person_id=None,
                tenant_id=None,
                action="rbac.super_admin_bootstrapped",
                resource_type="person",
                resource_id=person_id,
                after={"role": "SUPER_ADMIN"},
            )
        return person_id
    finally:
        await db.dispose()
