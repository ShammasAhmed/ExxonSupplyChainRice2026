"""Simple US map of supply chain nodes using Folium (Leaflet.js).

    pip install folium

Folium produces an interactive HTML map (OpenStreetMap/CARTO tiles, zoom/pan).
Static PNG export is optional and needs selenium + a browser driver:

    pip install selenium

Flows follow their actual route (rail track, highways, waterways, sea lanes)
on the same scgraph / USACE networks build_distances.py prices them on, over
a gray backdrop of the North American Class 1 rail network (the look of
CN_Tests/CN_path_visualizer.py, for every railroad and mode). Without scgraph
the map falls back to straight lines.
"""

from __future__ import annotations

import math
import os
import webbrowser
from functools import cache
from pathlib import Path
from typing import Iterable

import folium

import config
from node import Mode, Node, NodeCategory
from routing import haversine_miles

# CARTO basemaps need a free key (https://carto.com/basemaps/apikey/). Set it
# in your shell, e.g. `export CARTO_API_KEY=...` in ~/.zshrc; never commit it.
# Without a key the maps use plain OpenStreetMap tiles instead.
CARTO_API_KEY = os.environ.get("CARTO_API_KEY", "").strip()

# (hex color, SVG dash pattern or None). Rail, barge and ocean take the three
# hues that stay distinguishable for color-blind readers when any two routes
# cross; truck and pipeline add a dash pattern so they never rely on hue alone.
_MODE_STYLE = {
    Mode.RAIL: ("#eb6834", None),
    Mode.BARGE: ("#2a78d6", None),
    Mode.OCEAN: ("#1baf7a", None),
    Mode.TRUCK: ("#6250d6", "7 5"),
    Mode.PIPELINE: ("#e87ba4", "1 6"),
}
_RAIL_BACKDROP_COLOR = "#8a8a86"
_FLOW_WEIGHT = (2.5, 7.0)   # px line width for the smallest / largest flow


def _pos(n: Node) -> tuple[float, float]:
    """(lat, lon) for drawing. Eastern-hemisphere sites (China) are shifted by
    -360 degrees so they sit west of North America and trans-Pacific lines
    cross the Pacific, not the Atlantic."""
    return (n.lat, n.lon - 360.0 if n.lon > 0 else n.lon)


# ---- route geometry --------------------------------------------------------

@cache
def _network(mode: Mode):
    """The scgraph GeoGraph build_distances.py routes this mode on, or None
    (pipeline, scgraph not installed, or no cached waterway network)."""
    try:
        import build_distances as bd
    except ImportError:
        return None
    if mode is Mode.BARGE:
        if not config.NWN_CACHE_FILE.exists():   # don't download while drawing a map
            return None
        return bd.build_nwn_graph(bd.fetch_nwn())[0]
    name = bd.SCGRAPH_NETWORKS.get(mode)
    return bd.GeoGraph.load_geograph(name) if name else None


@cache
def _routed_points(a_lat: float, a_lon: float, b_lat: float, b_lon: float,
                   mode: Mode) -> tuple[tuple[float, float], ...] | None:
    graph = _network(mode)
    if graph is None:
        return None
    try:
        r = graph.get_shortest_path(
            {"latitude": a_lat, "longitude": a_lon}, {"latitude": b_lat, "longitude": b_lon},
            node_addition_circuity=config.MODE_PARAMS[mode.value]["circuity"])
    except Exception:   # scgraph raises plain Exceptions for unreachable points
        return None
    return tuple((round(lat, 4), round(lon, 4)) for lat, lon in r["coordinate_path"])


def _route_path(a: Node, b: Node, mode: Mode) -> list[tuple[float, float]]:
    """(lat, lon) points along the lane's route, or a straight line if it has none.

    Longitudes are unwrapped so the path starts at _pos(a) and never jumps
    360 degrees (trans-Pacific sea lanes cross the antimeridian)."""
    pts = _routed_points(a.lat, a.lon, b.lat, b.lon, Mode(mode)) or ((a.lat, a.lon), (b.lat, b.lon))
    out, prev = [], _pos(a)[1]
    for lat, lon in pts:
        lon += 360.0 * round((prev - lon) / 360.0)
        out.append((lat, lon))
        prev = lon
    return out


