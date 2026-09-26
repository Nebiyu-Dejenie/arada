"""Request dependencies shared by all routers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from arada.access.scopes import platform_scope, tenant_scope
from arada.kernel.config import Settings
from arada.kernel.context import Principal, RequestMeta
from arada.kernel.crypto import Keyring
from arada.kernel.db import Database
from arada.kernel.scope import Scope


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    db: Database
    keyring: Keyring


def container_of(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def request_meta(request: Request) -> RequestMeta:
    meta: RequestMeta = request.scope["state"]["meta"]
    return meta


Meta = Annotated[RequestMeta, Depends(request_meta)]


@asynccontextmanager
async def platform(request: Request, principal: Principal) -> AsyncIterator[Scope]:
    c = container_of(request)
    async with platform_scope(c.db, c.settings, request_meta(request), principal) as scope:
        yield scope


@asynccontextmanager
async def tenant(request: Request, principal: Principal, slug: str) -> AsyncIterator[Scope]:
    c = container_of(request)
    async with tenant_scope(c.db, c.settings, request_meta(request), principal, slug) as scope:
        yield scope
