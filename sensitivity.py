"""Line-haul rate sensitivity: re-solve every scenario with one mode's rates scaled.

    python sensitivity.py --mode rail --multipliers 0.8 1 1.2 1.5 2
    python sensitivity.py --mode rail --cross-border     # only US <-> Canada lanes

For each multiplier and scenario, reports total cost, $/ton, modes built, and
tons shipped by each mode, and writes the table to the output directory.
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

import config
from loader import _US_ALIASES, load_nodes, load_site_modes
from main import apply_exclusions
from model import solve_scenario
from network import build_network
from node import Mode, Node


def _country(n: Node) -> str:
    return "US" if n.country.upper() in _US_ALIASES else n.country.upper()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mode", required=True, choices=[m.value for m in Mode])
    ap.add_argument("--multipliers", nargs="+", type=float, default=[0.8, 1.0, 1.2, 1.5, 2.0])
    ap.add_argument("--cross-border", action="store_true", help="scale only lanes between countries")
    ap.add_argument("--out", default=str(config.OUTPUT_DIR))
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    mode = Mode(args.mode)
    nodes, site_modes = apply_exclusions(load_nodes(config.WORKBOOK), load_site_modes(config.MODES_FILE))

    rows = []
    for k in args.multipliers:
        def scale(a: Node, b: Node, m: Mode, k=k) -> float:
            hit = m is mode and (not args.cross_border or _country(a) != _country(b))
            return k if hit else 1.0

        net = build_network(nodes, site_modes, rate_multiplier=scale)
        for scenario in config.SCENARIOS:
            sol = solve_scenario(net, scenario)
            row = dict(multiplier=k, scenario=scenario, status=sol.status,
                       total_usd=sol.objective_usd, usd_per_ton=sol.avg_cost,
                       built=", ".join(f"{m.value}@{s}" for s, m in sol.built))
            for m in Mode:
                row[f"{m.value}_tons"] = sum(v for (_, _, lane_mode), v in sol.flows.items() if lane_mode is m)
            rows.append(row)

    df = pd.DataFrame(rows)
    scope = f"{mode.value}{'_cross_border' if args.cross_border else ''}"
    out = config.OUTPUT_DIR.__class__(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / f"sensitivity_{scope}.csv", index=False)

    print(f"Sensitivity of {scope.replace('_', ' ')} line-haul rates:")
    with pd.option_context("display.width", 200, "display.max_columns", None, "display.float_format", "{:,.2f}".format):
        print(df.to_string(index=False))
    print(f"\nWritten to {out / f'sensitivity_{scope}.csv'}")


if __name__ == "__main__":
    main()
