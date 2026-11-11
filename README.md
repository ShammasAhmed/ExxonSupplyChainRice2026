
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
Chrome). Part of the output:

```text
25 sites, 44 site-modes (3 candidates to build), 298 arcs

[base] OPTIMAL  delivered=197,592 DST/yr  total=$106,771,035/yr ($540.36/ton)  lanes used=18
   product=$76,920,905  line haul=$27,038,689  handling + terminal=$2,404,032  build=$407,409
   BUILD rail at Joliet Refinery ($407,409/yr)
       44,439  Olin Plaquemine Plant  ->  Baton Rouge Complex  [barge]   ($5.95/ton, 33 mi, routed)
       44,092  China export (Qingdao)  ->  Univar North Vancouver  [ocean]   ($263.08/ton, 5,942 mi, quote)
       ...
```

Other scripts:

| Command | What it does |
| --- | --- |
| `python export_rate_check.py` | Writes `output/XOM_rate_check.xlsx`, the workbook XOM uses to check our freight rates. Every cost is a live formula on the rate inputs. It also has the rail lanes, a Chicago hub comparison and the source of every number. |
| `python sensitivity.py --mode rail --cross-border --multipliers 0.8 1 1.2 1.5` | Re-solves every scenario with one mode's line-haul rates scaled. `--cross-border` scales only US <-> Canada lanes. Writes `output/sensitivity_<scope>.csv`. |
| `python build_distances.py` | Recomputes routed miles into `data/model/lane_distances.csv`. Only needed after adding sites or `modes.csv` rows (`--modes barge` redoes one mode). Needs internet; the waterway network is cached in `.cache/`. |

Common changes:

- **Add or move a site:** add a row to `data/model/sites.csv` (`role` is
  `source`, `sink`, or `intermediate` for a transfer hub), add its modes to
  `data/model/modes.csv`, then rerun `build_distances.py`.
- **Change a volume:** edit `base_dst_per_yr` in `data/model/sites.csv`. Bear
  and bull follow from `SCENARIO_MULTIPLIERS` in `config.py`.
- **Change a product price or terminal fee:** edit `price_usd_per_dst`
  (required for sources) or `terminal_fee_usd_per_wet_mt` (intermediates
  only) in `data/model/sites.csv`.
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
- **Objective:** minimize total landed cost in $/yr: product price at each
  source (ex freight) + line haul + handling + terminal fees at intermediates
  + annualized build cost of candidate modes.
- **Intermediates** (IMTT Lemont in Chicago, Univar North Vancouver, CN
  railheads for Kearl and Cold Lake) let product change mode. Each ton through
  one pays unload + load handling plus the site's terminal fee.
- **Constraints:** sources ship at most their supply; sinks get exactly their
  demand; optional per-mode capacity and minimum demand share from
  `modes.csv`; a candidate mode carries flow only if the model builds it
  (binary).
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
| `lane_rates.csv` | Quoted line-haul rates per lane. Holds the China -> Vancouver ocean rate; no XOM quotes yet. |

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
| `config.py` | Every setting: all file paths, scenario multipliers, rates, solution strength, handling cost, excluded sites and lanes. |
| `loader.py`, `node.py` | Read `sites.csv`, `modes.csv` and the lane tables into `Node`, `SiteMode` and lane objects. |
| `network.py` | Builds the hub + mode node graph and its arcs. |
| `routing.py` | Line-haul $/ton for each lane. |
| `model.py` | The Gurobi MILP. |
| `main.py` | Runs all scenarios, prints results and draws maps. |
| `visualize.py` | Folium map rendering (HTML + PNG). |
| `sensitivity.py`, `export_rate_check.py`, `build_distances.py` | See [Quickstart](#quickstart). |
| `scripts/cfs_circuity.py`, `scripts/puws_caustic.py` | One-off scripts that derived the circuity factors and the rail rate fit from public datasets (download links are in each file). |

**Outputs** go to `output/`, which is gitignored. Downloaded data is cached in `.cache/`, also gitignored.

## Status and open gaps (as of 2026-11-10)

- **Supply is today's volume.** A source's supply is the volume it ships to
  XOM today (`base_dst_per_yr`), scaled by the scenario multiplier. US and
  Canadian supply therefore equals demand, and only the China node (a
  placeholder cap equal to Alberta demand) adds slack. Which source wins in
  Alberta depends on this setting.
- **One China node.** It stands for coastal Shandong exporters at one FOB
  price. China -> US is not modeled (37.5% Section 301 duties).
- **Unconfirmed plumbing.** Strathcona rail receipt, CN Vermilion as the Cold
  Lake railhead, and the IMTT Lemont truck rack are unconfirmed; coordinates
  for IMTT Lemont and CN Lynton are approximate.
- **Who runs the Lemont terminal.** XOM's sheet says Joliet buys from WLK
  (Westlake) at Lemont. The only public caustic terminal there is Olin's
  (the former K.A. Steel site; barge, railcar and truck), which is what
  `sites.csv` models. Confirm with XOM.
- **No XOM rate quotes.** XOM can't share contract rates, so they are
  checking our estimates in the rate-check workbook instead, and
  `data/model/lane_rates.csv` stays empty.
