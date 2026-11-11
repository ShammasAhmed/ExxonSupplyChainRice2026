import heapq
import time
from pathlib import Path
import pandas as pd

import folium
import geopandas as gpd
import networkx as nx
import requests
import shapely
from pyproj import Geod
from shapely import STRtree
from shapely.geometry import Point
from shapely.ops import substring, unary_union

# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROJECT_FOLDER = Path(__file__).resolve().parent
DATA_FILE = PROJECT_FOLDER / "CN_Network.gpkg"
MAP_FILE = PROJECT_FOLDER / "CN_Network.html"

BASE_URL = (
    "https://services.arcgis.com/xOi1kZaI0eWDREZv/ArcGIS/rest/services/"
    "NTAD_North_American_Rail_Network_Lines_CN/FeatureServer/0"
)

# Set with:  export CARTO_API_KEY=...   (Windows: setx CARTO_API_KEY ...)
CARTO_API_KEY = "cb1_4ucd_1_afe46a94d28c9a77ce4e06cc"

GEOD = Geod(ellps="WGS84")

ATTR_FIELDS = ("arcid", "subdiv", "division", "branch", "yard",
               "state", "tracks", "owner", "rights")

def glen(line):
    """Geodesic length of a lon/lat geometry, in meters."""
    return GEOD.geometry_length(line)


def key(pt):
    """Node key: coordinates rounded to ~1 m so touching endpoints merge."""
    return (round(pt[0], 5), round(pt[1], 5))


# --------------------------------------------------
# Data loading
# --------------------------------------------------

def download_network():
    """Download the CN network from ArcGIS in batches."""
    print("Local CN network file not found.")
    print("Downloading railway network from ArcGIS...")

    response = requests.get(
        f"{BASE_URL}/query",
        params={"where": "1=1", "returnIdsOnly": "true", "f": "json"},
    )
    response.raise_for_status()
    object_ids = response.json()["objectIds"]
    print(f"Found {len(object_ids)} railway segments.")

    features = []
    batch_size = 500
    for i in range(0, len(object_ids), batch_size):
        batch = object_ids[i:i + batch_size]
        response = requests.post(
            f"{BASE_URL}/query",
            data={
                "objectIds": ",".join(map(str, batch)),
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
            },
        )
        response.raise_for_status()
        result = response.json()

        if "error" in result:
            raise RuntimeError(result["error"])
        if "features" not in result:
            raise RuntimeError(f"Unexpected response: {result}")

        features.extend(result["features"])
        print(f"Downloaded {len(features)} / {len(object_ids)} railway segments")
        time.sleep(0.2)

    if len(features) != len(object_ids):
        raise RuntimeError("Some railway segments were not downloaded.")

    cn = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")

    print("Saving CN network to local storage...")
    cn.to_file(DATA_FILE, driver="GPKG", layer="CN_Network")
    print(f"CN network saved to: {DATA_FILE}")
    return cn


def load_network():
    """Load the CN network from disk, or download and cache it."""
    if DATA_FILE.exists():
        print("Loading CN railway network from local storage...")
        cn = gpd.read_file(DATA_FILE, layer="CN_Network")
        print("CN network successfully loaded from disk!")
        return cn
    return download_network()


# --------------------------------------------------
# Graph construction
# --------------------------------------------------

def build_graph(cn):
    """Graph on the FRA's own node IDs; each edge keeps its track attributes."""
    G = nx.Graph()
    xy, mismatched = {}, 0

    for r in cn.itertuples(index=False):
        geom = r.geometry
        if geom is None or geom.is_empty or r.FRFRANODE == r.TOFRANODE:
            continue
        line = shapely.line_merge(geom) if geom.geom_type == "MultiLineString" else geom
        u, v = r.FRFRANODE, r.TOFRANODE

        if line.geom_type == "LineString":
            a, b = key(line.coords[0]), key(line.coords[-1])
            for node, pt in ((u, a), (v, b)):
                if xy.setdefault(node, pt) != pt:
                    mismatched += 1   # geometry not digitized FRFRANODE -> TOFRANODE

        L = glen(line)
        if G.has_edge(u, v) and G[u][v]["length"] <= L:
            continue   # parallel arcs: keep the shorter one

        rights = [getattr(r, f"TRKRGHTS{i}") for i in range(1, 10)]
        G.add_edge(
            u, v, length=L, geom=line,
            arcid=r.FRAARCID, subdiv=r.SUBDIV, division=r.DIVISION,
            branch=r.BRANCH, yard=r.YARDNAME, state=r.STATEAB,
            tracks=r.TRACKS, owner=r.RROWNER1,
            rights="/".join(x for x in rights if isinstance(x, str) and x),
        )

    G.graph["xy"] = xy
    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, "
          f"{nx.number_connected_components(G)} components "
          f"({mismatched} endpoint/node-coordinate mismatches)")
    return G

