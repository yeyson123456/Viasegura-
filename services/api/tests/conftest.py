"""Shared fixtures.

* `client`: the real app with a fake database (unit tests, no MongoDB needed).
* `api`: the real app against a real MongoDB in a throw-away database (integration tests).
"""

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db import get_mongo
from app.main import create_app

TEST_MONGODB_URI = os.getenv("TEST_MONGODB_URI", "mongodb://localhost:27017")
ADMIN_KEY = "test-admin-key"


class FakeMongo:
    """Stands in for app.db.Mongo; `reachable` decides what ping() answers."""

    def __init__(self, reachable: bool = True) -> None:
        self.reachable = reachable
        self.pings = 0

    async def ping(self) -> bool:
        self.pings += 1
        return self.reachable


def unit_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "api_env": "test",
        "api_cors_origins": "http://localhost:5173",
        # Unreachable on purpose: unit tests never touch a real database.
        "mongodb_uri": "mongodb://127.0.0.1:1",
        "mongodb_timeout_ms": 200,
        "startup_schema_wait_s": 0,
        "model_path": str(tmp_path / "no-model.onnx"),
        "media_dir": str(tmp_path / "media"),
    }
    return Settings(**{**values, **overrides})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return unit_settings(tmp_path)


@pytest.fixture
def make_settings(tmp_path: Path):
    """Unit-test settings with overrides, e.g. make_settings(mongodb_uri=...)."""
    return lambda **overrides: unit_settings(tmp_path, **overrides)


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


async def _require_mongo() -> None:
    from app.db import Mongo

    probe = Mongo(TEST_MONGODB_URI, "admin", timeout_ms=1500)
    reachable = await probe.ping()
    await probe.close()
    if not reachable:
        if os.getenv("TEST_REQUIRE_MONGO") == "1":
            pytest.fail(f"MongoDB is required but not reachable at {TEST_MONGODB_URI}")
        pytest.skip(f"MongoDB not reachable at {TEST_MONGODB_URI}")


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, FastAPI]]:
    """Real app + real MongoDB (unique database, dropped afterwards). Consensus: N=3, R=30 m,
    T=60 min."""
    await _require_mongo()
    db_name = f"viasegura_test_{uuid.uuid4().hex[:10]}"
    application = create_app(
        Settings(
            api_env="test",
            mongodb_uri=TEST_MONGODB_URI,
            mongodb_db=db_name,
            admin_api_key=ADMIN_KEY,
            consensus_min_devices=3,
            consensus_radius_m=30,
            consensus_window_min=60,
            model_path=str(tmp_path / "no-model.onnx"),
            media_dir=str(tmp_path / "media"),
            startup_schema_wait_s=15,
        )
    )
    async for http in _client_for(application):
        yield http, application
        await application.state.mongo.client.drop_database(db_name)
