"""ASGI middleware: correlation, security headers, request size limit.

Pure ASGI (not BaseHTTPMiddleware) so context variables propagate correctly
and streaming is not buffered.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from arada.kernel.context import RequestMeta, bind_request, current_correlation
from arada.kernel.logging import get_logger
from arada.kernel.tracing import new_span, parse_traceparent

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

log = get_logger("arada.http")


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return str(value.decode("latin-1"))
    return None


class CorrelationMiddleware:
    """Assigns request_id and W3C trace context to every request.

    A client-supplied X-Request-Id is never trusted: in production the edge
    proxy is the only party allowed to originate one, and in Phase 1 the
    application always generates its own. A valid ``traceparent`` continues
    the caller's trace; anything else starts a new trace.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        span = new_span(parse_traceparent(_header(scope, b"traceparent")))
        bind_request(request_id, span.trace_id)
        client = scope.get("client")
        scope.setdefault("state", {})["meta"] = RequestMeta(
            request_id=request_id,
            trace_id=span.trace_id,
            source="api",
            ip=client[0] if client else None,
            user_agent=(_header(scope, b"user-agent") or "")[:256] or None,
        )

        started = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                headers.append((b"traceparent", span.header().encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            corr = current_correlation()
            log.info(
                "http.request",
                method=scope.get("method"),
                route=getattr(route, "path", None) or "unmatched",
                status=status_holder["status"],
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                tenant_id=corr.tenant_id,
                user_id=corr.user_id,
            )


class SecurityHeadersMiddleware:
    _HEADERS = (
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"no-referrer"),
        (b"x-frame-options", b"DENY"),
        (b"cache-control", b"no-store"),
        (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    )

    def __init__(self, app: ASGIApp, *, csp_exempt_prefixes: tuple[str, ...] = ()) -> None:
        self.app = app
        self.csp_exempt_prefixes = csp_exempt_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        exempt = str(scope.get("path", "")).startswith(self.csp_exempt_prefixes)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for key, value in self._HEADERS:
                    if exempt and key == b"content-security-policy":
                        continue
                    if key not in present:
                        headers.append((key, value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than the configured limit with 413."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _header(scope, b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await _reject_too_large(send)
            return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await _reject_too_large(send)


class _BodyTooLarge(Exception):
    pass


async def _reject_too_large(send: Send) -> None:
    body = (
        b'{"type":"urn:arada:problem:payload-too-large","title":"Payload too large","status":413}'
    )
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
