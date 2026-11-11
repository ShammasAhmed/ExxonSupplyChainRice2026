"""Central settings for the caustic soda network model. Edit this file, not the code."""

from pathlib import Path

# --- File paths ----------------------------------------------------------
# Every file the code reads or writes is named here. Paths are anchored to the
# repo folder, so scripts work from any working directory.
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

# data/model/: inputs the optimization reads. Editing these changes results.
MODEL_DATA_DIR = DATA_DIR / "model"
# Sources, sinks (and optional intermediates): location and base-scenario
# volume in DST/yr. Bear / bull volumes come from SCENARIO_MULTIPLIERS.
SITES_FILE = MODEL_DATA_DIR / "sites.csv"
# Which modes each site supports (existing or candidate to build).
MODES_FILE = MODEL_DATA_DIR / "modes.csv"
# Routed lane miles, written by build_distances.py. Lanes missing from it fall
# back to great-circle distance x circuity (see routing.py).
LANE_DISTANCES_FILE = MODEL_DATA_DIR / "lane_distances.csv"
# Quoted line-haul rates ($/metric ton). A quote replaces the rate formula
# for that lane; handling is still charged on the transfer arcs.
LANE_RATES_FILE = MODEL_DATA_DIR / "lane_rates.csv"

# data/reference/: research the model does not read. Only the XOM rate-check
# workbook (export_rate_check.py) uses these.
REFERENCE_DATA_DIR = DATA_DIR / "reference"
# Source of every rate and assumption below (ids X = XOM, D = derived, A = assumption).
RATE_SOURCES_FILE = REFERENCE_DATA_DIR / "rate_sources.csv"
# Existing and candidate rail lanes: railroads, likely route, interchanges.
RAIL_LANES_FILE = REFERENCE_DATA_DIR / "rail_lanes.csv"
# Railroads serving each site, with confidence and sources.
SITE_RAIL_FILE = REFERENCE_DATA_DIR / "site_rail_access.csv"
# The original site workbook is also kept in REFERENCE_DATA_DIR (network.xlsx)
# to show where SITES_FILE came from. No code reads it; edit SITES_FILE.

# Outputs (git-ignored). {scenario} / {scope} are filled in by the scripts.
OUTPUT_DIR = ROOT / "output"
NETWORK_MAP_NAME = "network_map_{scenario}"            # main.py, + .html / .png
SENSITIVITY_NAME = "sensitivity_{scope}.csv"           # sensitivity.py
RATE_CHECK_NAME = "XOM_rate_check.xlsx"                # export_rate_check.py
SITES_MAP_NAME = "network_map"                         # visualize.py run directly, + .html / .png
MAP_PREVIEW_FILE = OUTPUT_DIR / "_network_map_preview.html"   # visualize.plot_nodes(show=True)

# Downloaded data (git-ignored): the USACE waterway network for build_distances.py.
CACHE_DIR = ROOT / ".cache"
NWN_CACHE_FILE = CACHE_DIR / "nwn.json"

# --- Scenarios -----------------------------------------------------------
# Volume in each scenario = base_dst_per_yr in SITES_FILE x this multiplier.
SCENARIO_MULTIPLIERS = {"bear": 0.8, "base": 1.0, "bull": 1.2}
SCENARIOS = tuple(SCENARIO_MULTIPLIERS)

