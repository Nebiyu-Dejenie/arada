from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Table, Text
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP, UUID

from arada.kernel.sql import metadata

TS = TIMESTAMP(timezone=True)

permissions = Table(
    "permissions",
    metadata,
    Column("key", Text, primary_key=True),
    Column("scopes", ARRAY(Text), nullable=False),
)

roles = Table(
    "roles",
    metadata,
    Column("key", Text, primary_key=True),
    Column("scope_type", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("is_system", Boolean, nullable=False),
)

role_permissions = Table(
    "role_permissions",
    metadata,
    Column("role_key", Text, ForeignKey("control.roles.key"), primary_key=True),
    Column("permission_key", Text, ForeignKey("control.permissions.key"), primary_key=True),
)

platform_role_assignments = Table(
    "platform_role_assignments",
    metadata,
    Column("person_id", UUID(as_uuid=True), ForeignKey("control.persons.id"), primary_key=True),
    Column("role_key", Text, primary_key=True),
    Column("scope_type", Text, nullable=False),
    Column("granted_by", UUID(as_uuid=True), ForeignKey("control.persons.id"), nullable=True),
    Column("granted_at", TS, nullable=False),
)

vertical_role_assignments = Table(
    "vertical_role_assignments",
    metadata,
    Column("person_id", UUID(as_uuid=True), ForeignKey("control.persons.id"), primary_key=True),
    Column("vertical_id", UUID(as_uuid=True), ForeignKey("control.verticals.id"), primary_key=True),
    Column("role_key", Text, primary_key=True),
    Column("scope_type", Text, nullable=False),
    Column("granted_by", UUID(as_uuid=True), ForeignKey("control.persons.id"), nullable=True),
    Column("granted_at", TS, nullable=False),
)
