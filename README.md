
# Exxon Supply Chain Rice 2026

Rice University CMOR 492 Senior Design Project with ExxonMobil

## Project Plan

ExxonMobil (EM) currently sources 100% of its caustic soda domestically. Rising
exports from India, China, and other global partners — driven by growing PVC
pipe demand (and therefore Chlorine/caustic-soda co-production) in those
construction markets — suggest EM may now be able to source caustic soda more
cheaply from abroad than from the US. This project's goal is to challenge EM's
current domestic-only caustic soda supply chain network and produce evidence
for or against the hypothesis that EM can source cheaper caustic soda
globally.

The work runs September 2026 - December 2026 in three levels:

### Level 1 - Regional U.S. Pricing Model (current phase)

Map, and ideally replicate, EM's existing regional supply chain network so it
can serve as the baseline for a later global comparison. Built from:

- **Demand nodes** - EM plant locations and approximate demand.
- **Supply nodes** - domestic caustic soda producers: locations, production
  capacity ranges, and estimated price (index + markup).
- **Node costs** - a transport cost model connecting supply and demand nodes,
  expressed as one of: USD/mile transported, USD/dry short ton (DST) moved,
  USD/mile-ton, or a fixed USD amount per lane.
- **Nodal flow** (optional) - actual EM flow data, to cross-reference the
  model's output against reality.

All data is modeled with low/high/mean range scenarios (bear/base/bull), and
weights are converted to dry short tons (DST). Bear and bull volumes are 0.8x
and 1.2x base (`SCENARIO_MULTIPLIERS` in `config.py`).

**Level 1 timeline:**

| Window | Milestone |
| --- | --- |
| Sept 24 - Oct 12 | Data wrangling: receive and standardize all data from EM |
| Oct 12 - Oct 19 | Build the model on Gurobi; the optimal solution should reproduce EM's current network |
| Oct 19 - Nov 2 | Present the solution to EM for sign-off to proceed to the global sourcing study |

Levels 2 and 3 (the global sourcing study and beyond) are gated on EM
approving the Level 1 model.

**Where we are (2026-11-10):** the Level 1 North America model is built and
uses sourced public freight rates. XOM is checking those rates in the
rate-check workbook (`export_rate_check.py`). Level 2 work has started:
the model now has product prices, a Chicago hub (IMTT Lemont), and a China
export node shipping by ocean to Vancouver and by CN rail into Alberta.

## Quickstart

Requires Python 3.11+ and a Gurobi license (free for academic use).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Optional: for the lighter CARTO basemap on the maps, get a free key at
https://carto.com/basemaps/apikey/ and add `export CARTO_API_KEY=<your key>` to
your `~/.zshrc`. Never commit the key. Without it, maps use OpenStreetMap
tiles.

`main.py` solves the bear, base and bull scenarios. For each one it prints the
total cost, the cost breakdown and every lane used, and it writes a map to
`output/network_map_<scenario>.html` (plus a `.png` if selenium can find
Chrome). On the map, a box shows the cost breakdown in $/yr and $/DST, and
hovering shows freight $/DST on each flow, the price at each source, the
terminal fee at each hub, and the landed $/DST at each EM site (product +
logistics; build costs are not allocated to sites). Part of the output:

```text
25 sites, 44 site-modes (3 candidates to build), 298 arcs

[base] OPTIMAL  delivered=197,592 DST/yr  total=$103,545,796/yr ($524.04/ton)  lanes used=15
   product=$80,959,927  line haul=$21,185,359  handling + terminal=$993,101  build=$407,409
   BUILD rail at Joliet Refinery ($407,409/yr)
       44,439  Olin Plaquemine Plant  ->  Baton Rouge Complex  [barge]   ($5.95/ton, 33 mi, routed)
       43,455  Covestro Baytown Industrial Complex  ->  Baytown Complex  [barge]   ($5.47/ton, 16 mi, routed)
       ...
```

Other scripts:

