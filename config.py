"""Central settings for the caustic soda network model. Edit this file, not the code."""

from pathlib import Path

# --- Inputs / outputs ----------------------------------------------------
WORKBOOK = "network.xlsx"
# Which modes each site supports (existing or candidate to build). A .csv
# file, or a workbook path to read its "Modes" sheet instead.
MODES_FILE = "modes.csv"
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
#   circuity          route miles / great-circle miles
#   usd_per_ton_mile  line-haul rate
#   min_miles         billed distance floor (barge is flat within ~20-30 mi)
#   max_miles         lanes longer than this are not offered (None = no limit)
MODE_PARAMS = {
    "truck":    dict(circuity=1.30, usd_per_ton_mile=0.20, min_miles=0,  max_miles=None),
    "rail":     dict(circuity=1.25, usd_per_ton_mile=0.06, min_miles=0,  max_miles=None),
    "barge":    dict(circuity=1.60, usd_per_ton_mile=0.03, min_miles=30, max_miles=None),
    "pipeline": dict(circuity=1.00, usd_per_ton_mile=0.05, min_miles=0,  max_miles=25),
}

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
