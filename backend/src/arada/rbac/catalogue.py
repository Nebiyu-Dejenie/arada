"""The permission and system-role catalogue (10_RBAC.md, charter §10, §32).

This is the code mirror of what migration 0004 seeds into the database. The
database is authoritative at runtime; ``tests/unit/test_rbac_catalogue.py``
and ``tests/integration/test_rbac_db.py`` fail if the two drift. Changing the
catalogue therefore always means a new migration plus a code change.

Scopes: P = platform, V = vertical, T = tenant. A permission may only appear
in a role whose scope is listed for it; the database enforces this too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ScopeType = Literal["platform", "vertical", "tenant"]
P: tuple[ScopeType, ...] = ("platform",)
PV: tuple[ScopeType, ...] = ("platform", "vertical")
PT: tuple[ScopeType, ...] = ("platform", "tenant")
PVT: tuple[ScopeType, ...] = ("platform", "vertical", "tenant")
T: tuple[ScopeType, ...] = ("tenant",)

PERMISSIONS: dict[str, tuple[ScopeType, ...]] = {
    # Platform administration
    "platform.settings.manage": P,
    "security.manage": P,
    "infra.read": P,
    "deploy.manage": P,
    "flags.manage": P,
    "plans.manage": P,
    "users.read": P,
    "users.manage": P,
    "roles.manage": P,
    "verticals.manage": P,
    # Blueprints
    "attributes.manage": PV,
    "blueprints.read": PVT,
    "blueprints.manage": PV,
    "blueprints.publish": PV,
    "blueprints.migrate": PV,
    # Tenants and staff
    "tenants.create": PV,
    "tenants.read": PVT,
    "tenants.manage": PVT,
    "tenants.suspend": PV,
    "tenants.archive": P,
    "tenants.support_access": P,
    "domains.manage": P,
    "bots.manage": P,
    "bots.rotate_token": P,
    "audit.read": PVT,
    "staff.read": PVT,
    "staff.manage": PVT,
    # Commerce (enforced by endpoints from Phase 3)
    "products.read": PVT,
    "products.write": PT,
    "products.publish": T,
    "inventory.adjust": T,
    "orders.read": PVT,
    "orders.write": T,
    "orders.create": T,
    "orders.fulfil": T,
    "orders.cancel": PT,
    "orders.refund": PT,
    "customers.read": PVT,
    "customers.contact": T,
    "customers.export": T,
    # Payments and finance (enforced by endpoints from Phase 4)
    "payments.read": PVT,
    "payments.capture": PT,
    "payments.refund": PT,
    "payments.configure": PT,
    "finance.read": PVT,
    "finance.export": PVT,
    "finance.reconcile": P,
    "finance.adjust": P,
    "finance.commission.manage": PV,
    "finance.payout": P,
    "finance.payout.approve": P,
    "finance.payout_destination.manage": T,
    # Engagement, delivery, support, AI, analytics (later phases)
    "promotions.manage": T,
    "reviews.moderate": PT,
    "notifications.send": PT,
    "campaigns.manage": T,
    "ads.manage": PT,
    "delivery.read": PT,
    "delivery.update": T,
    "delivery.assign": T,
    "support.read": PT,
    "support.respond": PT,
    "disputes.manage": P,
    "ai.use": PVT,
    "ai.configure": PT,
    "ai.budget.manage": P,
    "analytics.read": PVT,
    "analytics.export": PVT,
}


def _in(scope: ScopeType) -> frozenset[str]:
    return frozenset(k for k, scopes in PERMISSIONS.items() if scope in scopes)


_PLATFORM_ALL = _in("platform")
_TENANT_ALL = _in("tenant")

_PLATFORM_ADMIN_EXCLUDED = frozenset(
    {
        "security.manage",
        "roles.manage",
        "tenants.support_access",
        "finance.reconcile",
        "finance.adjust",
        "finance.commission.manage",
        "finance.payout",
        "finance.payout.approve",
        "payments.capture",
        "payments.refund",
        "payments.configure",
        "orders.refund",
        "ai.budget.manage",
    }
)


@dataclass(frozen=True, slots=True)
class RoleDef:
    scope: ScopeType
    description: str
    permissions: frozenset[str]


ROLES: dict[str, RoleDef] = {
    "SUPER_ADMIN": RoleDef(
        "platform", "Owner of the platform: every platform permission", _PLATFORM_ALL
    ),
    "PLATFORM_ADMIN": RoleDef(
        "platform",
        "Operates verticals, blueprints, tenants, bots, domains and flags; no money or security",
        _PLATFORM_ALL - _PLATFORM_ADMIN_EXCLUDED,
    ),
    "PLATFORM_FINANCE": RoleDef(
        "platform",
        "Platform finance: reconciliation, adjustments, commissions, payouts",
        frozenset(
            {
                "finance.read",
                "finance.export",
                "finance.reconcile",
                "finance.adjust",
                "finance.commission.manage",
                "finance.payout",
                "finance.payout.approve",
                "payments.read",
                "payments.refund",
                "orders.read",
                "orders.refund",
                "tenants.read",
                "audit.read",
                "analytics.read",
                "analytics.export",
            }
        ),
    ),
    "PLATFORM_SUPPORT": RoleDef(
        "platform",
        "Support: read-only tenant overview; tenant data only through just-in-time grants",
        frozenset(
            {
                "tenants.read",
                "support.read",
                "support.respond",
                "orders.read",
                "payments.read",
                "staff.read",
                "blueprints.read",
                "tenants.support_access",
            }
        ),
    ),
    "VERTICAL_ADMIN": RoleDef(
        "vertical",
        "Manages one vertical: its blueprints, attributes and merchants",
        frozenset(
            {
                "attributes.manage",
                "blueprints.read",
                "blueprints.manage",
                "blueprints.publish",
                "blueprints.migrate",
                "tenants.create",
                "tenants.read",
                "tenants.manage",
                "tenants.suspend",
                "audit.read",
                "staff.read",
                "staff.manage",
                "products.read",
                "orders.read",
                "analytics.read",
                "ai.use",
            }
        ),
    ),
    "VERTICAL_FINANCE": RoleDef(
        "vertical",
        "Finance for the merchants of one vertical (read and export)",
        frozenset(
            {
                "finance.read",
                "finance.export",
                "payments.read",
                "orders.read",
                "tenants.read",
                "analytics.read",
                "analytics.export",
            }
        ),
    ),
    "TENANT_OWNER": RoleDef("tenant", "Owns the merchant: every tenant permission", _TENANT_ALL),
    "TENANT_ADMIN": RoleDef(
        "tenant",
        "Runs the merchant except payment provider and payout destination",
        _TENANT_ALL - {"payments.configure", "finance.payout_destination.manage"},
    ),
    "TENANT_FINANCE": RoleDef(
        "tenant",
        "Merchant finance: read, export, refunds",
        frozenset(
            {
                "finance.read",
                "finance.export",
                "payments.read",
                "payments.refund",
                "orders.read",
                "orders.refund",
                "tenants.read",
                "audit.read",
                "analytics.read",
                "analytics.export",
                "blueprints.read",
            }
        ),
    ),
    "TENANT_MANAGER": RoleDef(
        "tenant",
        "Catalog, orders, promotions and delivery",
        frozenset(
            {
                "tenants.read",
                "blueprints.read",
                "staff.read",
                "products.read",
                "products.write",
                "products.publish",
                "inventory.adjust",
                "orders.read",
                "orders.write",
                "orders.create",
                "orders.fulfil",
                "orders.cancel",
                "customers.read",
                "customers.contact",
                "promotions.manage",
                "reviews.moderate",
                "campaigns.manage",
                "delivery.read",
                "delivery.update",
                "delivery.assign",
                "support.read",
                "support.respond",
                "analytics.read",
                "ai.use",
                "notifications.send",
            }
        ),
    ),
    "TENANT_STAFF": RoleDef(
        "tenant",
        "Day-to-day fulfilment",
        frozenset(
            {
                "tenants.read",
                "blueprints.read",
                "products.read",
                "orders.read",
                "orders.fulfil",
                "inventory.adjust",
                "customers.read",
                "delivery.read",
                "delivery.update",
                "support.read",
            }
        ),
    ),
}

TENANT_ROLES = frozenset(k for k, r in ROLES.items() if r.scope == "tenant")
PLATFORM_ROLES = frozenset(k for k, r in ROLES.items() if r.scope == "platform")
VERTICAL_ROLES = frozenset(k for k, r in ROLES.items() if r.scope == "vertical")

# Tenant roles that hold money, staff-management or security permissions are
# usable only in an MFA-verified session (09_SECURITY.md §3, ADR-035). Every
# other tenant role (manager, staff) works with a password-only session.
MFA_REQUIRED_TENANT_ROLES = frozenset({"TENANT_OWNER", "TENANT_ADMIN", "TENANT_FINANCE"})
