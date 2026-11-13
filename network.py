"""Mode-expanded network: each site becomes a hub plus one node per transport mode.

    (site, "hub")    holds the site's supply or demand
    (site, mode)     the site's terminal for that mode (truck rack, rail spur, dock)

Arcs:
    LOAD       (site, hub)  -> (site, mode)   product leaves the site by `mode`
    UNLOAD     (site, mode) -> (site, hub)    product arrives at the site by `mode`
    TRANSPORT  (a, mode)    -> (b, mode)      line haul, only if both sites have `mode`

Sources only load, sinks only unload, and intermediates (terminals) do both,
so product changes mode only at an intermediate site, paying unload + load
plus the site's terminal fee (charged on the unload arc).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Iterator

import config
from node import CurrentLane, LaneKey, Mode, Node, SiteMode
from routing import CostBasis, lane_cost, lane_rates

logger = logging.getLogger(__name__)

HUB = "hub"
NodeKey = tuple[str, str]   # (site name, HUB or Mode value)


class ArcKind(str, Enum):
    LOAD = "load"
    UNLOAD = "unload"
    TRANSPORT = "transport"


@dataclass(frozen=True, slots=True)
class Arc:
    tail: NodeKey
    head: NodeKey
    kind: ArcKind
    mode: Mode
    cost: float                     # $/ton
    miles: float = 0.0              # transport arcs only
    basis: CostBasis | None = None  # transport arcs only: quote / routed / estimated

    @property
    def label(self) -> str:
        return f"{self.tail[0]}[{self.tail[1]}] -> {self.head[0]}[{self.head[1]}]"


@dataclass
class Network:
    sites: dict[str, Node]
    modes: dict[NodeKey, SiteMode]      # (site, mode) -> availability row
    arcs: list[Arc]
    current: dict[LaneKey, CurrentLane] = field(default_factory=dict)   # XOM's current network
    _in: dict[NodeKey, list[int]] = field(init=False, repr=False)
    _out: dict[NodeKey, list[int]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._in = {k: [] for k in self.nodes}
        self._out = {k: [] for k in self.nodes}
        for i, a in enumerate(self.arcs):
            self._out[a.tail].append(i)
            self._in[a.head].append(i)

    @property
    def nodes(self) -> list[NodeKey]:
        return [(s, HUB) for s in self.sites] + list(self.modes)

    @property
    def candidates(self) -> list[SiteMode]:
        return [sm for sm in self.modes.values() if not sm.existing]

    @property
    def lanes(self) -> dict[LaneKey, Arc]:
        """Transport arcs by (origin site, destination site, mode)."""
        return {(a.tail[0], a.head[0], a.mode): a for a in self.arcs if a.kind is ArcKind.TRANSPORT}

    def arcs_into(self, key: NodeKey) -> list[int]:
        return self._in[key]

    def arcs_out_of(self, key: NodeKey) -> list[int]:
        return self._out[key]


def transport_lanes(sites: dict[str, Node], modes: Iterable[NodeKey]) -> Iterator[LaneKey]:
    """Every directed line haul the network can offer, as (origin, destination, mode).

    A lane needs the mode at both sites, an origin that is not a sink, and a
    destination that is not a source. config.EXCLUDED_EDGES are skipped.
    """
    modes = list(modes)
    for a, mode in modes:
        if sites[a].is_sink:
            continue
        for b, mode_b in modes:
            if mode_b != mode or a == b or sites[b].is_source or (a, b) in config.EXCLUDED_EDGES:
                continue
            yield a, b, Mode(mode)


def build_network(nodes: Iterable[Node], site_modes: Iterable[SiteMode], *,
                  rate_multiplier: Callable[[Node, Node, Mode], float] | None = None,
                  current: dict[LaneKey, CurrentLane] | None = None) -> Network:
    """Expand sites into hub + mode nodes and connect them.

    `rate_multiplier(origin, destination, mode)` scales each lane's line-haul
    rate, for sensitivity runs (default 1 everywhere). `current` is XOM's
    current network (loader.load_current_flows); without it the model uses
    one price per supplier and has no as-is case or switching costs.

    Raises ValueError if a Modes row or a current lane names a site that is
    not in `nodes`, or a current lane the network cannot carry.
    """
    sites = {n.name: n for n in nodes}
    modes: dict[NodeKey, SiteMode] = {}
    for sm in site_modes:
        if sm.site not in sites:
            raise ValueError(f"Modes table names unknown site {sm.site!r} "
                             f"(must match a name in sites.csv exactly).")
        if sm.min_demand_share and not sites[sm.site].is_sink:
            raise ValueError(f"{sm.site!r} {sm.mode.value}: min_demand_share only applies to sinks.")
        modes[(sm.site, sm.mode.value)] = sm

    for name in sites:
        if not any(site == name for site, _ in modes):
            logger.warning("Site %r has no transport modes, so it cannot ship or receive.", name)

    arcs: list[Arc] = []
    for (site, mode), sm in modes.items():
        handling = config.HANDLING_USD_PER_TON[mode] / config.SOLUTION_STRENGTH  # wet ton -> DST
        n = sites[site]
        if n.is_source or n.is_intermediate:
            arcs.append(Arc((site, HUB), (site, mode), ArcKind.LOAD, sm.mode, handling))
        if n.is_sink or n.is_intermediate:
            # Every ton through a terminal unloads exactly once, so its throughput fee goes here.
            arcs.append(Arc((site, mode), (site, HUB), ArcKind.UNLOAD, sm.mode, handling + n.terminal_fee))

    for a, b, mode in transport_lanes(sites, modes):
        multiplier = rate_multiplier(sites[a], sites[b], mode) if rate_multiplier else 1.0
        lane = lane_cost(sites[a], sites[b], mode, multiplier)
        if lane is not None:
            arcs.append(Arc((a, mode.value), (b, mode.value), ArcKind.TRANSPORT, mode,
                            lane.usd_per_ton, lane.miles, lane.basis))

    offered = {(a.tail[0], a.head[0], a.mode) for a in arcs if a.kind is ArcKind.TRANSPORT}
    for a, b, mode in sorted(set(lane_rates()) - offered):
        logger.warning("Quoted rate %r -> %r [%s] matches no lane in the network (check names "
                       "and that both sites have the mode in the Modes table).", a, b, mode.value)

    net = Network(sites, modes, arcs, dict(current or {}))
    _check_current(net)
    return net


def _check_current(net: Network) -> None:
    """Each current lane must be a direct lane the network offers on existing
    modes; each sink's current volume should equal its base demand."""
    if not net.current:
        return
    lanes = net.lanes
    for (s, t, _), lane in net.current.items():
        if s not in net.sites or not net.sites[s].is_source:
            raise ValueError(f"Current lane supplier {s!r} is not a source in sites.csv.")
        if t not in net.sites or not net.sites[t].is_sink:
            raise ValueError(f"Current lane sink {t!r} is not a sink in sites.csv.")
        if lane.via is not None and (lane.via not in net.sites or not net.sites[lane.via].is_intermediate):
            raise ValueError(f"Current lane {s!r} -> {t!r}: via {lane.via!r} is not an intermediate in sites.csv.")
        for a, b, mode in lane.path:
            if (a, b, mode) not in lanes:
                raise ValueError(f"Current lane leg {a!r} -> {b!r} [{mode.value}] is not in the network "
                                 f"(check modes.csv has {mode.value} at both sites).")
            for site in (a, b):
                if not net.modes[(site, mode.value)].existing:
                    raise ValueError(f"Current lane leg {a!r} -> {b!r} uses {mode.value} at {site!r}, "
                                     f"which modes.csv lists as a candidate, not existing.")
    for t, n in net.sites.items():
        if not n.is_sink:
            continue
        today = sum(l.dst_per_yr for l in net.current.values() if l.sink == t)
        if abs(today - n.base) > 1e-6 * max(n.base, 1.0):
            logger.warning("Sink %r: current lanes carry %s DST/yr but base demand is %s; "
                           "the as-is case will be infeasible.", t, f"{today:,.0f}", f"{n.base:,.0f}")
