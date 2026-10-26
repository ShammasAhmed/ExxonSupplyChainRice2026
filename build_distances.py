"""Precompute routed miles for every truck, rail and barge lane in the network.

    python build_distances.py                  # all modes
    python build_distances.py --modes barge    # rebuild one mode; other rows are kept

Writes config.LANE_DISTANCES_FILE, which routing.py reads. Rerun after adding
sites or Modes rows: lanes missing from the file fall back to great-circle x
circuity. Only this script needs scgraph and internet access; model runs just
read the CSV.

Networks:
    truck  scgraph "world_highways" (OpenStreetMap; covers Canada)
    rail   scgraph "north_america_rail" (Class 1 lines, USDOT)
    barge  USACE National Waterway Network (USDOT NTAD), routed on its
           published link lengths, also counting miles against the current

Each site joins its nearest network node by a straight leg x the mode's
circuity (config.MODE_PARAMS). `off_network_miles` reports those legs, so a
site far from any rail line or waterway stands out. Rows whose source is
"manual" are hand-entered overrides and are never replaced.
"""

from __future__ import annotations

import argparse
import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
from scgraph import GeoGraph

import config
from loader import load_nodes, load_site_modes
from network import transport_lanes
from node import LaneKey, Mode, Node
from routing import great_circle_miles, haversine_miles

logger = logging.getLogger("build_distances")

SCGRAPH_NETWORKS = {Mode.TRUCK: "world_highways", Mode.RAIL: "north_america_rail"}

NWN_URL = ("https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/"
           "Waterway_Networks/FeatureServer")
NWN_NODES_LAYER, NWN_LINKS_LAYER = 0, 1
NWN_CACHE = Path(".cache/nwn.json")

# Rivers whose current makes upstream tows slower and costlier. River miles
# increase upstream on all of these, so a link run toward higher river miles
# is upstream. Tidal channels, the Gulf Intracoastal Waterway and canals are
# treated as slack water.
CURRENT_RIVERS = {"MISSISSIPPI RIVER", "ILLINOIS RIVER", "OHIO RIVER", "MISSOURI RIVER",
                  "TENNESSEE RIVER", "CUMBERLAND RIVER", "ARKANSAS RIVER"}

# Connector legs longer than this get a warning: the site may not really be
# served by that network (e.g. no rail spur nearby).
WARN_OFF_NETWORK_MILES = 25.0

COLUMNS = ["origin", "destination", "mode", "miles", "upstream_miles",
           "off_network_miles", "great_circle_miles", "source"]


def _point(n: Node) -> dict[str, float]:
    return {"latitude": n.lat, "longitude": n.lon}


def _off_network_miles(a: Node, b: Node, path: list[list[float]]) -> float:
    """Straight-line legs from each site to the first / last network node of the path."""
    if len(path) < 3:
        return great_circle_miles(a, b)
    return haversine_miles(a.lat, a.lon, *path[1]) + haversine_miles(*path[-2], b.lat, b.lon)


def route_scgraph(network: str, lanes: list[LaneKey], sites: dict[str, Node]) -> list[dict]:
    graph = GeoGraph.load_geograph(network)
    rows = []
    for a, b, mode in lanes:
        try:
            r = graph.get_shortest_path(_point(sites[a]), _point(sites[b]), output_units="mi",
                                        node_addition_circuity=config.MODE_PARAMS[mode.value]["circuity"])
        except Exception as exc:   # scgraph raises plain Exceptions for unreachable points
            logger.warning("No %s route %r -> %r (%s); lane will use great-circle miles.",
                           network, a, b, exc)
            continue
        rows.append(dict(origin=a, destination=b, mode=mode.value, miles=r["length"], upstream_miles=0.0,
                         off_network_miles=_off_network_miles(sites[a], sites[b], r["coordinate_path"]),
                         source=f"scgraph:{network}"))
    return rows


def _query_layer(layer: int, out_fields: str, geometry: bool) -> list[dict]:
    """Every feature of one NWN layer as GeoJSON, paged (the service returns at most 2000 per call)."""
    features, offset, page = [], 0, 2000
    while True:
        query = urllib.parse.urlencode(dict(
            where="1=1", outFields=out_fields, returnGeometry=str(geometry).lower(), outSR=4326,
            resultOffset=offset, resultRecordCount=page, f="geojson"))
        with urllib.request.urlopen(f"{NWN_URL}/{layer}/query?{query}", timeout=120) as resp:
            batch = json.load(resp)["features"]
        features += batch
        if len(batch) < page:
            return features
        offset += page


def fetch_nwn(refresh: bool = False) -> dict[str, list[dict]]:
    """National Waterway Network nodes (points) and links (attributes only), cached in NWN_CACHE.

    Link geometries are not used: they are not consistently digitized from
    ANODE to BNODE, so node locations come from the nodes layer instead.
    """
    if NWN_CACHE.exists() and not refresh:
        return json.loads(NWN_CACHE.read_text())
    nwn = {"nodes": _query_layer(NWN_NODES_LAYER, "NODENUM", geometry=True),
           "links": _query_layer(NWN_LINKS_LAYER, "ANODE,BNODE,LENGTH,RIVERNAME,AMILE,BMILE", geometry=False)}
    NWN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    NWN_CACHE.write_text(json.dumps(nwn))
    logger.info("Downloaded %d waterway nodes and %d links to %s",
                len(nwn["nodes"]), len(nwn["links"]), NWN_CACHE)
    return nwn


