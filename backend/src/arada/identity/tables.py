from __future__ import annotations

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, LargeBinary, Table, Text
from sqlalchemy.dialects.postgresql import INET, TIMESTAMP, UUID

from arada.kernel.sql import metadata

TS = TIMESTAMP(timezone=True)

persons = Table(
    "persons",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("updated_at", TS, nullable=False),
    Column("version", Integer, nullable=False),
)

identities = Table(
    "identities",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("person_id", UUID(as_uuid=True), ForeignKey("control.persons.id"), nullable=False),
    Column("provider", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("created_at", TS, nullable=False),
)

password_credentials = Table(
    "password_credentials",
    metadata,
    Column(
        "identity_id", UUID(as_uuid=True), ForeignKey("control.identities.id"), primary_key=True
    ),
    Column("password_hash", Text, nullable=False),
    Column("failed_attempts", Integer, nullable=False),
    Column("locked_until", TS, nullable=True),
    Column("updated_at", TS, nullable=False),
)

totp_factors = Table(
    "totp_factors",
    metadata,
    Column("person_id", UUID(as_uuid=True), ForeignKey("control.persons.id"), primary_key=True),
    Column("id", UUID(as_uuid=True), nullable=False),
    Column("secret_ciphertext", LargeBinary, nullable=False),
    Column("secret_nonce", LargeBinary, nullable=False),
    Column("wrapped_dek", LargeBinary, nullable=False),
    Column("dek_nonce", LargeBinary, nullable=False),
    Column("kek_version", Integer, nullable=False),
    Column("confirmed_at", TS, nullable=True),
    Column("last_used_step", BigInteger, nullable=True),
    Column("created_at", TS, nullable=False),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("person_id", UUID(as_uuid=True), ForeignKey("control.persons.id"), nullable=False),
    Column("token_hash", LargeBinary, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("last_seen_at", TS, nullable=False),
    Column("idle_expires_at", TS, nullable=False),
    Column("expires_at", TS, nullable=False),
    Column("mfa_verified_at", TS, nullable=True),
    Column("revoked_at", TS, nullable=True),
    Column("revoked_reason", Text, nullable=True),
    Column("ip", INET, nullable=True),
    Column("user_agent", Text, nullable=True),
)
