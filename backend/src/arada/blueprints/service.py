"""Blueprint lifecycle: blueprints, draft versions, publication, deprecation.

Authorisation is at the vertical: platform roles, or vertical roles for the
blueprint's own vertical. A published version is immutable (enforced by the
database), and publication refuses a version number that under-declares the
change (a breaking change can never ship as 1.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from arada.audit import service as audit
from arada.blueprints import definition as bp_def
from arada.blueprints.tables import blueprint_versions, blueprints
from arada.kernel.errors import Conflict, NotFound, PreconditionFailed, ValidationFailed
from arada.kernel.ids import uuid7
from arada.kernel.scope import Scope
from arada.verticals import service as verticals


@dataclass(frozen=True, slots=True)
class Blueprint:
    id: UUID
    vertical_id: UUID
    key: str
    name_en: str
    name_am: str | None


@dataclass(frozen=True, slots=True)
class Version:
    id: UUID
    blueprint_id: UUID
    vertical_id: UUID
    version: str
    status: str
    lock_version: int
    change_level: str | None
    content_hash: str | None
    published_at: datetime | None
    definition: dict[str, Any] | None = None


_BP_COLS = (
    blueprints.c.id,
    blueprints.c.vertical_id,
    blueprints.c.key,
    blueprints.c.name_en,
    blueprints.c.name_am,
)
_V = blueprint_versions.c
_V_COLS = (
    _V.id, _V.blueprint_id, _V.vertical_id, _V.version_major, _V.version_minor, _V.version_patch,
    _V.status, _V.lock_version, _V.change_level, _V.content_hash, _V.published_at,
)  # fmt: skip


def _version(row: Any, with_definition: bool = False) -> Version:
    return Version(
        id=row.id,
        blueprint_id=row.blueprint_id,
        vertical_id=row.vertical_id,
        version=f"{row.version_major}.{row.version_minor}.{row.version_patch}",
        status=row.status,
        lock_version=row.lock_version,
        change_level=row.change_level,
        content_hash=row.content_hash.hex() if row.content_hash else None,
        published_at=row.published_at,
        definition=row.definition if with_definition else None,
    )


async def create_blueprint(
    scope: Scope, *, vertical_key: str, key: str, name_en: str, name_am: str | None
) -> Blueprint:
    vertical = await verticals.get_by_key(scope.conn, vertical_key)
    scope.require("blueprints.manage", vertical_id=vertical.id)
    blueprint_id = uuid7()
    try:
        async with scope.conn.begin_nested():
            await scope.conn.execute(
                insert(blueprints).values(
                    id=blueprint_id,
                    vertical_id=vertical.id,
                    key=key,
                    name_en=name_en,
                    name_am=name_am,
                    created_by=scope.actor_person_id,
                )
            )
    except IntegrityError as exc:
        raise Conflict("a blueprint with this key already exists in the vertical") from exc
    await audit.record_in(
        scope,
        action="blueprint.created",
        resource_type="blueprint",
        resource_id=blueprint_id,
        after={"vertical": vertical_key, "key": key, "name_en": name_en},
    )
    return Blueprint(blueprint_id, vertical.id, key, name_en, name_am)


async def get_blueprint(conn: AsyncConnection, blueprint_id: UUID) -> Blueprint:
    row = (await conn.execute(select(*_BP_COLS).where(blueprints.c.id == blueprint_id))).first()
    if row is None:
        raise NotFound("blueprint not found")
    return Blueprint(*row)


async def _visible_blueprint(scope: Scope, blueprint_id: UUID, permission: str) -> Blueprint:
    blueprint = await get_blueprint(scope.conn, blueprint_id)
    if not scope.has(permission, vertical_id=blueprint.vertical_id):
        # Callers without read access learn nothing about the blueprint.
        if not scope.has("blueprints.read", vertical_id=blueprint.vertical_id):
            raise NotFound("blueprint not found")
        scope.require(permission, vertical_id=blueprint.vertical_id)
    return blueprint


async def list_blueprints(scope: Scope, *, vertical_key: str | None = None) -> list[Blueprint]:
    query = select(*_BP_COLS).order_by(blueprints.c.key)
    if vertical_key is not None:
        vertical = await verticals.get_by_key(scope.conn, vertical_key)
        scope.require("blueprints.read", vertical_id=vertical.id)
        query = query.where(blueprints.c.vertical_id == vertical.id)
    elif "blueprints.read" not in scope.grants.platform:
        visible = [v for v, perms in scope.grants.vertical.items() if "blueprints.read" in perms]
        if not visible:
            scope.require("blueprints.read")
        query = query.where(blueprints.c.vertical_id.in_(visible))
    return [Blueprint(*row) for row in (await scope.conn.execute(query)).all()]


async def _latest_published(conn: AsyncConnection, blueprint_id: UUID) -> Any:
    return (
        await conn.execute(
            select(*_V_COLS, _V.definition)
            .where(and_(_V.blueprint_id == blueprint_id, _V.status != "draft"))
            .order_by(_V.version_major.desc(), _V.version_minor.desc(), _V.version_patch.desc())
            .limit(1)
        )
    ).first()


async def create_draft(
    scope: Scope, *, blueprint_id: UUID, version: str, definition: dict[str, Any]
) -> Version:
    blueprint = await _visible_blueprint(scope, blueprint_id, "blueprints.manage")
    semver = bp_def.SemVer.parse(version)
    bp_def.validate(definition)
    latest = await _latest_published(scope.conn, blueprint_id)
    if latest is not None:
        released = bp_def.SemVer(latest.version_major, latest.version_minor, latest.version_patch)
        if not semver > released:
            raise ValidationFailed(errors={"version": [f"must be greater than {released}"]})
    version_id = uuid7()
    try:
        async with scope.conn.begin_nested():
            await scope.conn.execute(
                insert(blueprint_versions).values(
                    id=version_id,
                    blueprint_id=blueprint_id,
                    vertical_id=blueprint.vertical_id,
                    version_major=semver.major,
                    version_minor=semver.minor,
                    version_patch=semver.patch,
                    definition=definition,
                    created_by=scope.actor_person_id,
                )
            )
    except IntegrityError as exc:
        raise Conflict(f"version {semver} already exists") from exc
    await audit.record_in(
        scope,
        action="blueprint.version_drafted",
        resource_type="blueprint_version",
        resource_id=version_id,
        after={"blueprint_id": blueprint_id, "version": str(semver)},
    )
    return await get_version(scope, blueprint_id=blueprint_id, version_id=version_id)


async def _locked_version(scope: Scope, blueprint_id: UUID, version_id: UUID) -> Any:
    row = (
        await scope.conn.execute(
            select(*_V_COLS, _V.definition)
            .where(and_(_V.id == version_id, _V.blueprint_id == blueprint_id))
            .with_for_update()
        )
    ).first()
    if row is None:
        raise NotFound("blueprint version not found")
    return row


async def update_draft(
    scope: Scope,
    *,
    blueprint_id: UUID,
    version_id: UUID,
    definition: dict[str, Any],
    expected_lock_version: int,
) -> Version:
    await _visible_blueprint(scope, blueprint_id, "blueprints.manage")
    row = await _locked_version(scope, blueprint_id, version_id)
    if row.status != "draft":
        raise Conflict("published blueprint versions are immutable; draft a new version")
    if row.lock_version != expected_lock_version:
        raise PreconditionFailed()
    bp_def.validate(definition)
    await scope.conn.execute(
        update(blueprint_versions)
        .where(_V.id == version_id)
        .values(definition=definition, lock_version=_V.lock_version + 1, updated_at=func.now())
    )
    await audit.record_in(
        scope,
        action="blueprint.version_updated",
        resource_type="blueprint_version",
        resource_id=version_id,
    )
    return await get_version(scope, blueprint_id=blueprint_id, version_id=version_id)


async def publish(scope: Scope, *, blueprint_id: UUID, version_id: UUID) -> Version:
    await _visible_blueprint(scope, blueprint_id, "blueprints.publish")
    # Serialise publications of the same blueprint without needing UPDATE on
    # the blueprints table (least privilege): a transaction-scoped advisory lock.
    await scope.conn.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(blueprint_id), 0)))
    )
    row = await _locked_version(scope, blueprint_id, version_id)
    if row.status != "draft":
        raise Conflict("only drafts can be published")
    bp_def.validate(row.definition)  # extensions may have changed since drafting

    semver = bp_def.SemVer(row.version_major, row.version_minor, row.version_patch)
    latest = await _latest_published(scope.conn, blueprint_id)
    reasons: tuple[str, ...] = ()
    if latest is None:
        change_level = "initial"
    else:
        released = bp_def.SemVer(latest.version_major, latest.version_minor, latest.version_patch)
        if not semver > released:
            raise Conflict(f"version {semver} is not greater than published {released}")
        compat = bp_def.classify(latest.definition, row.definition)
        if compat.level == "none":
            raise Conflict("no changes compared with the latest published version")
        declared = semver.bump_from(released)
        if bp_def.LEVELS.index(declared) < bp_def.LEVELS.index(compat.level):
            raise Conflict(
                f"this is a {compat.level} change but {semver} declares a {declared} bump",
            )
        change_level, reasons = declared, compat.reasons

    await scope.conn.execute(
        update(blueprint_versions)
        .where(_V.id == version_id)
        .values(
            status="published",
            change_level=change_level,
            published_at=func.now(),
            published_by=scope.actor_person_id,
            updated_at=func.now(),
        )
    )
    await audit.record_in(
        scope,
        action="blueprint.version_published",
        resource_type="blueprint_version",
        resource_id=version_id,
        after={"version": str(semver), "change_level": change_level, "changes": list(reasons)},
    )
    return await get_version(scope, blueprint_id=blueprint_id, version_id=version_id)


async def set_lifecycle(
    scope: Scope, *, blueprint_id: UUID, version_id: UUID, status: str
) -> Version:
    await _visible_blueprint(scope, blueprint_id, "blueprints.publish")
    row = await _locked_version(scope, blueprint_id, version_id)
    if row.status == "draft":
        raise Conflict("drafts must be published first")
    await scope.conn.execute(
        update(blueprint_versions)
        .where(_V.id == version_id)
        .values(status=status, updated_at=func.now())
    )
    await audit.record_in(
        scope,
        action=f"blueprint.version_{status}",
        resource_type="blueprint_version",
        resource_id=version_id,
        before={"status": row.status},
        after={"status": status},
    )
    return await get_version(scope, blueprint_id=blueprint_id, version_id=version_id)


async def list_versions(scope: Scope, *, blueprint_id: UUID) -> list[Version]:
    await _visible_blueprint(scope, blueprint_id, "blueprints.read")
    rows = (
        await scope.conn.execute(
            select(*_V_COLS)
            .where(_V.blueprint_id == blueprint_id)
            .order_by(_V.version_major, _V.version_minor, _V.version_patch)
        )
    ).all()
    return [_version(r) for r in rows]


async def get_version(scope: Scope, *, blueprint_id: UUID, version_id: UUID) -> Version:
    await _visible_blueprint(scope, blueprint_id, "blueprints.read")
    row = (
        await scope.conn.execute(
            select(*_V_COLS, _V.definition).where(
                and_(_V.id == version_id, _V.blueprint_id == blueprint_id)
            )
        )
    ).first()
    if row is None:
        raise NotFound("blueprint version not found")
    return _version(row, with_definition=True)


async def version_summary(conn: AsyncConnection, version_id: UUID) -> Version:
    """Unauthorised internal read used by tenancy after its own checks."""
    row = (await conn.execute(select(*_V_COLS).where(_V.id == version_id))).first()
    if row is None:
        raise NotFound("blueprint version not found")
    return _version(row)
