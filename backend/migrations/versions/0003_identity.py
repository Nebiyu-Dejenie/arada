"""Identity: persons, provider identities, credentials, TOTP factors, sessions.

Revision ID: 0003_identity
Revises: 0002_audit
Create Date: 2026-09-26

Identity is platform-level (a person may belong to many tenants), so these
tables are not tenant-scoped. Secrets are never stored in clear: passwords are
argon2id hashes, TOTP secrets are envelope-encrypted, session tokens are
stored only as SHA-256 hashes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_identity"
down_revision: str | None = "0002_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE control.persons (
            id           uuid PRIMARY KEY,
            display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 120),
            status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),
            version      integer NOT NULL DEFAULT 1 CHECK (version >= 1)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE control.identities (
            id         uuid PRIMARY KEY,
            person_id  uuid NOT NULL REFERENCES control.persons (id),
            provider   text NOT NULL CHECK (provider IN ('password', 'telegram')),
            subject    text NOT NULL CHECK (length(subject) BETWEEN 1 AND 128),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_identities__provider_subject UNIQUE (provider, subject),
            CONSTRAINT ck_identities__password_subject
                CHECK (provider <> 'password' OR subject ~ '^[a-z0-9][a-z0-9._-]{2,63}$')
        )
        """
    )
    op.execute("CREATE INDEX ix_identities__person_id ON control.identities (person_id)")
    op.execute(
        """
        CREATE TABLE control.password_credentials (
            identity_id     uuid PRIMARY KEY REFERENCES control.identities (id),
            password_hash   text NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
            failed_attempts integer NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
            locked_until    timestamptz NULL,
            updated_at      timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE control.totp_factors (
            person_id         uuid PRIMARY KEY REFERENCES control.persons (id),
            id                uuid NOT NULL UNIQUE,
            secret_ciphertext bytea NOT NULL,
            secret_nonce      bytea NOT NULL CHECK (octet_length(secret_nonce) = 12),
            wrapped_dek       bytea NOT NULL,
            dek_nonce         bytea NOT NULL CHECK (octet_length(dek_nonce) = 12),
            kek_version       integer NOT NULL CHECK (kek_version >= 1),
            confirmed_at      timestamptz NULL,
            last_used_step    bigint NULL,
            created_at        timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE control.sessions (
            id              uuid PRIMARY KEY,
            person_id       uuid NOT NULL REFERENCES control.persons (id),
            token_hash      bytea NOT NULL CHECK (octet_length(token_hash) = 32),
            created_at      timestamptz NOT NULL DEFAULT now(),
            last_seen_at    timestamptz NOT NULL DEFAULT now(),
            idle_expires_at timestamptz NOT NULL,
            expires_at      timestamptz NOT NULL,
            mfa_verified_at timestamptz NULL,
            revoked_at      timestamptz NULL,
            revoked_reason  text NULL CHECK (length(revoked_reason) <= 64),
            ip              inet NULL,
            user_agent      text NULL CHECK (length(user_agent) <= 256),
            CONSTRAINT uq_sessions__token_hash UNIQUE (token_hash),
            CONSTRAINT ck_sessions__expiry CHECK (idle_expires_at <= expires_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_sessions__person_id ON control.sessions (person_id) "
        "WHERE revoked_at IS NULL"
    )

    op.execute("GRANT SELECT, INSERT, UPDATE ON control.persons TO arada_app")
    op.execute("GRANT SELECT, INSERT ON control.identities TO arada_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.password_credentials TO arada_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON control.totp_factors TO arada_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.sessions TO arada_app")
    # The platform reader never needs credentials, factors or sessions.
    op.execute("GRANT SELECT ON control.persons, control.identities TO arada_platform_reader")


def downgrade() -> None:
    for table in ("sessions", "totp_factors", "password_credentials", "identities", "persons"):
        op.execute(f"DROP TABLE control.{table}")
