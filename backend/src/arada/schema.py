"""Imports every module's table declarations so ``metadata`` is complete.

Used by Alembic (target metadata) and by the schema drift test.
"""

from __future__ import annotations

import arada.audit.tables  # noqa: F401
from arada.kernel.sql import metadata

__all__ = ["metadata"]
