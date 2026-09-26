from __future__ import annotations

from sqlalchemy import Column, Table, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, TIMESTAMP, UUID

from arada.kernel.sql import metadata

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("occurred_at", TIMESTAMP(timezone=True), nullable=False),
    Column("actor_type", Text, nullable=False),
    Column("actor_person_id", UUID(as_uuid=True), nullable=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=True),
    Column("action", Text, nullable=False),
    Column("resource_type", Text, nullable=False),
    Column("resource_id", Text, nullable=True),
    Column("outcome", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("request_id", Text, nullable=True),
    Column("trace_id", Text, nullable=True),
    Column("ip", INET, nullable=True),
    Column("user_agent", Text, nullable=True),
    Column("reason", Text, nullable=True),
    Column("before", JSONB, nullable=True),
    Column("after", JSONB, nullable=True),
)
