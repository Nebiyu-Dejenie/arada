from __future__ import annotations

from sqlalchemy import Column, LargeBinary, Table, Text
from sqlalchemy.dialects.postgresql import INET, TIMESTAMP, UUID

from arada.kernel.sql import metadata

TS = TIMESTAMP(timezone=True)

customers = Table(
    "customers",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("person_id", UUID(as_uuid=True), nullable=False),
    Column("first_seen_at", TS, nullable=False),
    schema="commerce",
)

customer_sessions = Table(
    "customer_sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("customer_id", UUID(as_uuid=True), nullable=False),
    Column("token_hash", LargeBinary, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("last_seen_at", TS, nullable=False),
    Column("idle_expires_at", TS, nullable=False),
    Column("expires_at", TS, nullable=False),
    Column("revoked_at", TS, nullable=True),
    Column("revoked_reason", Text, nullable=True),
    Column("ip", INET, nullable=True),
    Column("user_agent", Text, nullable=True),
)
