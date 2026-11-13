"""Lane-by-lane gap between XOM's current network and the optimal one.

    python gap.py
    python gap.py --scenarios base --supplier-switch-cost 250000 --mode-switch-cost 250000

Each scenario is solved twice on the same costs: as-is (flows fixed to XOM's
current lanes, config.CURRENT_FLOWS_FILE) and optimal. Writes, per scenario:

    gap_sites_<scenario>.csv   one row per XOM site: as-is vs. optimal $/yr,
                               savings, and who supplies it by which route
    gap_lanes_<scenario>.csv   every route in either plan with its $/DST
                               breakdown, plus the builds and switches

A site's cost is its routes (tons x landed $/DST) plus the builds and
switches charged at that site. One site's savings can be negative when the
optimum moves a capped supplier's volume to a site where it saves more; the
total is what matters.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

import config
from loader import load_current_flows, load_nodes, load_site_modes
from main import apply_exclusions
from model import Solution, solve_scenario
from network import Network, build_network

PLANS = ("as-is", "optimal")
NETWORK = "(network)"   # site label for builds at sites that are not XOM sites


def site_costs(net: Network, sol: Solution) -> dict[str, float]:
    """$/yr charged to each XOM site: its routes plus builds and switches there."""
    out = {t: 0.0 for t, n in net.sites.items() if n.is_sink}
    for r in sol.routes:
        out[r.sink] += r.dst * r.landed
    for f in sol.fixed:
        site = f.site if f.site in out else NETWORK
        out[site] = out.get(site, 0.0) + f.usd
    return out


def lane_rows(scenario: str, plan: str, sol: Solution) -> list[dict]:
    rows = [dict(scenario=scenario, site=r.sink, plan=plan, item="route", supplier=r.supplier,
                 route=r.label, via=" > ".join(r.via), load_mode=r.load_mode.value,
                 arrival_mode=r.arrival_mode.value, current_lane=r.current, dst_per_yr=r.dst,
                 product_usd_per_dst=r.product, line_haul_usd_per_dst=r.line_haul,
                 handling_terminal_usd_per_dst=r.handling, landed_usd_per_dst=r.landed,
                 usd_per_yr=r.dst * r.landed)
            for r in sol.routes]
    rows += [dict(scenario=scenario, site=f.site, plan=plan, item=f.kind, route=f.detail, usd_per_yr=f.usd)
             for f in sol.fixed]
    return rows


def describe(sol: Solution, site: str) -> str:
    parts = []
    for r in sol.routes:
        if r.sink == site:
            hops = "".join(f" -{mode.value}->" + ("" if b == site else f" {b}") for _, b, mode in r.legs)
            parts.append(f"{r.supplier}{hops} ({r.dst:,.0f})")
    parts += [f.detail for f in sol.fixed if f.site == site]
    return "; ".join(parts)


def site_rows(net: Network, scenario: str, as_is: Solution, opt: Solution) -> list[dict]:
    before, after = site_costs(net, as_is), site_costs(net, opt)
    rows = []
    for t in sorted(before, key=lambda t: before[t] - after.get(t, 0.0), reverse=True):
        demand = net.sites[t].value(scenario) if t in net.sites else 0.0
        saving = before[t] - after.get(t, 0.0)
        rows.append(dict(
            scenario=scenario, site=t, demand_dst_per_yr=demand,
            as_is_usd_per_yr=before[t], optimal_usd_per_yr=after.get(t, 0.0), savings_usd_per_yr=saving,
            as_is_usd_per_dst=before[t] / demand if demand else None,
            optimal_usd_per_dst=after.get(t, 0.0) / demand if demand else None,
            savings_usd_per_dst=saving / demand if demand else None,
            as_is_supply=describe(as_is, t), optimal_supply=describe(opt, t),
        ))
    total_d = sum(r["demand_dst_per_yr"] for r in rows)
    rows.append(dict(scenario=scenario, site="TOTAL", demand_dst_per_yr=total_d,
                     as_is_usd_per_yr=as_is.objective_usd, optimal_usd_per_yr=opt.objective_usd,
                     savings_usd_per_yr=as_is.objective_usd - opt.objective_usd,
                     as_is_usd_per_dst=as_is.objective_usd / total_d,
                     optimal_usd_per_dst=opt.objective_usd / total_d,
                     savings_usd_per_dst=(as_is.objective_usd - opt.objective_usd) / total_d))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--scenarios", nargs="+", default=list(config.SCENARIOS), choices=config.SCENARIOS)
    ap.add_argument("--supplier-switch-cost", type=float, default=None,
                    help=f"$/yr per new (supplier, site) pair (default {config.SUPPLIER_SWITCH_USD_PER_YR:,.0f})")
    ap.add_argument("--mode-switch-cost", type=float, default=None,
                    help=f"$/yr per new (site, mode) (default {config.MODE_SWITCH_USD_PER_YR:,.0f})")
    ap.add_argument("--out", default=str(config.OUTPUT_DIR))
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    nodes, site_modes = apply_exclusions(load_nodes(config.SITES_FILE), load_site_modes(config.MODES_FILE))
    net = build_network(nodes, site_modes, current=load_current_flows(config.CURRENT_FLOWS_FILE))
    if not net.current:
        raise SystemExit(f"{config.CURRENT_FLOWS_FILE} is missing or empty; there is no as-is network.")
    switch = dict(supplier_switch_cost=args.supplier_switch_cost, mode_switch_cost=args.mode_switch_cost)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for scenario in args.scenarios:
        as_is = solve_scenario(net, scenario, as_is=True, **switch)
        opt = solve_scenario(net, scenario, **switch)
        if as_is.status != "OPTIMAL" or opt.status != "OPTIMAL":
            print(f"[{scenario}] as-is {as_is.status}, optimal {opt.status}: skipped.")
            continue

        sites = pd.DataFrame(site_rows(net, scenario, as_is, opt))
        lanes = pd.DataFrame(lane_rows(scenario, "as-is", as_is) + lane_rows(scenario, "optimal", opt))
        sites.to_csv(out / config.GAP_SITES_NAME.format(scenario=scenario), index=False)
        lanes.to_csv(out / config.GAP_LANES_NAME.format(scenario=scenario), index=False)

        saving = as_is.objective_usd - opt.objective_usd
        print(f"\n[{scenario}] as-is ${as_is.objective_usd:,.0f}/yr  optimal ${opt.objective_usd:,.0f}/yr  "
              f"savings ${saving:,.0f}/yr ({saving / as_is.objective_usd:.1%})")
        for key in as_is.cost_breakdown:
            a, o = as_is.cost_breakdown[key], opt.cost_breakdown.get(key, 0.0)
            if a or o:
                print(f"   {key:<20} ${a:>14,.0f} -> ${o:>14,.0f}   ({a - o:>+14,.0f})")
        print(f"   {'site':<36} {'as-is $/DST':>11} {'optimal':>9} {'savings $/yr':>14}  optimal supply")
        for r in sites.itertuples():
            if r.site == "TOTAL":
                continue
            per = (f"{r.as_is_usd_per_dst:>11,.2f} {r.optimal_usd_per_dst:>9,.2f}"
                   if r.demand_dst_per_yr else f"{'':>11} {'':>9}")
            print(f"   {r.site[:36]:<36} {per} {r.savings_usd_per_yr:>+14,.0f}  {r.optimal_supply}")
    print(f"\nWritten to {out}/ ({config.GAP_SITES_NAME.format(scenario='<scenario>')}, "
          f"{config.GAP_LANES_NAME.format(scenario='<scenario>')})")


if __name__ == "__main__":
    main()
