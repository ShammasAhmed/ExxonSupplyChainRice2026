"""Multimodal min-cost flow that tracks where each ton was loaded, for one scenario.

Flow is split into commodities k = (supplier s, mode m it leaves s by). That
way the model knows which supplier serves which XOM site, and how the product
left the supplier, even when it passes through any number of terminals. The
model grows with (commodities x arcs), not with the number of possible
routes. Routes are recovered after the solve by decomposing each commodity's
flow (Solution.routes).

    min   sum_{k,t} price[k,t] * deliv[k,t]                   product
        + sum_a cost[a] * X[a]                                 line haul, handling, terminal fees
        + sum_c build_cost[c] * z[c]                           candidate modes
        + S_sup * sum_(s,t) y[s,t] + S_mode * sum_(t,m) u[t,m] switching (new pairs / new modes only)

    X[a] = sum_k x[k,a]   (total flow on arc a)
    deliv[k,t] = flow of k unloaded into sink t's hub

    s.t.  sum_{k of s} x[k, load arc of k] <= supply cap[s]       (none if uncapped)
          sum_k deliv[k,t]                == demand[t]
          per commodity k, at every node except its source hub and sink hubs: in == out
          X into mode node (i,m)  <= cap(i,m) * z(i,m)            (z = 1 for existing modes)
          X unloaded at (t,m)     >= min_demand_share(t,m) * demand[t]
          sum_{k of s} deliv[k,t] <= demand[t] * y[s,t]           (s,t) not a current pair
          X unloaded at (t,m)     <= demand[t] * u[t,m]           t does not receive by m today
          X unloaded at terminal i <= throughput cap[i]           (only if a cap is given)
          x >= 0;  z, y, u binary

price[k,t] follows the rule in config ("Product price"). cap(i, m) is the
Modes-table capacity, or total demand when uncapped. With as_is=True the
flows are fixed to XOM's current lanes (Network.current), scaled to the
scenario, so the same costs price today's network.

What-if inputs (all optional, used by build_webapp_data.py): closed_sites and
closed_lanes take sites and lanes out of the network, fixed_builds forces a
candidate mode to be built (True) or not (False), and caps overrides a
source's supply cap or sets a terminal's throughput cap (None = uncapped).
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field

import gurobipy as gp
from gurobipy import GRB

import config
from network import HUB, ArcKind, Network, NodeKey
from node import LaneKey, Mode

logger = logging.getLogger(__name__)

EPS = 1e-6
Commodity = tuple[str, str]     # (supplier site, mode value it leaves by)


@dataclass(frozen=True)
class Route:
    """One way product gets from a supplier to an XOM site in a solution."""

    supplier: str
    sink: str
    legs: tuple[tuple[str, str, Mode], ...]   # line hauls in order: (from site, to site, mode)
    dst: float                                # DST/yr on this route
    product: float                            # $/DST, price paid to the supplier
    line_haul: float                          # $/DST
    handling: float                           # $/DST, loading, unloading and terminal fees
    current: bool = False                     # True if this is one of XOM's current lanes

    @property
    def landed(self) -> float:
        return self.product + self.line_haul + self.handling

    @property
    def load_mode(self) -> Mode:
        return self.legs[0][2]

    @property
    def arrival_mode(self) -> Mode:
        return self.legs[-1][2]

    @property
    def via(self) -> tuple[str, ...]:
        """Terminals the route passes through."""
        return tuple(leg[1] for leg in self.legs[:-1])

    @property
    def label(self) -> str:
        parts = [self.supplier]
        for _, b, mode in self.legs:
            parts.append(f"-{mode.value}-> {b}")
        return " ".join(parts)


@dataclass(frozen=True)
class FixedCost:
    """A yearly cost that does not scale with tons: a build or a switch."""

    site: str        # the site it is charged at (an XOM site for switches)
    kind: str        # "build", "supplier switch" or "mode switch"
    detail: str
    usd: float


@dataclass
class Solution:
    scenario: str
    status: str
    objective_usd: float | None                     # $/yr: product + logistics + builds + switches
    flows: dict[tuple[str, str, Mode], float]       # (origin, destination, mode) -> tons/yr, line haul only
    built: list[tuple[str, Mode]] = field(default_factory=list)
    cost_breakdown: dict[str, float] = field(default_factory=dict)
    total_flow: float = 0.0                         # tons/yr delivered to sinks
    landed: dict[str, tuple[float, float]] = field(default_factory=dict)  # sink -> ($/ton product, $/ton logistics)
    routes: list[Route] = field(default_factory=list)
    fixed: list[FixedCost] = field(default_factory=list)
    as_is: bool = False

    @property
    def avg_cost(self) -> float | None:
        """Total $ per delivered ton."""
        return self.objective_usd / self.total_flow if self.objective_usd is not None and self.total_flow else None


def commodities(net: Network) -> dict[Commodity, int]:
    """Every (supplier, mode) the network can load at, with the index of its load arc."""
    return {(a.tail[0], a.head[1]): i for i, a in enumerate(net.arcs)
            if a.kind is ArcKind.LOAD and net.sites[a.tail[0]].is_source}


def reachable_arcs(net: Network, load_arc: int) -> list[int]:
    """Arcs a commodity can use: its load arc plus everything downstream of it."""
    seen, out, queue = set(), [load_arc], deque([net.arcs[load_arc].head])
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        for i in net.arcs_out_of(node):
            out.append(i)
            queue.append(net.arcs[i].head)
    return out


def price_table(net: Network, *, lane_prices: bool = True) -> dict[tuple[Commodity, str], float]:
    """$/DST paid for commodity k delivered to sink t (rule in config, "Product price").

    lane_prices=False uses one price per supplier (SITES_FILE) everywhere.
    """
    by_mode: dict[Commodity, list[tuple[float, float]]] = defaultdict(list)
    for (s, _, mode), lane in net.current.items():
        by_mode[(s, mode.value)].append((lane.dst_per_yr, lane.price))
    out = {}
    sinks = [t for t, n in net.sites.items() if n.is_sink]
    for k in commodities(net):
        s, mode = k
        for t in sinks:
            lane = net.current.get((s, t, Mode(mode))) if lane_prices else None
            if lane is not None:
                out[(k, t)] = lane.price
            elif lane_prices and by_mode.get(k):
                vols = by_mode[k]
                weight = sum(v for v, _ in vols)
                out[(k, t)] = (sum(v * p for v, p in vols) / weight if weight > 0
                               else sum(p for _, p in vols) / len(vols))
            else:
                out[(k, t)] = net.sites[s].price
    return out


def solve_scenario(net: Network, scenario: str, *, as_is: bool = False, lane_prices: bool = True,
                   supplier_switch_cost: float | None = None, mode_switch_cost: float | None = None,
                   closed_sites: frozenset[str] | set[str] = frozenset(),
                   closed_lanes: frozenset[LaneKey] | set[LaneKey] = frozenset(),
                   fixed_builds: dict[NodeKey, bool] | None = None,
                   caps: dict[str, float | None] | None = None,
                   verbose: bool = False) -> Solution:
    """Solve one scenario. Switch costs default to config (0 = off).

    as_is=True fixes the flows to XOM's current lanes (net.current) scaled by
    the scenario multiplier; it needs net.current.
    """
    if as_is and not net.current:
        raise ValueError("as_is=True needs the network built with current=load_current_flows(...).")
    sup_cost = config.SUPPLIER_SWITCH_USD_PER_YR if supplier_switch_cost is None else supplier_switch_cost
    mode_cost = config.MODE_SWITCH_USD_PER_YR if mode_switch_cost is None else mode_switch_cost
    if not net.current:
        sup_cost = mode_cost = 0.0

    sites = net.sites
    demand = {s: n.value(scenario) for s, n in sites.items() if n.is_sink}
    big_u = sum(demand.values())
    comms = commodities(net)
    reach = {k: reachable_arcs(net, i) for k, i in comms.items()}
    prices = price_table(net, lane_prices=lane_prices)

    m = gp.Model(f"CausticSupplyChain_{scenario}")
    m.Params.OutputFlag = 1 if verbose else 0
    x = m.addVars([(k, i) for k in comms for i in reach[k]], lb=0.0, name="x")
    z = m.addVars([(sm.site, sm.mode.value) for sm in net.candidates], vtype=GRB.BINARY, name="z")
    closed = {i for i, a in enumerate(net.arcs)
              if a.tail[0] in closed_sites or a.head[0] in closed_sites
              or (a.kind is ArcKind.TRANSPORT and (a.tail[0], a.head[0], a.mode) in closed_lanes)}
    for (k, i), var in x.items():
        if i in closed or k[0] in closed_sites:
            var.UB = 0.0
    for key, build in (fixed_builds or {}).items():
        if key in z:
            z[key].LB = z[key].UB = 1.0 if build else 0.0

    on_arc: dict[int, list] = defaultdict(list)        # arc -> its x vars across commodities
    for (k, i), var in x.items():
        on_arc[i].append(var)

    def total(i: int):
        return gp.quicksum(on_arc[i])

    def total_into(key: NodeKey):
        return gp.quicksum(total(i) for i in net.arcs_into(key))

    def unloaded(key: NodeKey):
        return gp.quicksum(total(i) for i in net.arcs_out_of(key) if net.arcs[i].kind is ArcKind.UNLOAD)

    # deliv[k, t]: commodity k unloaded into sink t's hub
    deliv = {}
    for k in comms:
        arcs_k = set(reach[k])
        for t in demand:
            terms = [x[k, i] for i in net.arcs_into((t, HUB)) if i in arcs_k]
            if terms:
                deliv[k, t] = gp.quicksum(terms)

    # --- objective ---------------------------------------------------------
    product = gp.quicksum(prices[k, t] * e for (k, t), e in deliv.items())
    logistics = gp.quicksum(a.cost * total(i) for i, a in enumerate(net.arcs) if on_arc[i])
    builds = gp.quicksum(net.modes[k].build_cost * z[k] for k in z)

    current_pairs = {(s, t) for s, t, _ in net.current}
    current_modes = {(lane.sink, lane.last_mode.value) for lane in net.current.values()}
    y, u = {}, {}
    if sup_cost > 0:
        for s in {k[0] for k in comms}:
            for t in demand:
                if (s, t) not in current_pairs and any((k, t) in deliv for k in comms if k[0] == s):
                    y[s, t] = m.addVar(vtype=GRB.BINARY, name=f"y[{s},{t}]")
    if mode_cost > 0:
        for (site, mode) in net.modes:
            if site in demand and (site, mode) not in current_modes:
                u[site, mode] = m.addVar(vtype=GRB.BINARY, name=f"u[{site},{mode}]")
    switches = sup_cost * gp.quicksum(y.values()) + mode_cost * gp.quicksum(u.values())
    m.setObjective(product + logistics + builds + switches, GRB.MINIMIZE)

    # --- constraints -------------------------------------------------------
    caps = caps or {}
    for s, n in sites.items():
        cap = caps.get(s, n.supply_cap)
        if cap is None:
            continue
        if n.is_source:   # capacity: the same in every scenario
            m.addConstr(gp.quicksum(x[k, i] for k, i in comms.items() if k[0] == s) <= cap,
                        name=f"supply[{s}]")
        elif n.is_intermediate:   # terminal throughput: everything unloaded there
            m.addConstr(gp.quicksum(total(i) for i in net.arcs_into((s, HUB))) <= cap,
                        name=f"throughput[{s}]")
    for t, d in demand.items():
        m.addConstr(gp.quicksum(e for (k, tt), e in deliv.items() if tt == t) == d, name=f"demand[{t}]")

    for k, arcs_k in reach.items():
        nodes = {net.arcs[i].head for i in arcs_k}
        arcs_k = set(arcs_k)
        for node in nodes:
            if node[1] == HUB and sites[node[0]].is_sink:
                continue
            inflow = gp.quicksum(x[k, i] for i in net.arcs_into(node) if i in arcs_k)
            outflow = gp.quicksum(x[k, i] for i in net.arcs_out_of(node) if i in arcs_k)
            m.addConstr(inflow == outflow, name=f"balance[{k},{node}]")

    for key, sm in net.modes.items():
        cap = sm.capacity if sm.capacity is not None else big_u
        if not sm.existing:
            m.addConstr(total_into(key) <= cap * z[key], name=f"build[{key[0]},{key[1]}]")
        elif sm.capacity is not None:
            m.addConstr(total_into(key) <= cap, name=f"cap[{key[0]},{key[1]}]")
        if sm.min_demand_share:
            m.addConstr(unloaded(key) >= sm.min_demand_share * demand[sm.site],
                        name=f"share[{key[0]},{key[1]}]")

    for (s, t), var in y.items():
        m.addConstr(gp.quicksum(e for (k, tt), e in deliv.items() if tt == t and k[0] == s)
                    <= demand[t] * var, name=f"supplier_switch[{s},{t}]")
    for (t, mode), var in u.items():
        m.addConstr(unloaded((t, mode)) <= demand[t] * var, name=f"mode_switch[{t},{mode}]")

    if as_is:
        _fix_to_current(net, scenario, x, comms)

    m.optimize()

    if m.Status != GRB.OPTIMAL:
        names = {GRB.INFEASIBLE: "INFEASIBLE", GRB.INF_OR_UNBD: "INFEASIBLE_OR_UNBOUNDED",
                 GRB.UNBOUNDED: "UNBOUNDED"}
        return Solution(scenario, names.get(m.Status, f"STATUS_{m.Status}"), None, {}, as_is=as_is)

    flow = {(k, i): v.X for (k, i), v in x.items() if v.X > EPS}
    arc_total: dict[int, float] = defaultdict(float)
    for (k, i), v in flow.items():
        arc_total[i] += v

    flows, breakdown = {}, {"product": product.getValue(), "line haul": 0.0, "handling + terminal": 0.0}
    for i, v in arc_total.items():
        a = net.arcs[i]
        if a.kind is ArcKind.TRANSPORT:
            flows[(a.tail[0], a.head[0], a.mode)] = v
            breakdown["line haul"] += a.cost * v
        else:
            breakdown["handling + terminal"] += a.cost * v

    built = [(s, Mode(mode)) for (s, mode) in z if z[s, mode].X > 0.5]
    # A forced build may carry no flow; it is still paid for and reported.
    fixed = [FixedCost(s, "build", f"build {mode.value}", net.modes[(s, mode.value)].build_cost)
             for s, mode in built]
    routes = _routes(net, flow, comms, prices)
    new_pairs = sorted({(r.supplier, r.sink) for r in routes} - current_pairs) if net.current else []
    new_modes = sorted({(r.sink, r.arrival_mode.value) for r in routes} - current_modes) if net.current else []
    fixed += [FixedCost(t, "supplier switch", f"new supplier {s}", sup_cost) for s, t in new_pairs]
    fixed += [FixedCost(t, "mode switch", f"starts receiving by {mode}", mode_cost) for t, mode in new_modes]
    breakdown["build"] = builds.getValue()
    breakdown["supplier switch"] = sup_cost * len(new_pairs)
    breakdown["mode switch"] = mode_cost * len(new_modes)
    if abs(sum(breakdown.values()) - m.ObjVal) > 1e-4 * max(abs(m.ObjVal), 1.0):
        logger.warning("Cost breakdown ($%s) does not add up to the objective ($%s).",
                       f"{sum(breakdown.values()):,.0f}", f"{m.ObjVal:,.0f}")

    return Solution(scenario, "OPTIMAL", m.ObjVal, flows, built, breakdown, sum(demand.values()),
                    _landed(routes), routes, fixed, as_is)


def _fix_to_current(net: Network, scenario: str, x, comms: dict[Commodity, int]) -> None:
    """Allow only XOM's current lanes, each at its volume x the scenario multiplier."""
    k_scen = config.SCENARIO_MULTIPLIERS[scenario]
    lanes = {(a.tail[0], a.head[0], a.mode): i for i, a in enumerate(net.arcs) if a.kind is ArcKind.TRANSPORT}

    def arc(tail: NodeKey, head: NodeKey) -> int:
        return next(i for i in net.arcs_out_of(tail) if net.arcs[i].head == head)

    keep: dict[tuple[Commodity, int], float | None] = {}
    for (s, t, mode), lane in net.current.items():
        k = (s, mode.value)
        keep[(k, comms[k])] = None
        for j, (a, b, leg_mode) in enumerate(lane.path):
            keep[(k, lanes[(a, b, leg_mode)])] = lane.dst_per_yr * k_scen
            keep[(k, arc((b, leg_mode.value), (b, HUB)))] = None           # unload at b
            if j + 1 < len(lane.path):                                     # reload at the terminal
                keep[(k, arc((b, HUB), (b, lane.path[j + 1][2].value)))] = None
    for key, var in x.items():
        if key not in keep:
            var.UB = 0.0
        elif keep[key] is not None:
            var.LB = var.UB = keep[key]


