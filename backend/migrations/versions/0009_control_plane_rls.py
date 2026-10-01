"""Row-level security for the last three tables that carry a tenant_id.

Revision ID: 0009_control_plane_rls
Revises: 0008_super_admin_guard
Create Date: 2026-10-01

Migration 0006 left ``domains`` and ``tenant_blueprint_assignments`` (and
0007 left ``feature_flag_overrides``) without RLS as "control-plane
metadata", so a bug in service code met no database backstop. None of them
has a technical reason to stay outside RLS (ADR-034):

* ``tenant_blueprint_assignments``: written and read only inside the
  tenant's own context. Plain tenant isolation.
* ``domains``: written inside the tenant's context. The one read that must
  happen before a tenant is known (Host header -> tenant) goes through the
  narrow SECURITY DEFINER resolver ``control.resolve_storefront_host``,
  owned by ``arada_resolver``, like the resolvers of 0006. Platform-kind rows
  (``tenant_id IS NULL``) are not reachable by the runtime role at all until
  a platform-domain feature defines their access path.
* ``feature_flag_overrides``: platform and vertical rows (``tenant_id IS
  NULL``) are global configuration, readable in every context; a tenant row
  is readable only in its own tenant's context. Writes are stricter: a tenant
  row only inside its tenant's context, a global row only outside any tenant
  context, so tenant-scoped code can never flip a platform kill switch.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_control_plane_rls"
down_revision: str | None = "0008_super_admin_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ONLY = ("tenant_blueprint_assignments", "domains")
SAME_CONTEXT = "tenant_id IS NOT DISTINCT FROM control.current_tenant_id()"


def upgrade() -> None:
    for table in (*TENANT_ONLY, "feature_flag_overrides"):
        op.execute(f"ALTER TABLE control.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE control.{table} FORCE ROW LEVEL SECURITY")

    for table in TENANT_ONLY:
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON control.{table}
            FOR ALL TO arada_app
            USING (tenant_id = control.current_tenant_id())
            WITH CHECK (tenant_id = control.current_tenant_id())
            """
        )

    op.execute(
        """
        CREATE POLICY feature_flag_overrides_read ON control.feature_flag_overrides
        FOR SELECT TO arada_app
        USING (tenant_id IS NULL OR tenant_id = control.current_tenant_id())
        """
    )
    op.execute(
        f"""
        CREATE POLICY feature_flag_overrides_insert ON control.feature_flag_overrides
        FOR INSERT TO arada_app
        WITH CHECK ({SAME_CONTEXT})
        """
    )
    op.execute(
        f"""
        CREATE POLICY feature_flag_overrides_update ON control.feature_flag_overrides
        FOR UPDATE TO arada_app
        USING ({SAME_CONTEXT})
        WITH CHECK ({SAME_CONTEXT})
        """
    )
    op.execute(
        f"""
        CREATE POLICY feature_flag_overrides_delete ON control.feature_flag_overrides
        FOR DELETE TO arada_app
        USING ({SAME_CONTEXT})
        """
    )

    # --- Host header -> tenant, before any tenant context exists ------------
    op.execute("GRANT SELECT ON control.domains TO arada_resolver")
    op.execute(
        """
        CREATE POLICY domains_resolver_read ON control.domains
        FOR SELECT TO arada_resolver USING (true)
        """
    )
    op.execute(
        """
        CREATE FUNCTION control.resolve_storefront_host(p_hostname text) RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
          SELECT d.tenant_id FROM control.domains d
          WHERE d.hostname = p_hostname AND d.kind = 'storefront' AND d.status = 'active'
        $$
        """
    )
    # A new function owner needs CREATE on the schema; grant it only for the
    # ownership transfer (as in 0006).
    op.execute("GRANT CREATE ON SCHEMA control TO arada_resolver")
    op.execute("ALTER FUNCTION control.resolve_storefront_host(text) OWNER TO arada_resolver")
    op.execute("REVOKE CREATE ON SCHEMA control FROM arada_resolver")
    op.execute("REVOKE ALL ON FUNCTION control.resolve_storefront_host(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION control.resolve_storefront_host(text) TO arada_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION control.resolve_storefront_host(text)")
    op.execute("DROP POLICY domains_resolver_read ON control.domains")
    op.execute("REVOKE SELECT ON control.domains FROM arada_resolver")
    for policy in ("read", "insert", "update", "delete"):
        op.execute(f"DROP POLICY feature_flag_overrides_{policy} ON control.feature_flag_overrides")
    for table in TENANT_ONLY:
        op.execute(f"DROP POLICY {table}_tenant_isolation ON control.{table}")
    for table in (*TENANT_ONLY, "feature_flag_overrides"):
        op.execute(f"ALTER TABLE control.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE control.{table} DISABLE ROW LEVEL SECURITY")
