"""Blueprint version immutability enforced by PostgreSQL (Gate 6, DB layer)."""

from __future__ import annotations

import hashlib
import json

import asyncpg
import pytest

from arada.kernel.ids import uuid7


async def _published_version(conn: asyncpg.Connection) -> asyncpg.Record:
    vertical, blueprint, version = uuid7(), uuid7(), uuid7()
    await conn.execute(
        "INSERT INTO control.verticals (id, key, name_en) VALUES ($1, $2, 'V')",
        vertical,
        f"v{vertical.hex[:12]}",
    )
    await conn.execute(
        "INSERT INTO control.blueprints (id, vertical_id, key, name_en) VALUES ($1, $2, 'bp', 'B')",
        blueprint,
        vertical,
    )
    definition = json.dumps(
        {
            "schema_version": 1,
            "entities": {"x": {"kind": "core", "attributes": [{"key": "a", "type": "string"}]}},
        }
    )
    await conn.execute(
        "INSERT INTO control.blueprint_versions "
        "(id, blueprint_id, vertical_id, version_major, version_minor, version_patch, definition) "
        "VALUES ($1, $2, $3, 1, 0, 0, $4::jsonb)",
        version,
        blueprint,
        vertical,
        definition,
    )
    await conn.execute(
        "UPDATE control.blueprint_versions SET status = 'published', published_at = now(), "
        "change_level = 'initial' WHERE id = $1",
        version,
    )
    row = await conn.fetchrow("SELECT * FROM control.blueprint_versions WHERE id = $1", version)
    assert row is not None
    return row


async def test_database_computes_content_hash_at_publication(
    owner_conn: asyncpg.Connection,
) -> None:
    row = await _published_version(owner_conn)
    text = await owner_conn.fetchval(
        "SELECT definition::text FROM control.blueprint_versions WHERE id = $1", row["id"]
    )
    assert bytes(row["content_hash"]) == hashlib.sha256(text.encode()).digest()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE control.blueprint_versions SET definition = '{}'::jsonb WHERE id = $1",
        "UPDATE control.blueprint_versions SET version_minor = 9 WHERE id = $1",
        "UPDATE control.blueprint_versions SET content_hash = sha256('x') WHERE id = $1",
        "UPDATE control.blueprint_versions SET status = 'draft' WHERE id = $1",
        "DELETE FROM control.blueprint_versions WHERE id = $1",
    ],
)
async def test_published_versions_are_immutable_even_for_the_owner(
    owner_conn: asyncpg.Connection, statement: str
) -> None:
    row = await _published_version(owner_conn)
    with pytest.raises(asyncpg.RestrictViolationError):
        await owner_conn.execute(statement, row["id"])


async def test_lifecycle_transitions(owner_conn: asyncpg.Connection) -> None:
    row = await _published_version(owner_conn)
    update = "UPDATE control.blueprint_versions SET status = $2 WHERE id = $1"
    await owner_conn.execute(update, row["id"], "deprecated")
    await owner_conn.execute(update, row["id"], "published")  # reinstated
    await owner_conn.execute(update, row["id"], "deprecated")
    await owner_conn.execute(update, row["id"], "retired")
    with pytest.raises(asyncpg.RestrictViolationError):
        await owner_conn.execute(update, row["id"], "published")  # retired is final
