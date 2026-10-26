"""Mode-expanded network: each site becomes a hub plus one node per transport mode.

    (site, "hub")    holds the site's supply or demand
    (site, mode)     the site's terminal for that mode (truck rack, rail spur, dock)

Arcs:
    LOAD       (site, hub)  -> (site, mode)   product leaves the site by `mode`
    UNLOAD     (site, mode) -> (site, hub)    product arrives at the site by `mode`
    TRANSPORT  (a, mode)    -> (b, mode)      line haul, only if both sites have `mode`

Sources only load, sinks only unload, and intermediates (terminals) do both,
so product changes mode only at an intermediate site, paying unload + load.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Iterator

import config
from node import LaneKey, Mode, Node, SiteMode
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
                  rate_multiplier: Callable[[Node, Node, Mode], float] | None = None) -> Network:
    """Expand sites into hub + mode nodes and connect them.

    `rate_multiplier(origin, destination, mode)` scales each lane's line-haul
    rate, for sensitivity runs (default 1 everywhere).

    Raises ValueError if a Modes row names a site that is not in `nodes`.
    """
    sites = {n.name: n for n in nodes}
    modes: dict[NodeKey, SiteMode] = {}
    for sm in site_modes:
        if sm.site not in sites:
            raise ValueError(f"Modes table names unknown site {sm.site!r} "
                             f"(must match a Sources/Sinks name exactly).")
        if sm.min_demand_share and not sites[sm.site].is_sink:
            raise ValueError(f"{sm.site!r} {sm.mode.value}: min_demand_share only applies to sinks.")
        modes[(sm.site, sm.mode.value)] = sm

    for name in sites:
        if not any(site == name for site, _ in modes):
            logger.warning("Site %r has no transport modes, so it cannot ship or receive.", name)

    arcs: list[Arc] = []
    for (site, mode), sm in modes.items():
        handling = config.HANDLING_USD_PER_TON[mode]
        n = sites[site]
        if n.is_source or n.is_intermediate:
            arcs.append(Arc((site, HUB), (site, mode), ArcKind.LOAD, sm.mode, handling))
        if n.is_sink or n.is_intermediate:
            arcs.append(Arc((site, mode), (site, HUB), ArcKind.UNLOAD, sm.mode, handling))

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

    return Network(sites, modes, arcs)
