from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Table, Text
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP, UUID

from arada.kernel.sql import metadata

TS = TIMESTAMP(timezone=True)

feature_flags = Table(
    "feature_flags",
    metadata,
    Column("key", Text, primary_key=True),
    Column("description", Text, nullable=False),
    Column("default_enabled", Boolean, nullable=False),
    Column("allowed_scopes", ARRAY(Text), nullable=False),
    Column("created_at", TS, nullable=False),
)

feature_flag_overrides = Table(
    "feature_flag_overrides",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("flag_key", Text, ForeignKey("control.feature_flags.key"), nullable=False),
    Column("scope_type", Text, nullable=False),
    Column("vertical_id", UUID(as_uuid=True), ForeignKey("control.verticals.id"), nullable=True),
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("control.tenants.id"), nullable=True),
    Column("enabled", Boolean, nullable=False),
    Column("enforced", Boolean, nullable=False),
    Column("reason", Text, nullable=True),
    Column("updated_at", TS, nullable=False),
    Column("updated_by", UUID(as_uuid=True), ForeignKey("control.persons.id"), nullable=True),
)
