"""Checks against a real MongoDB.

Skipped when no database is reachable (e.g. Docker is off). Set TEST_REQUIRE_MONGO=1 to turn the
skip into a failure, as CI does.
"""

import os
from collections.abc import AsyncIterator

import pytest

from app.config import Settings
from app.db import Mongo
from app.main import create_app

pytestmark = pytest.mark.integration

MONGODB_URI = os.getenv("TEST_MONGODB_URI", "mongodb://localhost:27017")
TEST_DB = "viasegura_test"


@pytest.fixture
async def mongo() -> AsyncIterator[Mongo]:
    database = Mongo(MONGODB_URI, TEST_DB, timeout_ms=1500)
    if not await database.ping():
        await database.close()
        if os.getenv("TEST_REQUIRE_MONGO") == "1":
            pytest.fail(f"MongoDB is required but not reachable at {MONGODB_URI}")
        pytest.skip(f"MongoDB not reachable at {MONGODB_URI}")
    yield database
    await database.client.drop_database(TEST_DB)
    await database.close()


async def test_insert_and_read_back(mongo: Mongo) -> None:
    result = await mongo.db.smoke.insert_one({"hello": "world"})

    document = await mongo.db.smoke.find_one({"_id": result.inserted_id})

    assert document is not None
    assert document["hello"] == "world"


async def test_health_is_ok_against_real_database(mongo: Mongo, client_for) -> None:
    app = create_app(Settings(api_env="test", mongodb_uri=MONGODB_URI, mongodb_db=TEST_DB))

    async for http in client_for(app):
        response = await http.get("/health")

    assert response.status_code == 200
    assert response.json()["checks"] == {"database": "ok"}
