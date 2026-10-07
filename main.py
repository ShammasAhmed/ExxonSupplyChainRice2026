"""Caustic soda supply chain: min drive-time flow for bear / base / bull scenarios.

    python main.py

Drive times are estimates: great-circle distance x 1.3 at 55 mph (see routing.py).
"""

from __future__ import annotations

import argparse
import logging

import config
from loader import load_nodes
from model import solve_scenario
from node import Node
from routing import get_drive_times
from visualize1 import plot_nodes

logger = logging.getLogger("main")


def apply_exclusions(nodes: list[Node]) -> list[Node]:
    """Drop nodes listed in config.EXCLUDED_NODES (error on unknown names)."""
    unknown = config.EXCLUDED_NODES - {n.name for n in nodes}
    if unknown:
        raise ValueError(f"EXCLUDED_NODES names not found in workbook: {sorted(unknown)}")
    kept = [n for n in nodes if n.name not in config.EXCLUDED_NODES]
    for name in sorted(config.EXCLUDED_NODES):
        logger.warning("Excluding node: %s", name)
    return kept


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", default=config.WORKBOOK)
    ap.add_argument("--out", default=str(config.OUTPUT_DIR))
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    nodes = apply_exclusions(load_nodes(args.workbook))
    sources = [n for n in nodes if n.is_source]
    sinks = [n for n in nodes if n.is_sink]
    print(f"{len(sources)} sources x {len(sinks)} sinks = {len(sources) * len(sinks)} candidate edges")

    times = get_drive_times(sources, sinks)
    print("Using estimated drive times (see routing.py).")

    out = config.OUTPUT_DIR.__class__(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for scenario in config.SCENARIOS:
        sol = solve_scenario(sources, sinks, times, scenario)
        if sol.status != "OPTIMAL":
            print(f"\n[{scenario}] {sol.status}: demand cannot be met with the available supply/edges.")
            continue

        print(f"\n[{scenario}] OPTIMAL  flow={sol.total_flow:,.0f} DMT/yr  "
              f"avg drive time={sol.avg_hours:.2f} h/DMT  edges used={len(sol.flows)}")
        for (s, t), v in sorted(sol.flows.items(), key=lambda kv: -kv[1]):
            print(f"   {v:>10,.0f}  {s}  ->  {t}   ({times[(s, t)] / 3600:.2f} h)")

        title = f"Caustic soda flows: {scenario.capitalize()} scenario (DMT/yr)"
        title += " - estimated drive times"
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
