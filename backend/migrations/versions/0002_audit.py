"""Append-only audit events.

Revision ID: 0002_audit
Revises: 0001_foundation
Create Date: 2026-09-26

Protection is layered: the runtime role may only INSERT/SELECT; triggers reject
UPDATE/DELETE/TRUNCATE even for the owner; RLS lets a tenant read and write
only its own events, and platform events (tenant_id NULL) only outside any
tenant context. Platform-wide reads go through the BYPASSRLS reader role.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_audit"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE control.audit_events (
            id              uuid PRIMARY KEY,
            occurred_at     timestamptz NOT NULL DEFAULT now(),
            actor_type      text NOT NULL CHECK (actor_type IN ('person', 'system')),
            actor_person_id uuid NULL,
            tenant_id       uuid NULL,
            action          text NOT NULL
                            CHECK (action ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
            resource_type   text NOT NULL CHECK (resource_type ~ '^[a-z][a-z0-9_]*$'),
            resource_id     text NULL CHECK (length(resource_id) <= 200),
            outcome         text NOT NULL DEFAULT 'success'
                            CHECK (outcome IN ('success', 'failure', 'denied')),
            source          text NOT NULL CHECK (source IN ('api', 'cli', 'system', 'worker')),
            request_id      text NULL CHECK (length(request_id) <= 64),
            trace_id        text NULL CHECK (length(trace_id) <= 64),
            ip              inet NULL,
            user_agent      text NULL CHECK (length(user_agent) <= 256),
            reason          text NULL CHECK (length(reason) <= 1000),
            before          jsonb NULL,
            after           jsonb NULL,
            CONSTRAINT ck_audit_events__actor
                CHECK ((actor_type = 'person') = (actor_person_id IS NOT NULL))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_audit_events__tenant_id ON control.audit_events (tenant_id, id DESC)"
    )
    op.execute(
        "CREATE INDEX ix_audit_events__actor ON control.audit_events (actor_person_id, id DESC)"
    )
    op.execute("CREATE INDEX ix_audit_events__action ON control.audit_events (action, id DESC)")

    for event in ("UPDATE", "DELETE"):
        op.execute(
            f"""
            CREATE TRIGGER tr_audit_events__no_{event.lower()}
            BEFORE {event} ON control.audit_events
            FOR EACH ROW EXECUTE FUNCTION control.reject_mutation()
            """
        )
    op.execute(
        """
        CREATE TRIGGER tr_audit_events__no_truncate
        BEFORE TRUNCATE ON control.audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION control.reject_mutation()
        """
    )

    op.execute("ALTER TABLE control.audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE control.audit_events FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY audit_events_tenant_read ON control.audit_events
        FOR SELECT TO arada_app
        USING (tenant_id = control.current_tenant_id())
        """
    )
    op.execute(
        """
        CREATE POLICY audit_events_insert_in_context ON control.audit_events
        FOR INSERT TO arada_app
        WITH CHECK (tenant_id IS NOT DISTINCT FROM control.current_tenant_id())
        """
    )
    op.execute("GRANT SELECT, INSERT ON control.audit_events TO arada_app")
    op.execute("GRANT SELECT ON control.audit_events TO arada_platform_reader")


def downgrade() -> None:
    op.execute("DROP TABLE control.audit_events")
