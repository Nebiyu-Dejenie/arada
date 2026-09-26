"""Scope construction: the single place where authorisation context is built.

Order of operations per request (Permanent Command §5):
edge → authentication (done by the caller) → tenant resolution →
grants (authorisation data) → business logic, all inside one transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arada.kernel.config import Settings
from arada.kernel.context import Principal, RequestMeta
from arada.kernel.db import Database
from arada.kernel.scope import Scope
from arada.rbac import service as rbac


@asynccontextmanager
async def platform_scope(
    db: Database, settings: Settings, meta: RequestMeta, principal: Principal
) -> AsyncIterator[Scope]:
    """Scope for platform-level operations (no tenant context)."""
    async with db.transaction(person_id=principal.person_id) as conn:
        grants = await rbac.load_privileged_grants(
            conn, principal.person_id, mfa_ok=rbac.mfa_satisfied(settings, principal)
        )
        yield Scope(conn=conn, meta=meta, principal=principal, tenant=None, grants=grants)
