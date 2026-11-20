"""Local stand-in for the Azure Function (used by docker compose).

Recomputes risk as soon as an outbox event appears (incident confirmed/resolved) and every
30 minutes anyway (rain changes).

Usage:  python -m risk_engine.worker [--once]
"""

from __future__ import annotations

import argparse
import logging
import os
import time

from pymongo import MongoClient

from risk_engine.engine import recompute_all

POLL_SECONDS = 10
FULL_EVERY_SECONDS = 30 * 60


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"), tz_aware=True)
    db = client[os.environ.get("MONGODB_DB", "viasegura")]
    if args.once:
        print(recompute_all(db))
        return
    last_full = 0.0
    while True:
        try:
            pending = db["events"].count_documents({"processedAt": None})
            if pending or time.monotonic() - last_full > FULL_EVERY_SECONDS:
                recompute_all(db)
                last_full = time.monotonic()
        except Exception:  # noqa: BLE001 - keep the worker alive through outages
            logging.exception("risk_worker_error")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
