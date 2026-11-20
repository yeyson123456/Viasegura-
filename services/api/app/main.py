"""FastAPI application factory and ASGI entry point (`uvicorn app.main:app`)."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pymongo.errors import PyMongoError

from app import __version__
from app.config import Settings, get_settings
from app.db import Mongo, ensure_schema
from app.errors import register_error_handlers
from app.logging_setup import configure_logging
from app.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.routers import health, incidents, media, reports, segments
from app.schemas.common import ErrorResponse
from app.services.consensus import ConsensusRules, ConsensusService
from app.services.detector import HazardDetector
from app.services.events import EventPublisher
from app.services.storage import build_storage

logger = logging.getLogger("viasegura.api")


async def _ensure_schema_until_ready(app: FastAPI, mongo: Mongo, settings: Settings) -> None:
    """Retry with backoff: the API stays up (and /health says why) while MongoDB is down."""
    delay = 1.0
    while True:
        try:
            await ensure_schema(mongo.db, settings.reports_ttl_days, settings.seed_segments)
            app.state.schema_ready = True
            logger.info("schema_ready")
            return
        except PyMongoError as exc:
            logger.warning("schema_not_ready", extra={"error": str(exc)[:300], "retry_s": delay})
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.api_log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started_at = time.monotonic()
        mongo = Mongo(settings.mongodb_uri, settings.mongodb_db, settings.mongodb_timeout_ms)
        app.state.mongo = mongo
        app.state.schema_ready = False
        app.state.detector = HazardDetector.load(settings.model_path)
        app.state.storage = build_storage(
            settings.azure_storage_connection_string, settings.blob_container, settings.media_dir
        )
        events = EventPublisher(
            mongo.db, settings.azure_storage_connection_string, settings.events_queue
        )
        app.state.consensus = ConsensusService(
            mongo.db,
            ConsensusRules(
                min_devices=settings.consensus_min_devices,
                radius_m=settings.consensus_radius_m,
                window=timedelta(minutes=settings.consensus_window_min),
                segment_radius_m=settings.segment_match_radius_m,
            ),
            events,
        )
        schema_task = asyncio.create_task(_ensure_schema_until_ready(app, mongo, settings))
        # Fast path: when MongoDB is up the schema is ready before the first request.
        if settings.startup_schema_wait_s > 0:
            await asyncio.wait({schema_task}, timeout=settings.startup_schema_wait_s)
        logger.info("startup", extra={"environment": settings.api_env, "version": __version__})
        try:
            yield
        finally:
            schema_task.cancel()
            await mongo.close()
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
    for router in (health.router, reports.router, incidents.router, segments.router, media.router):
        app.include_router(router)
    return app


app = create_app()
