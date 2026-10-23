"""Multimodal min-cost flow with optional mode build decisions, for one scenario.

    min   sum_a cost[a] * x[a]  +  sum_c build_cost[c] * z[c]
    s.t.  source hub:        out - in  <= supply
          sink hub:          in  - out == demand
          intermediate hub:  in  - out == 0
          mode node:         in  - out == 0
          throughput(i, m) <= cap(i, m) * z(i, m)        (z = 1 for existing modes)
          unloaded(i, m)   >= min_demand_share(i, m) * demand(i)
          x >= 0,  z binary

cap(i, m) is the Modes-table capacity, or total demand when uncapped (no
terminal can usefully carry more than everything).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import gurobipy as gp
from gurobipy import GRB

from network import HUB, ArcKind, Network
from node import Mode


@dataclass
class Solution:
    scenario: str
    status: str
    objective_usd: float | None                     # $/yr: line haul + handling + builds
    flows: dict[tuple[str, str, Mode], float]       # (source, sink, mode) -> tons/yr, line haul only
    built: list[tuple[str, Mode]] = field(default_factory=list)
    cost_breakdown: dict[str, float] = field(default_factory=dict)
    total_flow: float = 0.0                         # tons/yr delivered to sinks

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

    freight = gp.quicksum(a.cost * x[i] for i, a in enumerate(net.arcs))
    builds = gp.quicksum(net.modes[k].build_cost * z[k] for k in z)
    m.setObjective(freight + builds, GRB.MINIMIZE)

    for s, n in sites.items():
        hub = (s, HUB)
        if n.is_source:
            m.addConstr(outflow(hub) - inflow(hub) <= n.value(scenario), name=f"supply[{s}]")
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
    flows, breakdown = {}, {"line haul": 0.0, "handling": 0.0, "build": builds.getValue()}
    for i, v in used.items():
        a = net.arcs[i]
        if a.kind is ArcKind.TRANSPORT:
            flows[(a.tail[0], a.head[0], a.mode)] = v
            breakdown["line haul"] += a.cost * v
        else:
            breakdown["handling"] += a.cost * v
    built = [(s, Mode(mode)) for (s, mode) in z if z[s, mode].X > 0.5]
    return Solution(scenario, "OPTIMAL", m.ObjVal, flows, built, breakdown, sum(demand.values()))
