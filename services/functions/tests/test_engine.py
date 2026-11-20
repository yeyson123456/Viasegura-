"""Risk formula, including the equity rule (run: python -m pytest services/functions/tests)."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine.engine import incident_term, rain_term, score_segment  # noqa: E402

NOW = datetime(2026, 11, 20, tzinfo=UTC)


def incident(kind: str, days_ago: float = 0) -> dict:
    return {"type": kind, "lastSeen": NOW - timedelta(days=days_ago)}


def test_obstacles_weigh_more_than_potholes_and_old_incidents_fade() -> None:
    assert incident_term([incident("obstacle")], NOW, 10) > incident_term([incident("pothole")], NOW, 10)
    assert incident_term([incident("obstacle", 14)], NOW, 10) < incident_term([incident("obstacle")], NOW, 10)


def test_rain_saturates() -> None:
    assert rain_term(None) == 0
    assert rain_term(25) == 0.5
    assert rain_term(500) == 1.0


def test_equity_rule_prioritises_isolated_segment_with_same_hazards() -> None:
    hazards = [incident("obstacle")]
    busy_but_connected = {"lengthKm": 10, "isolationIndex": 0.0, "trafficLevel": "high"}
    quiet_but_isolated = {"lengthKm": 10, "isolationIndex": 1.0, "trafficLevel": "low"}

    connected_score, _ = score_segment(busy_but_connected, hazards, 10, None, NOW)
    isolated_score, breakdown = score_segment(quiet_but_isolated, hazards, 10, None, NOW)

    assert isolated_score == round(connected_score * 1.5, 2) or isolated_score == 100
    assert breakdown["equityMultiplier"] == 1.5


def test_traffic_level_never_changes_the_score() -> None:
    hazards = [incident("pothole")]
    low = score_segment({"lengthKm": 10, "isolationIndex": 0.4, "trafficLevel": "low"}, hazards, 0, None, NOW)
    high = score_segment({"lengthKm": 10, "isolationIndex": 0.4, "trafficLevel": "high"}, hazards, 0, None, NOW)
    assert low[0] == high[0]


def test_no_hazards_no_rain_scores_zero() -> None:
    score, breakdown = score_segment({"lengthKm": 10, "isolationIndex": 0.9}, [], 0, None, NOW)
    assert score == 0
    assert breakdown["confirmedIncidents"] == 0