def _path_midpoint(path: list[tuple[float, float]]) -> tuple[float, float]:
    """The point halfway along a path, by distance."""
    legs = [haversine_miles(*p, *q) for p, q in zip(path, path[1:])]
    half = sum(legs) / 2
    for (p, q), leg in zip(zip(path, path[1:]), legs):
        if leg >= half and leg > 0:
            t = half / leg
            return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
        half -= leg
    return path[len(path) // 2]


@cache
def _rail_backdrop() -> list[list[tuple[float, float]]]:
    """The Class 1 rail network as polylines, chaining through pass-through
    nodes so the map holds a few thousand lines instead of every edge."""
    graph = _network(Mode.RAIL)
    if graph is None:
        return []
    adj: list[set[int]] = [set() for _ in graph.nodes]
    for u, nbrs in enumerate(graph.graph):
        for v in nbrs:
            if u != v:
                adj[u].add(v)
                adj[v].add(u)
    seen: set[tuple[int, int]] = set()

    def walk(u: int, v: int) -> list[int]:
        chain = [u, v]
        seen.update({(u, v), (v, u)})
        while len(adj[v]) == 2:
            w = next(x for x in adj[v] if x != chain[-2])
            if (v, w) in seen:
                break
            seen.update({(v, w), (w, v)})
            chain.append(w)
            v = w
        return chain

    chains = []
    for start in sorted(range(len(adj)), key=lambda n: len(adj[n]) == 2):   # junctions first, then loops
        for v in adj[start]:
            if (start, v) not in seen:
                chains.append(walk(start, v))
    return [[(round(graph.nodes[n][0], 3), round(graph.nodes[n][1], 3)) for n in c] for c in chains]

_STYLE = {
    NodeCategory.SOURCE: dict(color="#1a9641", symbol="triangle", label="Source"),
    NodeCategory.SINK: dict(color="#d7191c", symbol="circle", label="Sink"),
    NodeCategory.INTERMEDIATE: dict(color="#2c7bb6", symbol="square", label="Intermediate"),
}


def _symbol_html(symbol: str, color: str) -> tuple[str, tuple[int, int]]:
    """Return (html, (width, height)) for a CSS-drawn marker symbol."""
    if symbol == "triangle":
        return (
            f'<div style="width:0;height:0;border-left:7px solid transparent;'
            f'border-right:7px solid transparent;border-bottom:13px solid {color};"></div>',
            (14, 13),
        )
    if symbol == "square":
        return (
            f'<div style="width:11px;height:11px;background:{color};'
            f'border:1px solid white;"></div>',
            (13, 13),
        )
    return (  # circle
        f'<div style="width:11px;height:11px;background:{color};'
        f'border:1px solid white;border-radius:50%;"></div>',
        (13, 13),
    )


def _legend_html(entries: list[tuple[str, str, str]], title: str) -> str:
    """entries: (kind, color, label) with kind in {"symbol:<shape>", "line", "line:<dash>"}."""
    rows = []
    for kind, color, label in entries:
        if kind.startswith("line"):
            dash = kind.partition(":")[2]
            width = 1.5 if color == _RAIL_BACKDROP_COLOR else 3
            swatch = (f'<svg width="22" height="8" style="vertical-align:middle;">'
                      f'<line x1="2" y1="4" x2="20" y2="4" stroke="{color}" stroke-width="{width}" '
                      f'stroke-linecap="round"{f" stroke-dasharray={chr(34)}{dash}{chr(34)}" if dash else ""}/>'
                      f'</svg>')
        else:
            html, _ = _symbol_html(kind.split(":")[1], color)
            swatch = f'<span style="display:inline-block;width:18px;text-align:center;">{html}</span>'
        rows.append(f'<div style="margin:3px 0;">{swatch} &nbsp;{label}</div>')
    return (
        '<div style="position:fixed;top:12px;right:12px;z-index:9999;'
        'background:rgba(255,255,255,0.9);padding:8px 12px;border-radius:6px;'
        'box-shadow:0 1px 4px rgba(0,0,0,0.3);font:12px sans-serif;">'
        f'<b>{title}</b>' + "".join(rows) + "</div>"
    )


def _cost_box_html(breakdown: dict[str, float], total_flow: float) -> str:
    """Bottom-left box: each cost component in $/yr and $ per delivered DST."""
    rows = [(k.capitalize(), v) for k, v in breakdown.items()] + [("Total", sum(breakdown.values()))]
    cells = "".join(
        f'<tr style="{"font-weight:bold;border-top:1px solid #999;" if label == "Total" else ""}">'
        f'<td style="padding:1px 8px 1px 0;">{label}</td>'
        f'<td style="text-align:right;padding:1px 8px;">${v / 1e6:,.2f}M</td>'
        f'<td style="text-align:right;padding:1px 0 1px 8px;">${v / total_flow:,.2f}</td></tr>'
        for label, v in rows)
    return ('<div style="position:fixed;bottom:44px;left:12px;z-index:9999;'
            'background:rgba(255,255,255,0.9);padding:8px 12px;border-radius:6px;'
            'box-shadow:0 1px 4px rgba(0,0,0,0.3);font:12px sans-serif;">'
            '<b>Cost breakdown</b><table style="border-collapse:collapse;margin-top:3px;">'
            '<tr style="color:#555;"><td></td><td style="text-align:right;padding:0 8px;">per yr</td>'
            '<td style="text-align:right;padding-left:8px;">per DST</td></tr>'
            f'{cells}</table></div>')


def _site_tooltip(n: Node, label: str, landed: dict[str, tuple[float, float]] | None) -> str:
    lines = [f"<b>{n.name}</b>", f"{n.city}, {n.state}"]
    if n.is_source:
        cap = "uncapped" if n.supply_cap is None else f"cap {n.supply_cap:,.0f}"
        lines += [f"Today's volume to XOM: {n.base:,.0f} DST/yr ({cap})",
                  f"Price: ${n.price:,.2f}/DST ex freight"]
    elif n.is_sink:
        lines.append(f"Demand (base): {n.base:,.0f} DST/yr")
        if landed and n.name in landed:
            product, logistics = landed[n.name]
            lines.append(f"Landed: ${product + logistics:,.2f}/DST "
                         f"(product ${product:,.2f} + logistics ${logistics:,.2f})")
    elif n.terminal_fee:
        lines.append(f"Terminal fee: ${n.terminal_fee:,.2f}/DST")
    return "<br>".join(lines + [f"<i>{label}</i>"])


def plot_nodes(
    nodes: Iterable[Node],
    *,
    show_names: bool = False,
    show_intermediate: bool = True,
    flows: dict[tuple[str, str, Mode], float] | None = None,
    lane_costs: dict[tuple[str, str, Mode], float] | None = None,
    landed: dict[str, tuple[float, float]] | None = None,
    cost_breakdown: dict[str, float] | None = None,
    total_flow: float = 0.0,
    routes: bool = True,
    rail_network: bool = True,
    title: str | None = None,
    save_path: str | Path | None = None,
    show: bool = False,
) -> folium.Map:
    """Plot sources (green triangles), sinks (red circles) and intermediate hubs
    (blue squares) on a Folium map.

    Hovering a point shows its name, location and base value; set show_names
    to also print names on the map (cluttered where nodes are close).

    save_path: ".html" -> interactive page (no extra install);
               ".png"  -> static image (needs selenium + browser driver).
    show:      open the interactive map in your browser.
    flows:     optional {(source_name, sink_name, mode): volume}. Each is drawn
               along its routed path, colored by mode, with width growing
               with volume and a small volume label halfway along.
    routes:    draw flows along their rail / road / waterway / sea-lane route
               (False: straight lines).
    rail_network: draw the Class 1 rail network in gray underneath.
    lane_costs: optional {(origin, destination, mode): line haul $/DST}, shown
               when hovering a flow.
    landed:    optional {sink: ($/DST product, $/DST logistics)}, shown when
               hovering a sink (model.Solution.landed).
    cost_breakdown, total_flow: optional {component: $/yr} and delivered
               DST/yr, drawn as a box in the bottom-left corner.
    """
    nodes = list(nodes)
    categories = [NodeCategory.SOURCE, NodeCategory.SINK]
    if show_intermediate:
        categories.append(NodeCategory.INTERMEDIATE)

    m = folium.Map(location=[39.5, -98.35], zoom_start=4,
                   tiles=None, control_scale=True, prefer_canvas=True)
    if CARTO_API_KEY:
        folium.TileLayer(
            tiles=(f"https://basemaps.cartocdn.com/rastertiles/light_all/"
                   f"{{z}}/{{x}}/{{y}}.png?key={CARTO_API_KEY}"),
            attr=('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
                  'contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'),
            name="CARTO Positron",
        ).add_to(m)
    else:
        folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    legend_entries: list[tuple[str, str, str]] = []
    flow_paths: list[list[tuple[float, float]]] = []

    # ---- rail network backdrop --------------------------------------------
    if rail_network and (rail_lines := _rail_backdrop()):
        folium.PolyLine(rail_lines, color=_RAIL_BACKDROP_COLOR, weight=1, opacity=0.45,
                        interactive=False).add_to(
            folium.FeatureGroup(name="Class 1 rail network (USDOT)").add_to(m))
        legend_entries.append(("line", _RAIL_BACKDROP_COLOR, "Rail network"))

    # ---- flows -----------------------------------------------------------
    if flows:
        by_name = {n.name: n for n in nodes}
        mode_groups: dict[Mode, folium.FeatureGroup] = {}
        label_group = folium.FeatureGroup(name="Flow labels (DST/yr)", show=True)
        per_pair: dict[tuple[str, str], int] = {}
        top = max(flows.values()) or 1.0

        # Largest flows first, so smaller ones are drawn on top and stay hoverable.
        for (src, snk, mode), vol in sorted(flows.items(), key=lambda kv: -kv[1]):
            a, b = by_name[src], by_name[snk]
            color, dash = _MODE_STYLE[mode]
            path = _route_path(a, b, mode) if routes else [_pos(a), _pos(b)]
            flow_paths.append(path)
            lo, hi = _FLOW_WEIGHT
            weight = lo + (hi - lo) * math.sqrt(max(vol, 0) / top)

            if mode not in mode_groups:
                mode_groups[mode] = folium.FeatureGroup(name=mode.value.capitalize())
                legend_entries.append((f"line:{dash}" if dash else "line", color,
                                       mode.value.capitalize()))
            tooltip = (f"{src} → {snk}<br>{vol:,.0f} DST/yr ({mode.value})"
                       + (f"<br>Freight ${lane_costs[(src, snk, mode)]:,.2f}/DST"
                          if lane_costs and (src, snk, mode) in lane_costs else ""))
            # White casing under each route so it reads over the gray rail backdrop.
            folium.PolyLine(path, color="white", weight=weight + 3, opacity=0.9,
                            interactive=False).add_to(mode_groups[mode])
            folium.PolyLine(path, color=color, weight=weight, opacity=0.95, dash_array=dash,
                            tooltip=tooltip).add_to(mode_groups[mode])

            # Stagger labels when one pair is served by several modes.
            k = per_pair[(src, snk)] = per_pair.get((src, snk), -1) + 1
            mid_lat, mid_lon = _path_midpoint(path)
            folium.Marker(
                (mid_lat + 0.4 * k, mid_lon),
                icon=folium.DivIcon(
                    icon_size=(0, 0),
                    icon_anchor=(0, 0),
                    html=(
                        '<div style="font:8px sans-serif;color:#333;white-space:nowrap;'
                        'transform:translate(-50%,-50%);'
                        'text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,'
                        '-1px 1px 0 #fff,1px 1px 0 #fff;">'
                        f"{vol:,.0f} ({mode.value})</div>"
                    ),
                ),
            ).add_to(label_group)

        for g in mode_groups.values():
            g.add_to(m)
        label_group.add_to(m)

    # ---- nodes -----------------------------------------------------------
    for cat in categories:
        group = [n for n in nodes if n.category is cat]
        if not group:
            continue
        style = _STYLE[cat]
        fg = folium.FeatureGroup(name=style["label"])
        html, size = _symbol_html(style["symbol"], style["color"])
        legend_entries.append((f"symbol:{style['symbol']}", style["color"], style["label"]))

        for n in group:
            marker = folium.Marker(
                _pos(n),
                icon=folium.DivIcon(
                    html=html, icon_size=size,
                    icon_anchor=(size[0] // 2, size[1] // 2),
                ),
                tooltip=_site_tooltip(n, style["label"], landed),
            )
            marker.add_to(fg)
            if show_names:
                folium.Marker(
                    _pos(n),
                    icon=folium.DivIcon(
                        icon_size=(0, 0),
                        icon_anchor=(-8, 8),
                        html=(f'<div style="font:9px sans-serif;white-space:nowrap;'
                              f'text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,'
                              f'-1px 1px 0 #fff,1px 1px 0 #fff;">{n.name}</div>'),
                    ),
                ).add_to(fg)
        fg.add_to(m)

    # ---- view, legend, title, layer toggle ------------------------------
    # With flows, frame the routes and every sink (unused far-off sources such
    # as China stay on the map, just off the opening view); else every node.
    pos = ([p for path in flow_paths for p in path]
           + [_pos(n) for n in nodes if n.category is NodeCategory.SINK]
           if flows else [_pos(n) for n in nodes])
    if pos:
        m.fit_bounds([[min(p[0] for p in pos), min(p[1] for p in pos)],
                      [max(p[0] for p in pos), max(p[1] for p in pos)]],
                     padding=(30, 30))

    m.get_root().html.add_child(folium.Element(_legend_html(legend_entries, "Legend")))
    if cost_breakdown and total_flow:
        m.get_root().html.add_child(folium.Element(_cost_box_html(cost_breakdown, total_flow)))
    if title:
        m.get_root().html.add_child(folium.Element(
            '<div style="position:fixed;top:10px;left:50%;transform:translateX(-50%);'
            'z-index:9999;background:rgba(255,255,255,0.9);padding:4px 14px;'
            f'border-radius:6px;font:bold 15px sans-serif;">{title}</div>'))
    folium.LayerControl(collapsed=True).add_to(m)

    # ---- output ----------------------------------------------------------
    if save_path is not None:
        save_path = Path(save_path)
        if not save_path.suffix:
            save_path = save_path.with_suffix(".html")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = save_path.suffix.lower()
        if suffix == ".html":
            m.save(str(save_path))
        elif suffix == ".png":
            save_path.write_bytes(m._to_png(delay=3))  # needs selenium + driver
        else:
            raise ValueError("save_path must end in .html or .png")
    if show:
        tmp = config.MAP_PREVIEW_FILE
        tmp.parent.mkdir(parents=True, exist_ok=True)
        m.save(str(tmp))
        webbrowser.open(tmp.as_uri())
    return m


if __name__ == "__main__":
    from loader import load_nodes

    nodes = load_nodes(config.SITES_FILE)
    out = config.OUTPUT_DIR / config.SITES_MAP_NAME
    plot_nodes(nodes, save_path=out.with_suffix(".html"))  # interactive page
    plot_nodes(nodes, save_path=out.with_suffix(".png"))   # static image (needs selenium)
    plot_nodes(nodes, show=True)