def _routes(net: Network, flow: dict[tuple[Commodity, int], float], comms: dict[Commodity, int],
            prices: dict[tuple[Commodity, str], float]) -> list[Route]:
    """Decompose each commodity's flow into supplier -> sink routes.

    Repeatedly follows positive flow from the commodity's load arc to a sink
    hub and peels off the smallest flow on that walk. Costs are positive on
    every line haul, so an optimal flow has no cycles.
    """
    residual: dict[Commodity, dict[int, float]] = defaultdict(dict)
    for (k, i), v in flow.items():
        residual[k][i] = v
    merged: dict[tuple, float] = defaultdict(float)
    for k, load in comms.items():
        res = residual.get(k)
        while res and res.get(load, 0.0) > EPS:
            walk, node, seen = [load], net.arcs[load].head, set()
            while not (node[1] == HUB and net.sites[node[0]].is_sink):
                if node in seen:
                    raise RuntimeError(f"Flow of {k} has a cycle at {node}; cannot decompose into routes.")
                seen.add(node)
                nxt = max((i for i in net.arcs_out_of(node) if res.get(i, 0.0) > EPS),
                          key=lambda i: res[i], default=None)
                if nxt is None:
                    raise RuntimeError(f"Flow of {k} stops at {node}; cannot decompose into routes.")
                walk.append(nxt)
                node = net.arcs[nxt].head
            amount = min(res[i] for i in walk)
            for i in walk:
                res[i] -= amount
            merged[(k, node[0], tuple(walk))] += amount

    routes = []
    for (k, sink, walk), dst in merged.items():
        arcs = [net.arcs[i] for i in walk]
        legs = tuple((a.tail[0], a.head[0], a.mode) for a in arcs if a.kind is ArcKind.TRANSPORT)
        routes.append(Route(
            supplier=k[0], sink=sink, legs=legs, dst=dst, product=prices[k, sink],
            line_haul=sum(a.cost for a in arcs if a.kind is ArcKind.TRANSPORT),
            handling=sum(a.cost for a in arcs if a.kind is not ArcKind.TRANSPORT),
            current=_is_current(net, k[0], sink, legs),
        ))
    return sorted(routes, key=lambda r: (r.sink, -r.dst))


def _is_current(net: Network, supplier: str, sink: str, legs: tuple) -> bool:
    lane = net.current.get((supplier, sink, legs[0][2])) if legs else None
    return lane is not None and lane.path == legs


def _landed(routes: list[Route]) -> dict[str, tuple[float, float]]:
    """Average $/DST of product and of logistics (line haul, handling, terminal
    fees) in what each sink receives. Builds and switches are not allocated."""
    acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in routes:
        a = acc[r.sink]
        a[0] += r.dst
        a[1] += r.dst * r.product
        a[2] += r.dst * (r.line_haul + r.handling)
    return {t: (p / d, l / d) for t, (d, p, l) in acc.items() if d > 0}
