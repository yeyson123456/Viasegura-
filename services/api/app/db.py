"""MongoDB access through the PyMongo Async API (Motor's official successor, docs/decisions.md)."""

import logging

from fastapi import Request
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

logger = logging.getLogger("viasegura.db")


class Mongo:
    """Owns the MongoDB client for the lifetime of the application."""

    def __init__(self, uri: str, db_name: str, timeout_ms: int) -> None:
        # The async client connects lazily, so constructing it never blocks start-up.
        self.client: AsyncMongoClient = AsyncMongoClient(
            uri,
            appname="viasegura-api",
            tz_aware=True,
            serverSelectionTimeoutMS=timeout_ms,
            connectTimeoutMS=timeout_ms,
        )
        self.db = self.client[db_name]

    async def ping(self) -> bool:
        try:
            await self.client.admin.command("ping")
        except PyMongoError as exc:
            logger.warning("mongodb_unreachable", extra={"error": str(exc)[:300]})
            return False
        return True

    async def close(self) -> None:
        await self.client.close()


def get_mongo(request: Request) -> Mongo:
    """FastAPI dependency; tests override it with a fake."""
    return request.app.state.mongo
