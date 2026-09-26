"""Feature flags with platform, vertical and tenant overrides.

Revision ID: 0007_feature_flags
Revises: 0006_tenancy
Create Date: 2026-09-26

Flags are platform configuration (control plane, not tenant-owned data).
Evaluation order, most decisive first:
  enforced platform override (kill switch) > tenant override >
  vertical override > tenant's blueprint default > platform override >
  flag default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_feature_flags"
down_revision: str | None = "0006_tenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen seed (Permanent Command §29 examples). All off by default.
FLAGS_V1 = {
    "ai": "AI features (shopping assistant, merchant assistant, listing generator)",
    "delivery": "Platform delivery engine",
    "reviews": "Product and merchant reviews",
    "coupons": "Coupons and discount codes",
    "loyalty": "Loyalty programmes",
    "protected_checkout": "Protected checkout (escrow-style release)",
    "advertising": "Sponsored listings and placements",
    "advanced_analytics": "Advanced merchant analytics",
    "subscriptions": "Merchant subscription plans",
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.feature_flags (
            key             text PRIMARY KEY CHECK (key ~ '^[a-z][a-z0-9_]{1,39}$'),
            description     text NOT NULL CHECK (length(description) BETWEEN 1 AND 300),
            default_enabled boolean NOT NULL DEFAULT false,
            allowed_scopes  text[] NOT NULL DEFAULT ARRAY['platform', 'vertical', 'tenant']
                            CHECK (cardinality(allowed_scopes) BETWEEN 1 AND 3
                                   AND allowed_scopes <@ ARRAY['platform', 'vertical', 'tenant']::text[]),
            created_at      timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE control.feature_flag_overrides (
            id          uuid PRIMARY KEY,
            flag_key    text NOT NULL REFERENCES control.feature_flags (key),
            scope_type  text NOT NULL CHECK (scope_type IN ('platform', 'vertical', 'tenant')),
            vertical_id uuid NULL REFERENCES control.verticals (id),
            tenant_id   uuid NULL REFERENCES control.tenants (id),
            enabled     boolean NOT NULL,
            enforced    boolean NOT NULL DEFAULT false,
            reason      text NULL CHECK (length(reason) <= 500),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            updated_by  uuid NULL REFERENCES control.persons (id),
            CONSTRAINT ck_feature_flag_overrides__target CHECK (
                (scope_type = 'platform' AND vertical_id IS NULL AND tenant_id IS NULL)
                OR (scope_type = 'vertical' AND vertical_id IS NOT NULL AND tenant_id IS NULL)
                OR (scope_type = 'tenant' AND tenant_id IS NOT NULL AND vertical_id IS NULL)
            ),
            CONSTRAINT ck_feature_flag_overrides__enforced
                CHECK (NOT enforced OR scope_type = 'platform')
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_feature_flag_overrides__platform "
        "ON control.feature_flag_overrides (flag_key) WHERE scope_type = 'platform'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_feature_flag_overrides__vertical "
        "ON control.feature_flag_overrides (flag_key, vertical_id) WHERE scope_type = 'vertical'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_feature_flag_overrides__tenant "
        "ON control.feature_flag_overrides (flag_key, tenant_id) WHERE scope_type = 'tenant'"
    )
    flags = sa.table("feature_flags", sa.column("key"), sa.column("description"), schema="control")
    op.bulk_insert(flags, [{"key": k, "description": d} for k, d in FLAGS_V1.items()])
    op.execute("GRANT SELECT ON control.feature_flags TO arada_app, arada_platform_reader")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON control.feature_flag_overrides TO arada_app"
    )
    op.execute("GRANT SELECT ON control.feature_flag_overrides TO arada_platform_reader")


def downgrade() -> None:
    op.execute("DROP TABLE control.feature_flag_overrides")
    op.execute("DROP TABLE control.feature_flags")
