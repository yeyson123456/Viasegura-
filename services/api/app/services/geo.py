"""Small geodesy helpers."""

import itertools
import math

# Radius MongoDB uses to convert distances to radians for $centerSphere queries.
EARTH_RADIUS_M = 6_378_100.0


def meters_to_radians(meters: float) -> float:
    return meters / EARTH_RADIUS_M


def haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """Great-circle distance in metres between two lng/lat points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi, d_lambda = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def line_length_km(coordinates: list[list[float]] | list[tuple[float, float]]) -> float:
    return (
        sum(haversine_m(a[0], a[1], b[0], b[1]) for a, b in itertools.pairwise(coordinates)) / 1000
    )
