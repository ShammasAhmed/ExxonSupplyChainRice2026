"""Precompute every webapp scenario and write config.WEBAPP_DATA_FILE.

    python build_webapp_data.py                 # full grid, all CPU cores but one
    python build_webapp_data.py --workers 4
    python build_webapp_data.py --limit 50      # quick test: first 50 runs only

The webapp (webapp/index.html) never solves anything: it looks up results
for the control settings the user picks. This script solves the optimum for
every combination of control stops (CONTROLS below; 18,816 runs) plus XOM's
current network once, and packs them in the format webapp/DATA_SCHEMA.md
describes. Identical solutions are stored once.

Finished runs are checkpointed in config.WEBAPP_GRID_CACHE_DIR, so an
interrupted build resumes where it stopped. Delete that folder after changing
the model or its data, or the old results are reused.

Controls (stop values; the default is marked *):
    china_ocean        China -> Vancouver ocean rate, $/wet MT: 80, 100, 120, 145*, 185, Off
    supplier_switch    $/yr per new (supplier, XOM site) pair: 0, 25k, 50k*, 100k, 250k, 500k, 1M
    mode_switch        $/yr per (XOM site, new arrival mode): 0, 10k, 50k*, 100k, 250k, 500k, 1M
    supply_cap         terminals and distributors, x today's volume: 1.0, 1.25*, 1.5, uncapped
    joliet_rail        Joliet rail spur: don't build / build
    sarnia_rail        Sarnia rail spur: don't build / build
    chicago_hub        off = IMTT Lemont closed and the Olin Lemont Terminal serves Joliet only
                       (today's role); on = both Lemont terminals can ship anywhere
    alberta_railheads  CN Lynton and CN Vermilion rail-to-truck transloads: off / on
The decision controls (the last four) default to the best choice under the
default assumptions. The Joliet barge berth is never built (it never pays
for itself at $1.93M/yr), and demand is the base scenario.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import logging
import multiprocessing as mp
import os
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import config
from loader import load_current_flows, load_nodes, load_site_modes, wet_mt_to_dst
from model import Solution, solve_scenario
from network import ArcKind, Network, build_network
from node import Mode

logger = logging.getLogger("build_webapp_data")

SCENARIO = "base"
CHINA = "China export (Qingdao)"
VANCOUVER = "Univar North Vancouver"
IMTT = "IMTT Lemont"
OLIN_LEMONT = "Olin Lemont Terminal"
JOLIET = "Joliet Refinery"
SARNIA = "Sarnia Refinery"
RAILHEADS = ("CN Lynton (Fort McMurray)", "CN Vermilion")


def _k(v: float) -> str:
    return "$0" if v == 0 else f"${v / 1e6:g}M" if v >= 1e6 else f"${v / 1e3:g}k"


SUPPLIER_STOPS = [0, 25e3, 50e3, 100e3, 250e3, 500e3, 1e6]
MODE_STOPS = [0, 10e3, 50e3, 100e3, 250e3, 500e3, 1e6]

CONTROLS = [
    dict(id="china_ocean", label="China ocean freight", group="Market", kind="slider", decision=False,
         unit="$/wet MT",
         help="Ocean rate from Qingdao to North Vancouver. Off removes China as a supplier. "
              "Our base estimate is $145 (range $115-185); China product is $320/DMT FOB.",
         stops=[dict(label=f"${v}", value=v) for v in (80, 100, 120, 145, 185)] + [dict(label="Off", value=None)],
         default=3),
    dict(id="supplier_switch", label="Supplier switching cost", group="Switching costs", kind="slider",
         decision=False, unit="$/yr per new supplier at a site",
         help="Yearly cost of each new supplier at an XOM site: qualification, audit, contract (team "
              "assumption A5; our estimate is $15k-35k bottom-up, up to ~$430k at 2-5% of spend).",
         stops=[dict(label=_k(v), value=v) for v in SUPPLIER_STOPS], default=2),
    dict(id="mode_switch", label="Mode switching cost", group="Switching costs", kind="slider",
         decision=False, unit="$/yr per site per new mode",
         help="Yearly cost when a site starts receiving by a new mode: procedures, training, staffing "
              "(team assumption A6). On top of construction. Add $170k-640k/yr if XOM must lease its own rail cars.",
         stops=[dict(label=_k(v), value=v) for v in MODE_STOPS], default=2),
    dict(id="supply_cap", label="Terminal & distributor capacity", group="Capacity", kind="slider",
         decision=False, unit="x today's volume",
         help="How much more than today the Olin Lemont Terminal and the Canadian distributors can handle "
              "(team assumption A4 = 1.25x). Producers and China are uncapped; IMTT Lemont is uncapped.",
         stops=[dict(label="1.0x", value=1.0), dict(label="1.25x", value=1.25), dict(label="1.5x", value=1.5),
                dict(label="Uncapped", value=None)], default=1),
    dict(id="joliet_rail", label="Joliet rail spur", group="Network decisions", kind="toggle", decision=True,
         help="Build a liquid rail spur at Joliet: $4.0M, annualized to $407k/yr (8%, 20 yr).",
         stops=[dict(label="Don't build", value=False), dict(label="Build", value=True)], default=0),
    dict(id="sarnia_rail", label="Sarnia rail spur", group="Network decisions", kind="toggle", decision=True,
         help="Build a liquid rail spur at Sarnia: $407k/yr. Sarnia takes 1,323 DST/yr today "
              "(20k+ DMT after the 2028 expansion, not modeled here).",
         stops=[dict(label="Don't build", value=False), dict(label="Build", value=True)], default=0),
    dict(id="chicago_hub", label="Chicago hub", group="Network decisions", kind="toggle", decision=True,
         help="On: IMTT Lemont opens and both Lemont terminals can ship onward to any site (e.g. rail to "
              "Alberta). Off: the Olin Lemont Terminal serves Joliet only, as today.",
         stops=[dict(label="Off", value=False), dict(label="On", value=True)], default=0),
    dict(id="alberta_railheads", label="Alberta railheads", group="Network decisions", kind="toggle",
         decision=True,
         help="CN Lynton (Fort McMurray) and CN Vermilion: rail-to-truck transloads that let rail reach "
              "Kearl and Cold Lake. Fee $4.15/wet MT.",
         stops=[dict(label="Off", value=False), dict(label="On", value=True)], default=0),
]

COST_COMPONENTS = [
    dict(id="product", label="Caustic (product)"),
    dict(id="line_haul", label="Freight"),
    dict(id="handling", label="Loading / unloading"),
    dict(id="terminal", label="Terminal fees"),
    dict(id="build", label="Construction (annualized)"),
    dict(id="supplier_switch", label="Supplier switching"),
    dict(id="mode_switch", label="Mode switching"),
]

LABELS = {
    "Olin Chlor Alkali Freeport Complex": "Olin Freeport",
    "Westlake Chemical Lake Charles Complex": "Westlake Lake Charles",
    "Olin Plaquemine Plant": "Olin Plaquemine",
    "Covestro Baytown Industrial Complex": "Covestro Baytown",
    CHINA: "China (Qingdao)",
    VANCOUVER: "Univar N. Vancouver",
    "CN Lynton (Fort McMurray)": "CN Lynton",
    JOLIET: "Joliet",
    "Baton Rouge Complex": "Baton Rouge",
    "Baytown Complex": "Baytown",
    "Beaumont Complex": "Beaumont",
    "Gulf Coast Growth Ventures (GCGV)": "GCGV",
    "Strathcona Refinery": "Strathcona",
    "Nanticoke Refinery": "Nanticoke",
    SARNIA: "Sarnia",
}

NOTES = [
    "Every result is precomputed by the optimization model (Gurobi); the page only looks them up. "
    "Demand is the base scenario (XOM's 10/07 volumes).",
    "Today's network is XOM's 14 North American lanes from its 10/07 sheet, priced with the same cost model.",
    "Caustic prices are XOM's prices per lane (10/07 sheet). A new lane gets XOM's average price for "
    "the same supplier and mode; suppliers XOM does not use get our estimate.",
    "Freight rates are public tariffs (Quality Carriers truck, STB waybill rail scaled to XOM's $12,000/car, "
    "Kirby barge towing). XOM's contract rates are probably lower.",
    "Gulf-to-Chicago barge is calibrated to XOM's own price: XOM pays $450/DST at the Lemont terminal with "
    "the inbound barge included, which implies 0.40x our tariff barge rate on that lane (D22).",
    "The Olin Lemont Terminal (formerly K.A. Steel) is a terminal, not a producer: per XOM, its caustic comes "
    "from Plaquemine, LA or Baytown, TX.",
    "Switching costs and terminal capacity have no public source; they are team assumptions to vary.",
    "Construction costs are one-time costs annualized at 8% over 20 years. The Joliet barge berth "
    "($1.93M/yr) is left out: it never pays for itself.",
    "$/DST = dollars per dry short ton of NaOH. $/DMT = per dry metric ton. $/wet MT = per metric ton of "
    "50% solution as shipped.",
]

ASSUMPTIONS = [
    dict(id="A1", text="Construction annualized at 8% over 20 years."),
    dict(id="A4", text="Terminals and distributors can handle 1.25x today's volume (slider)."),
    dict(id="A5", text="Supplier switching cost per new (supplier, XOM site) pair (slider)."),
    dict(id="A6", text="Mode switching cost per XOM site starting a new arrival mode (slider)."),
    dict(id="D19", text="China to Vancouver ocean freight $145/wet MT base, $115-185 range (slider)."),
    dict(id="D22", text="Gulf to Lemont barge implied by XOM's $450/DST terminal price."),
]


# --- one run --------------------------------------------------------------

_NETS: dict[float | None, Network] = {}
_TYPES: dict[str, str] = {}


def supplier_types() -> dict[str, str]:
    """supplier_type per source in SITES_FILE (producer, export, terminal, distributor)."""
    if not _TYPES:
        import pandas as pd
        df = pd.read_csv(config.SITES_FILE)
        _TYPES.update({r["name"]: str(r["supplier_type"]).strip() for _, r in df.iterrows()
                       if r["role"] == "source" and not pd.isna(r["supplier_type"])})
    return _TYPES


def _network(ocean_rate: float | None) -> Network:
    """The network with China's ocean lane at `ocean_rate` $/wet MT (None: China closed)."""
    if ocean_rate not in _NETS:
        nodes = load_nodes(config.SITES_FILE)
        net = build_network(nodes, load_site_modes(config.MODES_FILE),
                            current=load_current_flows(config.CURRENT_FLOWS_FILE))
        if ocean_rate is not None:
            for i, a in enumerate(net.arcs):
                if a.kind is ArcKind.TRANSPORT and a.mode is Mode.OCEAN and a.tail[0] == CHINA:
                    net.arcs[i] = replace(a, cost=wet_mt_to_dst(ocean_rate))
        _NETS[ocean_rate] = net
    return _NETS[ocean_rate]


