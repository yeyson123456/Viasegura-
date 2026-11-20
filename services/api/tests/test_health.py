"""Health endpoints and request-id propagation."""

import re

from httpx import AsyncClient

from app.main import create_app


async def test_health_ok_when_database_answers(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok"}
    assert body["environment"] == "test"
    assert body["uptime_s"] >= 0
    assert response.headers["cache-control"] == "no-store"


async def test_health_degraded_when_database_unreachable(client: AsyncClient, fake_mongo) -> None:
    fake_mongo.reachable = False

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"] == {"database": "unreachable"}


async def test_health_degraded_with_real_client_and_no_database(client_for, make_settings) -> None:
    # No dependency override: exercises the real PyMongo client against a closed port.
    app = create_app(make_settings())
    async for http in client_for(app):
        response = await http.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"] == {"database": "unreachable"}
    assert body["components"]["schema"] == "pending"
    assert body["components"]["detector"] == "disabled"


async def test_liveness_never_touches_database(client: AsyncClient, fake_mongo) -> None:
    fake_mongo.reachable = False

    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert fake_mongo.pings == 0


async def test_request_id_is_generated_when_missing(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])


async def test_safe_request_id_is_propagated(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "trace-123.abc_DEF"})

    assert response.headers["x-request-id"] == "trace-123.abc_DEF"


async def test_unsafe_request_id_is_replaced(client: AsyncClient) -> None:
    too_long = "x" * 65

    response = await client.get("/health/live", headers={"X-Request-ID": too_long})

    assert response.headers["x-request-id"] != too_long
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])
