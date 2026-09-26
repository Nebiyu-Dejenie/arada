"""Scope construction: the single place where authorisation context is built.

Order of operations per request (Permanent Command §5):
edge → authentication (done by the caller) → tenant resolution →
grants (authorisation data) → business logic, all inside one transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arada.kernel.config import Settings
from arada.kernel.context import Principal, RequestMeta, bind_tenant
from arada.kernel.db import Database, set_context
from arada.kernel.errors import NotFound
from arada.kernel.scope import Grants, MfaStepUpRequired, Scope
from arada.rbac import service as rbac
from arada.tenancy import service as tenancy


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


@asynccontextmanager
async def tenant_scope(
    db: Database, settings: Settings, meta: RequestMeta, principal: Principal, slug: str
) -> AsyncIterator[Scope]:
    """Scope for acting inside one tenant, resolved from trusted server state.

    The tenant comes from the slug via the tenants table; the transaction's
    RLS context is set to it before any tenant data is read. A person with no
    membership and no privileged grant for the tenant's vertical gets 404,
    exactly as if the tenant did not exist.
    """
    async with db.transaction(person_id=principal.person_id) as conn:
        tenant = await tenancy.resolve_by_slug(conn, slug)
        if tenant is None:
            raise NotFound("tenant not found")
        await set_context(conn, tenant_id=tenant.id, person_id=principal.person_id)
        privileged = await rbac.load_privileged_grants(
            conn, principal.person_id, mfa_ok=rbac.mfa_satisfied(settings, principal)
        )
        tenant_perms = await rbac.load_tenant_grants(conn, principal.person_id)
        grants = Grants(
            platform=privileged.platform,
            vertical=privileged.vertical,
            tenant=tenant_perms,
            withheld_for_mfa=privileged.withheld_for_mfa,
        )
        if not tenant_perms and not grants.privileged("tenants.read", tenant.vertical_id):
            if "tenants.read" in grants.withheld_for_mfa:
                raise MfaStepUpRequired()
            raise NotFound("tenant not found")
        bind_tenant(tenant.id)
        yield Scope(conn=conn, meta=meta, principal=principal, tenant=tenant, grants=grants)