def insert_point(G, lon, lat, name, max_dist_km=10):
    """Snap (lon, lat) onto the nearest arc, splitting it; pieces keep the arc's attributes."""
    p = Point(lon, lat)
    edges = list(G.edges(data=True))
    tree = STRtree([d["geom"] for _, _, d in edges])
    u, v, d = edges[tree.nearest(p)]
    line = d["geom"]

    q = line.interpolate(line.project(p))
    off_km = GEOD.inv(lon, lat, q.x, q.y)[2] / 1000
    if off_km > max_dist_km:
        raise ValueError(f"{name} is {off_km:.1f} km from the nearest track")
    print(f"  {name}: snapped {off_km:.2f} km to arc {d['arcid']} ({d['subdiv']})")

    xy = G.graph["xy"]
    if line.geom_type != "LineString":          # unmergeable multi-part arc: use closer node
        return u if Point(xy[u]).distance(p) <= Point(xy[v]).distance(p) else v

    # orient the line so it runs u -> v
    if key(line.coords[0]) == xy.get(v) and key(line.coords[0]) != xy.get(u):
        line = shapely.reverse(line)

    pos, eps = line.project(p), 1e-9
    if pos <= eps:
        return u
    if pos >= line.length - eps:
        return v

    g1, g2 = substring(line, 0, pos), substring(line, pos, line.length)
    G.remove_edge(u, v)
    G.add_edge(u, name, **{**d, "length": glen(g1), "geom": g1})
    G.add_edge(name, v, **{**d, "length": glen(g2), "geom": g2})
    return name

# --------------------------------------------------
# Shortest path
# --------------------------------------------------