def build_nwn_graph(nwn: dict[str, list[dict]]) -> tuple[GeoGraph, dict[tuple[int, int], tuple[str, float, float]]]:
    """GeoGraph over waterway nodes weighted by published link miles.

    Also returns, per directed node pair, (river name, river mile at start,
    river mile at end) for counting upstream miles.
    """
    index: dict[int, int] = {}
    coords: list[list[float]] = []
    for f in nwn["nodes"]:
        if f["geometry"]:
            lon, lat = f["geometry"]["coordinates"][:2]
            index[f["properties"]["NODENUM"]] = len(coords)
            coords.append([lat, lon])

    edges: dict[tuple[int, int], tuple[float, str, float, float]] = {}
    skipped = 0
    for f in nwn["links"]:
        p = f["properties"]
        u, v = index.get(p["ANODE"]), index.get(p["BNODE"])
        if u is None or v is None or u == v:
            skipped += 1
            continue
        miles = p["LENGTH"] or haversine_miles(*coords[u], *coords[v])
        river = (p["RIVERNAME"] or "").strip().upper()
        amile, bmile = p["AMILE"] or 0.0, p["BMILE"] or 0.0
        for key, attrs in (((u, v), (miles, river, amile, bmile)), ((v, u), (miles, river, bmile, amile))):
            if key not in edges or miles < edges[key][0]:
                edges[key] = attrs
    if skipped:
        logger.info("Skipped %d waterway links with a missing or repeated end node.", skipped)

    graph: list[dict[int, float]] = [{} for _ in coords]
    for (u, v), (miles, *_) in edges.items():
        graph[u][v] = miles
    rivers = {k: (river, start, end) for k, (_, river, start, end) in edges.items()}
    return GeoGraph(graph=graph, nodes=coords, geograph_units="mi"), rivers


def route_barge(lanes: list[LaneKey], sites: dict[str, Node], refresh: bool) -> list[dict]:
    graph, rivers = build_nwn_graph(fetch_nwn(refresh))
    circuity = config.MODE_PARAMS[Mode.BARGE.value]["circuity"]
    rows = []
    for a, b, mode in lanes:
        try:
            r = graph.get_shortest_path(_point(sites[a]), _point(sites[b]), output_units="mi",
                                        node_addition_circuity=circuity, output_path=True)
        except Exception as exc:
            logger.warning("No waterway route %r -> %r (%s); lane will use great-circle miles.", a, b, exc)
            continue
        ids = r["path"]   # network node ids, without the site connectors
        upstream = 0.0
        for u, v in zip(ids, ids[1:]):
            river, start, end = rivers[(u, v)]
            if river in CURRENT_RIVERS and end > start:
                upstream += graph.graph[u][v]
        rows.append(dict(origin=a, destination=b, mode=mode.value, miles=r["length"], upstream_miles=upstream,
                         off_network_miles=_off_network_miles(sites[a], sites[b], r["coordinate_path"]),
                         source="usace_nwn"))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--modes", nargs="+", choices=[m.value for m in (*SCGRAPH_NETWORKS, Mode.BARGE)],
                    default=[m.value for m in (*SCGRAPH_NETWORKS, Mode.BARGE)])
    ap.add_argument("--out", default=config.LANE_DISTANCES_FILE)
    ap.add_argument("--refresh", action="store_true", help="re-download the waterway network")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    sites = {n.name: n for n in load_nodes(config.WORKBOOK)}
    modes = [(sm.site, sm.mode.value) for sm in load_site_modes(config.MODES_FILE) if sm.site in sites]
    lanes = list(transport_lanes(sites, modes))
    rebuild = {Mode(m) for m in args.modes}

    out = Path(args.out)
    kept = pd.read_csv(out) if out.exists() else pd.DataFrame(columns=COLUMNS)
    manual = set(zip(kept.loc[kept["source"] == "manual", "origin"],
                     kept.loc[kept["source"] == "manual", "destination"],
                     kept.loc[kept["source"] == "manual", "mode"].map(Mode)))
    kept = kept[(kept["source"] == "manual") | ~kept["mode"].isin([m.value for m in rebuild])]

    rows = []
    for mode in rebuild:
        todo = [lane for lane in lanes if lane[2] is mode and lane not in manual]
        logger.info("Routing %d %s lanes", len(todo), mode.value)
        if not todo:
            continue
        if mode is Mode.BARGE:
            rows += route_barge(todo, sites, args.refresh)
        else:
            rows += route_scgraph(SCGRAPH_NETWORKS[mode], todo, sites)

    for r in rows:
        r["great_circle_miles"] = great_circle_miles(sites[r["origin"]], sites[r["destination"]])
        if r["off_network_miles"] > WARN_OFF_NETWORK_MILES:
            logger.warning("%s -> %s [%s]: %.0f of %.0f miles are off the network.",
                           r["origin"], r["destination"], r["mode"], r["off_network_miles"], r["miles"])

    df = pd.concat([kept, pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True)
    numeric = ["miles", "upstream_miles", "off_network_miles", "great_circle_miles"]
    df[numeric] = df[numeric].astype(float).round(1)
    df = df.sort_values(["mode", "origin", "destination"])
    df.to_csv(out, index=False)
    print(f"Wrote {len(df)} lanes to {out} ({len(rows)} routed now, {len(df) - len(rows)} kept).")


if __name__ == "__main__":
    main()
