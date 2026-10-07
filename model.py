"""Single-commodity min-cost flow (transportation problem) for one scenario."""

from __future__ import annotations

from dataclasses import dataclass

import gurobipy as gp
from gurobipy import GRB

import config
from node import Node


@dataclass
class Solution:
    scenario: str
    status: str
    objective_hours: float | None          # sum(time_h * flow), DMT-hours/yr
    flows: dict[tuple[str, str], float]    # (source, sink) -> DMT/yr, nonzero only
    total_flow: float = 0.0

    @property
    def avg_hours(self) -> float | None:
        """Volume-weighted average drive time per DMT."""
        return self.objective_hours / self.total_flow if self.objective_hours is not None and self.total_flow else None


def solve_scenario(
    sources: list[Node],
    sinks: list[Node],
    drive_seconds: dict[tuple[str, str], float | None],
    scenario: str,
    *,
    verbose: bool = False,
) -> Solution:
    """min sum(time*x)  s.t.  sum_t x[s,t] <= supply[s],  sum_s x[s,t] == demand[t],  x >= 0."""
    supply = {s.name: s.value(scenario) for s in sources}
    demand = {t.name: t.value(scenario) for t in sinks}

    edges = [
        (s.name, t.name) for s in sources for t in sinks
        if drive_seconds.get((s.name, t.name)) is not None
        and (s.name, t.name) not in config.EXCLUDED_EDGES
    ]
    hours = {e: drive_seconds[e] / 3600.0 for e in edges}

    m = gp.Model(f"CausticSupplyChain_{scenario}")
    m.Params.OutputFlag = 1 if verbose else 0
    x = m.addVars(edges, lb=0.0, vtype=GRB.CONTINUOUS, name="x")

    m.setObjective(gp.quicksum(hours[e] * x[e] for e in edges), GRB.MINIMIZE)
    m.addConstrs((x.sum(s, "*") <= supply[s] for s in supply), name="supply")
    m.addConstrs((x.sum("*", t) == demand[t] for t in demand), name="demand")
    m.optimize()

    if m.Status != GRB.OPTIMAL:
        names = {GRB.INFEASIBLE: "INFEASIBLE", GRB.INF_OR_UNBD: "INFEASIBLE_OR_UNBOUNDED",
                 GRB.UNBOUNDED: "UNBOUNDED"}
        return Solution(scenario, names.get(m.Status, f"STATUS_{m.Status}"), None, {})

    flows = {e: x[e].X for e in edges if x[e].X > 1e-6}
    return Solution(scenario, "OPTIMAL", m.ObjVal, flows, sum(flows.values()))
