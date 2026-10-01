"""Telegram foundation: merchant bots, customers, customer sessions, replay window.

Revision ID: 0010_telegram_customers
Revises: 0009_control_plane_rls
Create Date: 2026-10-01

Every table here carries a ``tenant_id`` and is under FORCE row-level security
keyed on the transaction's tenant context (ADR-034); children reference their
parents through composite ``(tenant_id, …)`` keys. The runtime role gets only
the column-level privileges each table needs, so ``tenant_id`` can never be
rewritten.

* ``control.telegram_bots``: a merchant's own (bring-your-own) bot. The token
  is envelope-encrypted (ADR-017). ``telegram_bot_id`` is supplied by the
  platform admin and never parsed from the token (assumption A9). At most one
  active bot per tenant, and an active bot belongs to exactly one tenant.
* ``commerce.customers``: a person as seen by one tenant (ADR-024). Minimal on
  purpose; Phase 3 extends it.
* ``control.customer_sessions``: opaque, server-side customer sessions bound to
  one tenant and one customer (ADR-036). Only the SHA-256 of a token is stored.
* ``control.telegram_init_data_uses``: the replay window per ``initData``
  (PHASE_2_PLAN.md §9). Rows may be deleted only once expired.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_telegram_customers"
down_revision: str | None = "0009_control_plane_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ISOLATION = "tenant_id = control.current_tenant_id()"


def upgrade() -> None:
    op.execute("CREATE SCHEMA commerce")
    op.execute("REVOKE ALL ON SCHEMA commerce FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA commerce TO arada_app")

    op.execute(
        """
        CREATE TABLE control.telegram_bots (
            id               uuid PRIMARY KEY,
            tenant_id        uuid NOT NULL REFERENCES control.tenants (id),
            telegram_bot_id  bigint NOT NULL
                             CHECK (telegram_bot_id > 0 AND telegram_bot_id < 9007199254740992),
            token_ciphertext bytea NOT NULL,
            token_nonce      bytea NOT NULL CHECK (octet_length(token_nonce) = 12),
            wrapped_dek      bytea NOT NULL,
            dek_nonce        bytea NOT NULL CHECK (octet_length(dek_nonce) = 12),
            kek_version      integer NOT NULL CHECK (kek_version >= 1),
            status           text NOT NULL DEFAULT 'active'
                             CHECK (status IN ('active', 'disabled')),
            created_at       timestamptz NOT NULL DEFAULT now(),
            created_by       uuid NULL REFERENCES control.persons (id),
            disabled_at      timestamptz NULL,
            CONSTRAINT uq_telegram_bots__tenant_id UNIQUE (tenant_id, id),
            CONSTRAINT ck_telegram_bots__disabled
                CHECK ((status = 'disabled') = (disabled_at IS NOT NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_telegram_bots__one_active_per_tenant "
        "ON control.telegram_bots (tenant_id) WHERE status = 'active'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_telegram_bots__active_bot "
        "ON control.telegram_bots (telegram_bot_id) WHERE status = 'active'"
    )

    op.execute(
        """
        CREATE TABLE commerce.customers (
            id            uuid PRIMARY KEY,
            tenant_id     uuid NOT NULL REFERENCES control.tenants (id),
            person_id     uuid NOT NULL REFERENCES control.persons (id),
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_customers__tenant_person UNIQUE (tenant_id, person_id),
            CONSTRAINT uq_customers__tenant_id UNIQUE (tenant_id, id)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE control.customer_sessions (
            id              uuid PRIMARY KEY,
            tenant_id       uuid NOT NULL,
            customer_id     uuid NOT NULL,
            token_hash      bytea NOT NULL CHECK (octet_length(token_hash) = 32),
            created_at      timestamptz NOT NULL DEFAULT now(),
            last_seen_at    timestamptz NOT NULL DEFAULT now(),
            idle_expires_at timestamptz NOT NULL,
            expires_at      timestamptz NOT NULL,
            revoked_at      timestamptz NULL,
            revoked_reason  text NULL CHECK (length(revoked_reason) <= 64),
            ip              inet NULL,
            user_agent      text NULL CHECK (length(user_agent) <= 256),
            CONSTRAINT uq_customer_sessions__token_hash UNIQUE (token_hash),
            CONSTRAINT uq_customer_sessions__tenant_id UNIQUE (tenant_id, id),
            CONSTRAINT fk_customer_sessions__customer
                FOREIGN KEY (tenant_id, customer_id)
                REFERENCES commerce.customers (tenant_id, id),
            CONSTRAINT ck_customer_sessions__expiry
                CHECK (idle_expires_at <= expires_at AND created_at < expires_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_customer_sessions__active ON control.customer_sessions "
        "(tenant_id, customer_id) WHERE revoked_at IS NULL"
    )

    op.execute(
        """
        CREATE TABLE control.telegram_init_data_uses (
            tenant_id     uuid NOT NULL REFERENCES control.tenants (id),
            hash_digest   bytea NOT NULL CHECK (octet_length(hash_digest) = 32),
            first_used_at timestamptz NOT NULL DEFAULT now(),
            use_count     integer NOT NULL DEFAULT 1 CHECK (use_count >= 1),
            expires_at    timestamptz NOT NULL,
            PRIMARY KEY (tenant_id, hash_digest)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_telegram_init_data_uses__expiry "
        "ON control.telegram_init_data_uses (tenant_id, expires_at)"
    )

    # --- row-level security ----------------------------------------------------
    for table in (
        "control.telegram_bots",
        "commerce.customers",
        "control.customer_sessions",
        "control.telegram_init_data_uses",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    for table, policy in (
        ("control.telegram_bots", "telegram_bots_tenant_isolation"),
        ("commerce.customers", "customers_tenant_isolation"),
        ("control.customer_sessions", "customer_sessions_tenant_isolation"),
    ):
        op.execute(
            f"""
            CREATE POLICY {policy} ON {table}
            FOR ALL TO arada_app
            USING ({ISOLATION}) WITH CHECK ({ISOLATION})
            """
        )
    for command, clause in (
        ("SELECT", f"USING ({ISOLATION})"),
        ("INSERT", f"WITH CHECK ({ISOLATION})"),
        ("UPDATE", f"USING ({ISOLATION}) WITH CHECK ({ISOLATION})"),
        # Only expired rows may be removed: the window cannot be reset early.
        ("DELETE", f"USING ({ISOLATION} AND expires_at < now())"),
    ):
        op.execute(
            f"""
            CREATE POLICY telegram_init_data_uses_{command.lower()}
            ON control.telegram_init_data_uses
            FOR {command} TO arada_app {clause}
            """
        )

    # --- least-privilege grants -----------------------------------------------
    op.execute("GRANT SELECT, INSERT ON control.telegram_bots TO arada_app")
    op.execute("GRANT UPDATE (status, disabled_at) ON control.telegram_bots TO arada_app")
    op.execute("GRANT SELECT, INSERT ON commerce.customers TO arada_app")
    op.execute("GRANT SELECT, INSERT ON control.customer_sessions TO arada_app")
    op.execute(
        "GRANT UPDATE (last_seen_at, idle_expires_at, revoked_at, revoked_reason) "
        "ON control.customer_sessions TO arada_app"
    )
    op.execute("GRANT SELECT, INSERT, DELETE ON control.telegram_init_data_uses TO arada_app")
    op.execute("GRANT UPDATE (use_count) ON control.telegram_init_data_uses TO arada_app")


def downgrade() -> None:
    op.execute("DROP TABLE control.telegram_init_data_uses")
    op.execute("DROP TABLE control.customer_sessions")
    op.execute("DROP TABLE commerce.customers")
    op.execute("DROP TABLE control.telegram_bots")
    op.execute("DROP SCHEMA commerce")
