"""Mode-dependent lane distance and freight cost between two sites.

`lane_cost(a, b, mode)` returns the line haul for one directed lane as a
LaneCost ($/ton, miles, and where the cost came from), or None when the mode
does not offer that lane (e.g. pipeline beyond its max length). Loading and
unloading are charged separately on the network's transfer arcs.

Cost basis, best first:
    quote      a quoted rate from config.LANE_RATES_FILE
    routed     the config.MODE_PARAMS rate formula on routed road / rail /
               waterway miles from config.LANE_DISTANCES_FILE (written by
               build_distances.py)
    estimated  the same formula on great-circle miles x per-mode circuity
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from functools import cache

import config
from loader import load_lane_distances, load_lane_rates
from node import LaneDistance, LaneKey, LaneRate, Mode, Node

EARTH_RADIUS_MILES = 3958.8
GREAT_CIRCLE = "great_circle"   # LaneDistance.source for lanes not in the routed table


class CostBasis(str, Enum):
    QUOTE = "quote"
    ROUTED = "routed"
    ESTIMATED = "estimated"


@dataclass(frozen=True, slots=True)
class LaneCost:
    usd_per_ton: float
    miles: float
    basis: CostBasis


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(h))


def great_circle_miles(a: Node, b: Node) -> float:
    return haversine_miles(a.lat, a.lon, b.lat, b.lon)


@cache
def lane_distances() -> dict[LaneKey, LaneDistance]:
    return load_lane_distances(config.LANE_DISTANCES_FILE)


@cache
def lane_rates() -> dict[LaneKey, LaneRate]:
    return load_lane_rates(config.LANE_RATES_FILE)


def lane_distance(a: Node, b: Node, mode: Mode) -> LaneDistance:
    """Route miles from a to b by this mode: the routed table, else great circle x circuity."""
    mode = Mode(mode)
    routed = lane_distances().get((a.name, b.name, mode))
    if routed is not None:
        return routed
    return LaneDistance(great_circle_miles(a, b) * config.MODE_PARAMS[mode.value]["circuity"],
                        source=GREAT_CIRCLE)


def quote_usd_per_ton(rate: LaneRate) -> float:
    """Convert a quote in $/metric ton (dry or wet basis) to $ per model ton (dry short ton)."""
    usd_per_dry_mt = rate.usd_per_mt / config.SOLUTION_STRENGTH if rate.weight_basis == "wet" else rate.usd_per_mt
    return usd_per_dry_mt * config.METRIC_TONS_PER_SHORT_TON


def lane_cost(a: Node, b: Node, mode: Mode, multiplier: float = 1.0) -> LaneCost | None:
    """Line-haul $/ton from a to b by this mode, or None if the lane is not offered.

    `multiplier` scales the rate (quoted or formula), for sensitivity runs.
    """
    mode = Mode(mode)
    dist = lane_distance(a, b, mode)
    quote = lane_rates().get((a.name, b.name, mode))
    if quote is not None:
        return LaneCost(quote_usd_per_ton(quote) * multiplier, dist.miles, CostBasis.QUOTE)

    p = config.MODE_PARAMS[mode.value]
    if p["max_miles"] is not None and dist.miles > p["max_miles"]:
        return None
    billed = max(dist.miles + (p["upstream_factor"] - 1) * dist.upstream_miles, p["min_miles"])
    usd = (p["fixed_usd_per_ton"] + p["usd_per_ton_mile"] * billed) * multiplier
    basis = CostBasis.ESTIMATED if dist.source == GREAT_CIRCLE else CostBasis.ROUTED
    return LaneCost(usd, dist.miles, basis)