| Command | What it does |
| --- | --- |
| `python gap.py --supplier-switch-cost 250000 --mode-switch-cost 250000` | Prices XOM's current network (`data/model/current_flows.csv`) and the optimum on the same costs, and writes the gap site by site (`output/gap_sites_<scenario>.csv`) and route by route (`output/gap_lanes_<scenario>.csv`). Switch costs default to 0. |
| `python export_rate_check.py` | Writes `output/XOM_rate_check.xlsx`, the workbook XOM uses to check our freight rates. Every cost is a live formula on the rate inputs. It also has the rail lanes, a Chicago hub comparison and the source of every number. |
| `python sensitivity.py --mode rail --cross-border --multipliers 0.8 1 1.2 1.5` | Re-solves every scenario with one mode's line-haul rates scaled. `--cross-border` scales only US <-> Canada lanes. Writes `output/sensitivity_<scope>.csv`. |
| `python build_distances.py` | Recomputes routed miles into `data/model/lane_distances.csv`. Only needed after adding sites or `modes.csv` rows (`--modes barge` redoes one mode). Needs internet; the waterway network is cached in `.cache/`. |

Common changes:

- **Add or move a site:** add a row to `data/model/sites.csv` (`role` is
  `source`, `sink`, or `intermediate` for a transfer hub), add its modes to
  `data/model/modes.csv`, then rerun `build_distances.py`.
- **Change a volume:** edit `base_dst_per_yr` in `data/model/sites.csv`. For
  sinks it is base-scenario demand; bear and bull follow from
  `SCENARIO_MULTIPLIERS` in `config.py`. For sources it is today's volume to
  XOM, which sets the supply cap (below).
- **Change a supply cap:** each source has a `supplier_type` (producer,
  terminal, distributor or export) in `sites.csv`, and
  `SUPPLY_CAP_MULTIPLIER` in `config.py` sets its cap as a multiple of
  today's volume (`None` = uncapped). Caps don't change with the scenario.
- **Change a product price or terminal fee:** a current supplier's prices
  are per lane in `data/model/current_flows.csv`. `price_usd_per_dst` in
  `data/model/sites.csv` (required for sources) is used only for suppliers
  XOM doesn't buy from today (rule under "How the model works").
  `terminal_fee_usd_per_wet_mt` applies to intermediates only.
- **Change XOM's current network:** edit `data/model/current_flows.csv` (one
  row per supplier, XOM site and mode, from XOM's 10/07 sheet). Each site's
  rows must add up to its base demand in `sites.csv`.
- **Turn on switching costs:** `SUPPLIER_SWITCH_USD_PER_YR` and
  `MODE_SWITCH_USD_PER_YR` in `config.py`, or `--supplier-switch-cost` /
  `--mode-switch-cost` on `main.py` and `gap.py`.
- **Change a rate:** edit `MODE_PARAMS` in `config.py`, and cite a row in
  `data/reference/rate_sources.csv`.
- **Use a quoted rate for one lane:** add a row to `data/model/lane_rates.csv`.
  It replaces the rate formula for that lane.
- **Move or rename a data file:** change its path in `config.py`. No other
  file names a path.
- **Leave a site out:** add its name to `EXCLUDED_NODES` in `config.py`.

## How the model works

One min-cost-flow MILP per scenario, solved with Gurobi (`model.py`):

- **Network** (`network.py`): each site becomes a hub node plus one node per
  transport mode it has. Load/unload arcs between the hub and its mode nodes
  carry handling cost, and transport arcs between sites carry line-haul cost.
  This way, changing mode at a terminal costs a second round of handling.
- **Flow tracks its origin:** flow is split by where it was loaded (supplier
  and the mode it leaves by), so the model knows which supplier serves which
  XOM site even through any number of terminals. Its size grows with
  suppliers x arcs, not with the number of possible routes. After the solve,
  each supplier's flow is split into routes (supplier -> terminals -> site)
  for reporting.
- **Objective:** minimize total landed cost in $/yr: product price + line
  haul + handling + terminal fees at intermediates + annualized build cost of
  candidate modes + switching costs.
- **Product price per lane:** XOM's prices differ by lane (Covestro: $380 by
  barge to Baytown, $450 by truck). A delivery from supplier s, leaving by
  mode m, to site t pays (1) XOM's price for that lane in `current_flows.csv`,
  else (2) XOM's volume-weighted price for what s ships by m today, else (3)
  `price_usd_per_dst` in `sites.csv`.
- **As-is vs. optimal:** the same model with flows fixed to XOM's current
  lanes (`current_flows.csv`, scaled to the scenario) prices today's network.
  The difference is the gap (`gap.py`).
