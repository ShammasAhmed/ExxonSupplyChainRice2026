"""Mode-dependent lane distance and freight cost between two sites.

`lane_cost(a, b, mode)` returns $/ton for the line haul, or None when the
mode does not offer that lane (e.g. pipeline beyond its max length). Loading
and unloading are charged separately on the network's transfer arcs.

Distances are approximations: great-circle distance x a per-mode circuity
factor (config.MODE_PARAMS). To use real routed mileage later (e.g. a road
routing API, or rail/waterway networks), replace `lane_miles` and keep its
signature; nothing else needs to change.
"""

from __future__ import annotations

import math

import config
from node import Mode, Node

EARTH_RADIUS_MILES = 3958.8


def great_circle_miles(a: Node, b: Node) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def lane_miles(a: Node, b: Node, mode: Mode) -> float:
    """Estimated route miles from a to b by this mode."""
    return great_circle_miles(a, b) * config.MODE_PARAMS[Mode(mode).value]["circuity"]


def lane_cost(a: Node, b: Node, mode: Mode) -> float | None:
    """Line-haul $/ton from a to b by this mode, or None if the lane is not offered."""
    p = config.MODE_PARAMS[Mode(mode).value]
    miles = lane_miles(a, b, mode)
    if p["max_miles"] is not None and miles > p["max_miles"]:
        return None
    return max(miles, p["min_miles"]) * p["usd_per_ton_mile"]
