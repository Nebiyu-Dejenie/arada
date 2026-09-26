"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from arada.api.deps import Container
from arada.api.errors import install_error_handlers
from arada.api.middleware import (
    BodySizeLimitMiddleware,
    CorrelationMiddleware,
    SecurityHeadersMiddleware,
)
from arada.api.routes import auth, blueprints, health, me, platform
from arada.kernel.config import Settings, get_settings
from arada.kernel.crypto import Keyring
from arada.kernel.db import Database
from arada.kernel.logging import configure_logging, get_logger

log = get_logger("arada.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings)
        app.state.container = Container(
            settings=settings,
            db=db,
            keyring=Keyring({settings.kek_version: settings.kek}, settings.kek_version),
        )
        log.info("app.started", environment=settings.environment.value)
        try:
            yield
        finally:
            await db.dispose()
            log.info("app.stopped")

    docs = settings.expose_api_docs
    app = FastAPI(
        title="ARADA Platform API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(platform.router)
    app.include_router(blueprints.router)

    # Outermost first: correlation wraps everything so even 413s carry ids.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, csp_exempt_prefixes=("/docs",))
    app.add_middleware(CorrelationMiddleware)
    return app