def _settings(key: tuple[int, ...]) -> dict:
    return {c["id"]: c["stops"][i]["value"] for c, i in zip(CONTROLS, key)}


def solve_run(key: tuple[int, ...]) -> tuple[tuple[int, ...], dict]:
    s = _settings(key)
    net = _network(s["china_ocean"])
    closed_sites: set[str] = set()
    closed_lanes: set = set()
    if s["china_ocean"] is None:
        closed_sites.add(CHINA)
    if not s["chicago_hub"]:
        closed_sites.add(IMTT)
        closed_lanes |= {lane for lane in net.lanes if lane[0] == OLIN_LEMONT and lane[1] != JOLIET}
    if not s["alberta_railheads"]:
        closed_sites |= set(RAILHEADS)
    caps: dict[str, float | None] = {}
    mult = s["supply_cap"]
    for name, n in net.sites.items():
        if n.is_source and supplier_types().get(name) in ("terminal", "distributor"):
            caps[name] = None if mult is None else n.base * mult
    today_lemont = sum(l.dst_per_yr for l in net.current.values() if l.via == OLIN_LEMONT)
    caps[OLIN_LEMONT] = None if mult is None else today_lemont * mult
    fixed_builds = {(JOLIET, "rail"): s["joliet_rail"], (SARNIA, "rail"): s["sarnia_rail"],
                    (JOLIET, "barge"): False}
    sol = solve_scenario(net, SCENARIO, supplier_switch_cost=s["supplier_switch"],
                         mode_switch_cost=s["mode_switch"], closed_sites=closed_sites,
                         closed_lanes=closed_lanes, fixed_builds=fixed_builds, caps=caps)
    if sol.status != "OPTIMAL":
        raise RuntimeError(f"Run {key} ({s}) is {sol.status}.")
    return key, plan_dict(net, sol)


