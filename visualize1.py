"""Simple US map of supply chain nodes using plotly (no osmnx, no downloads).

    pip install plotly kaleido

plotly ships its own US state outlines, and the "albers usa" projection puts
Alaska and Hawaii in insets automatically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import plotly.graph_objects as go

from node import Node, NodeCategory

_STYLE = {
    NodeCategory.SOURCE: dict(color="#1a9641", symbol="triangle-up", label="Source"),
    NodeCategory.SINK: dict(color="#d7191c", symbol="circle", label="Sink"),
    NodeCategory.INTERMEDIATE: dict(color="#2c7bb6", symbol="square", label="Intermediate"),
}


def plot_nodes(
    nodes: Iterable[Node],
    *,
    show_names: bool = False,
    show_intermediate: bool = False,
    flows: dict[tuple[str, str], float] | None = None,
    title: str | None = None,
    save_path: str | Path | None = None,
    show: bool = False,
) -> go.Figure:
    """Plot sources (green triangles) and sinks (red circles) on a US state map.

    Hovering a point shows its name, location and base value; set show_names
    to also print names on the map (cluttered where nodes are close).

    save_path: ".html" -> interactive page (no extra install);
               ".png" / ".pdf" / ".svg" -> static image (needs kaleido).
    show:      open the interactive map in your browser.
    flows:     optional {(source_name, sink_name): volume}. Each is drawn as a
               straight line (not the road geometry) with a small volume label
               at its midpoint.
    """
    nodes = list(nodes)
    categories = [NodeCategory.SOURCE, NodeCategory.SINK]
    if show_intermediate:
        categories.append(NodeCategory.INTERMEDIATE)

    fig = go.Figure()
    if flows:
        by_name = {n.name: n for n in nodes}
        mid_lon, mid_lat, mid_txt = [], [], []
        for (src, snk), vol in flows.items():
            a, b = by_name[src], by_name[snk]
            fig.add_trace(go.Scattergeo(
                lon=[a.lon, b.lon], lat=[a.lat, b.lat], mode="lines",
                line=dict(width=1.5, color="rgba(80,80,80,0.55)"),
                hoverinfo="skip", showlegend=False))
            mid_lon.append((a.lon + b.lon) / 2)
            mid_lat.append((a.lat + b.lat) / 2)
            mid_txt.append(f"{vol:,.0f}")
        fig.add_trace(go.Scattergeo(
            lon=mid_lon, lat=mid_lat, mode="text", text=mid_txt,
            textfont=dict(size=8, color="#333333"), name="Flow (DMT/yr)",
            hoverinfo="skip", showlegend=False))
    for cat in categories:
        group = [n for n in nodes if n.category is cat]
        if not group:
            continue
        style = _STYLE[cat]
        fig.add_trace(go.Scattergeo(
            lon=[n.lon for n in group],
            lat=[n.lat for n in group],
            name=style["label"],
            mode="markers+text" if show_names else "markers",
            text=[n.name for n in group],
            textposition="top right",
            textfont=dict(size=9),
            marker=dict(size=11, color=style["color"], symbol=style["symbol"],
                        line=dict(width=1, color="white")),
            customdata=[[n.city, n.state, n.base] for n in group],
            hovertemplate=("<b>%{text}</b><br>%{customdata[0]}, %{customdata[1]}"
                           "<br>Base: %{customdata[2]:,.0f}<extra>" + style["label"] + "</extra>"),
        ))

    fig.update_geos(
        scope="usa",                  # albers usa: lower 48 + Alaska/Hawaii insets
        showsubunits=True,            # state borders
        subunitcolor="#9a9a9a",
        showland=True,
        landcolor="#f3f3f0",
        showlakes=True,
        lakecolor="white",
    )
    fig.update_layout(
        title=title,
        margin=dict(l=10, r=10, t=50 if title else 10, b=10),
        legend=dict(x=0.86, y=0.98, bgcolor="rgba(255,255,255,0.8)"),
        width=1100,
        height=650,
    )

    if save_path is not None:
        save_path = Path(save_path)
        if not save_path.suffix:
            save_path = save_path.with_suffix(".png")
        save_path.parent.mkdir(parents=True, exist_ok=True)
        if save_path.suffix.lower() == ".html":
            fig.write_html(save_path)
        else:
            fig.write_image(save_path, scale=2)  # scale=2 -> crisp 2200x1300 px
    if show:
        fig.show()
    return fig

if __name__ == "__main__":
    from loader import load_nodes

    nodes = load_nodes("network.xlsx")
    plot_nodes(nodes, save_path="network_map.png")   # static image
    plot_nodes(nodes, save_path="network_map.html")  # interactive page
    plot_nodes(nodes, show=True)
