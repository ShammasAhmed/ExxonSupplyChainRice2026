"""Load the model inputs in config.MODEL_DATA_DIR: sites (sources / sinks),
per-site transport modes, and the per-lane distance and quoted-rate tables."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

import config
from node import LaneDistance, LaneKey, LaneRate, Mode, Node, NodeCategory, SiteMode

logger = logging.getLogger(__name__)

# Canonical model unit: dry short tons (100% NaOH) per year.
VOLUME_UNIT = "DST/yr"

_US_ALIASES = {"US", "USA", "U.S.", "U.S.A.", "UNITED STATES", "UNITED STATES OF AMERICA"}

_SITE_COLUMNS = ("name", "role", "city", "state", "country", "longitude", "latitude", "base_dst_per_yr",
                 "price_usd_per_dst", "terminal_fee_usd_per_wet_mt", "supplier_type")


def wet_mt_to_dst(usd_per_wet_mt: float) -> float:
    """$ per metric ton of solution as shipped -> $ per dry short ton (the model unit)."""
    return usd_per_wet_mt / config.SOLUTION_STRENGTH * config.METRIC_TONS_PER_SHORT_TON


def load_nodes(path: str | Path) -> list[Node]:
    """Read the sites table and return a list of Nodes.

    Columns: name, role (source/sink/intermediate), city, state, country,
    longitude, latitude, base_dst_per_yr, price_usd_per_dst,
    terminal_fee_usd_per_wet_mt, supplier_type, notes. For sinks, each
    scenario's demand is base_dst_per_yr x config.SCENARIO_MULTIPLIERS. For
    sources, base_dst_per_yr is today's volume to XOM, and the supply cap is
    that x config.SUPPLY_CAP_MULTIPLIER[supplier_type] in every scenario
    (supplier_type is required for sources and must be blank elsewhere).
    base_dst_per_yr may be blank only for intermediates. price_usd_per_dst (product price ex freight) is required
    for sources and must be blank elsewhere. terminal_fee_usd_per_wet_mt is
    charged on every ton passing through an intermediate (blank = 0) and must
    be blank elsewhere. Raises ValueError for missing columns, duplicate
    names, or bad values.
    """
    path = Path(path)
    df = pd.read_csv(path, skipinitialspace=True).dropna(how="all")
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in _SITE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}. Headers: {list(df.columns)}")

    nodes: list[Node] = []
    for idx, row in df.iterrows():
        where = f"{path.name} row {idx + 2}"
        name = str(row["name"]).strip()
        try:
            category = NodeCategory(str(row["role"]).strip().lower())
        except ValueError as exc:
            raise ValueError(f"{where} ({name!r}): role must be one of "
                             f"{[c.value for c in NodeCategory]}, got {row['role']!r}.") from exc
        base = _opt_float(row["base_dst_per_yr"], None)
        if base is None:
            if category is not NodeCategory.INTERMEDIATE:
                raise ValueError(f"{where} ({name!r}): base_dst_per_yr is blank.")
            base = 0.0
        price = _opt_float(row["price_usd_per_dst"], None)
        if (price is None) == (category is NodeCategory.SOURCE):
            raise ValueError(f"{where} ({name!r}): price_usd_per_dst is required for sources "
                             f"and must be blank for {category.value}s.")
        fee = _opt_float(row["terminal_fee_usd_per_wet_mt"], None)
        if fee is not None and category is not NodeCategory.INTERMEDIATE:
            raise ValueError(f"{where} ({name!r}): terminal_fee_usd_per_wet_mt only applies to intermediates.")
        supplier_type = "" if pd.isna(row["supplier_type"]) else str(row["supplier_type"]).strip().lower()
        if bool(supplier_type) != (category is NodeCategory.SOURCE):
            raise ValueError(f"{where} ({name!r}): supplier_type is required for sources "
                             f"and must be blank for {category.value}s.")
        if supplier_type and supplier_type not in config.SUPPLY_CAP_MULTIPLIER:
            raise ValueError(f"{where} ({name!r}): supplier_type must be one of "
                             f"{list(config.SUPPLY_CAP_MULTIPLIER)}, got {supplier_type!r}.")
        cap_k = config.SUPPLY_CAP_MULTIPLIER.get(supplier_type)
        country = str(row["country"]).strip()
        lat, lon = _coords(row["latitude"], row["longitude"], country, name, where)
        try:
            nodes.append(Node(
                name=name,
                city=str(row["city"]).strip(),
                state=str(row["state"]).strip(),
                country=country,
                category=category,
                coords=(lat, lon),
                **{s: base * k for s, k in config.SCENARIO_MULTIPLIERS.items()},
                price=price or 0.0,
                terminal_fee=wet_mt_to_dst(fee or 0.0),
                supply_cap=base * cap_k if cap_k is not None else None,
            ))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{where} ({name!r}): {exc}") from exc

    names = [n.name for n in nodes]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"{path.name}: duplicate site names: {dupes}")
    return nodes


def load_site_modes(path: str | Path) -> list[SiteMode]:
    """Read the modes table (config.MODES_FILE).

    Columns: site, mode, status (existing/candidate), build_cost_usd_per_yr,
    capacity_dst_per_yr, min_demand_share, notes. Blank optional cells mean
    0 build cost, no capacity cap, and no forced share.
    """
    path = Path(path)
    df = pd.read_csv(path).dropna(how="all")
    df.columns = [str(c).strip().lower() for c in df.columns]

    rows: list[SiteMode] = []
    for idx, row in df.iterrows():
        where = f"{path.name} row {idx + 2}"
        site = str(row["site"]).strip()
        status = str(row["status"]).strip().lower()
        if status not in ("existing", "candidate"):
            raise ValueError(f"{where} ({site!r}): status must be existing/candidate, got {status!r}.")
        try:
            mode = Mode(str(row["mode"]).strip().lower())
        except ValueError as exc:
            raise ValueError(f"{where} ({site!r}): unknown mode {row['mode']!r}; "
                             f"expected one of {[m.value for m in Mode]}.") from exc
        build_cost = _opt_float(row.get("build_cost_usd_per_yr"), 0.0)
        if status == "candidate" and build_cost <= 0:
            logger.warning("%s (%r, %s): candidate has no build cost, so building it is free.",
                           where, site, mode.value)
        share = _opt_float(row.get("min_demand_share"), 0.0)
        if not 0.0 <= share <= 1.0:
            raise ValueError(f"{where} ({site!r}): min_demand_share {share} not in [0, 1].")
        rows.append(SiteMode(
            site=site, mode=mode, existing=status == "existing", build_cost=build_cost,
            capacity=_opt_float(row.get("capacity_dst_per_yr"), None), min_demand_share=share,
        ))

    keys = [(r.site, r.mode) for r in rows]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise ValueError(f"{path.name}: duplicate (site, mode) rows: {dupes}")
    return rows


def load_lane_distances(path: str | Path) -> dict[LaneKey, LaneDistance]:
    """Read the routed lane miles written by build_distances.py.

    Columns: origin, destination, mode, miles, upstream_miles, source (other
    columns are kept for reference and ignored). Returns {} when the file does
    not exist, so every lane falls back to the great-circle estimate.
    """
    out = {}
    for where, key, row in _read_lane_table(path, ("miles",)):
        miles = float(row["miles"])
        if miles < 0:
            raise ValueError(f"{where}: miles {miles} is negative.")
        out[key] = LaneDistance(miles, _opt_float(row.get("upstream_miles"), 0.0),
                                str(row.get("source", "")).strip())
    return out


def load_lane_rates(path: str | Path) -> dict[LaneKey, LaneRate]:
    """Read quoted line-haul rates.

    Columns: origin, destination, mode, usd_per_mt, weight_basis (dry/wet),
    source, notes. Returns {} when the file does not exist.
    """
    out = {}
    for where, key, row in _read_lane_table(path, ("usd_per_mt", "weight_basis")):
        rate = float(row["usd_per_mt"])
        basis = str(row["weight_basis"]).strip().lower()
        if rate < 0:
            raise ValueError(f"{where}: usd_per_mt {rate} is negative.")
        if basis not in ("dry", "wet"):
            raise ValueError(f"{where}: weight_basis must be dry/wet, got {basis!r}.")
        out[key] = LaneRate(rate, basis, str(row.get("source", "")).strip())
    return out


def _read_lane_table(path: str | Path, required: tuple[str, ...]):
    """Yield (location for error messages, (origin, destination, Mode), row) per lane row."""
    path = Path(path)
    if not path.exists():
        return
    df = pd.read_csv(path, skipinitialspace=True).dropna(how="all")
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in ("origin", "destination", "mode", *required) if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}.")

    seen = set()
    for idx, row in df.iterrows():
        where = f"{path.name} row {idx + 2}"
        try:
            mode = Mode(str(row["mode"]).strip().lower())
        except ValueError as exc:
            raise ValueError(f"{where}: unknown mode {row['mode']!r}; "
                             f"expected one of {[m.value for m in Mode]}.") from exc
        key = (str(row["origin"]).strip(), str(row["destination"]).strip(), mode)
        if key in seen:
            raise ValueError(f"{where}: duplicate lane {key[0]!r} -> {key[1]!r} [{mode.value}].")
        seen.add(key)
        yield where, key, row


def _opt_float(value, default):
    return default if value is None or pd.isna(value) or str(value).strip() == "" else float(value)


def _coords(lat, lon, country, name, where) -> tuple[float, float]:
    """Return (lat, lon), correcting rows where the two columns are swapped.

    A swap is detected when the 'latitude' is outside [-90, 90], or, for US
    nodes, when latitude is negative and longitude positive (the US is entirely
    north and west, so a correct US point is always lat > 0, lon < 0).
    """
    lat, lon = float(lat), float(lon)
    swapped = abs(lat) > 90 or (country.upper() in _US_ALIASES and lat < 0 < lon)
    if swapped:
        logger.warning("%s (%r): latitude/longitude look swapped; correcting to (%s, %s).",
                       where, name, lon, lat)
        lat, lon = lon, lat
    return lat, lon


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    for n in load_nodes(sys.argv[1] if len(sys.argv) > 1 else config.SITES_FILE):
        print(f"{n.category.value:<12} {n.name:<42} ({n.lat:8.4f}, {n.lon:9.4f})  "
              f"base={n.base:>12,.0f} {VOLUME_UNIT}")