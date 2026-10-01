"""Request-scoped context: who is acting, on which tenant, under which request.

``RequestMeta`` is created by the HTTP middleware (or the CLI) and carried into
every service call. Correlation fields are also bound to ``contextvars`` so
every log line carries them (Permanent Command §24).
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

Source = Literal["api", "cli", "system", "worker"]

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
_tenant_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_id", default=None)
_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)


@dataclass(frozen=True, slots=True)
class RequestMeta:
    request_id: str
    trace_id: str
    source: Source
    ip: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated person acting through a session."""

    person_id: UUID
    session_id: UUID
    mfa_verified_at: datetime | None = None

    @property
    def mfa_verified(self) -> bool:
        return self.mfa_verified_at is not None


@dataclass(frozen=True, slots=True)
class CustomerPrincipal:
    """An authenticated customer: one person, as seen by exactly one tenant.

    Deliberately a different type from ``Principal``: a customer session can
    never be passed where a staff session is expected, and it carries no
    roles or permissions (ADR-036).
    """

    tenant_id: UUID
    customer_id: UUID
    person_id: UUID
    session_id: UUID


@dataclass(frozen=True, slots=True)
class TenantRef:
    id: UUID
    slug: str
    vertical_id: UUID
    status: str


@dataclass(slots=True)
class CorrelationFields:
    request_id: str | None = None
    trace_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


def bind_request(request_id: str, trace_id: str) -> None:
    _request_id.set(request_id)
    _trace_id.set(trace_id)
    _tenant_id.set(None)
    _user_id.set(None)


def bind_tenant(tenant_id: UUID | None) -> None:
    _tenant_id.set(str(tenant_id) if tenant_id else None)


def bind_user(person_id: UUID | None) -> None:
    _user_id.set(str(person_id) if person_id else None)


def current_correlation() -> CorrelationFields:
    return CorrelationFields(
        request_id=_request_id.get(),
        trace_id=_trace_id.get(),
        tenant_id=_tenant_id.get(),
        user_id=_user_id.get(),
    )