# --- packing --------------------------------------------------------------

def plan_dict(net: Network, sol: Solution) -> dict:
    """A solution in the webapp's Plan format (DATA_SCHEMA.md)."""
    sites = net.sites
    lanes = net.lanes
    breakdown = dict.fromkeys((c["id"] for c in COST_COMPONENTS), 0.0)
    routes = []
    for n, r in enumerate(sorted(sol.routes, key=lambda r: (r.sink, -r.dst, r.supplier))):
        if r.dst <= 1e-6:
            continue
        legs = []
        for a, b, mode in r.legs:
            handling = 2 * config.HANDLING_USD_PER_TON[mode.value] / config.SOLUTION_STRENGTH
            terminal = sites[b].terminal_fee if sites[b].is_intermediate else 0.0
            arc = lanes[(a, b, mode)]
            legs.append(dict(**{"from": a}, to=b, mode=mode.value, miles=round(arc.miles, 1),
                             line_haul_usd_per_dst=round(arc.cost, 4),
                             handling_usd_per_dst=round(handling, 4),
                             terminal_usd_per_dst=round(terminal, 4)))
        logistics = sum(l["line_haul_usd_per_dst"] + l["handling_usd_per_dst"] + l["terminal_usd_per_dst"]
                        for l in legs)
        if abs(logistics - (r.line_haul + r.handling)) > 0.01:
            raise RuntimeError(f"Leg costs of {r.label} (${logistics:.2f}) do not match the route "
                               f"(${r.line_haul + r.handling:.2f}).")
        for l in legs:
            breakdown["line_haul"] += r.dst * l["line_haul_usd_per_dst"]
            breakdown["handling"] += r.dst * l["handling_usd_per_dst"]
            breakdown["terminal"] += r.dst * l["terminal_usd_per_dst"]
        breakdown["product"] += r.dst * r.product
        routes.append(dict(id=f"r{n}", supplier=r.supplier, site=r.sink, dst_per_yr=round(r.dst, 3),
                           current=r.current, legs=legs, product_usd_per_dst=round(r.product, 4),
                           landed_usd_per_dst=round(r.landed, 4), usd_per_yr=round(r.landed * r.dst, 2)))
    builds, sup, mode_sw = [], [], []
    for f in sol.fixed:
        if f.kind == "build":
            builds.append(dict(site=f.site, mode=f.detail.removeprefix("build "), usd_per_yr=f.usd))
            breakdown["build"] += f.usd
        elif f.kind == "supplier switch":
            sup.append(dict(supplier=f.detail.removeprefix("new supplier "), site=f.site, usd_per_yr=f.usd))
            breakdown["supplier_switch"] += f.usd
        else:
            mode_sw.append(dict(site=f.site, mode=f.detail.removeprefix("starts receiving by "), usd_per_yr=f.usd))
            breakdown["mode_switch"] += f.usd
    total = sum(breakdown.values())
    if abs(total - sol.objective_usd) > 1e-4 * sol.objective_usd:
        raise RuntimeError(f"Plan breakdown ${total:,.0f} != objective ${sol.objective_usd:,.0f}.")
    return dict(total_usd_per_yr=round(sol.objective_usd, 2),
                breakdown={k: round(v, 2) for k, v in breakdown.items()},
                routes=routes, builds=builds, supplier_switches=sup, mode_switches=mode_sw)


