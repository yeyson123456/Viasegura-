"""Domain events for the risk function (transactional-outbox style).

Every event is first written to MongoDB (`events`, the source of truth). When a storage
connection string is configured it is also pushed to an Azure Storage Queue, which triggers the
risk Azure Function right away; the function's timer trigger later sweeps any event whose queue
message was lost, so delivery is at-least-once.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("viasegura.events")


class EventPublisher:
    def __init__(self, db: Any, connection_string: str = "", queue_name: str = "") -> None:
        self.collection = db["events"]
        self.queue = None
        if connection_string and queue_name:
            from azure.storage.queue import QueueClient, TextBase64EncodePolicy

            # Azure Functions' queue trigger expects base64-encoded messages by default.
            self.queue = QueueClient.from_connection_string(
                connection_string, queue_name, message_encode_policy=TextBase64EncodePolicy()
            )
            self._queue_ready = False

    def _send(self, message: str) -> None:
        from azure.core.exceptions import ResourceExistsError

        assert self.queue is not None  # noqa: S101 - guarded by the caller
        if not self._queue_ready:
            with contextlib.suppress(ResourceExistsError):
                self.queue.create_queue()
            self._queue_ready = True
        self.queue.send_message(message)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> str:
        document = {"type": event_type, **payload, "ts": datetime.now(UTC), "processedAt": None}
        result = await self.collection.insert_one(document)
        event_id = str(result.inserted_id)
        if self.queue is not None:
            message = json.dumps({"eventId": event_id, "type": event_type, **payload}, default=str)
            try:
                await asyncio.to_thread(self._send, message)
            except Exception as exc:
                logger.warning("queue_send_failed", extra={"event_id": event_id, "error": str(exc)})
        logger.info("event_published", extra={"event_id": event_id, "event_type": event_type})
        return event_id
