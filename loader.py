"""Load network nodes from the network workbook (Sources / Sinks sheets)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from node import Node, NodeCategory

logger = logging.getLogger(__name__)

# Sheet name -> node category. Sheets not listed here (e.g. "Edges") are ignored.
SHEET_CATEGORIES = {
    "Sources": NodeCategory.SOURCE,
    "Sinks": NodeCategory.SINK,
    "Intermediates": NodeCategory.INTERMEDIATE,
}

# Canonical model unit. The workbook also carries DST (short ton) columns, but
# those are Excel formulas derived from the DMT columns, so DMT is read directly.
VOLUME_UNIT = "DMT/yr"

_US_ALIASES = {"US", "USA", "U.S.", "U.S.A.", "UNITED STATES", "UNITED STATES OF AMERICA"}

# Header patterns, matched case-insensitively against the column headers, so
# "Name" vs "Facility Name" or "Bear Production" vs "Bear Demand" both work.
_COLUMN_PATTERNS = {
    "name": r"^(facility\s+)?name$",
    "city": r"^city$",
    "state": r"^state$",
    "country": r"^country$",
    "lon": r"^long(itude)?$",
    "lat": r"^lat(itude)?$",
    "bear": rf"^bear\b.*\({re.escape(VOLUME_UNIT)}\)$",
    "base": rf"^base\b.*\({re.escape(VOLUME_UNIT)}\)$",
    "bull": rf"^bull\b.*\({re.escape(VOLUME_UNIT)}\)$",
}


def load_nodes(path: str | Path) -> list[Node]:
    """Read every known node sheet in the workbook and return a list of Nodes.

    Raises ValueError for missing columns, duplicate names, or bad values.
    """
    sheets = pd.read_excel(path, sheet_name=None)  # dict of all sheets
    nodes: list[Node] = []

    for sheet_name, df in sheets.items():
        category = SHEET_CATEGORIES.get(sheet_name.strip())
        if category is None:
            logger.info("Skipping sheet %r (not a node sheet).", sheet_name)
            continue
        nodes.extend(_parse_sheet(df, sheet_name, category))

    names = [n.name for n in nodes]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"Duplicate node names across sheets: {dupes}")
    return nodes


def _parse_sheet(df: pd.DataFrame, sheet_name: str, category: NodeCategory) -> list[Node]:
    cols = _map_columns(df, sheet_name)

    # Drop fully blank rows (Excel often has trailing empty formatted rows).
    df = df.dropna(how="all")
    df = df[df[cols["name"]].notna()]

    nodes = []
    for idx, row in df.iterrows():
        excel_row = idx + 2  # header is row 1, pandas index is 0-based
        name = str(row[cols["name"]]).strip()
        country = str(row[cols["country"]]).strip()
        lat, lon = _coords(row[cols["lat"]], row[cols["lon"]], country, name, sheet_name, excel_row)
        try:
            nodes.append(Node(
                name=name,
                city=str(row[cols["city"]]).strip(),
                state=str(row[cols["state"]]).strip(),
                country=country,
                category=category,
                coords=(lat, lon),
                bear=float(row[cols["bear"]]),
                base=float(row[cols["base"]]),
                bull=float(row[cols["bull"]]),
            ))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{sheet_name} row {excel_row} ({name!r}): {exc}") from exc

        n = nodes[-1]
        if not (n.bear <= n.base <= n.bull):
            logger.warning("%s row %d (%r): scenarios not ordered bear <= base <= bull.",
                           sheet_name, excel_row, name)
    return nodes


def _map_columns(df: pd.DataFrame, sheet_name: str) -> dict[str, str]:
    """Find the actual header for each field using _COLUMN_PATTERNS."""
    headers = [str(c).strip() for c in df.columns]
    mapping, missing = {}, []
    for field, pattern in _COLUMN_PATTERNS.items():
        matches = [h for h in headers if re.match(pattern, h, flags=re.IGNORECASE)]
        if len(matches) == 1:
            mapping[field] = df.columns[headers.index(matches[0])]
        elif not matches:
            missing.append(field)
        else:
            raise ValueError(f"Sheet {sheet_name!r}: ambiguous columns for {field!r}: {matches}")
    if missing:
        raise ValueError(f"Sheet {sheet_name!r}: missing columns for {missing}. Headers: {headers}")
    return mapping


def _coords(lat, lon, country, name, sheet_name, excel_row) -> tuple[float, float]:
    """Return (lat, lon), correcting rows where the two columns are swapped.

    A swap is detected when the 'latitude' is outside [-90, 90], or, for US
    nodes, when latitude is negative and longitude positive (the US is entirely
    north and west, so a correct US point is always lat > 0, lon < 0).
    """
    lat, lon = float(lat), float(lon)
    swapped = abs(lat) > 90 or (country.upper() in _US_ALIASES and lat < 0 < lon)
    if swapped:
        logger.warning("%s row %d (%r): latitude/longitude look swapped; correcting to (%s, %s).",
                       sheet_name, excel_row, name, lon, lat)
        lat, lon = lon, lat
    return lat, lon


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    for n in load_nodes(sys.argv[1] if len(sys.argv) > 1 else "network.xlsx"):
        print(f"{n.category.value:<12} {n.name:<42} ({n.lat:8.4f}, {n.lon:9.4f})  "
              f"base={n.base:>12,.0f} {VOLUME_UNIT}")