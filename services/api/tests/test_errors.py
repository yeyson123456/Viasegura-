"""Every error shares one JSON shape and never leaks internals."""

import re

from fastapi import FastAPI
from httpx import AsyncClient

from app.errors import ApiError


async def test_unknown_route_returns_json_not_found(client: AsyncClient) -> None:
    response = await client.get("/no-such-route")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["x-request-id"]


async def test_wrong_method_returns_json_405(client: AsyncClient) -> None:
    response = await client.post("/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


async def test_validation_error_lists_details(app: FastAPI, client: AsyncClient) -> None:
    @app.get("/test/echo")
    async def echo(n: int) -> dict[str, int]:
        return {"n": n}

    response = await client.get("/test/echo", params={"n": "not-a-number"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["query", "n"]


async def test_api_error_keeps_its_status_code_and_details(
    app: FastAPI, client: AsyncClient
) -> None:
    @app.get("/test/conflict")
    async def conflict() -> None:
        raise ApiError(409, "duplicate_report", "Report already received", {"report_id": "r1"})

    response = await client.get("/test/conflict")

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "duplicate_report",
        "message": "Report already received",
        "request_id": response.headers["x-request-id"],
        "details": {"report_id": "r1"},
    }


async def test_unexpected_error_returns_generic_500(app: FastAPI, client: AsyncClient) -> None:
    @app.get("/test/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    response = await client.get("/test/boom")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert re.fullmatch(r"[0-9a-f]{32}", error["request_id"])
    assert "hunter2" not in response.text