def dijkstra(G, s, t):
    """Dijkstra's algorithm with a binary heap. Returns (length_m, path)."""
    dist, prev, done = {s: 0.0}, {}, set()
    pq = [(0.0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if u in done:
            continue
        done.add(u)
        if u == t:
            break
        for v, data in G[u].items():
            nd = d + data["length"]
            if nd < dist.get(v, float("inf")):
                dist[v], prev[v] = nd, u
                heapq.heappush(pq, (nd, v))

    path = [t]
    while path[-1] != s:
        path.append(prev[path[-1]])
    return dist[t], path[::-1]

def route_tables(H, path):
    """Arc-level table and per-subdivision summary for a node path."""
    rows = []
    for u, v in zip(path[:-1], path[1:]):
        d = H[u][v]
        rows.append({"from_node": u, "to_node": v, "length_m": d["length"],
                     **{k: d[k] for k in ATTR_FIELDS}})
    arcs = pd.DataFrame(rows)
    arcs["subdiv"] = arcs["subdiv"].fillna("(unnamed)")
    arcs["block"] = arcs["subdiv"].ne(arcs["subdiv"].shift()).cumsum()

    uniq = lambda s: "/".join(dict.fromkeys(str(x) for x in s if pd.notna(x) and x != ""))
    summary = arcs.groupby("block", sort=False).agg(
        subdivision=("subdiv", "first"),
        division=("division", "first"),
        states=("state", uniq),
        from_node=("from_node", "first"),
        to_node=("to_node", "last"),
        miles=("length_m", lambda x: x.sum() / 1609.344),
        arcs=("arcid", "count"),
        min_tracks=("tracks", "min"),
        owners=("owner", uniq),
        trackage_rights=("rights", uniq),
        yards=("yard", uniq),
    ).reset_index(drop=True)
    return arcs, summary

def find_route(G, origin, destination):
    """Returns (length_m, route GeoDataFrame, arcs table, summary table) or None."""
    o_lon, o_lat, o_name = origin
    d_lon, d_lat, d_name = destination
    print(f"\nRoute: {o_name} -> {d_name}")

    H = G.copy()
    s = insert_point(H, o_lon, o_lat, f"ORIGIN:{o_name}")
    t = insert_point(H, d_lon, d_lat, f"DEST:{d_name}")

    if not nx.has_path(H, s, t):
        print(f"  No path between {o_name} and {d_name}.")
        return None

    my_len, my_path = dijkstra(H, s, t)
    nx_len = nx.shortest_path_length(H, s, t, weight="length")
    assert abs(my_len - nx_len) < 1e-6, "Implementations disagree!"
    print(f"  Shortest path: {my_len / 1000:.1f} km ({my_len / 1609.344:.1f} mi), "
          f"matches networkx length")

    gc = GEOD.inv(o_lon, o_lat, d_lon, d_lat)[2]
    print(f"  Circuity (rail / straight-line): {my_len / gc:.2f}")

    arcs, summary = route_tables(H, my_path)
    geoms = [H[u][v]["geom"] for u, v in zip(my_path[:-1], my_path[1:])]
    route = gpd.GeoDataFrame(arcs.drop(columns=["block"]), geometry=geoms, crs=4326)

    print("\n" + summary.to_string(float_format=lambda x: f"{x:.1f}"))
    print("\n  Owners on path:", arcs["owner"].value_counts(dropna=False).to_dict())
    return my_len, route, arcs, summary

# --------------------------------------------------
# Mapping
# --------------------------------------------------

def create_base_map(cn):
    """Folium map with the full CN network drawn in gray."""
    m = folium.Map(location=[43, -90], zoom_start=4, tiles=None, control_scale=True)

    tile_url = "https://basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}.png"
    if CARTO_API_KEY:
        tile_url += f"?key={CARTO_API_KEY}"

    folium.TileLayer(
        tiles=tile_url,
        attr=(
            '&copy; <a href="https://www.openstreetmap.org/copyright">'
            'OpenStreetMap</a> contributors &copy; '
            '<a href="https://carto.com/attributions">CARTO</a>'
        ),
        name="CARTO Positron",
    ).add_to(m)

    folium.GeoJson(
        cn,
        name="Entire CN Railway Network",
        style_function=lambda f: {"color": "#777777", "weight": 1.5, "opacity": 0.6},
        popup=folium.GeoJsonPopup(
            fields=["OBJECTID", "FRAARCID", "SUBDIV"],
            aliases=["Object ID:", "Arc ID:", "Subdivision:"],
        ),
    ).add_to(m)

    return m


def add_route_to_map(m, route, length_m, origin, destination, color):
    o_lon, o_lat, o_name = origin
    d_lon, d_lat, d_name = destination
    group = folium.FeatureGroup(name=f"{o_name} to {d_name} ({length_m / 1609.344:.0f} mi)")

    folium.GeoJson(
        route[["arcid", "subdiv", "division", "owner", "tracks", "geometry"]],
        style_function=lambda f, c=color: {"color": c, "weight": 4, "opacity": 0.95},
        tooltip=folium.GeoJsonTooltip(
            fields=["subdiv", "division", "owner", "tracks", "arcid"],
            aliases=["Subdivision:", "Division:", "Owner:", "Tracks:", "Arc ID:"]),
    ).add_to(group)

    for lon, lat, name in (origin, destination):
        folium.CircleMarker([lat, lon], radius=7, color="black", weight=2,
                            fill=True, fill_color=color, fill_opacity=1,
                            tooltip=name).add_to(group)
    group.add_to(m)

# --------------------------------------------------
# Main
# --------------------------------------------------

def main(*arcs):
    """
    Each arc is a tuple (O, D, C):
        O = (lon, lat, name)  origin
        D = (lon, lat, name)  destination
        C = hex color string, e.g. "#d62728"
    All arcs are drawn on one map saved to CN_Network.html.
    """
    cn = load_network()
    G = build_graph(cn)
    m = create_base_map(cn)

    bounds = []
    for origin, destination, color in arcs:
        result = find_route(G, origin, destination)
        if result is None:
            continue
        length_m, route, arc_table, summary = result
        add_route_to_map(m, route, length_m, origin, destination, color)
        bounds.append(route.total_bounds)

        tag = f"{origin[2]}_to_{destination[2]}".replace(" ", "_")
        arc_table.to_csv(PROJECT_FOLDER / f"route_{tag}_arcs.csv", index=False)
        summary.to_csv(PROJECT_FOLDER / f"route_{tag}_summary.csv", index=False)
        route.to_file(PROJECT_FOLDER / f"route_{tag}.geojson", driver="GeoJSON")

    if bounds:
        minx = min(b[0] for b in bounds)
        miny = min(b[1] for b in bounds)
        maxx = max(b[2] for b in bounds)
        maxy = max(b[3] for b in bounds)
    else:
        minx, miny, maxx, maxy = cn.total_bounds
    m.fit_bounds([[miny, minx], [maxy, maxx]])

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(str(MAP_FILE))
    print(f"\nMap saved to: {MAP_FILE}")


if __name__ == "__main__":
    BR = (-91.147385, 30.471165, "Baton Rouge")
    LM = (-88.1506, 41.5206, "Lemont")
    SN = (-82.4066, 42.9745, "Sarnia")
    EM = (-113.494, 53.5461, "Edmonton")

    main(
        (BR, LM, "#d62728"),
        (LM, SN, "#1f77b4"),
        (LM, EM, "#ff7f0e"),
    )