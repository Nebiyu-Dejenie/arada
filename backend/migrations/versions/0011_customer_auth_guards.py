"""Forward-only guards for customer sessions, merchant bots and the replay window.

Revision ID: 0011_customer_auth_guards
Revises: 0010_telegram_customers
Create Date: 2026-10-02

The runtime role needs UPDATE on ``customer_sessions.revoked_at``,
``telegram_bots.status`` and ``telegram_init_data_uses.use_count`` to do its
job, so column grants alone cannot stop a faulty code path from resurrecting
a revoked customer session, reactivating a replaced or disabled bot, or
resetting a replay counter. These invariants must survive bugs and races, so
they live in the database (ADR-033): each of these values may only move
forward. Triggers bind every role, including the table owner.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_customer_auth_guards"
down_revision: str | None = "0010_telegram_customers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUARDS = {
    # A revoked session stays revoked, with its original time and reason.
    "guard_customer_session_revocation": (
        "control.customer_sessions",
        "BEFORE UPDATE OF revoked_at, revoked_reason",
        """
        IF OLD.revoked_at IS NOT NULL AND (
             NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
             OR NEW.revoked_reason IS DISTINCT FROM OLD.revoked_reason) THEN
          RAISE EXCEPTION 'customer session revocation can only move forward'
            USING ERRCODE = 'restrict_violation';
        END IF;
        """,
    ),
    # A disabled bot binding is terminal: re-binding inserts a new row.
    "guard_telegram_bot_disabling": (
        "control.telegram_bots",
        "BEFORE UPDATE OF status, disabled_at",
        """
        IF OLD.status = 'disabled' AND (
             NEW.status IS DISTINCT FROM OLD.status
             OR NEW.disabled_at IS DISTINCT FROM OLD.disabled_at) THEN
          RAISE EXCEPTION 'telegram bot disabling can only move forward'
            USING ERRCODE = 'restrict_violation';
        END IF;
        """,
    ),
    # A replay counter only counts up.
    "guard_init_data_use_count": (
        "control.telegram_init_data_uses",
        "BEFORE UPDATE OF use_count",
        """
        IF NEW.use_count <= OLD.use_count THEN
          RAISE EXCEPTION 'initData use counts can only move forward'
            USING ERRCODE = 'restrict_violation';
        END IF;
        """,
    ),
}


def upgrade() -> None:
    for name, (table, timing, body) in _GUARDS.items():
        op.execute(
            f"""
            CREATE FUNCTION control.{name}() RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
              {body}
              RETURN NEW;
            END
            $$
            """
        )
        op.execute(f"REVOKE ALL ON FUNCTION control.{name}() FROM PUBLIC")
        op.execute(
            f"CREATE TRIGGER tr_{name} {timing} ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION control.{name}()"
        )


def downgrade() -> None:
    for name, (table, _timing, _body) in reversed(_GUARDS.items()):
        op.execute(f"DROP TRIGGER tr_{name} ON {table}")
        op.execute(f"DROP FUNCTION control.{name}()")
