from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

from arada.kernel.sql import metadata

TS = TIMESTAMP(timezone=True)

blueprints = Table(
    "blueprints",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("vertical_id", UUID(as_uuid=True), ForeignKey("control.verticals.id"), nullable=False),
    Column("key", Text, nullable=False),
    Column("name_en", Text, nullable=False),
    Column("name_am", Text, nullable=True),
    Column("created_at", TS, nullable=False),
    Column("created_by", UUID(as_uuid=True), ForeignKey("control.persons.id"), nullable=True),
)

blueprint_versions = Table(
    "blueprint_versions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("blueprint_id", UUID(as_uuid=True), nullable=False),
    Column("vertical_id", UUID(as_uuid=True), nullable=False),
    Column("version_major", Integer, nullable=False),
    Column("version_minor", Integer, nullable=False),
    Column("version_patch", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("definition", JSONB, nullable=False),
    Column("lock_version", Integer, nullable=False),
    Column("content_hash", LargeBinary, nullable=True),
    Column("change_level", Text, nullable=True),
    Column("created_at", TS, nullable=False),
    Column("created_by", UUID(as_uuid=True), ForeignKey("control.persons.id"), nullable=True),
    Column("updated_at", TS, nullable=False),
    Column("published_at", TS, nullable=True),
    Column("published_by", UUID(as_uuid=True), ForeignKey("control.persons.id"), nullable=True),
)
