"""Simple US map of supply chain nodes using Folium (Leaflet.js).

    pip install folium

Folium produces an interactive HTML map (OpenStreetMap/CARTO tiles, zoom/pan).
Static PNG export is optional and needs selenium + a browser driver:

    pip install selenium
"""

from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from typing import Iterable

import folium

from node import Mode, Node, NodeCategory

# CARTO basemaps now require a free key (https://carto.com/basemaps/apikey/).
# Easiest: set an environment variable named CARTO_API_KEY.
# Or paste the key between the quotes below (don't commit it to git).
CARTO_API_KEY = "cb1_4ucd_1_afe46a94d28c9a77ce4e06cc"

# (hex color, opacity)
_MODE_COLORS = {
    Mode.TRUCK: ("#d6604d", 0.75),
    Mode.RAIL: ("#5a5a5a", 0.8),
    Mode.BARGE: ("#2166ac", 0.75),
    Mode.PIPELINE: ("#762a83", 0.75),
}

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
    """entries: (kind, color, label) with kind in {"symbol:<shape>", "line"}."""
    rows = []
    for kind, color, label in entries:
        if kind == "line":
            swatch = (f'<span style="display:inline-block;width:18px;height:3px;'
                      f'background:{color};vertical-align:middle;"></span>')
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


def plot_nodes(
    nodes: Iterable[Node],
    *,
    show_names: bool = False,
    show_intermediate: bool = False,
    flows: dict[tuple[str, str, Mode], float] | None = None,
    title: str | None = None,
    save_path: str | Path | None = None,
    show: bool = False,
) -> folium.Map:
    """Plot sources (green triangles) and sinks (red circles) on a Folium map.

    Hovering a point shows its name, location and base value; set show_names
    to also print names on the map (cluttered where nodes are close).

    save_path: ".html" -> interactive page (no extra install);
               ".png"  -> static image (needs selenium + browser driver).
    show:      open the interactive map in your browser.
    flows:     optional {(source_name, sink_name, mode): volume}. Each is drawn
               as a straight line (not the route geometry) colored by mode,
               with a small volume label at its midpoint.
    """
    nodes = list(nodes)
    categories = [NodeCategory.SOURCE, NodeCategory.SINK]
    if show_intermediate:
        categories.append(NodeCategory.INTERMEDIATE)

    m = folium.Map(location=[39.5, -98.35], zoom_start=4,
                   tiles=None, control_scale=True)
    folium.TileLayer(
        tiles=(f"https://basemaps.cartocdn.com/rastertiles/light_all/"
               f"{{z}}/{{x}}/{{y}}.png?key={CARTO_API_KEY}"),
        attr=('&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
              'contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'),
        name="CARTO Positron",
    ).add_to(m)
    legend_entries: list[tuple[str, str, str]] = []

    # ---- flows -----------------------------------------------------------
    if flows:
        by_name = {n.name: n for n in nodes}
        mode_groups: dict[Mode, folium.FeatureGroup] = {}
        label_group = folium.FeatureGroup(name="Flow labels (DMT/yr)", show=True)
        per_pair: dict[tuple[str, str], int] = {}

        for (src, snk, mode), vol in flows.items():
            a, b = by_name[src], by_name[snk]
            color, opacity = _MODE_COLORS[mode]

            if mode not in mode_groups:
                mode_groups[mode] = folium.FeatureGroup(name=mode.value.capitalize())
                legend_entries.append(("line", color, mode.value.capitalize()))
            folium.PolyLine(
                [(a.lat, a.lon), (b.lat, b.lon)],
                color=color, weight=2, opacity=opacity,
                tooltip=f"{src} → {snk}<br>{vol:,.0f} ({mode.value})",
            ).add_to(mode_groups[mode])

            # Stagger labels when one pair is served by several modes.
            k = per_pair[(src, snk)] = per_pair.get((src, snk), -1) + 1
            mid_lat = (a.lat + b.lat) / 2 + 0.4 * k
            mid_lon = (a.lon + b.lon) / 2
            folium.Marker(
                (mid_lat, mid_lon),
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
                (n.lat, n.lon),
                icon=folium.DivIcon(
                    html=html, icon_size=size,
                    icon_anchor=(size[0] // 2, size[1] // 2),
                ),
                tooltip=(f"<b>{n.name}</b><br>{n.city}, {n.state}"
                         f"<br>Base: {n.base:,.0f}"
                         f"<br><i>{style['label']}</i>"),
            )
            marker.add_to(fg)
            if show_names:
                folium.Marker(
                    (n.lat, n.lon),
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
    if nodes:
        m.fit_bounds([[min(n.lat for n in nodes), min(n.lon for n in nodes)],
                      [max(n.lat for n in nodes), max(n.lon for n in nodes)]],
                     padding=(30, 30))

    m.get_root().html.add_child(folium.Element(_legend_html(legend_entries, "Legend")))
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
        tmp = Path("_network_map_preview.html").resolve()
        m.save(str(tmp))
        webbrowser.open(tmp.as_uri())
    return m


if __name__ == "__main__":
    from loader import load_nodes

    nodes = load_nodes("network.xlsx")
    plot_nodes(nodes, save_path="network_map.html")  # interactive page
    plot_nodes(nodes, save_path="network_map.png")   # static image (needs selenium)
    plot_nodes(nodes, show=True)