def node_list(net: Network) -> list[dict]:
    out = []
    for name, n in net.sites.items():
        modes = sorted(m for (s, m), sm in net.modes.items() if s == name and sm.existing)
        cands = sorted(m for (s, m), sm in net.modes.items() if s == name and not sm.existing)
        if n.is_sink:
            role, kind = "sink", "xom_site"
        elif n.is_intermediate:
            role, kind = "intermediate", "railhead" if name.startswith("CN ") else "terminal"
        else:
            role, kind = "source", supplier_types().get(name, "producer")
        out.append(dict(id=name, label=LABELS.get(name, name), role=role, kind=kind,
                        lat=n.lat, lon=n.lon, city=n.city, region=n.state, country=n.country,
                        demand_dst_per_yr=n.base if n.is_sink else None,
                        price_usd_per_dst=n.price if n.is_source else None,
                        terminal_fee_usd_per_dst=round(n.terminal_fee, 4) if n.is_intermediate else None,
                        modes=modes, candidate_modes=cands))
    return out


# --- driver ---------------------------------------------------------------

def _cache_file(cache_dir: Path) -> Path:
    return cache_dir / "runs.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--limit", type=int, default=None, help="solve only the first N runs (testing)")
    ap.add_argument("--out", default=str(config.WEBAPP_DATA_FILE))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    keys = list(itertools.product(*(range(len(c["stops"])) for c in CONTROLS)))
    if args.limit:
        keys = keys[:args.limit]
    cache_dir = Path(config.WEBAPP_GRID_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    done: dict[tuple[int, ...], dict] = {}
    if _cache_file(cache_dir).exists():
        for line in _cache_file(cache_dir).read_text().splitlines():
            rec = json.loads(line)
            done[tuple(rec["key"])] = rec["plan"]
    todo = [k for k in keys if k not in done]
    logger.info("%d runs: %d cached, %d to solve on %d workers", len(keys), len(keys) - len(todo),
                len(todo), args.workers)

    t0 = time.time()
    with open(_cache_file(cache_dir), "a") as fh:
        def keep(result):
            key, plan = result
            done[key] = plan
            fh.write(json.dumps(dict(key=list(key), plan=plan)) + "\n")
            n = len(done)
            if n % 500 == 0:
                fh.flush()
                rate = (n - (len(keys) - len(todo))) / max(time.time() - t0, 1e-9)
                logger.info("%d / %d runs (%.1f/s)", n, len(keys), rate)

        if args.workers > 1 and len(todo) > 1:
            with mp.get_context("spawn").Pool(args.workers) as pool:
                for result in pool.imap_unordered(solve_run, todo, chunksize=8):
                    keep(result)
        else:
            for k in todo:
                keep(solve_run(k))
    logger.info("Solved %d runs in %.0f s", len(todo), time.time() - t0)

    # Baseline: XOM's network as it is today.
    net = _network(145)
    as_is = solve_scenario(net, SCENARIO, as_is=True)
    if as_is.status != "OPTIMAL":
        raise RuntimeError(f"As-is case is {as_is.status}.")
    baseline = plan_dict(net, as_is)

    plans: dict[str, dict] = {}
    plan_id: dict[str, str] = {}
    runs = {}
    for key in keys:
        plan = done[key]
        digest = hashlib.sha1(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        if digest not in plan_id:
            plan_id[digest] = f"p{len(plan_id)}"
            plans[plan_id[digest]] = plan
        runs["-".join(map(str, key))] = dict(plan=plan_id[digest], total_usd_per_yr=plan["total_usd_per_yr"])

    controls = [dict(c) for c in CONTROLS]
    if not args.limit:
        # Decision toggles start at the best choice for the default assumptions.
        decision = [i for i, c in enumerate(controls) if c["decision"]]
        default = [c["default"] for c in controls]
        best = min(itertools.product(*(range(len(controls[i]["stops"])) for i in decision)),
                   key=lambda combo: runs["-".join(map(str, [combo[decision.index(i)] if i in decision
                                                              else default[i] for i in range(len(controls))]))]
                   ["total_usd_per_yr"])
        for i, v in zip(decision, best):
            controls[i]["default"] = v

    data = dict(
        meta=dict(title="Caustic soda network", generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  scenario=SCENARIO, notes=NOTES, assumptions=ASSUMPTIONS),
        nodes=node_list(net),
        modes=[dict(id=m, label=m.title()) for m in ("truck", "rail", "barge", "ocean")],
        controls=controls, cost_components=COST_COMPONENTS,
        baseline=baseline,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.limit:
        data.update(plans=plans, runs=runs)   # partial grid: unpacked, for inspection only
        out.write_text("window.APP_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n")
    else:
        out.write_text(packed_js(data, [plans[runs["-".join(map(str, k))]["plan"]] for k in keys], keys))
    logger.info("Wrote %s: %d runs, %d distinct plans, %.1f MB", out, len(runs), len(plans),
                out.stat().st_size / 1e6)


# The plans repeat the same routes thousands of times, so the file stores each
# distinct route once and each plan as references to them; INFLATE_JS rebuilds
# the full DATA_SCHEMA.md structure in the browser.
INFLATE_JS = """window.APP_DATA = (function (c) {
  var ids = c.nodes.map(function (n) { return n.id; });
  var modes = c.mode_ids, comps = c.cost_components.map(function (x) { return x.id; });
  var defs = c.route_defs.map(function (d) {
    return { supplier: ids[d[0]], site: ids[d[1]], current: !!d[2], product_usd_per_dst: d[3],
      landed_usd_per_dst: d[4], legs: d[5].map(function (l) {
        return { from: ids[l[0]], to: ids[l[1]], mode: modes[l[2]], miles: l[3],
          line_haul_usd_per_dst: l[4], handling_usd_per_dst: l[5], terminal_usd_per_dst: l[6] }; }) };
  });
  function plan(p) {
    var b = {}; comps.forEach(function (k, i) { b[k] = p[1][i]; });
    return { total_usd_per_yr: p[0], breakdown: b,
      routes: p[2].map(function (r, i) { var d = defs[r[0]];
        return { id: "r" + i, supplier: d.supplier, site: d.site, dst_per_yr: r[1], current: d.current,
          legs: d.legs, product_usd_per_dst: d.product_usd_per_dst, landed_usd_per_dst: d.landed_usd_per_dst,
          usd_per_yr: Math.round(d.landed_usd_per_dst * r[1] * 100) / 100 }; }),
      builds: p[3].map(function (x) { return { site: ids[x[0]], mode: modes[x[1]], usd_per_yr: x[2] }; }),
      supplier_switches: p[4].map(function (x) { return { supplier: ids[x[0]], site: ids[x[1]], usd_per_yr: x[2] }; }),
      mode_switches: p[5].map(function (x) { return { site: ids[x[0]], mode: modes[x[1]], usd_per_yr: x[2] }; }) };
  }
  var plans = {}; c.plans.forEach(function (p, i) { plans["p" + i] = plan(p); });
  var runs = {}, sizes = c.controls.map(function (x) { return x.stops.length; }), n = c.run_plans.length;
  for (var r = 0; r < n; r++) {
    var key = [], rem = r;
    for (var j = sizes.length - 1; j >= 0; j--) { key.unshift(rem % sizes[j]); rem = Math.floor(rem / sizes[j]); }
    var pid = c.run_plans[r];
    runs[key.join("-")] = { plan: "p" + pid, total_usd_per_yr: c.plans[pid][0] };
  }
  return { meta: c.meta, nodes: c.nodes, modes: c.modes, controls: c.controls,
    cost_components: c.cost_components, baseline: plan(c.baseline), plans: plans, runs: runs };
})(__COMPACT__);
"""


def packed_js(data: dict, run_plans: list[dict], keys: list[tuple[int, ...]]) -> str:
    """window.APP_DATA as compact JSON plus INFLATE_JS. Runs must be in
    itertools.product order of the control stops (the inflater rebuilds keys)."""
    expected = list(itertools.product(*(range(len(c["stops"])) for c in data["controls"])))
    if keys != expected:
        raise ValueError("Packing needs every run, in control-stop product order (no --limit).")
    idx = {n["id"]: i for i, n in enumerate(data["nodes"])}
    mode_ids = [m["id"] for m in data["modes"]]
    comps = [c["id"] for c in data["cost_components"]]
    defs: dict[str, int] = {}
    route_defs: list = []
    plan_index: dict[int, int] = {}
    plans: list = []

    def r2(v: float) -> float:
        return round(v, 4)

    def pack(p: dict) -> list:
        routes = []
        for r in p["routes"]:
            d = [idx[r["supplier"]], idx[r["site"]], int(r["current"]), r2(r["product_usd_per_dst"]),
                 r2(r["landed_usd_per_dst"]),
                 [[idx[l["from"]], idx[l["to"]], mode_ids.index(l["mode"]), l["miles"],
                   r2(l["line_haul_usd_per_dst"]), r2(l["handling_usd_per_dst"]), r2(l["terminal_usd_per_dst"])]
                  for l in r["legs"]]]
            sig = json.dumps(d)
            if sig not in defs:
                defs[sig] = len(route_defs)
                route_defs.append(d)
            routes.append([defs[sig], round(r["dst_per_yr"], 2)])
        return [round(p["total_usd_per_yr"]), [round(p["breakdown"][k]) for k in comps], routes,
                [[idx[b["site"]], mode_ids.index(b["mode"]), round(b["usd_per_yr"])] for b in p["builds"]],
                [[idx[x["supplier"]], idx[x["site"]], round(x["usd_per_yr"])] for x in p["supplier_switches"]],
                [[idx[x["site"]], mode_ids.index(x["mode"]), round(x["usd_per_yr"])] for x in p["mode_switches"]]]

    run_idx = []
    for p in run_plans:
        if id(p) not in plan_index:
            plan_index[id(p)] = len(plans)
            plans.append(pack(p))
        run_idx.append(plan_index[id(p)])
    compact = {k: v for k, v in data.items() if k != "baseline"}
    compact.update(mode_ids=mode_ids, route_defs=route_defs, plans=plans, run_plans=run_idx,
                   baseline=pack(data["baseline"]))
    return INFLATE_JS.replace("__COMPACT__", json.dumps(compact, separators=(",", ":")))


if __name__ == "__main__":
    main()
