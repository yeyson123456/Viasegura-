"""Settings parsing and the JSON log format."""

import json
import logging

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.logging_setup import JsonFormatter, request_id_var


def test_cors_origins_are_split_and_trimmed() -> None:
    settings = Settings(api_cors_origins=" http://a.test , http://b.test ,, ")

    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_log_level_is_normalized_and_validated() -> None:
    assert Settings(api_log_level="debug").api_log_level == "DEBUG"
    with pytest.raises(ValidationError):
        Settings(api_log_level="LOUD")


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONGODB_DB", "viasegura_other")
    monkeypatch.setenv("MONGODB_TIMEOUT_MS", "1500")

    settings = Settings()

    assert settings.mongodb_db == "viasegura_other"
    assert settings.mongodb_timeout_ms == 1500


def test_json_log_line_carries_extras_and_request_id() -> None:
    record = logging.LogRecord(
        "viasegura.test", logging.INFO, __file__, 1, "hello %s", ("world",), None
    )
    record.duration_ms = 12.5
    token = request_id_var.set("req-1")
    try:
        line = JsonFormatter().format(record)
    finally:
        request_id_var.reset(token)

    payload = json.loads(line)
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "viasegura.test"
    assert payload["request_id"] == "req-1"
    assert payload["duration_ms"] == 12.5
