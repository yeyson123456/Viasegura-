"""CORS is driven by API_CORS_ORIGINS."""

from httpx import AsyncClient


async def test_preflight_allows_configured_origin(client: AsyncClient) -> None:
    response = await client.options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_preflight_rejects_unknown_origin(client: AsyncClient) -> None:
    response = await client.options(
        "/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


async def test_simple_request_exposes_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()
