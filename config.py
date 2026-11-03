"""Central settings for the caustic soda network model. Edit this file, not the code."""

from pathlib import Path

# --- Inputs / outputs ----------------------------------------------------
WORKBOOK = "network.xlsx"
# Which modes each site supports (existing or candidate to build). A .csv
# file, or a workbook path to read its "Modes" sheet instead.
MODES_FILE = "modes.csv"
# Routed lane miles, written by build_distances.py. Lanes missing from it fall
# back to great-circle distance x circuity (see routing.py).
LANE_DISTANCES_FILE = "lane_distances.csv"
# Quoted line-haul rates ($/metric ton). A quote replaces the rate formula
# for that lane; handling is still charged on the transfer arcs.
LANE_RATES_FILE = "lane_rates.csv"
OUTPUT_DIR = Path("output")

# --- Scenarios -----------------------------------------------------------
SCENARIOS = ("bear", "base", "bull")

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
MODE_PARAMS = {
    "truck":    dict(circuity=1.19, fixed_usd_per_ton=36.78, usd_per_ton_mile=0.3878, upstream_factor=1.0,
                     min_miles=34, max_miles=None),
    "rail":     dict(circuity=1.45, fixed_usd_per_ton=18.66, usd_per_ton_mile=0.04537, upstream_factor=1.0,
                     min_miles=0,  max_miles=None),
    "barge":    dict(circuity=1.60, fixed_usd_per_ton=1.863, usd_per_ton_mile=0.0290, upstream_factor=1.173,
                     min_miles=30, max_miles=None),   # min_miles: XOM, flat within ~20-30 mi (X6)
    "pipeline": dict(circuity=1.00, fixed_usd_per_ton=0.0, usd_per_ton_mile=0.2005, upstream_factor=1.0,
                     min_miles=0,  max_miles=25),
}
RATE_SOURCES_FILE = "sources/rate_sources.csv"

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
# barge (D11).
HANDLING_USD_PER_TON = {"truck": 0.0, "rail": 0.0, "barge": 1.433, "pipeline": 0.0}

# --- Modular exclusions --------------------------------------------------
# Any node whose name is listed here is dropped before edges/model/maps are
# built. Remove a name to bring it back (e.g. delete the Alaska line).
# Names must match the workbook exactly.
EXCLUDED_NODES: set[str] = {
    # "North Slope Processing Facilities",   # Prudhoe Bay, AK: no road link from the lower 48 without Canada
}

# Individual (source_name, sink_name) pairs to forbid, e.g. a lane you know is
# not usable. Applies to every mode. Leave empty for the full source x sink graph.
EXCLUDED_EDGES: set[tuple[str, str]] = set()
