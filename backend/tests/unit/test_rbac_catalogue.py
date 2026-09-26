"""The permission catalogue matches the charter and is internally consistent."""

from __future__ import annotations

import pytest

from arada.rbac.catalogue import PERMISSIONS, ROLES

CHARTER_PERMISSIONS = {
    # Permanent Command §10 and the Phase 1 approval message.
    "products.read", "products.write", "orders.read", "orders.write", "orders.refund",
    "payments.read", "payments.capture", "payments.refund", "finance.read", "finance.payout",
    "users.read", "users.manage", "staff.read", "staff.manage", "blueprints.read",
    "blueprints.manage", "tenants.read", "tenants.manage",
}  # fmt: skip

CHARTER_ROLES = {
    "SUPER_ADMIN", "PLATFORM_ADMIN", "PLATFORM_FINANCE", "PLATFORM_SUPPORT", "VERTICAL_ADMIN",
    "VERTICAL_FINANCE", "TENANT_OWNER", "TENANT_ADMIN", "TENANT_FINANCE", "TENANT_MANAGER",
    "TENANT_STAFF",
}  # fmt: skip


def test_charter_permissions_and_roles_exist() -> None:
    assert PERMISSIONS.keys() >= CHARTER_PERMISSIONS
    assert ROLES.keys() >= CHARTER_ROLES


@pytest.mark.parametrize("role", sorted(ROLES))
def test_role_permissions_are_valid_for_its_scope(role: str) -> None:
    definition = ROLES[role]
    for permission in definition.permissions:
        assert permission in PERMISSIONS, permission
        assert definition.scope in PERMISSIONS[permission], (role, permission)


def test_role_hierarchy_nests() -> None:
    """SUPER_ADMIN > PLATFORM_ADMIN; TENANT_OWNER > ADMIN > MANAGER > STAFF."""
    perms = {k: r.permissions for k, r in ROLES.items()}
    assert perms["PLATFORM_ADMIN"] < perms["SUPER_ADMIN"]
    assert perms["TENANT_ADMIN"] < perms["TENANT_OWNER"]
    assert perms["TENANT_MANAGER"] < perms["TENANT_ADMIN"]
    assert perms["TENANT_STAFF"] < perms["TENANT_MANAGER"]


def test_staff_cannot_administer() -> None:
    staff = ROLES["TENANT_STAFF"].permissions
    assert not staff & {"staff.manage", "tenants.manage", "audit.read", "payments.refund"}


def test_platform_admin_cannot_move_money_or_grant_roles() -> None:
    admin = ROLES["PLATFORM_ADMIN"].permissions
    assert not admin & {
        "roles.manage", "security.manage", "finance.payout", "finance.adjust",
        "payments.refund", "payments.capture",
    }  # fmt: skip