- **Switching costs** (`config.py`, default 0, team assumptions A5 and A6):
  - *Supplier switch:* charged once per (supplier, XOM site) pair that
    isn't in today's network. It's per pair because supplier qualification,
    contracts and receiving checks happen site by site.
  - *Mode switch:* charged once per (XOM site, arrival mode) the site doesn't
    receive by today, on top of any build cost. It's per site because a new
    mode's operating burden falls on the site (XOM 10/07: sites don't want
    to switch modes back and forth). A lane moving to a mode its site
    already uses (Baytown truck -> barge) pays nothing.
- **Intermediates** (the Olin Lemont Terminal and IMTT Lemont in Chicago,
  Univar North Vancouver, CN railheads for Kearl and Cold Lake) let product
  change mode. Each ton through one pays unload + load handling plus the
  site's terminal fee. A current lane can pass through one
  (`current_flows.csv` columns `via` and `arrival_mode`): Joliet's supply is
  Plaquemine -barge-> Olin Lemont Terminal -truck-> Joliet.
- **Constraints:** sources ship at most their supply cap (producers and
  China are uncapped; terminals and distributors get 1.25x today's volume); sinks get exactly their
  demand; optional per-mode capacity and minimum demand share from
  `modes.csv`; a candidate mode carries flow only if the model builds it
  (binary); a new supplier pair or site mode carries flow only if its switch
  is paid (binary, only when the switch cost is above 0).
- **Line haul** (`routing.py`): a quoted rate from `lane_rates.csv` if there
  is one, else fixed $/ton + $/ton-mile x routed miles. Ocean has no formula,
  so an ocean lane exists only if it is quoted. Barge miles against
  the river current cost more, and short barge and truck moves have a minimum
  billed distance.
- **Units:** volumes are dry short tons (DST/yr). Freight is billed on wet
  (as-shipped, 50% solution) tons, so rates are converted with
  `config.SOLUTION_STRENGTH`. Quotes in `lane_rates.csv` are in $/metric ton.

**Rates.** Every rate in `config.py` and every build cost in `modes.csv` cites
a row in `data/reference/rate_sources.csv` (value, date, URL, page):

- Truck: Quality Carriers liquid chemical tariff, plus fuel surcharge.
- Rail: STB 2024 waybill fit for caustic tank cars, scaled to the ~$12,000/car
  supplier rate XOM gave for Gulf Coast -> Edmonton.
- Barge: Kirby Inland Marine Aug 2026 towing tariffs (towing only; barge hire
  is not public).
- Ocean (China -> Vancouver): Clarksons chemical tanker spot rates (Odfjell
  3Q26) scaled to the US West Coast with SSY lane ratios.
- Product prices: XOM's 10/07 sheet for current suppliers; Argus / PriceSeek
  FOB China for the China node.

These are public list rates, so XOM's contract rates are probably lower.

## Repo map

**Model inputs** (`data/model/`): the optimization reads these, so editing
them changes the results.

| File | Contents |
| --- | --- |
| `sites.csv` | 11 suppliers (10 in the US and Canada, 1 China export node), 4 intermediate hubs and 10 EM sites: role, location, base-scenario volume (DST/yr), product price ($/DST, sources) and terminal fee ($/wet MT, intermediates). `notes` records unit conversions and sources. |
| `modes.csv` | Modes each site has: `existing`, or `candidate` with an annualized build cost. Optional capacity and minimum share. Built from EM's caustic model data sheet. |
| `lane_distances.csv` | Routed miles per lane, written by `build_distances.py`: truck on OpenStreetMap highways, rail on Class 1 lines, barge on the USACE National Waterway Network, ocean on scgraph's marnet sea lanes. |
| `lane_rates.csv` | Quoted line-haul rates per lane: the China -> Vancouver ocean rate, and Gulf -> Lemont barge rates implied by XOM's $450/DST terminal price (D22). |
| `current_flows.csv` | XOM's current network from its 10/07 sheet: supplier, XOM site, mode, volume (DST/yr) and the price XOM pays on that lane. Canadian rows converted from DMT. |

**Reference data** (`data/reference/`): research behind the numbers. The model
does not read these; only the rate-check workbook does.

| File | Contents |
| --- | --- |
| `network.xlsx` | The original site workbook (bear/base/bull volumes in DST and DMT, with formulas), kept to show where `sites.csv` came from. The model does not read it: edit `data/model/sites.csv` instead. |
| `rate_sources.csv` | Source of every rate, price and assumption. IDs start with X (XOM-stated), T / R / B / O (truck, rail, barge, ocean sources), P (product prices and suppliers), G (general: circuity, terminals, borders, build costs), D (derived) or A (team assumption). |
| `rail_lanes.csv` | Existing and candidate rail lanes: serving railroads, likely route, interchanges. |
| `site_rail_access.csv` | Railroads serving each site, with confidence and sources. |

**Code**

| File | Role |
| --- | --- |
| `config.py` | Every setting: all file paths, scenario multipliers, supply caps, price rule, switching costs, rates, solution strength, handling cost, excluded sites and lanes. |
| `loader.py`, `node.py` | Read `sites.csv`, `modes.csv` and the lane tables into `Node`, `SiteMode` and lane objects. |
| `network.py` | Builds the hub + mode node graph and its arcs. |
| `routing.py` | Line-haul $/ton for each lane. |
| `model.py` | The Gurobi MILP, the as-is case, and route decomposition. |
| `gap.py` | As-is vs. optimal, site by site and route by route. |
| `main.py` | Runs all scenarios, prints results and draws maps. |
| `visualize.py` | Folium map rendering (HTML + PNG). |
| `build_webapp_data.py` | Solves every webapp scenario (18,816 runs, ~2 min on 8 cores) and writes `webapp/data/app_data.js`. |
| `webapp/` | Static scenario explorer: open `webapp/index.html` in a browser. Data format in `webapp/DATA_SCHEMA.md`. |
| `scripts/build_route_geometry.py` | Routed lane shapes for the webapp map (`webapp/data/geometry.js`). |
| `sensitivity.py`, `export_rate_check.py`, `build_distances.py` | See [Quickstart](#quickstart). |
| `scripts/cfs_circuity.py`, `scripts/puws_caustic.py` | One-off scripts that derived the circuity factors and the rail rate fit from public datasets (download links are in each file). |

**Outputs** go to `output/`, which is gitignored. Downloaded data is cached in `.cache/`, also gitignored.

## Status and open gaps (as of 2026-11-11)

- **Supply caps.** Producers and China are uncapped, and terminals and
  distributors can grow 25% over today's volume (a team assumption, A4).
  The Olin Lemont Terminal's throughput is capped the same way (1.25 x
  Joliet's 19,260 DST/yr); IMTT Lemont is uncapped.
- **Prices on new lanes.** A supplier serving a new site, or moving a lane to
  another mode, gets XOM's price for that kind of shipment (e.g. Baytown's
  truck volume moving to barge gets Covestro's $380 barge price). That price
  gap is a large part of the savings at Baytown and Beaumont. Confirm with
  XOM that it reflects the mode and not something else.
- **Switching costs are 0 by default.** Supplier and mode switch costs have
  no source yet (A5, A6). Run `gap.py` with a few values to show how the
  savings hold up.
- **One China node.** It stands for coastal Shandong exporters at one FOB
  price. China -> US is not modeled (37.5% Section 301 duties).
- **Unconfirmed plumbing.** Strathcona rail receipt, CN Vermilion as the Cold
  Lake railhead, and the IMTT Lemont truck rack are unconfirmed; coordinates
  for IMTT Lemont and CN Lynton are approximate.
- **Who runs the Lemont terminal.** XOM's sheet says Joliet buys from WLK
  (Westlake) at Lemont, a terminal fed from Plaquemine or Baytown. The model
  has it as the Olin Lemont Terminal, an intermediate at Olin's site (the
  former K.A. Steel site, 15185 Main St; barge, railcar and truck). The
  inbound barge rate is set so Plaquemine product reaches it at XOM's $450/DST
  (D22): 0.40x our tariff, which also makes Chicago cheaper for Canada.
  The team's call list also has Westlake at 13589 Main St, Lemont, and on W.
  Durkee Rd, Channahon (tank truck). Those aren't in the model yet. If Joliet's
  supplier is the truck-only Westlake site, a move to rail also means a new
  supplier.
- **No XOM rate quotes.** XOM can't share contract rates, so they are
  checking our estimates in the rate-check workbook instead, and
  `data/model/lane_rates.csv` stays empty.
