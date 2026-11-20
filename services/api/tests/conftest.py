"""Shared fixtures: the real app with a fake database, driven through httpx's ASGI transport."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db import get_mongo
from app.main import create_app


class FakeMongo:
    """Stands in for app.db.Mongo; `reachable` decides what ping() answers."""

    def __init__(self, reachable: bool = True) -> None:
        self.reachable = reachable
        self.pings = 0

    async def ping(self) -> bool:
        self.pings += 1
        return self.reachable


@pytest.fixture
def settings() -> Settings:
    return Settings(
        api_env="test",
        api_cors_origins="http://localhost:5173",
        # Unused while get_mongo is overridden; the real client connects lazily anyway.
        mongodb_uri="mongodb://localhost:1",
        mongodb_timeout_ms=200,
    )


@pytest.fixture
def fake_mongo() -> FakeMongo:
    return FakeMongo(reachable=True)


@pytest.fixture
def app(settings: Settings, fake_mongo: FakeMongo) -> FastAPI:
    application = create_app(settings)
    application.dependency_overrides[get_mongo] = lambda: fake_mongo
    return application


async def _client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    # Run the real lifespan (start-up and shutdown) around the requests, as uvicorn does.
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async for http in _client_for(app):
        yield http


@pytest.fixture
def client_for():
    """Factory for tests that need a client around a differently configured app."""
    return _client_for
