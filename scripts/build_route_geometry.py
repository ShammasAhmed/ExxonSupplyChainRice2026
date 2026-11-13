"""Routed line shapes for every transport lane, for the webapp map.

    python scripts/build_route_geometry.py                     # lanes from SITES_FILE + MODES_FILE
    python scripts/build_route_geometry.py --lanes lanes.csv   # lanes from a CSV instead
    python scripts/build_route_geometry.py --modes barge ocean # only these modes

Writes config.WEBAPP_GEOMETRY_FILE as
    window.APP_GEOMETRY = {"lanes": {"<origin>|<destination>|<mode>": [[lon, lat], ...]}};
(see webapp/DATA_SCHEMA.md). Lanes are routed on the same networks as
build_distances.py, but this keeps the path coordinates instead of the miles:

    truck  scgraph "world_highways"
    rail   scgraph "north_america_rail"
    barge  USACE National Waterway Network (config.NWN_CACHE_FILE; drawn
           node to node, since link geometries are not oriented)
    ocean  scgraph "marnet"

Each line starts and ends exactly at the site coordinates (the straight legs
to the nearest network node are kept). Lines are simplified with
Ramer-Douglas-Peucker to at most --max-points points, rounded to 4 decimals,
and their longitudes are made continuous (a trans-Pacific line may go below
-180). A lane that cannot be routed is logged and left out; the webapp then
draws an arc for it.

The --lanes CSV needs columns origin, destination, mode, origin_lon,
origin_lat, dest_lon, dest_lat.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402

logger = logging.getLogger("build_route_geometry")

SCGRAPH_NETWORKS = {"truck": "world_highways", "rail": "north_america_rail", "ocean": "marnet"}
MODES = ("truck", "rail", "barge", "ocean")

# Longitude the network is centred on: when a line crosses the antimeridian,
# its end nearer this keeps its real longitude and the other end is shifted.
HOME_LON = -95.0


# --------------------------------------------------------------------------- lanes

def lanes_from_model() -> pd.DataFrame:
    """Lanes the model offers, built from SITES_FILE + MODES_FILE as build_distances.py does."""
    from loader import load_nodes, load_site_modes
    from network import transport_lanes

    sites = {n.name: n for n in load_nodes(config.SITES_FILE)}
    modes = [(sm.site, sm.mode.value) for sm in load_site_modes(config.MODES_FILE) if sm.site in sites]
    rows = []
    for a, b, mode in transport_lanes(sites, modes):
        mode = getattr(mode, "value", mode)
        rows.append(dict(origin=a, destination=b, mode=mode,
                         origin_lon=sites[a].lon, origin_lat=sites[a].lat,
                         dest_lon=sites[b].lon, dest_lat=sites[b].lat))
    return pd.DataFrame(rows)


def load_lanes(csv: str | None) -> pd.DataFrame:
    if csv:
        return pd.read_csv(csv)
    try:
        return lanes_from_model()
    except Exception as exc:
        sys.exit(f"Could not build lanes from {config.SITES_FILE} / {config.MODES_FILE} ({exc!r}). "
                 "Pass --lanes <csv> instead.")


# --------------------------------------------------------------------------- routing

def _circuity(mode: str) -> float:
    return config.MODE_PARAMS.get(mode, {}).get("circuity", 1.0)


def barge_graph():
    """GeoGraph over USACE waterway nodes, weighted by published link miles.

    Reuses build_distances.build_nwn_graph when it imports; otherwise builds
    the same graph from config.NWN_CACHE_FILE directly.
    """
    try:
        from build_distances import build_nwn_graph, fetch_nwn
        return build_nwn_graph(fetch_nwn())[0]
    except Exception as exc:   # build_distances or its imports may be mid-edit
        logger.info("build_distances did not import (%s); reading %s directly.", exc, config.NWN_CACHE_FILE)

    from scgraph import GeoGraph
    nwn = json.loads(config.NWN_CACHE_FILE.read_text())
    index, coords = {}, []
    for f in nwn["nodes"]:
        if f["geometry"]:
            lon, lat = f["geometry"]["coordinates"][:2]
            index[f["properties"]["NODENUM"]] = len(coords)
            coords.append([lat, lon])
    graph: list[dict[int, float]] = [{} for _ in coords]
    for f in nwn["links"]:
        p = f["properties"]
        u, v = index.get(p["ANODE"]), index.get(p["BNODE"])
        if u is None or v is None or u == v:
            continue
        miles = p["LENGTH"] or _haversine_mi(*coords[u], *coords[v])
        for x, y in ((u, v), (v, u)):
            if y not in graph[x] or miles < graph[x][y]:
                graph[x][y] = miles
    return GeoGraph(graph=graph, nodes=coords, geograph_units="mi")


def _haversine_mi(lat1, lon1, lat2, lon2) -> float:
    p1, p2, dl = np.radians(lat1), np.radians(lat2), np.radians(lon2 - lon1)
    h = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(3958.8 * 2 * np.arcsin(np.sqrt(h)))


def load_graph(mode: str):
    if mode == "barge":
        return barge_graph()
    from scgraph import GeoGraph
    return GeoGraph.load_geograph(SCGRAPH_NETWORKS[mode])


def route(graph, mode: str, lane) -> list[list[float]]:
    """[[lon, lat], ...] from the origin site to the destination site."""
    r = graph.get_shortest_path({"latitude": lane.origin_lat, "longitude": lane.origin_lon},
                                {"latitude": lane.dest_lat, "longitude": lane.dest_lon},
                                output_units="mi", node_addition_circuity=_circuity(mode))
    line = [[lon, lat] for lat, lon in r["coordinate_path"]]
    # Pin both ends to the exact site coordinates (scgraph already starts and
    # ends at the query points; this guards against rounding or a dropped leg).
    for site, end in (((lane.origin_lon, lane.origin_lat), 0), ((lane.dest_lon, lane.dest_lat), -1)):
        if line and np.hypot(line[end][0] - site[0], line[end][1] - site[1]) < 1e-6:
            line[end] = list(site)
        elif end == 0:
            line.insert(0, list(site))
        else:
            line.append(list(site))
    return line


# --------------------------------------------------------------------------- shaping

def unwrap(line: list[list[float]]) -> np.ndarray:
    """Make longitudes continuous, then keep the end nearer HOME_LON at its real longitude."""
    pts = np.asarray(line, dtype=float)
    lon = np.degrees(np.unwrap(np.radians(pts[:, 0])))
    first, last = pts[0, 0], pts[-1, 0]
    anchor_idx, anchor_lon = (0, first) if abs(first - HOME_LON) <= abs(last - HOME_LON) else (-1, last)
    lon += 360.0 * round((anchor_lon - lon[anchor_idx]) / 360.0)
    pts[:, 0] = lon
    return pts


def rdp_mask(pts: np.ndarray, eps: float) -> np.ndarray:
    """Ramer-Douglas-Peucker in planar lon/lat degrees; boolean mask of points kept."""
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        seg = pts[i + 1:j]
        d = b - a
        n = np.hypot(*d)
        if n == 0:
            dist = np.hypot(*(seg - a).T)
        else:
            dist = np.abs(d[0] * (seg[:, 1] - a[1]) - d[1] * (seg[:, 0] - a[0])) / n
        k = int(np.argmax(dist))
        if dist[k] > eps:
            m = i + 1 + k
            keep[m] = True
            stack += [(i, m), (m, j)]
    return keep


def simplify(pts: np.ndarray, max_points: int, eps: float) -> np.ndarray:
    """RDP at `eps` degrees, loosened until the line has at most max_points points."""
    while True:
        out = pts[rdp_mask(pts, eps)]
        if len(out) <= max_points:
            return out
        eps *= 1.5


def finish(line: list[list[float]], max_points: int, eps: float) -> list[list[float]]:
    pts = simplify(unwrap(line), max_points, eps)
    out: list[list[float]] = []
    for lon, lat in np.round(pts, 4).tolist():
        if not out or out[-1] != [lon, lat]:
            out.append([lon, lat])
    if len(out) == 1:
        out.append(out[0])
    return out


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--lanes", help="CSV of lanes (default: build them from SITES_FILE + MODES_FILE)")
    ap.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    ap.add_argument("--out", default=config.WEBAPP_GEOMETRY_FILE)
    ap.add_argument("--max-points", type=int, default=150, help="most points kept per line")
    ap.add_argument("--epsilon", type=float, default=0.01,
                    help="starting RDP tolerance in degrees (~1 km); loosened per line to meet --max-points")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    lanes = load_lanes(args.lanes)
    lanes = lanes[lanes["mode"].isin(args.modes)]
    shapes: dict[str, list[list[float]]] = {}
    routed, failed = Counter(), Counter()
    for mode in args.modes:
        todo = lanes[lanes["mode"] == mode]
        if todo.empty:
            continue
        logger.info("Routing %d %s lanes", len(todo), mode)
        graph = load_graph(mode)
        for lane in todo.itertuples(index=False):
            key = f"{lane.origin}|{lane.destination}|{mode}"
            try:
                shapes[key] = finish(route(graph, mode, lane), args.max_points, args.epsilon)
                routed[mode] += 1
            except Exception as exc:   # scgraph raises plain Exceptions for unreachable points
                logger.warning("No %s route %r -> %r (%s); the map will draw an arc.",
                               mode, lane.origin, lane.destination, exc)
                failed[mode] += 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"lanes": dict(sorted(shapes.items()))}, separators=(",", ":"), ensure_ascii=False)
    out.write_text(f"window.APP_GEOMETRY = {body};\n", encoding="utf-8")

    for mode in args.modes:
        print(f"{mode:6s} routed {routed[mode]:4d}  failed {failed[mode]:3d}")
    n_pts = sum(len(v) for v in shapes.values())
    print(f"Wrote {len(shapes)} lanes ({n_pts} points, {out.stat().st_size / 1e6:.2f} MB) to {out}")


if __name__ == "__main__":
    main()
