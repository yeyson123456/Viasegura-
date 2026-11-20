"""FastAPI application factory and ASGI entry point (`uvicorn app.main:app`)."""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import Settings, get_settings
from app.db import Mongo
from app.errors import register_error_handlers
from app.logging_setup import configure_logging
from app.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.routers import health
from app.schemas.common import ErrorResponse

logger = logging.getLogger("viasegura.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.api_log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started_at = time.monotonic()
        app.state.mongo = Mongo(
            settings.mongodb_uri, settings.mongodb_db, settings.mongodb_timeout_ms
        )
        logger.info("startup", extra={"environment": settings.api_env, "version": __version__})
        try:
            yield
        finally:
            await app.state.mongo.close()
            logger.info("shutdown")

    app = FastAPI(
        title="VíaSegura IA API",
        version=__version__,
        summary="Crowdsourced road-hazard reports, consensus and road-segment risk.",
        lifespan=lifespan,
        responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    app.state.settings = settings

    # The middleware added last runs first, so CORS answers pre-flight requests directly.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER, "X-Admin-Key"],
        expose_headers=[REQUEST_ID_HEADER],
        max_age=600,
    )
    register_error_handlers(app)
    app.include_router(health.router)
    return app


app = create_app()
