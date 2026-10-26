"""Caustic soda supply chain: multimodal min-cost flow for bear / base / bull scenarios.

    python main.py

Line-haul costs use quoted rates (lane_rates.csv) where available, else the
placeholder rate formula in config.MODE_PARAMS on routed miles
(lane_distances.csv, from build_distances.py) or great-circle estimates.
"""

from __future__ import annotations

import argparse
import logging

import config
from loader import VOLUME_UNIT, load_nodes, load_site_modes
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
        raise ValueError(f"EXCLUDED_NODES names not found in workbook: {sorted(unknown)}")
    kept = [n for n in nodes if n.name not in config.EXCLUDED_NODES]
    for name in sorted(config.EXCLUDED_NODES):
        logger.warning("Excluding node: %s", name)
    return kept, [sm for sm in site_modes if sm.site not in config.EXCLUDED_NODES]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", default=config.WORKBOOK)
    ap.add_argument("--modes", default=config.MODES_FILE)
    ap.add_argument("--out", default=str(config.OUTPUT_DIR))
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    nodes, site_modes = apply_exclusions(load_nodes(args.workbook), load_site_modes(args.modes))
    net = build_network(nodes, site_modes)
    print(f"{len(net.sites)} sites, {len(net.modes)} site-modes "
          f"({len(net.candidates)} candidates to build), {len(net.arcs)} arcs")
    bases = [a.basis for a in net.lanes.values()]
    print("Line-haul basis: " + ", ".join(f"{bases.count(b)} {b.value}" for b in CostBasis) + " lanes")
    if bases.count(CostBasis.QUOTE) < len(bases):
        print("Unquoted lanes use PLACEHOLDER rates (config.MODE_PARAMS).")

    out = config.OUTPUT_DIR.__class__(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for scenario in config.SCENARIOS:
        sol = solve_scenario(net, scenario)
        if sol.status != "OPTIMAL":
            print(f"\n[{scenario}] {sol.status}: demand cannot be met with the available supply/modes.")
            continue

        print(f"\n[{scenario}] OPTIMAL  delivered={sol.total_flow:,.0f} {VOLUME_UNIT}  "
              f"total=${sol.objective_usd:,.0f}/yr (${sol.avg_cost:.2f}/ton)  lanes used={len(sol.flows)}")
        print("   " + "  ".join(f"{k}=${v:,.0f}" for k, v in sol.cost_breakdown.items()))
        for site, mode in sol.built:
            print(f"   BUILD {mode.value} at {site} (${net.modes[(site, mode.value)].build_cost:,.0f}/yr)")
        lanes = net.lanes
        for (s, t, mode), v in sorted(sol.flows.items(), key=lambda kv: -kv[1]):
            arc = lanes[(s, t, mode)]
            print(f"   {v:>10,.0f}  {s}  ->  {t}  [{mode.value}]   "
                  f"(${arc.cost:.2f}/ton, {arc.miles:,.0f} mi, {arc.basis.value})")

        title = f"Caustic soda flows: {scenario.capitalize()} scenario ({VOLUME_UNIT})"
        title += " - placeholder freight rates"
        for ext in ("html", "png"):
            try:
                plot_nodes(nodes, flows=sol.flows, title=title,
                           save_path=out / f"network_map_{scenario}.{ext}")
            except RuntimeError as exc:   # kaleido/Chrome missing: keep the HTML map
                logger.warning("Could not write .%s (%s). Run `plotly_get_chrome` for PNG export.",
                               ext, str(exc).strip().splitlines()[0] if str(exc).strip() else "kaleido error")
    print(f"\nMaps written to {out}/")


if __name__ == "__main__":
    main()
