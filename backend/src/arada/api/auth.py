"""Authentication dependency: bearer token -> Principal.

Tokens are accepted only in the ``Authorization`` header: never in query
strings (which end up in logs and browser history).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from arada.api.deps import container_of
from arada.identity import sessions
from arada.kernel.context import Principal, bind_user
from arada.kernel.errors import Unauthenticated

_MIN_TOKEN, _MAX_TOKEN = 20, 200


async def authenticated(request: Request) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not _MIN_TOKEN <= len(token) <= _MAX_TOKEN:
        raise Unauthenticated()
    container = container_of(request)
    async with container.db.transaction() as conn:
        principal = await sessions.authenticate(conn, container.settings, token)
    bind_user(principal.person_id)
    return principal


CurrentPrincipal = Annotated[Principal, Depends(authenticated)]


async def optionally_authenticated(request: Request) -> Principal | None:
    """For endpoints usable both anonymously and logged in (e.g. accepting an
    invitation). A present-but-invalid token is still rejected."""
    if "authorization" not in request.headers:
        return None
    return await authenticated(request)


OptionalPrincipal = Annotated[Principal | None, Depends(optionally_authenticated)]