# --- Transport costs -----------------------------------------------------
# The model's volume unit is the dry short ton (DST, see loader.VOLUME_UNIT),
# but freight is billed on the weight actually loaded. So the rates below and
# HANDLING_USD_PER_TON are per WET short ton (solution as shipped), and the
# model divides them by SOLUTION_STRENGTH to get $ per DST.
#
# Every number below cites a row id in RATE_SOURCES_FILE (value, unit, date,
# URL and page for each). They are public list or benchmark rates, so XOM's
# contract rates are likely lower (XOM's own rail quote was 0.69x the
# supplier rate, rate_sources D14).
#
#   line haul $/ton = fixed_usd_per_ton + usd_per_ton_mile * billed miles
#   billed miles    = max(miles + (upstream_factor - 1) * upstream miles, min_miles)
#
#   circuity           route miles / great-circle miles, for lanes not in
#                      LANE_DISTANCES_FILE (and for the off-network leg from a
#                      site to the nearest road/rail/waterway node)
#   fixed_usd_per_ton  per-shipment charges that do not scale with distance
#                      (minimums, switching, fleeting); loading/unloading is
#                      separate, see HANDLING_USD_PER_TON
#   usd_per_ton_mile   line-haul rate
#   upstream_factor    rate multiplier for miles against the river current
#                      (barge only; upstream miles come from build_distances.py)
#   min_miles          billed distance floor (barge is flat within ~20-30 mi)
#   max_miles          lanes longer than this are not offered (None = no limit)
#
#   truck     Quality Carriers distance tariff for liquid chemicals, fit to
#             $516 + $5.44/mi per load, plus a 65% fuel surcharge at EIA diesel
#             of $6.352 (week of 10/26/2026), over 21 wet MT per load (D1-D3).
#             min_miles reproduces the tariff's $700 flat charge up to 40 mi.
#   rail      STB 2024 waybill fit for caustic tank cars, $2,062 + $5.014/car-mi,
#             scaled to the ~$12,000/car supplier rate XOM gave for USGC ->
#             Edmonton, over 84 wet MT per car (D5, D6).
#   barge     Kirby Inland Marine Aug 2026 LMR towing tariff, per 1,420-ton
#             barge: same-zone tow as the fixed part, the downstream rate slope
#             per mile, loaded upstream / downstream as the upstream factor
#             (D8-D10). Towing only; barge hire is not public.
#   pipeline  INGAA 4-inch line cost annualized at the Baytown volume (D13).
#             No site uses pipeline in MODES_FILE.
#   circuity  2017 Commodity Flow Survey, basic chemicals (G1); pipeline 1.0
#             is an assumption.
#   ocean     quote-only: no rate formula (None), so an ocean lane exists only
#             if LANE_RATES_FILE quotes it. Miles come from scgraph's marnet
#             sea-lane graph; circuity is only the fallback for unrouted lanes
#             (team assumption, A2).
MODE_PARAMS = {
    "truck":    dict(circuity=1.19, fixed_usd_per_ton=36.78, usd_per_ton_mile=0.3878, upstream_factor=1.0,
                     min_miles=34, max_miles=None),
    "rail":     dict(circuity=1.45, fixed_usd_per_ton=18.66, usd_per_ton_mile=0.04537, upstream_factor=1.0,
                     min_miles=0,  max_miles=None),
    "barge":    dict(circuity=1.60, fixed_usd_per_ton=1.863, usd_per_ton_mile=0.0290, upstream_factor=1.173,
                     min_miles=30, max_miles=None),   # min_miles: XOM, flat within ~20-30 mi (X6)
    "pipeline": dict(circuity=1.00, fixed_usd_per_ton=0.0, usd_per_ton_mile=0.2005, upstream_factor=1.0,
                     min_miles=0,  max_miles=25),
    "ocean":    dict(circuity=1.15, fixed_usd_per_ton=None, usd_per_ton_mile=None, upstream_factor=1.0,
                     min_miles=0,  max_miles=None),
}

# --- Quoted rates (LANE_RATES_FILE) --------------------------------------
# Quotes are in $/metric ton, on a dry (100% NaOH) or wet (as-shipped
# solution) basis per row. Caustic soda usually ships as ~50% solution, so a
# wet ton carries only SOLUTION_STRENGTH dry tons. Confirm both with EM.
SOLUTION_STRENGTH = 0.50       # dry tons NaOH per wet ton shipped
METRIC_TONS_PER_SHORT_TON = 0.90718474

# Cost to load or unload one wet short ton at a site, by mode (charged once at
# each end of a lane, and twice when product changes mode at a terminal).
# Truck and rail carriers charge nothing within free time and their rates
# exclude loading (D4, D7). Barge: Kirby dock shift + fleeting in/out per
# barge (D11). Ocean: loading is in the FOB price and discharge is in the
# import terminal's fee in SITES_FILE (D20).
HANDLING_USD_PER_TON = {"truck": 0.0, "rail": 0.0, "barge": 1.433, "pipeline": 0.0, "ocean": 0.0}

# --- Modular exclusions --------------------------------------------------
# Any node whose name is listed here is dropped before edges/model/maps are
# built. Remove a name to bring it back (e.g. delete the Alaska line).
# Names must match SITES_FILE exactly.
EXCLUDED_NODES: set[str] = {
    # "North Slope Processing Facilities",   # Prudhoe Bay, AK: no road link from the lower 48 without Canada
}

# Individual (source_name, sink_name) pairs to forbid, e.g. a lane you know is
# not usable. Applies to every mode. Leave empty for the full source x sink graph.
EXCLUDED_EDGES: set[tuple[str, str]] = set()
