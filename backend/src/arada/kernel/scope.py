"""Authorisation scope: the only object services accept to act.

A ``Scope`` bundles the open transaction, the acting principal, the resolved
tenant (if any) and the permissions granted to the principal *for this
request*. Services call ``require`` before doing anything protected, so
authorisation holds whether the caller is the HTTP API, the CLI or a future
worker (Master Directive §6 "service-level authorization").

Authentication (who you are) is established before a scope exists;
authorisation (what you may do) is decided here, never in the UI.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from arada.kernel.context import Principal, RequestMeta, TenantRef
from arada.kernel.errors import AppError, Forbidden

WRITABLE_TENANT_STATUSES = frozenset({"draft", "active"})


class MfaStepUpRequired(AppError):
    status = 403
    code = "mfa-required-for-scope"
    title = "This action requires a session verified with a second factor"


@dataclass(frozen=True, slots=True)
class Grants:
    platform: frozenset[str] = frozenset()
    vertical: Mapping[UUID, frozenset[str]] = field(default_factory=lambda: MappingProxyType({}))
    tenant: frozenset[str] = frozenset()
    # Permissions the principal holds through privileged (platform/vertical)
    # roles but which are withheld because the session is not MFA-verified.
    withheld_for_mfa: frozenset[str] = frozenset()

    def privileged(self, permission: str, vertical_id: UUID | None) -> bool:
        if permission in self.platform:
            return True
        return vertical_id is not None and permission in self.vertical.get(vertical_id, frozenset())

    def allows(self, permission: str, vertical_id: UUID | None) -> bool:
        return self.privileged(permission, vertical_id) or permission in self.tenant

    def all_for(self, vertical_id: UUID | None) -> frozenset[str]:
        extra = self.vertical.get(vertical_id, frozenset()) if vertical_id else frozenset()
        return self.platform | extra | self.tenant


@dataclass(slots=True)
class Scope:
    conn: AsyncConnection
    meta: RequestMeta
    principal: Principal | None
    tenant: TenantRef | None
    grants: Grants

    @property
    def tenant_ref(self) -> TenantRef:
        """The scope's tenant; a programming error to ask for it outside one."""
        if self.tenant is None:
            raise RuntimeError("this operation requires a tenant scope")
        return self.tenant

    @property
    def actor_person_id(self) -> UUID | None:
        return self.principal.person_id if self.principal else None

    def has(self, permission: str, *, vertical_id: UUID | None = None) -> bool:
        vid = vertical_id or (self.tenant.vertical_id if self.tenant else None)
        return self.grants.allows(permission, vid)

    def require(
        self, permission: str, *, vertical_id: UUID | None = None, write: bool = False
    ) -> None:
        """Raise unless the principal holds ``permission`` in this scope.

        ``write=True`` additionally blocks tenant-level principals from
        changing a tenant that is not writable (for example suspended);
        platform and vertical administrators may still act on it.
        """
        vid = vertical_id or (self.tenant.vertical_id if self.tenant else None)
        if self.grants.privileged(permission, vid):
            return
        if permission in self.grants.tenant:
            if write and self.tenant and self.tenant.status not in WRITABLE_TENANT_STATUSES:
                raise Forbidden("tenant is not writable in its current status")
            return
        if permission in self.grants.withheld_for_mfa:
            raise MfaStepUpRequired()
        raise Forbidden()
