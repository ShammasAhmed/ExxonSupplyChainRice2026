"""Central settings for the caustic soda network model. Edit this file, not the code."""

from pathlib import Path

# --- Inputs / outputs ----------------------------------------------------
WORKBOOK = "network.xlsx"
OUTPUT_DIR = Path("output")

# --- Scenarios -----------------------------------------------------------
SCENARIOS = ("bear", "base", "bull")

# --- Modular exclusions --------------------------------------------------
# Any node whose name is listed here is dropped before edges/model/maps are
# built. Remove a name to bring it back (e.g. delete the Alaska line).
# Names must match the workbook exactly.
EXCLUDED_NODES: set[str] = {
    "North Slope Processing Facilities",   # Prudhoe Bay, AK: no road link from the lower 48 without Canada
}

# Individual (source_name, sink_name) pairs to forbid, e.g. a lane you know is
# not usable. Leave empty for the full source x sink graph.
EXCLUDED_EDGES: set[tuple[str, str]] = set()
