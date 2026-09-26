"""Blueprint lifecycle API (platform and vertical administrators)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import Field

from arada.api.auth import CurrentPrincipal
from arada.api.deps import platform
from arada.api.schemas import RequestModel, ResponseModel
from arada.blueprints import service as blueprints
from arada.kernel.errors import PreconditionFailed, PreconditionRequired

router = APIRouter(prefix="/v1/platform/blueprints", tags=["blueprints"])


class BlueprintIn(RequestModel):
    vertical: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")
    name_en: str = Field(min_length=1, max_length=80)
    name_am: str | None = Field(default=None, min_length=1, max_length=80)


class BlueprintOut(ResponseModel):
    id: UUID
    vertical_id: UUID
    key: str
    name_en: str
    name_am: str | None


class DraftIn(RequestModel):
    version: str = Field(max_length=14)
    definition: dict[str, Any]


class DefinitionIn(RequestModel):
    definition: dict[str, Any]


class VersionOut(ResponseModel):
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


def _out(v: blueprints.Version) -> VersionOut:
    return VersionOut.model_validate(v)


def _etag(v: blueprints.Version) -> str:
    return f'"{v.lock_version}"'


def _if_match(value: str | None) -> int:
    if value is None:
        raise PreconditionRequired()
    stripped = value.strip().removeprefix("W/").strip('"')
    if not stripped.isdigit():
        raise PreconditionFailed()
    return int(stripped)


@router.post("", response_model=BlueprintOut, status_code=201, summary="Create a blueprint")
async def create_blueprint(
    body: BlueprintIn, principal: CurrentPrincipal, request: Request
) -> BlueprintOut:
    async with platform(request, principal) as scope:
        bp = await blueprints.create_blueprint(
            scope,
            vertical_key=body.vertical,
            key=body.key,
            name_en=body.name_en,
            name_am=body.name_am,
        )
    return BlueprintOut.model_validate(bp)


@router.get("", response_model=list[BlueprintOut], summary="List visible blueprints")
async def list_blueprints(
    principal: CurrentPrincipal,
    request: Request,
    vertical: str | None = Query(default=None, pattern=r"^[a-z][a-z0-9_]{1,39}$"),
) -> list[BlueprintOut]:
    async with platform(request, principal) as scope:
        items = await blueprints.list_blueprints(scope, vertical_key=vertical)
    return [BlueprintOut.model_validate(b) for b in items]


@router.post(
    "/{blueprint_id}/versions",
    response_model=VersionOut,
    status_code=201,
    summary="Draft a version",
)
async def create_draft(
    blueprint_id: UUID,
    body: DraftIn,
    principal: CurrentPrincipal,
    request: Request,
    response: Response,
) -> VersionOut:
    async with platform(request, principal) as scope:
        v = await blueprints.create_draft(
            scope, blueprint_id=blueprint_id, version=body.version, definition=body.definition
        )
    response.headers["ETag"] = _etag(v)
    return _out(v)


@router.get("/{blueprint_id}/versions", response_model=list[VersionOut], summary="List versions")
async def list_versions(
    blueprint_id: UUID, principal: CurrentPrincipal, request: Request
) -> list[VersionOut]:
    async with platform(request, principal) as scope:
        items = await blueprints.list_versions(scope, blueprint_id=blueprint_id)
    return [_out(v) for v in items]


@router.get(
    "/{blueprint_id}/versions/{version_id}", response_model=VersionOut, summary="Get version"
)
async def get_version(
    blueprint_id: UUID,
    version_id: UUID,
    principal: CurrentPrincipal,
    request: Request,
    response: Response,
) -> VersionOut:
    async with platform(request, principal) as scope:
        v = await blueprints.get_version(scope, blueprint_id=blueprint_id, version_id=version_id)
    response.headers["ETag"] = _etag(v)
    return _out(v)


@router.put(
    "/{blueprint_id}/versions/{version_id}/definition",
    response_model=VersionOut,
    summary="Replace a draft's definition (If-Match required)",
)
async def update_draft(
    blueprint_id: UUID,
    version_id: UUID,
    body: DefinitionIn,
    principal: CurrentPrincipal,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None),
) -> VersionOut:
    expected = _if_match(if_match)
    async with platform(request, principal) as scope:
        v = await blueprints.update_draft(
            scope,
            blueprint_id=blueprint_id,
            version_id=version_id,
            definition=body.definition,
            expected_lock_version=expected,
        )
    response.headers["ETag"] = _etag(v)
    return _out(v)


@router.post(
    "/{blueprint_id}/versions/{version_id}:publish", response_model=VersionOut, summary="Publish"
)
async def publish(
    blueprint_id: UUID, version_id: UUID, principal: CurrentPrincipal, request: Request
) -> VersionOut:
    async with platform(request, principal) as scope:
        v = await blueprints.publish(scope, blueprint_id=blueprint_id, version_id=version_id)
    return _out(v)


@router.post(
    "/{blueprint_id}/versions/{version_id}:{action}",
    response_model=VersionOut,
    summary="Deprecate, retire or reinstate a published version",
)
async def lifecycle(
    blueprint_id: UUID,
    version_id: UUID,
    action: Literal["deprecate", "retire", "reinstate"],
    principal: CurrentPrincipal,
    request: Request,
) -> VersionOut:
    status = {"deprecate": "deprecated", "retire": "retired", "reinstate": "published"}[action]
    async with platform(request, principal) as scope:
        v = await blueprints.set_lifecycle(
            scope, blueprint_id=blueprint_id, version_id=version_id, status=status
        )
    return _out(v)
