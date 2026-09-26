from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Table, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

from arada.kernel.sql import metadata

verticals = Table(
    "verticals",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("key", Text, nullable=False),
    Column("name_en", Text, nullable=False),
    Column("name_am", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
    Column("created_by", UUID(as_uuid=True), ForeignKey("control.persons.id"), nullable=True),
)
