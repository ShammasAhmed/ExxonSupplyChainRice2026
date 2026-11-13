"""Caustic soda supply chain: multimodal min-cost flow for bear / base / bull scenarios.

    python main.py

Line-haul costs use quoted rates (config.LANE_RATES_FILE) where available, else the
placeholder rate formula in config.MODE_PARAMS on routed miles
(config.LANE_DISTANCES_FILE, from build_distances.py) or great-circle estimates.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import config
from loader import VOLUME_UNIT, load_current_flows, load_nodes, load_site_modes
from model import solve_scenario
from network import build_network
from node import Node, SiteMode
from routing import CostBasis
from visualize import plot_nodes

logger = logging.getLogger("main")


def apply_exclusions(nodes: list[Node], site_modes: list[SiteMode]) -> tuple[list[Node], list[SiteMode]]:
    """Drop nodes listed in config.EXCLUDED_NODES, and their Modes rows (error on unknown names)."""
    if not config.EXCLUDED_NODES:
        return nodes, site_modes
    unknown = config.EXCLUDED_NODES - {n.name for n in nodes}
    if unknown:
        raise ValueError(f"EXCLUDED_NODES names not found in {config.SITES_FILE.name}: {sorted(unknown)}")
    kept = [n for n in nodes if n.name not in config.EXCLUDED_NODES]
    for name in sorted(config.EXCLUDED_NODES):
        logger.warning("Excluding node: %s", name)
    return kept, [sm for sm in site_modes if sm.site not in config.EXCLUDED_NODES]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", default=config.SITES_FILE)
    ap.add_argument("--modes", default=config.MODES_FILE)
    ap.add_argument("--supplier-switch-cost", type=float, default=None,
                    help=f"$/yr per new (supplier, site) pair (default {config.SUPPLIER_SWITCH_USD_PER_YR:,.0f})")
    ap.add_argument("--mode-switch-cost", type=float, default=None,
                    help=f"$/yr per new (site, mode) (default {config.MODE_SWITCH_USD_PER_YR:,.0f})")
    ap.add_argument("--out", default=str(config.OUTPUT_DIR))
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    nodes, site_modes = apply_exclusions(load_nodes(args.sites), load_site_modes(args.modes))
    net = build_network(nodes, site_modes, current=load_current_flows(config.CURRENT_FLOWS_FILE))
    switch = dict(supplier_switch_cost=args.supplier_switch_cost, mode_switch_cost=args.mode_switch_cost)
    print(f"{len(net.sites)} sites, {len(net.modes)} site-modes "
          f"({len(net.candidates)} candidates to build), {len(net.arcs)} arcs")
    bases = [a.basis for a in net.lanes.values()]
    print("Line-haul basis: " + ", ".join(f"{bases.count(b)} {b.value}" for b in CostBasis) + " lanes")
    if bases.count(CostBasis.QUOTE) < len(bases):
        print("Unquoted lanes use PLACEHOLDER rates (config.MODE_PARAMS).")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for scenario in config.SCENARIOS:
        sol = solve_scenario(net, scenario, **switch)
        if sol.status != "OPTIMAL":
            print(f"\n[{scenario}] {sol.status}: demand cannot be met with the available supply/modes.")
            continue

        print(f"\n[{scenario}] OPTIMAL  delivered={sol.total_flow:,.0f} {VOLUME_UNIT}  "
              f"total=${sol.objective_usd:,.0f}/yr (${sol.avg_cost:.2f}/ton)  routes={len(sol.routes)}")
        if net.current:
            as_is = solve_scenario(net, scenario, as_is=True, **switch)
            if as_is.status == "OPTIMAL":
                print(f"   XOM's current network: ${as_is.objective_usd:,.0f}/yr, so the optimum saves "
                      f"${as_is.objective_usd - sol.objective_usd:,.0f}/yr (site by site: python gap.py)")
        print("   " + "  ".join(f"{k}=${v:,.0f}" for k, v in sol.cost_breakdown.items() if v))
        for f in sol.fixed:
            if f.usd:
                print(f"   {f.kind.upper()} at {f.site}: {f.detail} (${f.usd:,.0f}/yr)")
        for r in sorted(sol.routes, key=lambda r: -r.dst):
            print(f"   {r.dst:>10,.0f}  {'*' if r.current else ' '} {r.label}   (${r.landed:,.2f}/ton landed: "
                  f"${r.product:,.2f} product + ${r.line_haul + r.handling:,.2f} logistics)")
        if net.current:
            print("   (* = one of XOM's current lanes)")
        lanes = net.lanes

        title = f"Caustic soda flows: {scenario.capitalize()} scenario ({VOLUME_UNIT})"
        for ext in ("html", "png"):
            try:
                plot_nodes(nodes, flows=sol.flows, title=title,
                           lane_costs={k: lanes[k].cost for k in sol.flows}, landed=sol.landed,
                           cost_breakdown=sol.cost_breakdown, total_flow=sol.total_flow,
                           save_path=out / f"{config.NETWORK_MAP_NAME.format(scenario=scenario)}.{ext}")
            except RuntimeError as exc:   # kaleido/Chrome missing: keep the HTML map
                logger.warning("Could not write .%s (%s). Run `plotly_get_chrome` for PNG export.",
                               ext, str(exc).strip().splitlines()[0] if str(exc).strip() else "kaleido error")
    print(f"\nMaps written to {out}/")


if __name__ == "__main__":
    main()
