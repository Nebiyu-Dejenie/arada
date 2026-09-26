"""Shared SQLAlchemy metadata and column helpers.

Tables are declared with SQLAlchemy Core (not the ORM) so every query is
explicit about what it touches (ADR-004). The DDL itself lives in the
Alembic migrations, which also carry the PostgreSQL-specific parts (RLS,
triggers, grants). ``tests/integration/test_migrations.py`` fails if these
declarations and the migrated schema drift apart.
"""

from __future__ import annotations

from sqlalchemy import MetaData

metadata = MetaData(schema="control")
