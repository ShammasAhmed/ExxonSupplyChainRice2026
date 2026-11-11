"""Multimodal min-cost flow with optional mode build decisions, for one scenario.

    min   sum_s price[s] * shipped[s]  +  sum_a cost[a] * x[a]  +  sum_c build_cost[c] * z[c]
    s.t.  source hub:        out - in  <= supply cap      (none if uncapped)
          sink hub:          in  - out == demand
          intermediate hub:  in  - out == 0
          mode node:         in  - out == 0
          throughput(i, m) <= cap(i, m) * z(i, m)        (z = 1 for existing modes)
          unloaded(i, m)   >= min_demand_share(i, m) * demand(i)
          x >= 0,  z binary

price[s] is the source's product price ex freight ($/DST) and shipped[s] its
net outflow, so the objective is total landed cost.
cap(i, m) is the Modes-table capacity, or total demand when uncapped (no
terminal can usefully carry more than everything).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from graphlib import CycleError, TopologicalSorter

import gurobipy as gp
from gurobipy import GRB

from network import HUB, ArcKind, Network
from node import Mode

logger = logging.getLogger(__name__)


@dataclass
class Solution:
    scenario: str
    status: str
    objective_usd: float | None                     # $/yr: product + line haul + handling + builds
    flows: dict[tuple[str, str, Mode], float]       # (source, sink, mode) -> tons/yr, line haul only
    built: list[tuple[str, Mode]] = field(default_factory=list)
    cost_breakdown: dict[str, float] = field(default_factory=dict)
    total_flow: float = 0.0                         # tons/yr delivered to sinks
    landed: dict[str, tuple[float, float]] = field(default_factory=dict)  # sink -> ($/ton product, $/ton logistics)

    @property
    def avg_cost(self) -> float | None:
        """Total $ per delivered ton."""
        return self.objective_usd / self.total_flow if self.objective_usd is not None and self.total_flow else None


def solve_scenario(net: Network, scenario: str, *, verbose: bool = False) -> Solution:
    sites = net.sites
    demand = {s: n.value(scenario) for s, n in sites.items() if n.is_sink}
    big_u = sum(demand.values())

    m = gp.Model(f"CausticSupplyChain_{scenario}")
    m.Params.OutputFlag = 1 if verbose else 0
    x = m.addVars(len(net.arcs), lb=0.0, vtype=GRB.CONTINUOUS, name="x")
    z = m.addVars([(sm.site, sm.mode.value) for sm in net.candidates], vtype=GRB.BINARY, name="z")

    def inflow(key):
        return gp.quicksum(x[i] for i in net.arcs_into(key))

    def outflow(key):
        return gp.quicksum(x[i] for i in net.arcs_out_of(key))

    product = gp.quicksum(n.price * outflow((s, HUB)) for s, n in sites.items() if n.is_source)
    freight = gp.quicksum(a.cost * x[i] for i, a in enumerate(net.arcs))
    builds = gp.quicksum(net.modes[k].build_cost * z[k] for k in z)
    m.setObjective(product + freight + builds, GRB.MINIMIZE)

    for s, n in sites.items():
        hub = (s, HUB)
        if n.is_source:
            if n.supply_cap is not None:   # capacity: the same in every scenario
                m.addConstr(outflow(hub) - inflow(hub) <= n.supply_cap, name=f"supply[{s}]")
        elif n.is_sink:
            m.addConstr(inflow(hub) - outflow(hub) == demand[s], name=f"demand[{s}]")
        else:
            m.addConstr(inflow(hub) == outflow(hub), name=f"transship[{s}]")

    for key, sm in net.modes.items():
        m.addConstr(inflow(key) == outflow(key), name=f"balance[{key[0]},{key[1]}]")
        cap = sm.capacity if sm.capacity is not None else big_u
        if not sm.existing:
            m.addConstr(inflow(key) <= cap * z[key], name=f"build[{key[0]},{key[1]}]")
        elif sm.capacity is not None:
            m.addConstr(inflow(key) <= cap, name=f"cap[{key[0]},{key[1]}]")
        if sm.min_demand_share:
            unloaded = gp.quicksum(x[i] for i in net.arcs_out_of(key)
                                   if net.arcs[i].kind is ArcKind.UNLOAD)
            m.addConstr(unloaded >= sm.min_demand_share * demand[sm.site],
                        name=f"share[{key[0]},{key[1]}]")

    m.optimize()

    if m.Status != GRB.OPTIMAL:
        names = {GRB.INFEASIBLE: "INFEASIBLE", GRB.INF_OR_UNBD: "INFEASIBLE_OR_UNBOUNDED",
                 GRB.UNBOUNDED: "UNBOUNDED"}
        return Solution(scenario, names.get(m.Status, f"STATUS_{m.Status}"), None, {})

    used = {i: x[i].X for i in x if x[i].X > 1e-6}
    flows, breakdown = {}, {"product": product.getValue(), "line haul": 0.0, "handling + terminal": 0.0,
                            "build": builds.getValue()}
    for i, v in used.items():
        a = net.arcs[i]
        if a.kind is ArcKind.TRANSPORT:
            flows[(a.tail[0], a.head[0], a.mode)] = v
            breakdown["line haul"] += a.cost * v
        else:
            breakdown["handling + terminal"] += a.cost * v
    built = [(s, Mode(mode)) for (s, mode) in z if z[s, mode].X > 0.5]
    return Solution(scenario, "OPTIMAL", m.ObjVal, flows, built, breakdown, sum(demand.values()),
                    _landed_costs(net, used))


def _landed_costs(net: Network, used: dict[int, float]) -> dict[str, tuple[float, float]]:
    """Average $/ton of product and of logistics (line haul, handling, terminal
    fees) in what each sink receives, following the solved flows.

    Each node's average is the flow-weighted average over its inbound arcs of
    (upstream average + arc cost); a source hub starts at its price. Build
    costs are not allocated to sinks. Returns {} if the flow has a cycle
    (it cannot at an optimum, since every cycle has positive cost).
    """
    into: dict = defaultdict(list)
    preds: dict = defaultdict(set)
    for i, v in used.items():
        a = net.arcs[i]
        into[a.head].append((a, v))
        preds[a.head].add(a.tail)
        preds.setdefault(a.tail, set())   # sources have no predecessors but must be ordered
    try:
        order = list(TopologicalSorter(preds).static_order())
    except CycleError:
        logger.warning("Flow has a cycle; landed costs per sink are not reported.")
        return {}
    avg: dict = {}
    for key in order:
        if not into[key]:   # a source hub (sources only load)
            avg[key] = (net.sites[key[0]].price, 0.0)
            continue
        total = sum(v for _, v in into[key])
        avg[key] = (sum(v * avg[a.tail][0] for a, v in into[key]) / total,
                    sum(v * (avg[a.tail][1] + a.cost) for a, v in into[key]) / total)
    return {s: avg[(s, HUB)] for s, n in net.sites.items() if n.is_sink and (s, HUB) in avg}
