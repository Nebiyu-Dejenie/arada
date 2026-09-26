"""Blueprints and immutable blueprint versions.

Revision ID: 0005_blueprints
Revises: 0004_rbac
Create Date: 2026-09-26

A published version never changes: a trigger rejects any modification except
the lifecycle status (published -> deprecated -> retired, deprecated ->
published), and the content hash is computed by the database itself at
publication, so it cannot be supplied or forged by the application.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_blueprints"
down_revision: str | None = "0004_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE control.blueprints (
            id          uuid PRIMARY KEY,
            vertical_id uuid NOT NULL REFERENCES control.verticals (id),
            key         text NOT NULL CHECK (key ~ '^[a-z][a-z0-9_]{1,39}$'),
            name_en     text NOT NULL CHECK (length(btrim(name_en)) BETWEEN 1 AND 80),
            name_am     text NULL CHECK (length(btrim(name_am)) BETWEEN 1 AND 80),
            created_at  timestamptz NOT NULL DEFAULT now(),
            created_by  uuid NULL REFERENCES control.persons (id),
            CONSTRAINT uq_blueprints__vertical_key UNIQUE (vertical_id, key),
            CONSTRAINT uq_blueprints__id_vertical UNIQUE (id, vertical_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE control.blueprint_versions (
            id            uuid PRIMARY KEY,
            blueprint_id  uuid NOT NULL,
            vertical_id   uuid NOT NULL,
            version_major integer NOT NULL CHECK (version_major BETWEEN 0 AND 9999),
            version_minor integer NOT NULL CHECK (version_minor BETWEEN 0 AND 9999),
            version_patch integer NOT NULL CHECK (version_patch BETWEEN 0 AND 9999),
            status        text NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft', 'published', 'deprecated', 'retired')),
            definition    jsonb NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
            lock_version  integer NOT NULL DEFAULT 1 CHECK (lock_version >= 1),
            content_hash  bytea NULL CHECK (content_hash IS NULL OR octet_length(content_hash) = 32),
            change_level  text NULL CHECK (change_level IN ('initial', 'patch', 'minor', 'major')),
            created_at    timestamptz NOT NULL DEFAULT now(),
            created_by    uuid NULL REFERENCES control.persons (id),
            updated_at    timestamptz NOT NULL DEFAULT now(),
            published_at  timestamptz NULL,
            published_by  uuid NULL REFERENCES control.persons (id),
            CONSTRAINT fk_blueprint_versions__blueprint
                FOREIGN KEY (blueprint_id, vertical_id)
                REFERENCES control.blueprints (id, vertical_id),
            CONSTRAINT uq_blueprint_versions__semver
                UNIQUE (blueprint_id, version_major, version_minor, version_patch),
            CONSTRAINT uq_blueprint_versions__id_vertical UNIQUE (id, vertical_id),
            CONSTRAINT ck_blueprint_versions__publication CHECK (
                (status = 'draft' AND published_at IS NULL AND content_hash IS NULL
                    AND change_level IS NULL)
                OR (status <> 'draft' AND published_at IS NOT NULL AND content_hash IS NOT NULL
                    AND change_level IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_blueprint_versions__blueprint ON control.blueprint_versions "
        "(blueprint_id, version_major DESC, version_minor DESC, version_patch DESC)"
    )
    op.execute(
        """
        CREATE FUNCTION control.guard_blueprint_version() RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, pg_temp
        AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.status <> 'draft' THEN
              RAISE EXCEPTION 'published blueprint versions cannot be deleted'
                USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN OLD;
          END IF;

          IF OLD.status = 'draft' THEN
            IF NEW.status = 'published' THEN
              -- The database, not the application, fixes the content hash.
              NEW.content_hash := sha256(convert_to(NEW.definition::text, 'UTF8'));
            ELSIF NEW.status <> 'draft' THEN
              RAISE EXCEPTION 'a draft can only be published'
                USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
          END IF;

          IF (to_jsonb(NEW) - 'status' - 'updated_at')
             IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'updated_at') THEN
            RAISE EXCEPTION 'published blueprint versions are immutable'
              USING ERRCODE = 'restrict_violation';
          END IF;
          IF NOT (
               (OLD.status = 'published'  AND NEW.status IN ('published', 'deprecated'))
            OR (OLD.status = 'deprecated' AND NEW.status IN ('deprecated', 'published', 'retired'))
            OR (OLD.status = 'retired'    AND NEW.status = 'retired')
          ) THEN
            RAISE EXCEPTION 'invalid blueprint lifecycle transition % -> %', OLD.status, NEW.status
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION control.guard_blueprint_version() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER tr_blueprint_versions__guard
        BEFORE UPDATE OR DELETE ON control.blueprint_versions
        FOR EACH ROW EXECUTE FUNCTION control.guard_blueprint_version()
        """
    )
    op.execute("GRANT SELECT, INSERT ON control.blueprints TO arada_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.blueprint_versions TO arada_app")
    op.execute(
        "GRANT SELECT ON control.blueprints, control.blueprint_versions TO arada_platform_reader"
    )


def downgrade() -> None:
    op.execute("DROP TABLE control.blueprint_versions")
    op.execute("DROP FUNCTION control.guard_blueprint_version()")
    op.execute("DROP TABLE control.blueprints")
