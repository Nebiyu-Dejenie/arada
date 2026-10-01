"""Customer scope construction (ADR-036): host → tenant → session → scope.

The staff path (``access.scopes``) and this path never share credentials:
staff tokens live in ``control.sessions``, customer tokens in
``control.customer_sessions`` under FORCE RLS. A customer token is looked up
only inside the tenant the request host resolves to, so it is useless at any
other merchant's host, and it is never accepted by staff routes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arada.customers import sessions as customer_sessions
from arada.kernel.config import Settings
from arada.kernel.context import RequestMeta, bind_tenant, bind_user
from arada.kernel.db import Database, set_context
from arada.kernel.errors import Unauthenticated
from arada.kernel.scope import CustomerScope
from arada.tenancy import service as tenancy


@asynccontextmanager
async def customer_scope(
    db: Database, settings: Settings, meta: RequestMeta, *, host: str, token: str
) -> AsyncIterator[CustomerScope]:
    """One transaction: resolve the tenant from the host, then the session in it.

    An unknown host and an unknown token are the same 401: no customer session
    can exist for a host that is not a merchant.
    """
    async with db.transaction() as conn:
        tenant = await tenancy.resolve_by_host(conn, host)
        if tenant is None:
            raise Unauthenticated()
        await set_context(conn, tenant_id=tenant.id, person_id=None)
        principal = await customer_sessions.authenticate(
            conn, settings, tenant_id=tenant.id, token=token
        )
        await set_context(conn, tenant_id=tenant.id, person_id=principal.person_id)
        bind_tenant(tenant.id)
        bind_user(principal.person_id)
        yield CustomerScope(conn=conn, meta=meta, tenant=tenant, principal=principal)
