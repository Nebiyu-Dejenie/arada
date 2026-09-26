"""Tenancy: tenants, merchant profiles, domains, blueprint pins, memberships.

Revision ID: 0006_tenancy
Revises: 0005_blueprints
Create Date: 2026-09-26

Control-plane tenant metadata (tenants, domains, blueprint assignment
history) is platform-managed and read by resolvers *before* a tenant context
exists, so it is not RLS-scoped; services mediate every access.

Tenant-owned data (merchant profiles, memberships, membership roles,
invitations) is under FORCED row-level security keyed on the transaction's
tenant context, and child tables use composite (tenant_id, ...) foreign keys
so a row can never reference another tenant's row even if RLS were bypassed.

Two cross-tenant lookups are unavoidable ("which tenants am I a member of",
"which tenant does this invitation token belong to"); each is a narrow
SECURITY DEFINER function owned by the NOLOGIN role ``arada_resolver``,
which can read exactly those rows and nothing else.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_tenancy"
down_revision: str | None = "0005_blueprints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = (
    "merchant_profiles",
    "tenant_memberships",
    "tenant_membership_roles",
    "tenant_invitations",
    "tenant_invitation_roles",
)


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE control.tenants (
            id                   uuid PRIMARY KEY,
            slug                 text NOT NULL CHECK (
                                     slug ~ '^[a-z][a-z0-9-]{1,30}[a-z0-9]$'
                                     AND position('--' IN slug) = 0),
            display_name         text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 120),
            vertical_id          uuid NOT NULL REFERENCES control.verticals (id),
            blueprint_version_id uuid NOT NULL,
            status               text NOT NULL DEFAULT 'draft'
                                 CHECK (status IN ('draft', 'active', 'suspended', 'archived')),
            isolation_tier       text NOT NULL DEFAULT 'starter'
                                 CHECK (isolation_tier IN ('starter', 'pro', 'enterprise')),
            currency             char(3) NOT NULL DEFAULT 'ETB' CHECK (currency ~ '^[A-Z]{3}$'),
            default_locale       text NOT NULL DEFAULT 'am' CHECK (default_locale IN ('am', 'en')),
            timezone             text NOT NULL DEFAULT 'Africa/Addis_Ababa'
                                 CHECK (length(timezone) BETWEEN 1 AND 64),
            created_at           timestamptz NOT NULL DEFAULT now(),
            created_by           uuid NULL REFERENCES control.persons (id),
            updated_at           timestamptz NOT NULL DEFAULT now(),
            version              integer NOT NULL DEFAULT 1 CHECK (version >= 1),
            CONSTRAINT uq_tenants__slug UNIQUE (slug),
            CONSTRAINT uq_tenants__id_vertical UNIQUE (id, vertical_id),
            CONSTRAINT fk_tenants__blueprint_version
                FOREIGN KEY (blueprint_version_id, vertical_id)
                REFERENCES control.blueprint_versions (id, vertical_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_tenants__vertical ON control.tenants (vertical_id, status)")
    op.execute(
        """
        CREATE FUNCTION control.check_tenant_blueprint_pin() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
          IF TG_OP = 'INSERT' OR NEW.blueprint_version_id IS DISTINCT FROM OLD.blueprint_version_id THEN
            IF NOT EXISTS (
              SELECT 1 FROM control.blueprint_versions v
              WHERE v.id = NEW.blueprint_version_id AND v.status = 'published'
            ) THEN
              RAISE EXCEPTION 'tenants can only be pinned to a published blueprint version'
                USING ERRCODE = 'check_violation';
            END IF;
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION control.check_tenant_blueprint_pin() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER tr_tenants__blueprint_pin
        BEFORE INSERT OR UPDATE OF blueprint_version_id ON control.tenants
        FOR EACH ROW EXECUTE FUNCTION control.check_tenant_blueprint_pin()
        """
    )

    op.execute(
        """
        CREATE TABLE control.tenant_blueprint_assignments (
            id                            uuid PRIMARY KEY,
            tenant_id                     uuid NOT NULL REFERENCES control.tenants (id),
            blueprint_version_id          uuid NOT NULL REFERENCES control.blueprint_versions (id),
            previous_blueprint_version_id uuid NULL REFERENCES control.blueprint_versions (id),
            assigned_at                   timestamptz NOT NULL DEFAULT now(),
            assigned_by                   uuid NULL REFERENCES control.persons (id),
            reason                        text NULL CHECK (length(reason) <= 500)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_tenant_blueprint_assignments__tenant "
        "ON control.tenant_blueprint_assignments (tenant_id, assigned_at DESC)"
    )
    for event in ("UPDATE", "DELETE"):
        op.execute(
            f"""
            CREATE TRIGGER tr_tenant_blueprint_assignments__no_{event.lower()}
            BEFORE {event} ON control.tenant_blueprint_assignments
            FOR EACH ROW EXECUTE FUNCTION control.reject_mutation()
            """
        )

    op.execute(
        r"""
        CREATE TABLE control.domains (
            id         uuid PRIMARY KEY,
            tenant_id  uuid NULL REFERENCES control.tenants (id),
            hostname   text NOT NULL CHECK (
                           length(hostname) <= 253
                           AND hostname ~ '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$'),
            kind       text NOT NULL CHECK (kind IN ('storefront', 'platform')),
            status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
            created_at timestamptz NOT NULL DEFAULT now(),
            created_by uuid NULL REFERENCES control.persons (id),
            CONSTRAINT uq_domains__hostname UNIQUE (hostname),
            CONSTRAINT ck_domains__owner CHECK ((kind = 'platform') = (tenant_id IS NULL))
        )
        """
    )

    op.execute(
        r"""
        CREATE TABLE control.merchant_profiles (
            tenant_id          uuid PRIMARY KEY REFERENCES control.tenants (id),
            display_name       text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 120),
            tagline            text NULL CHECK (length(tagline) <= 160),
            description        text NULL CHECK (length(description) <= 4000),
            brand_primary_color text NULL CHECK (brand_primary_color ~ '^#[0-9a-f]{6}$'),
            brand_accent_color  text NULL CHECK (brand_accent_color ~ '^#[0-9a-f]{6}$'),
            contact_email      text NULL CHECK (
                                   length(contact_email) <= 254
                                   AND contact_email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
            contact_phone      text NULL CHECK (contact_phone ~ '^\+[1-9][0-9]{6,14}$'),
            version            integer NOT NULL DEFAULT 1 CHECK (version >= 1),
            updated_at         timestamptz NOT NULL DEFAULT now(),
            updated_by         uuid NULL REFERENCES control.persons (id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE control.tenant_memberships (
            id         uuid PRIMARY KEY,
            tenant_id  uuid NOT NULL REFERENCES control.tenants (id),
            person_id  uuid NOT NULL REFERENCES control.persons (id),
            status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'removed')),
            created_at timestamptz NOT NULL DEFAULT now(),
            created_by uuid NULL REFERENCES control.persons (id),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_tenant_memberships__tenant_person UNIQUE (tenant_id, person_id),
            CONSTRAINT uq_tenant_memberships__tenant_id UNIQUE (tenant_id, id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_tenant_memberships__person ON control.tenant_memberships (person_id)"
    )
    op.execute(
        """
        CREATE TABLE control.tenant_membership_roles (
            tenant_id     uuid NOT NULL,
            membership_id uuid NOT NULL,
            role_key      text NOT NULL,
            scope_type    text NOT NULL DEFAULT 'tenant' CHECK (scope_type = 'tenant'),
            granted_by    uuid NULL REFERENCES control.persons (id),
            granted_at    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, membership_id, role_key),
            CONSTRAINT fk_tenant_membership_roles__membership
                FOREIGN KEY (tenant_id, membership_id)
                REFERENCES control.tenant_memberships (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_tenant_membership_roles__role
                FOREIGN KEY (role_key, scope_type) REFERENCES control.roles (key, scope_type)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE control.tenant_invitations (
            id          uuid PRIMARY KEY,
            tenant_id   uuid NOT NULL REFERENCES control.tenants (id),
            token_hash  bytea NOT NULL CHECK (octet_length(token_hash) = 32),
            created_at  timestamptz NOT NULL DEFAULT now(),
            created_by  uuid NULL REFERENCES control.persons (id),
            expires_at  timestamptz NOT NULL,
            accepted_at timestamptz NULL,
            accepted_by uuid NULL REFERENCES control.persons (id),
            revoked_at  timestamptz NULL,
            CONSTRAINT uq_tenant_invitations__token UNIQUE (token_hash),
            CONSTRAINT uq_tenant_invitations__tenant_id UNIQUE (tenant_id, id),
            CONSTRAINT ck_tenant_invitations__accepted
                CHECK ((accepted_at IS NULL) = (accepted_by IS NULL)),
            CONSTRAINT ck_tenant_invitations__final
                CHECK (NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE control.tenant_invitation_roles (
            tenant_id     uuid NOT NULL,
            invitation_id uuid NOT NULL,
            role_key      text NOT NULL,
            scope_type    text NOT NULL DEFAULT 'tenant' CHECK (scope_type = 'tenant'),
            PRIMARY KEY (tenant_id, invitation_id, role_key),
            CONSTRAINT fk_tenant_invitation_roles__invitation
                FOREIGN KEY (tenant_id, invitation_id)
                REFERENCES control.tenant_invitations (tenant_id, id),
            CONSTRAINT fk_tenant_invitation_roles__role
                FOREIGN KEY (role_key, scope_type) REFERENCES control.roles (key, scope_type)
        )
        """
    )

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE control.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE control.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON control.{table}
            FOR ALL TO arada_app
            USING (tenant_id = control.current_tenant_id())
            WITH CHECK (tenant_id = control.current_tenant_id())
            """
        )

    # --- narrow cross-tenant resolvers ------------------------------------
    for table in ("tenant_memberships", "tenant_invitations"):
        op.execute(f"GRANT SELECT ON control.{table} TO arada_resolver")
        op.execute(
            f"""
            CREATE POLICY {table}_resolver_read ON control.{table}
            FOR SELECT TO arada_resolver USING (true)
            """
        )
    op.execute(
        """
        CREATE FUNCTION control.memberships_of_current_person()
        RETURNS TABLE (tenant_id uuid, membership_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
          SELECT m.tenant_id, m.id FROM control.tenant_memberships m
          WHERE m.person_id = control.current_person_id() AND m.status = 'active'
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION control.resolve_invitation(p_token_hash bytea) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
          SELECT i.tenant_id FROM control.tenant_invitations i
          WHERE i.token_hash = p_token_hash
            AND i.accepted_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > now()
        $$
        """
    )
    # A new function owner needs CREATE on the schema; grant it only for the
    # ownership transfer.
    op.execute("GRANT CREATE ON SCHEMA control TO arada_resolver")
    for fn in ("memberships_of_current_person()", "resolve_invitation(bytea)"):
        op.execute(f"ALTER FUNCTION control.{fn} OWNER TO arada_resolver")
        op.execute(f"REVOKE ALL ON FUNCTION control.{fn} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION control.{fn} TO arada_app")
    op.execute("REVOKE CREATE ON SCHEMA control FROM arada_resolver")

    # --- grants --------------------------------------------------------------
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.tenants TO arada_app")
    op.execute("GRANT SELECT, INSERT ON control.tenant_blueprint_assignments TO arada_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.domains TO arada_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.merchant_profiles TO arada_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.tenant_memberships TO arada_app")
    op.execute("GRANT SELECT, INSERT, DELETE ON control.tenant_membership_roles TO arada_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.tenant_invitations TO arada_app")
    op.execute("GRANT SELECT, INSERT ON control.tenant_invitation_roles TO arada_app")
    op.execute(
        "GRANT SELECT ON control.tenants, control.tenant_blueprint_assignments, control.domains, "
        "control.merchant_profiles, control.tenant_memberships, control.tenant_membership_roles "
        "TO arada_platform_reader"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION control.resolve_invitation(bytea)")
    op.execute("DROP FUNCTION control.memberships_of_current_person()")
    for table in (
        "tenant_invitation_roles",
        "tenant_invitations",
        "tenant_membership_roles",
        "tenant_memberships",
        "merchant_profiles",
        "domains",
        "tenant_blueprint_assignments",
        "tenants",
    ):
        op.execute(f"DROP TABLE control.{table}")
    op.execute("DROP FUNCTION control.check_tenant_blueprint_pin()")
