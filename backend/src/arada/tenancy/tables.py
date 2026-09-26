from __future__ import annotations

from sqlalchemy import CHAR, Column, ForeignKey, Integer, LargeBinary, Table, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

from arada.kernel.sql import metadata

TS = TIMESTAMP(timezone=True)
_PERSON = "control.persons.id"

tenants = Table(
    "tenants",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("slug", Text, nullable=False),
    Column("display_name", Text, nullable=False),
    Column("vertical_id", UUID(as_uuid=True), ForeignKey("control.verticals.id"), nullable=False),
    Column("blueprint_version_id", UUID(as_uuid=True), nullable=False),
    Column("status", Text, nullable=False),
    Column("isolation_tier", Text, nullable=False),
    Column("currency", CHAR(3), nullable=False),
    Column("default_locale", Text, nullable=False),
    Column("timezone", Text, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("created_by", UUID(as_uuid=True), ForeignKey(_PERSON), nullable=True),
    Column("updated_at", TS, nullable=False),
    Column("version", Integer, nullable=False),
)

tenant_blueprint_assignments = Table(
    "tenant_blueprint_assignments",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("control.tenants.id"), nullable=False),
    Column(
        "blueprint_version_id",
        UUID(as_uuid=True),
        ForeignKey("control.blueprint_versions.id"),
        nullable=False,
    ),
    Column(
        "previous_blueprint_version_id",
        UUID(as_uuid=True),
        ForeignKey("control.blueprint_versions.id"),
        nullable=True,
    ),
    Column("assigned_at", TS, nullable=False),
    Column("assigned_by", UUID(as_uuid=True), ForeignKey(_PERSON), nullable=True),
    Column("reason", Text, nullable=True),
)

domains = Table(
    "domains",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("control.tenants.id"), nullable=True),
    Column("hostname", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("created_by", UUID(as_uuid=True), ForeignKey(_PERSON), nullable=True),
)

merchant_profiles = Table(
    "merchant_profiles",
    metadata,
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("control.tenants.id"), primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("tagline", Text, nullable=True),
    Column("description", Text, nullable=True),
    Column("brand_primary_color", Text, nullable=True),
    Column("brand_accent_color", Text, nullable=True),
    Column("contact_email", Text, nullable=True),
    Column("contact_phone", Text, nullable=True),
    Column("version", Integer, nullable=False),
    Column("updated_at", TS, nullable=False),
    Column("updated_by", UUID(as_uuid=True), ForeignKey(_PERSON), nullable=True),
)

tenant_memberships = Table(
    "tenant_memberships",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("control.tenants.id"), nullable=False),
    Column("person_id", UUID(as_uuid=True), ForeignKey(_PERSON), nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("created_by", UUID(as_uuid=True), ForeignKey(_PERSON), nullable=True),
    Column("updated_at", TS, nullable=False),
)

tenant_membership_roles = Table(
    "tenant_membership_roles",
    metadata,
    Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    Column("membership_id", UUID(as_uuid=True), primary_key=True),
    Column("role_key", Text, primary_key=True),
    Column("scope_type", Text, nullable=False),
    Column("granted_by", UUID(as_uuid=True), ForeignKey(_PERSON), nullable=True),
    Column("granted_at", TS, nullable=False),
)

tenant_invitations = Table(
    "tenant_invitations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), ForeignKey("control.tenants.id"), nullable=False),
    Column("token_hash", LargeBinary, nullable=False),
    Column("created_at", TS, nullable=False),
    Column("created_by", UUID(as_uuid=True), ForeignKey(_PERSON), nullable=True),
    Column("expires_at", TS, nullable=False),
    Column("accepted_at", TS, nullable=True),
    Column("accepted_by", UUID(as_uuid=True), ForeignKey(_PERSON), nullable=True),
    Column("revoked_at", TS, nullable=True),
)

tenant_invitation_roles = Table(
    "tenant_invitation_roles",
    metadata,
    Column("tenant_id", UUID(as_uuid=True), primary_key=True),
    Column("invitation_id", UUID(as_uuid=True), primary_key=True),
    Column("role_key", Text, primary_key=True),
    Column("scope_type", Text, nullable=False),
)
