"""Request dependencies shared by all routers."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from arada.kernel.config import Settings
from arada.kernel.context import RequestMeta
from arada.kernel.crypto import Keyring
from arada.kernel.db import Database


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
