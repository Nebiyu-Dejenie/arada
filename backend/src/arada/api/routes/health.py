from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from arada.api.deps import container_of

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Process liveness")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness: the database answers")
async def readyz(request: Request) -> JSONResponse:
    ok = False
    try:
        ok = await container_of(request).db.ping()
    except Exception:  # noqa: BLE001  readiness must report, not raise
        ok = False
    return JSONResponse(
        {"status": "ready" if ok else "not-ready", "database": "ok" if ok else "unavailable"},
        status_code=200 if ok else 503,
    )
