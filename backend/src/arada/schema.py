"""Registry of every module's table declarations, so ``metadata`` is complete.

Used by Alembic (target metadata) and by the schema drift test. A module's
tables are declared on the shared metadata when its ``tables`` module is
imported; listing them here makes that dependency explicit.
"""

from __future__ import annotations

from arada.audit import tables as audit_tables
from arada.identity import tables as identity_tables
from arada.kernel.sql import metadata

TABLE_MODULES = (audit_tables, identity_tables)

__all__ = ["TABLE_MODULES", "metadata"]
