"""Driving-time estimates between nodes.

`get_drive_times` returns {(source_name, sink_name): seconds or None}. None means
no route exists for that pair, and the model skips the edge.

Times are approximations: great-circle distance x 1.3 detour factor at an
average 55 mph. To use a real routing API later, replace `get_drive_times`
(keep the same return shape) and nothing else needs to change.
"""

from __future__ import annotations

import math

from node import Node

DETOUR_FACTOR = 1.3     # road distance / straight-line distance
AVG_SPEED_MPH = 55.0
EARTH_RADIUS_MILES = 3958.8


def get_drive_times(sources: list[Node], sinks: list[Node]) -> dict[tuple[str, str], float | None]:
    """Estimated drive time in seconds for every (source, sink) pair."""
    return {(s.name, t.name): _estimate_seconds(s, t) for s in sources for t in sinks}


def _estimate_seconds(a: Node, b: Node) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    miles = 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h)) * DETOUR_FACTOR
    return miles / AVG_SPEED_MPH * 3600
