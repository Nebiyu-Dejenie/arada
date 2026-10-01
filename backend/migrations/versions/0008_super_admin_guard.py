"""The platform always keeps at least one SUPER_ADMIN (database-enforced).

Revision ID: 0008_super_admin_guard
Revises: 0007_feature_flags
Create Date: 2026-10-01

Until now only the service guarded the last SUPER_ADMIN, and it serialised
with ``SELECT ... FOR UPDATE``, which needs an UPDATE privilege the runtime
role deliberately lacks: every SUPER_ADMIN revocation failed (ADR-033).

This trigger makes the invariant hold for every role and code path without
granting anything new. It takes a transaction-scoped advisory lock, then
checks that a SUPER_ADMIN remains. Under READ COMMITTED (the only level the
application uses) that check runs on a fresh snapshot taken after the lock,
so it sees every revocation committed before it: two overlapping revocations
cannot each see "another one remains" and together remove the last one.
REPEATABLE READ would check a snapshot taken before the lock, so removing a
SUPER_ADMIN is refused at that level.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_super_admin_guard"
down_revision: str | None = "0007_feature_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION control.keep_one_super_admin() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtextextended('control.super_admin_invariant', 0));
          IF current_setting('transaction_isolation') = 'repeatable read' THEN
            RAISE EXCEPTION 'removing a SUPER_ADMIN requires READ COMMITTED or SERIALIZABLE'
              USING ERRCODE = 'restrict_violation';
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM control.platform_role_assignments WHERE role_key = 'SUPER_ADMIN'
          ) THEN
            RAISE EXCEPTION 'the platform must keep at least one SUPER_ADMIN'
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NULL;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION control.keep_one_super_admin() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER tr_platform_role_assignments__keep_one_super_admin
        AFTER DELETE OR UPDATE ON control.platform_role_assignments
        FOR EACH ROW WHEN (OLD.role_key = 'SUPER_ADMIN')
        EXECUTE FUNCTION control.keep_one_super_admin()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER tr_platform_role_assignments__keep_one_super_admin "
        "ON control.platform_role_assignments"
    )
    op.execute("DROP FUNCTION control.keep_one_super_admin()")
