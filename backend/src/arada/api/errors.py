"""RFC 9457 problem responses.

Every error leaving the API is a problem document with a stable ``type``, the
request id, and nothing else from the inside: no stack traces, SQL, driver
messages, or echoed input values (validation errors never include the
submitted value, so a mistyped password is never reflected back).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from arada.kernel.context import RequestMeta
from arada.kernel.errors import AppError
from arada.kernel.logging import get_logger

log = get_logger("arada.errors")

_PROBLEM = "application/problem+json"


def _problem(
    request: Request,
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    errors: dict[str, list[str]] | None = None,
) -> JSONResponse:
    meta: RequestMeta | None = request.scope.get("state", {}).get("meta")
    body: dict[str, Any] = {
        "type": f"urn:arada:problem:{code}",
        "title": title,
        "status": status,
        "instance": request.url.path,
        "request_id": meta.request_id if meta else None,
    }
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=_PROBLEM)


def _sqlstate(exc: DBAPIError) -> str | None:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(
        getattr(orig, "__cause__", None), "sqlstate", None
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        errors = {k: list(v) for k, v in exc.errors.items()} if exc.errors else None
        return _problem(request, exc.status, exc.code, exc.title, exc.detail, errors)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors: dict[str, list[str]] = {}
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", ()) if part != "body") or "request"
            # Only the message: never err["input"], which may contain secrets.
            errors.setdefault(loc, []).append(str(err.get("msg", "invalid")))
        return _problem(request, 422, "validation-failed", "Validation failed", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        titles = {404: "Not found", 405: "Method not allowed"}
        code = {404: "not-found", 405: "method-not-allowed"}.get(exc.status_code, "http-error")
        return _problem(request, exc.status_code, code, titles.get(exc.status_code, "HTTP error"))

    @app.exception_handler(IntegrityError)
    async def _integrity(request: Request, exc: IntegrityError) -> JSONResponse:
        state = _sqlstate(exc)
        log.warning("db.integrity_error", sqlstate=state)
        if state == "23505":
            return _problem(request, 409, "conflict", "Conflict", "resource already exists")
        return _problem(request, 422, "constraint-violation", "Request violates a data constraint")

    @app.exception_handler(DBAPIError)
    async def _dbapi(request: Request, exc: DBAPIError) -> JSONResponse:
        state = _sqlstate(exc)
        if state == "42501":  # RLS or privilege violation: defence in depth fired
            log.error("db.privilege_violation", sqlstate=state)
            return _problem(request, 403, "forbidden", "Not permitted")
        log.error("db.error", sqlstate=state, error_class=type(exc.orig).__name__)
        return _problem(request, 500, "internal-error", "Internal error")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("http.unhandled_exception", error_class=type(exc).__name__, exc_info=exc)
        return _problem(request, 500, "internal-error", "Internal error")
