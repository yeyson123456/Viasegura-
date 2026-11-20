"""Azure Functions (Python v2 model, Flex Consumption): recompute segment risk.

* Queue trigger: an incident was confirmed/resolved (message from the API) -> recompute now.
* Timer trigger: every 30 minutes (rain changes; sweeps events whose message was lost).
"""

import logging
import os

import azure.functions as func
from pymongo import MongoClient

from risk_engine.engine import recompute_all

app = func.FunctionApp()
_client: MongoClient | None = None


def _db():
    global _client
    _client = _client or MongoClient(os.environ["MONGODB_URI"], tz_aware=True)
    return _client[os.environ.get("MONGODB_DB", "viasegura")]


@app.queue_trigger(arg_name="message", queue_name="risk-events", connection="AzureWebJobsStorage")
def recompute_on_event(message: func.QueueMessage) -> None:
    logging.info("risk event: %s", message.get_body().decode("utf-8")[:200])
    recompute_all(_db())


@app.timer_trigger(arg_name="timer", schedule="0 */30 * * * *", run_on_startup=False)
def recompute_periodically(timer: func.TimerRequest) -> None:
    recompute_all(_db())
