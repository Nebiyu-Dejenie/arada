"""RBAC catalogue, verticals, and platform/vertical role assignments.

Revision ID: 0004_rbac
Revises: 0003_identity
Create Date: 2026-09-26

The permission and role catalogue is seeded from the frozen literals below
(never imported from application code, which may change after this migration
ships). A trigger guarantees a role can only hold permissions valid for its
scope, and composite foreign keys guarantee an assignment table can only hold
roles of its own scope.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_rbac"
down_revision: str | None = "0003_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# fmt: off
PERMISSIONS_V1: dict[str, list[str]] = {
    'platform.settings.manage': ['platform'],
    'security.manage': ['platform'],
    'infra.read': ['platform'],
    'deploy.manage': ['platform'],
    'flags.manage': ['platform'],
    'plans.manage': ['platform'],
    'users.read': ['platform'],
    'users.manage': ['platform'],
    'roles.manage': ['platform'],
    'verticals.manage': ['platform'],
    'attributes.manage': ['platform', 'vertical'],
    'blueprints.read': ['platform', 'vertical', 'tenant'],
    'blueprints.manage': ['platform', 'vertical'],
    'blueprints.publish': ['platform', 'vertical'],
    'blueprints.migrate': ['platform', 'vertical'],
    'tenants.create': ['platform', 'vertical'],
    'tenants.read': ['platform', 'vertical', 'tenant'],
    'tenants.manage': ['platform', 'vertical', 'tenant'],
    'tenants.suspend': ['platform', 'vertical'],
    'tenants.archive': ['platform'],
    'tenants.support_access': ['platform'],
    'domains.manage': ['platform'],
    'bots.manage': ['platform'],
    'bots.rotate_token': ['platform'],
    'audit.read': ['platform', 'vertical', 'tenant'],
    'staff.read': ['platform', 'vertical', 'tenant'],
    'staff.manage': ['platform', 'vertical', 'tenant'],
    'products.read': ['platform', 'vertical', 'tenant'],
    'products.write': ['platform', 'tenant'],
    'products.publish': ['tenant'],
    'inventory.adjust': ['tenant'],
    'orders.read': ['platform', 'vertical', 'tenant'],
    'orders.write': ['tenant'],
    'orders.create': ['tenant'],
    'orders.fulfil': ['tenant'],
    'orders.cancel': ['platform', 'tenant'],
    'orders.refund': ['platform', 'tenant'],
    'customers.read': ['platform', 'vertical', 'tenant'],
    'customers.contact': ['tenant'],
    'customers.export': ['tenant'],
    'payments.read': ['platform', 'vertical', 'tenant'],
    'payments.capture': ['platform', 'tenant'],
    'payments.refund': ['platform', 'tenant'],
    'payments.configure': ['platform', 'tenant'],
    'finance.read': ['platform', 'vertical', 'tenant'],
    'finance.export': ['platform', 'vertical', 'tenant'],
    'finance.reconcile': ['platform'],
    'finance.adjust': ['platform'],
    'finance.commission.manage': ['platform', 'vertical'],
    'finance.payout': ['platform'],
    'finance.payout.approve': ['platform'],
    'finance.payout_destination.manage': ['tenant'],
    'promotions.manage': ['tenant'],
    'reviews.moderate': ['platform', 'tenant'],
    'notifications.send': ['platform', 'tenant'],
    'campaigns.manage': ['tenant'],
    'ads.manage': ['platform', 'tenant'],
    'delivery.read': ['platform', 'tenant'],
    'delivery.update': ['tenant'],
    'delivery.assign': ['tenant'],
    'support.read': ['platform', 'tenant'],
    'support.respond': ['platform', 'tenant'],
    'disputes.manage': ['platform'],
    'ai.use': ['platform', 'vertical', 'tenant'],
    'ai.configure': ['platform', 'tenant'],
    'ai.budget.manage': ['platform'],
    'analytics.read': ['platform', 'vertical', 'tenant'],
    'analytics.export': ['platform', 'vertical', 'tenant'],
}

ROLES_V1: dict[str, tuple[str, str, list[str]]] = {
    'SUPER_ADMIN': (
        'platform',
        'Owner of the platform: every platform permission',
        [
            'ads.manage',
            'ai.budget.manage',
            'ai.configure',
            'ai.use',
            'analytics.export',
            'analytics.read',
            'attributes.manage',
            'audit.read',
            'blueprints.manage',
            'blueprints.migrate',
            'blueprints.publish',
            'blueprints.read',
            'bots.manage',
            'bots.rotate_token',
            'customers.read',
            'delivery.read',
            'deploy.manage',
            'disputes.manage',
            'domains.manage',
            'finance.adjust',
            'finance.commission.manage',
            'finance.export',
            'finance.payout',
            'finance.payout.approve',
            'finance.read',
            'finance.reconcile',
            'flags.manage',
            'infra.read',
            'notifications.send',
            'orders.cancel',
            'orders.read',
            'orders.refund',
            'payments.capture',
            'payments.configure',
            'payments.read',
            'payments.refund',
            'plans.manage',
            'platform.settings.manage',
            'products.read',
            'products.write',
            'reviews.moderate',
            'roles.manage',
            'security.manage',
            'staff.manage',
            'staff.read',
            'support.read',
            'support.respond',
            'tenants.archive',
            'tenants.create',
            'tenants.manage',
            'tenants.read',
            'tenants.support_access',
            'tenants.suspend',
            'users.manage',
            'users.read',
            'verticals.manage',
        ],
    ),
    'PLATFORM_ADMIN': (
        'platform',
        'Operates verticals, blueprints, tenants, bots, domains and flags; no money or security',
        [
            'ads.manage',
            'ai.configure',
            'ai.use',
            'analytics.export',
            'analytics.read',
            'attributes.manage',
            'audit.read',
            'blueprints.manage',
            'blueprints.migrate',
            'blueprints.publish',
            'blueprints.read',
            'bots.manage',
            'bots.rotate_token',
            'customers.read',
            'delivery.read',
            'deploy.manage',
            'disputes.manage',
            'domains.manage',
            'finance.export',
            'finance.read',
            'flags.manage',
            'infra.read',
            'notifications.send',
            'orders.cancel',
            'orders.read',
            'payments.read',
            'plans.manage',
            'platform.settings.manage',
            'products.read',
            'products.write',
            'reviews.moderate',
            'staff.manage',
            'staff.read',
            'support.read',
            'support.respond',
            'tenants.archive',
            'tenants.create',
            'tenants.manage',
            'tenants.read',
            'tenants.suspend',
            'users.manage',
            'users.read',
            'verticals.manage',
        ],
    ),
    'PLATFORM_FINANCE': (
        'platform',
        'Platform finance: reconciliation, adjustments, commissions, payouts',
        [
            'analytics.export',
            'analytics.read',
            'audit.read',
            'finance.adjust',
            'finance.commission.manage',
            'finance.export',
            'finance.payout',
            'finance.payout.approve',
            'finance.read',
            'finance.reconcile',
            'orders.read',
            'orders.refund',
            'payments.read',
            'payments.refund',
            'tenants.read',
        ],
    ),
    'PLATFORM_SUPPORT': (
        'platform',
        'Support: read-only tenant overview; tenant data only through just-in-time grants',
        [
            'blueprints.read',
            'orders.read',
            'payments.read',
            'staff.read',
            'support.read',
            'support.respond',
            'tenants.read',
            'tenants.support_access',
        ],
    ),
    'VERTICAL_ADMIN': (
        'vertical',
        'Manages one vertical: its blueprints, attributes and merchants',
        [
            'ai.use',
            'analytics.read',
            'attributes.manage',
            'audit.read',
            'blueprints.manage',
            'blueprints.migrate',
            'blueprints.publish',
            'blueprints.read',
            'orders.read',
            'products.read',
            'staff.manage',
            'staff.read',
            'tenants.create',
            'tenants.manage',
            'tenants.read',
            'tenants.suspend',
        ],
    ),
    'VERTICAL_FINANCE': (
        'vertical',
        'Finance for the merchants of one vertical (read and export)',
        [
            'analytics.export',
            'analytics.read',
            'finance.export',
            'finance.read',
            'orders.read',
            'payments.read',
            'tenants.read',
        ],
    ),
    'TENANT_OWNER': (
        'tenant',
        'Owns the merchant: every tenant permission',
        [
            'ads.manage',
            'ai.configure',
            'ai.use',
            'analytics.export',
            'analytics.read',
            'audit.read',
            'blueprints.read',
            'campaigns.manage',
            'customers.contact',
            'customers.export',
            'customers.read',
            'delivery.assign',
            'delivery.read',
            'delivery.update',
            'finance.export',
            'finance.payout_destination.manage',
            'finance.read',
            'inventory.adjust',
            'notifications.send',
            'orders.cancel',
            'orders.create',
            'orders.fulfil',
            'orders.read',
            'orders.refund',
            'orders.write',
            'payments.capture',
            'payments.configure',
            'payments.read',
            'payments.refund',
            'products.publish',
            'products.read',
            'products.write',
            'promotions.manage',
            'reviews.moderate',
            'staff.manage',
            'staff.read',
            'support.read',
            'support.respond',
            'tenants.manage',
            'tenants.read',
        ],
    ),
    'TENANT_ADMIN': (
        'tenant',
        'Runs the merchant except payment provider and payout destination',
        [
            'ads.manage',
            'ai.configure',
            'ai.use',
            'analytics.export',
            'analytics.read',
            'audit.read',
            'blueprints.read',
            'campaigns.manage',
            'customers.contact',
            'customers.export',
            'customers.read',
            'delivery.assign',
            'delivery.read',
            'delivery.update',
            'finance.export',
            'finance.read',
            'inventory.adjust',
            'notifications.send',
            'orders.cancel',
            'orders.create',
            'orders.fulfil',
            'orders.read',
            'orders.refund',
            'orders.write',
            'payments.capture',
            'payments.read',
            'payments.refund',
            'products.publish',
            'products.read',
            'products.write',
            'promotions.manage',
            'reviews.moderate',
            'staff.manage',
            'staff.read',
            'support.read',
            'support.respond',
            'tenants.manage',
            'tenants.read',
        ],
    ),
    'TENANT_FINANCE': (
        'tenant',
        'Merchant finance: read, export, refunds',
        [
            'analytics.export',
            'analytics.read',
            'audit.read',
            'blueprints.read',
            'finance.export',
            'finance.read',
            'orders.read',
            'orders.refund',
            'payments.read',
            'payments.refund',
            'tenants.read',
        ],
    ),
    'TENANT_MANAGER': (
        'tenant',
        'Catalog, orders, promotions and delivery',
        [
            'ai.use',
            'analytics.read',
            'blueprints.read',
            'campaigns.manage',
            'customers.contact',
            'customers.read',
            'delivery.assign',
            'delivery.read',
            'delivery.update',
            'inventory.adjust',
            'notifications.send',
            'orders.cancel',
            'orders.create',
            'orders.fulfil',
            'orders.read',
            'orders.write',
            'products.publish',
            'products.read',
            'products.write',
            'promotions.manage',
            'reviews.moderate',
            'staff.read',
            'support.read',
            'support.respond',
            'tenants.read',
        ],
    ),
    'TENANT_STAFF': (
        'tenant',
        'Day-to-day fulfilment',
        [
            'blueprints.read',
            'customers.read',
            'delivery.read',
            'delivery.update',
            'inventory.adjust',
            'orders.fulfil',
            'orders.read',
            'products.read',
            'support.read',
            'tenants.read',
        ],
    ),
}
# fmt: on


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE control.verticals (
            id         uuid PRIMARY KEY,
            key        text NOT NULL CHECK (key ~ '^[a-z][a-z0-9_]{1,39}$'),
            name_en    text NOT NULL CHECK (length(btrim(name_en)) BETWEEN 1 AND 80),
            name_am    text NULL CHECK (length(btrim(name_am)) BETWEEN 1 AND 80),
            status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
            created_at timestamptz NOT NULL DEFAULT now(),
            created_by uuid NULL REFERENCES control.persons (id),
            CONSTRAINT uq_verticals__key UNIQUE (key)
        )
        """
    )
    op.execute(
        r"""
        CREATE TABLE control.permissions (
            key    text PRIMARY KEY CHECK (key ~ '^[a-z][a-z_]*(\.[a-z][a-z_]*)+$'),
            scopes text[] NOT NULL CHECK (
                cardinality(scopes) BETWEEN 1 AND 3
                AND scopes <@ ARRAY['platform', 'vertical', 'tenant']::text[]
            )
        )
        """
    )
    op.execute(
        r"""
        CREATE TABLE control.roles (
            key         text PRIMARY KEY CHECK (key ~ '^[A-Z][A-Z_]{2,39}$'),
            scope_type  text NOT NULL CHECK (scope_type IN ('platform', 'vertical', 'tenant')),
            description text NOT NULL,
            is_system   boolean NOT NULL DEFAULT true,
            CONSTRAINT uq_roles__key_scope UNIQUE (key, scope_type)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE control.role_permissions (
            role_key       text NOT NULL REFERENCES control.roles (key),
            permission_key text NOT NULL REFERENCES control.permissions (key),
            PRIMARY KEY (role_key, permission_key)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION control.check_role_permission_scope() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM control.roles r
            JOIN control.permissions p ON p.key = NEW.permission_key
            WHERE r.key = NEW.role_key AND r.scope_type = ANY (p.scopes)
          ) THEN
            RAISE EXCEPTION 'permission % is not valid for the scope of role %',
              NEW.permission_key, NEW.role_key USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION control.check_role_permission_scope() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER tr_role_permissions__scope
        BEFORE INSERT OR UPDATE ON control.role_permissions
        FOR EACH ROW EXECUTE FUNCTION control.check_role_permission_scope()
        """
    )
    op.execute(
        """
        CREATE TABLE control.platform_role_assignments (
            person_id  uuid NOT NULL REFERENCES control.persons (id),
            role_key   text NOT NULL,
            scope_type text NOT NULL DEFAULT 'platform' CHECK (scope_type = 'platform'),
            granted_by uuid NULL REFERENCES control.persons (id),
            granted_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (person_id, role_key),
            CONSTRAINT fk_platform_role_assignments__role
                FOREIGN KEY (role_key, scope_type) REFERENCES control.roles (key, scope_type)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE control.vertical_role_assignments (
            person_id   uuid NOT NULL REFERENCES control.persons (id),
            vertical_id uuid NOT NULL REFERENCES control.verticals (id),
            role_key    text NOT NULL,
            scope_type  text NOT NULL DEFAULT 'vertical' CHECK (scope_type = 'vertical'),
            granted_by  uuid NULL REFERENCES control.persons (id),
            granted_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (person_id, vertical_id, role_key),
            CONSTRAINT fk_vertical_role_assignments__role
                FOREIGN KEY (role_key, scope_type) REFERENCES control.roles (key, scope_type)
        )
        """
    )

    permissions = sa.table("permissions", sa.column("key"), sa.column("scopes"), schema="control")
    roles = sa.table(
        "roles",
        sa.column("key"),
        sa.column("scope_type"),
        sa.column("description"),
        schema="control",
    )
    role_permissions = sa.table(
        "role_permissions", sa.column("role_key"), sa.column("permission_key"), schema="control"
    )
    op.bulk_insert(permissions, [{"key": k, "scopes": v} for k, v in PERMISSIONS_V1.items()])
    op.bulk_insert(
        roles,
        [{"key": k, "scope_type": s, "description": d} for k, (s, d, _) in ROLES_V1.items()],
    )
    op.bulk_insert(
        role_permissions,
        [
            {"role_key": k, "permission_key": p}
            for k, (_, _, perms) in ROLES_V1.items()
            for p in perms
        ],
    )

    op.execute(
        "GRANT SELECT ON control.permissions, control.roles, control.role_permissions TO arada_app, arada_platform_reader"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.verticals TO arada_app")
    op.execute(
        "GRANT SELECT, INSERT, DELETE ON control.platform_role_assignments, control.vertical_role_assignments TO arada_app"
    )
    op.execute(
        "GRANT SELECT ON control.verticals, control.platform_role_assignments, control.vertical_role_assignments TO arada_platform_reader"
    )


def downgrade() -> None:
    for table in (
        "vertical_role_assignments",
        "platform_role_assignments",
        "role_permissions",
        "roles",
        "permissions",
        "verticals",
    ):
        op.execute(f"DROP TABLE control.{table}")
    op.execute("DROP FUNCTION control.check_role_permission_scope()")
