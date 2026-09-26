"""Platform foundation: control schema and tenant-context helpers.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-09-26

``control.current_tenant_id()`` is what every RLS policy compares against. It
returns NULL when no tenant context is set, and ``tenant_id = NULL`` is never
true, so an unset context sees zero tenant rows (fail closed).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA control")
    op.execute("REVOKE ALL ON SCHEMA control FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA control TO arada_app, arada_platform_reader, arada_resolver")

    op.execute(
        """
        CREATE FUNCTION control.current_tenant_id() RETURNS uuid
        LANGUAGE sql STABLE PARALLEL SAFE
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION control.current_person_id() RETURNS uuid
        LANGUAGE sql STABLE PARALLEL SAFE
        SET search_path = pg_catalog, pg_temp
        AS $$ SELECT NULLIF(current_setting('app.person_id', true), '')::uuid $$
        """
    )
    # Generic guard for append-only tables: rejects UPDATE, DELETE and TRUNCATE
    # even for the table owner (grants alone do not bind the owner).
    op.execute(
        """
        CREATE FUNCTION control.reject_mutation() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
          RAISE EXCEPTION 'table %.% is append-only', TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = 'restrict_violation';
        END
        $$
        """
    )
    for fn in ("current_tenant_id()", "current_person_id()", "reject_mutation()"):
        op.execute(f"REVOKE ALL ON FUNCTION control.{fn} FROM PUBLIC")
    op.execute(
        "GRANT EXECUTE ON FUNCTION control.current_tenant_id(), control.current_person_id() "
        "TO arada_app, arada_platform_reader, arada_resolver"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION control.reject_mutation()")
    op.execute("DROP FUNCTION control.current_person_id()")
    op.execute("DROP FUNCTION control.current_tenant_id()")
    op.execute("DROP SCHEMA control")
