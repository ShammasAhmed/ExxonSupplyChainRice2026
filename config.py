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
# All $ are per ton of the model's volume unit (DST, see loader.VOLUME_UNIT).
#
# PLACEHOLDERS: rough public order-of-magnitude figures for US bulk liquid
# chemicals, chosen only so the model runs. Replace them with EM's freight
# rates before drawing conclusions from the outputs.
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
MODE_PARAMS = {
    "truck":    dict(circuity=1.30, fixed_usd_per_ton=8.0, usd_per_ton_mile=0.20, upstream_factor=1.0,
                     min_miles=0,  max_miles=None),
    "rail":     dict(circuity=1.25, fixed_usd_per_ton=6.0, usd_per_ton_mile=0.06, upstream_factor=1.0,
                     min_miles=0,  max_miles=None),
    "barge":    dict(circuity=1.60, fixed_usd_per_ton=2.0, usd_per_ton_mile=0.03, upstream_factor=1.25,
                     min_miles=30, max_miles=None),
    "pipeline": dict(circuity=1.00, fixed_usd_per_ton=0.0, usd_per_ton_mile=0.05, upstream_factor=1.0,
                     min_miles=0,  max_miles=25),
}

# --- Quoted rates (LANE_RATES_FILE) --------------------------------------
# Quotes are in $/metric ton, on a dry (100% NaOH) or wet (as-shipped
# solution) basis per row. Caustic soda usually ships as ~50% solution, so a
# wet ton carries only SOLUTION_STRENGTH dry tons. Confirm both with EM.
SOLUTION_STRENGTH = 0.50       # dry tons NaOH per wet ton shipped
METRIC_TONS_PER_SHORT_TON = 0.90718474

# Cost to load or unload one ton at a site, by mode (charged once at each
# end of a lane, and twice when product changes mode at a terminal).
HANDLING_USD_PER_TON = {"truck": 2.0, "rail": 4.0, "barge": 3.0, "pipeline": 0.0}

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
