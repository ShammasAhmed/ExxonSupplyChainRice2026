/*
 * map.js -- MapLibre map: today's network as a ghost, the selected plan's legs
 * coloured by mode, node markers, hover tooltips, click-to-select.
 */
(function () {
  "use strict";
  var CX = window.CX;
  var M = (CX.Map = {});
  var map = null, ready = false, markers = {}, pendingPlan = null;
  var legIndex = {};      // leg key -> {routes:[route], mode, dst}
  var planUsedNodes = {};
  var hoverKey = null;
  var STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

  // ------------------------------------------------------------------ geometry
  var R2D = 180 / Math.PI, D2R = Math.PI / 180;
  function mercY(lat) { return Math.log(Math.tan(Math.PI / 4 + lat * D2R / 2)) * R2D; }
  function invMercY(y) { return (2 * Math.atan(Math.exp(y * D2R)) - Math.PI / 2) * R2D; }

  var MODE_ORDER = {};
  function modeSlot(mode) {
    if (MODE_ORDER[mode] == null) MODE_ORDER[mode] = Object.keys(MODE_ORDER).length;
    return MODE_ORDER[mode];
  }
  (CX.modes || []).forEach(function (m) { modeSlot(m.id); });

  // Curved arc between two points (planar in Mercator space). Legs of different
  // modes between the same two nodes bow by different amounts so they don't overlap.
  function arc(a, b, mode) {
    var ax = a[0], ay = mercY(a[1]), bx = b[0], by = mercY(b[1]);
    var dx = bx - ax, dy = by - ay, len = Math.sqrt(dx * dx + dy * dy);
    if (len < 1e-6) return [a, b];
    var slot = modeSlot(mode);
    var k = (0.10 + 0.07 * slot) * (slot % 2 ? -1 : 1);
    if (len > 60) k = k * 0.6; // very long (ocean) lines: gentler
    // perpendicular, consistently oriented
    var px = -dy / len, py = dx / len;
    var cx = (ax + bx) / 2 + px * len * k, cy = (ay + by) / 2 + py * len * k;
    var pts = [], n = 40;
    for (var i = 0; i <= n; i++) {
      var t = i / n, u = 1 - t;
      var x = u * u * ax + 2 * u * t * cx + t * t * bx;
      var y = u * u * ay + 2 * u * t * cy + t * t * by;
      pts.push([x, invMercY(y)]);
    }
    return pts;
  }

  // Routed shape from geometry.js if present (either direction), else an arc.
  function laneCoords(from, to, mode) {
    var a = CX.nodeLngLat(from), b = CX.nodeLngLat(to);
    if (!a || !b) return null;
    var G = window.APP_GEOMETRY && window.APP_GEOMETRY.lanes;
    var pts = null;
    if (G) {
      var g = G[from + "|" + to + "|" + mode];
      if (g && g.length > 1) pts = g.map(function (p) { return [p[0], p[1]]; });
      else {
        g = G[to + "|" + from + "|" + mode];
        if (g && g.length > 1) pts = g.map(function (p) { return [p[0], p[1]]; }).reverse();
      }
    }
    if (!pts) return arc(a, b, mode);
    // unwrap so longitudes are continuous, then shift the whole line so it
    // starts at the displayed origin's copy of the world.
    for (var i = 1; i < pts.length; i++) {
      while (pts[i][0] - pts[i - 1][0] > 180) pts[i][0] -= 360;
      while (pts[i][0] - pts[i - 1][0] < -180) pts[i][0] += 360;
    }
    var shift = Math.round((a[0] - pts[0][0]) / 360) * 360;
    if (shift) pts.forEach(function (p) { p[0] += shift; });
    return pts;
  }
  var laneCache = {};
  function lane(from, to, mode) {
    var k = from + "|" + to + "|" + mode;
    if (!(k in laneCache)) laneCache[k] = laneCoords(from, to, mode);
    return laneCache[k];
  }

  var REF = 1;
  (function () {
    CX.sinks.forEach(function (n) { REF = Math.max(REF, n.demand_dst_per_yr || 0); });
  })();
  function widthFor(dst) { return Math.min(13, 1.6 + 8.5 * Math.sqrt(Math.max(0, dst) / REF)); }
  M.widthFor = widthFor;
  M.REF = REF;

  function legFeatures(plan, withIndex) {
    var agg = {}, order = [];
    (plan && plan.routes || []).forEach(function (r) {
      (r.legs || []).forEach(function (l) {
        var k = l.from + "|" + l.to + "|" + l.mode;
        if (!agg[k]) { agg[k] = { key: k, from: l.from, to: l.to, mode: l.mode, dst: 0, routes: [] }; order.push(k); }
        agg[k].dst += r.dst_per_yr || 0;
        agg[k].routes.push(r);
      });
    });
    if (withIndex) legIndex = agg;
    var feats = [];
    order.forEach(function (k) {
      var a = agg[k], coords = lane(a.from, a.to, a.mode);
      if (!coords) return;
      feats.push({
        type: "Feature",
        properties: {
          key: k, mode: a.mode, dst: a.dst, w: widthFor(a.dst),
          rids: "," + a.routes.map(function (r) { return r.id; }).join(",") + ","
        },
        geometry: { type: "LineString", coordinates: coords }
      });
    });
    return { type: "FeatureCollection", features: feats };
  }

  // ------------------------------------------------------------------ init
  M.init = function (el) {
    if (!window.maplibregl) {
      document.getElementById("map-fallback").hidden = false;
      return;
    }
    var b = M.homeBounds();
    try {
      map = new maplibregl.Map({
        container: el,
        style: STYLE,
        bounds: b,
        fitBoundsOptions: { padding: M.padding() },
        attributionControl: false,
        renderWorldCopies: true,
        dragRotate: false,
        pitchWithRotate: false,
        minZoom: 1.2,
        maxZoom: 11
      });
    } catch (e) {
      console.warn("Map failed to start", e);
      document.getElementById("map-fallback").hidden = false;
      return;
    }
    M.map = map;
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    map.on("load", onLoad);
    map.on("zoom", zoomClasses);
    map.on("moveend", updateOffMap);
    map.on("moveend", scheduleLabels);
    map.on("error", function (e) { if (e && e.error) console.warn("map:", e.error.message || e.error); });
    zoomClasses();
  };

  M.padding = function () {
    var stage = document.getElementById("stage");
    var right = stage && stage.classList.contains("drawer-open") ? 440 : 50;
    return { top: 125, bottom: 60, left: 40, right: right };
  };
  M.homeBounds = function () {
    var pts = CX.sinks.length ? CX.sinks : CX.nodes;
    var w = 999, e = -999, s = 99, n = -99;
    pts.forEach(function (p) {
      var lon = CX.wrapLon(p.lon);
      w = Math.min(w, lon); e = Math.max(e, lon); s = Math.min(s, p.lat); n = Math.max(n, p.lat);
    });
    return [[w - 3, s - 3], [e + 3, n + 2]];
  };
  M.home = function () {
    if (map) map.fitBounds(M.homeBounds(), { padding: M.padding(), duration: 700 });
  };

  function firstSymbolLayer() {
    var layers = map.getStyle().layers || [];
    for (var i = 0; i < layers.length; i++) if (layers[i].type === "symbol") return layers[i].id;
    return undefined;
  }

  function modeMatch() {
    var expr = ["match", ["get", "mode"]];
    CX.modes.forEach(function (m) { expr.push(m.id, CX.modeColor(m.id)); });
    expr.push("#bbbbbb");
    return expr;
  }
  function zw(mult, add) {
    return ["interpolate", ["linear"], ["zoom"],
      2, ["+", ["*", ["get", "w"], 0.95 * mult], add],
      5, ["+", ["*", ["get", "w"], 1.2 * mult], add],
      8, ["+", ["*", ["get", "w"], 1.7 * mult], add]];
  }

  function onLoad() {
    var before = firstSymbolLayer();
    var empty = { type: "FeatureCollection", features: [] };
    map.addSource("base", { type: "geojson", data: empty });
    map.addSource("plan", { type: "geojson", data: empty });

    // Ghost: today's network
    map.addLayer({ id: "base-line", type: "line", source: "base",
      layout: { "line-cap": "butt", "line-join": "round" },
      paint: { "line-color": "#c9c9d1", "line-opacity": 0.62, "line-width": ["interpolate", ["linear"], ["zoom"], 2, 1.5, 8, 2.6], "line-dasharray": [2, 2] } }, before);
    map.addLayer({ id: "base-hit", type: "line", source: "base",
      paint: { "line-color": "#000", "line-opacity": 0, "line-width": 10 } }, before);

    // Plan legs
    map.addLayer({ id: "plan-casing", type: "line", source: "plan",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#050506", "line-opacity": 0.75, "line-width": zw(1, 3) } }, before);
    map.addLayer({ id: "plan-glow", type: "line", source: "plan", filter: ["==", ["get", "mode"], "ocean"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": CX.modeColor("ocean"), "line-opacity": 0.35, "line-blur": 6, "line-width": zw(1, 8) } }, before);
    map.addLayer({ id: "plan-line", type: "line", source: "plan",
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": modeMatch(), "line-opacity": 0.95, "line-width": zw(1, 0) } }, before);
    // secondary encodings so mode never relies on colour alone
    map.addLayer({ id: "plan-ties", type: "line", source: "plan", filter: ["==", ["get", "mode"], "rail"],
      layout: { "line-cap": "butt", "line-join": "round" },
      paint: { "line-color": CX.modeColor("rail"), "line-opacity": 0.95, "line-width": zw(1, 5), "line-dasharray": [0.35, 1.6] } }, before);
    map.addLayer({ id: "plan-core", type: "line", source: "plan", filter: ["==", ["get", "mode"], "barge"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#06231a", "line-opacity": 0.9, "line-width": ["interpolate", ["linear"], ["zoom"], 2, ["*", ["get", "w"], 0.28], 8, ["*", ["get", "w"], 0.55]] } }, before);
    map.addLayer({ id: "plan-flow", type: "line", source: "plan",
      layout: { "line-cap": "butt", "line-join": "round" },
      paint: { "line-color": "#ffffff", "line-opacity": 0.55, "line-width": ["interpolate", ["linear"], ["zoom"], 2, ["max", 1, ["*", ["get", "w"], 0.22]], 8, ["max", 1.4, ["*", ["get", "w"], 0.35]]], "line-dasharray": [0, 4, 3] } }, before);
    map.addLayer({ id: "plan-hl", type: "line", source: "plan", filter: ["==", ["get", "key"], "__none__"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#ffffff", "line-opacity": 0.9, "line-width": zw(1, 4), "line-gap-width": 0 } }, "plan-line");
    map.addLayer({ id: "plan-hit", type: "line", source: "plan",
      paint: { "line-color": "#000", "line-opacity": 0, "line-width": ["max", 14, ["+", ["get", "w"], 8]] } });

    map.on("mousemove", "plan-hit", onLegHover);
    map.on("mouseleave", "plan-hit", onLegLeave);
    map.on("click", "plan-hit", onLegClick);
    map.on("mousemove", "base-hit", onBaseHover);
    map.on("mouseleave", "base-hit", onLegLeave);

    ready = true;
    buildMarkers();
    M.update(pendingPlan || CX.current().plan);
    M.setBaselineVisible(CX.state.showBaseline);
    startAnimation();
  }

  // ------------------------------------------------------------------ markers
  function markerSVG(n, size) {
    var s = size, h = s / 2;
    if (n.role === "sink") {
      var r = h - 1.5;
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 ' + s + " " + s + '" aria-hidden="true">' +
        '<rect x="1.5" y="1.5" width="' + (s - 3) + '" height="' + (s - 3) + '" rx="' + Math.max(2, s * 0.18) + '" fill="#f4f4f6" stroke="#0b0b0c" stroke-width="1.5"/>' +
        '<circle cx="' + h + '" cy="' + h + '" r="' + Math.max(1.6, r * 0.32) + '" fill="#2424f5"/></svg>';
    }
    if (n.role === "intermediate") {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 ' + s + " " + s + '" aria-hidden="true">' +
        '<path d="M' + h + ' 1 L' + (s - 1) + " " + h + " L" + h + " " + (s - 1) + " L1 " + h + ' Z" fill="#1b1b20" stroke="#d9d9de" stroke-width="2"/></svg>';
    }
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 ' + s + " " + s + '" aria-hidden="true">' +
      '<circle cx="' + h + '" cy="' + h + '" r="' + (h - 1.5) + '" fill="#0b0b0c" stroke="#f4f4f6" stroke-width="2.5"/>' +
      '<circle cx="' + h + '" cy="' + h + '" r="' + Math.max(1.5, (h - 1.5) * 0.38) + '" fill="#f4f4f6"/></svg>';
  }
  M.markerSVG = markerSVG;

  function buildMarkers() {
    CX.nodes.forEach(function (n) {
      var el = document.createElement("div");
      el.className = "node role-" + n.role;
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label", (n.label || n.id) + " (" + roleName(n) + ")");
      el.innerHTML = '<span class="node-svg"></span><span class="node-label">' + CX.esc(n.label || n.id) + "</span>";
      el.addEventListener("mouseenter", function (e) { showNodeTip(n, e); });
      el.addEventListener("mousemove", function (e) { CX.UI.moveTip(e); });
      el.addEventListener("mouseleave", function () { CX.UI.hideTip(); });
      el.addEventListener("click", function (e) { e.stopPropagation(); selectNode(n); });
      el.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectNode(n); } });
      var mk = new maplibregl.Marker({ element: el, anchor: "center" }).setLngLat(CX.nodeLngLat(n.id)).addTo(map);
      markers[n.id] = { el: el, marker: mk, node: n };
    });
  }
  function selectNode(n) {
    if (n.role === "sink") CX.select({ type: "site", id: n.id });
    else CX.select({ type: "node", id: n.id });
  }
  function roleName(n) {
    if (n.role === "sink") return "XOM site";
    if (n.role === "source") return n.kind === "distributor" ? "Supplier (distributor)" : n.kind === "export" ? "Supplier (export)" : "Supplier";
    return n.kind === "railhead" ? "Railhead (transload)" : "Terminal / hub";
  }
  M.roleName = roleName;

  function nodeVolumes(plan) {
    var v = {};
    (plan && plan.routes || []).forEach(function (r) {
      var q = r.dst_per_yr || 0;
      v[r.supplier] = (v[r.supplier] || 0) + q;
      (r.legs || []).forEach(function (l) { if (l.to !== r.site) v[l.to] = (v[l.to] || 0) + q; });
      v[r.site] = (v[r.site] || 0) + q;
    });
    return v;
  }
  M.nodeVolumes = nodeVolumes;
  var baseVol = null;

  function refreshMarkers(plan) {
    var vol = nodeVolumes(plan);
    if (!baseVol) baseVol = nodeVolumes(CX.D.baseline);
    CX.nodes.forEach(function (n) {
      var m = markers[n.id];
      if (!m) return;
      var q = n.role === "sink" ? (n.demand_dst_per_yr || vol[n.id] || 0) : (vol[n.id] || 0);
      var size = Math.round(Math.max(11, Math.min(28, 11 + 17 * Math.sqrt(q / REF))));
      if (n.role === "intermediate") size = Math.max(size, 13);
      m.el.querySelector(".node-svg").innerHTML = markerSVG(n, size);
      m.el.classList.toggle("unused", !vol[n.id] && n.role !== "sink");
      m.el.style.zIndex = n.role === "sink" ? 3 : n.role === "intermediate" ? 2 : 1;
      var sel = CX.state.sel;
      m.el.classList.toggle("selected", !!sel && (sel.type === "site" || sel.type === "node") && sel.id === n.id);
    });
  }

  function zoomClasses() { /* labels are placed by placeLabels() */ }

  // Greedy label placement: XOM sites first (largest first), then used nodes,
  // then unused ones; a label is hidden if it would overlap one already shown.
  var lastVol = {};
  function placeLabels() {
    if (!map) return;
    var z = map.getZoom();
    var list = CX.nodes.map(function (n) { return markers[n.id]; }).filter(Boolean);
    list.forEach(function (m) { m.el.classList.add("lbl-on"); });
    function prio(m) {
      var n = m.node, v = lastVol[n.id] || n.demand_dst_per_yr || 0;
      if (n.role === "sink") return 3e9 + v;
      if (v > 0) return 2e9 + v;
      return v;
    }
    list.sort(function (a, b) { return prio(b) - prio(a); });
    var placed = [];
    // marker icons are obstacles too
    list.forEach(function (m) { var r = m.el.querySelector(".node-svg").getBoundingClientRect(); placed.push(r); });
    var POS = ["pos-b", "pos-r", "pos-l", "pos-t"];
    list.forEach(function (m) {
      var n = m.node, lab = m.el.querySelector(".node-label");
      var own = m.el.querySelector(".node-svg").getBoundingClientRect();
      var used = n.role === "sink" || (lastVol[n.id] || 0) > 0;
      POS.forEach(function (p) { m.el.classList.remove(p); });
      if (!used && z < 5) { m.el.classList.remove("lbl-on"); return; }
      for (var k = 0; k < POS.length; k++) {
        m.el.classList.add(POS[k]);
        var r = lab.getBoundingClientRect(), pad = 2, hit = false;
        for (var i = 0; i < placed.length && !hit; i++) {
          var o = placed[i];
          if (o.left === own.left && o.top === own.top) continue;
          if (r.left - pad < o.right && r.right + pad > o.left && r.top - pad < o.bottom && r.bottom + pad > o.top) hit = true;
        }
        if (!hit) { placed.push(r); return; }
        m.el.classList.remove(POS[k]);
      }
      m.el.classList.remove("lbl-on");
    });
  }
  var labelTimer = null;
  function scheduleLabels() { clearTimeout(labelTimer); labelTimer = setTimeout(placeLabels, 60); }

  // ------------------------------------------------------------------ update
  M.update = function (plan) {
    pendingPlan = plan;
    if (!ready) return;
    map.getSource("base").setData(legFeatures(CX.D.baseline, false));
    map.getSource("plan").setData(legFeatures(plan, true));
    planUsedNodes = {};
    (plan && plan.routes || []).forEach(function (r) {
      planUsedNodes[r.supplier] = 1; planUsedNodes[r.site] = 1;
      (r.legs || []).forEach(function (l) { planUsedNodes[l.from] = 1; planUsedNodes[l.to] = 1; });
    });
    lastVol = nodeVolumes(plan);
    M.setBaselineVisible(CX.state.showBaseline);
    refreshMarkers(plan);
    M.applySelection();
    updateOffMap();
    scheduleLabels();
  };

  M.setBaselineVisible = function (on) {
    if (!ready) return;
    var v = on && !CX.isToday() ? "visible" : "none";
    map.setLayoutProperty("base-line", "visibility", v);
    map.setLayoutProperty("base-hit", "visibility", v);
  };

  // highlight the selected route(s); dim the rest
  M.applySelection = function () {
    if (!ready) return;
    var plan = CX.current().plan, sel = CX.state.sel, ids = [];
    if (sel && plan) {
      (plan.routes || []).forEach(function (r) {
        if (sel.type === "route" && CX.routeSig(r) === sel.sig) ids.push(r.id);
        else if (sel.type === "site" && r.site === sel.id) ids.push(r.id);
        else if (sel.type === "node" && (r.supplier === sel.id || (r.legs || []).some(function (l) { return l.to === sel.id || l.from === sel.id; }))) ids.push(r.id);
      });
    }
    if (ids.length) {
      var f = ["any"].concat(ids.map(function (id) { return ["in", "," + id + ",", ["get", "rids"]]; }));
      map.setFilter("plan-hl", f);
      var dim = ["case", f, 0.95, 0.22];
      map.setPaintProperty("plan-line", "line-opacity", dim);
      map.setPaintProperty("plan-ties", "line-opacity", dim);
      map.setPaintProperty("plan-flow", "line-opacity", ["case", f, 0.6, 0.12]);
      map.setPaintProperty("plan-core", "line-opacity", ["case", f, 0.9, 0.3]);
      map.setPaintProperty("plan-hl", "line-opacity", 0.22);
    } else {
      map.setFilter("plan-hl", ["==", ["get", "key"], "__none__"]);
      map.setPaintProperty("plan-line", "line-opacity", 0.95);
      map.setPaintProperty("plan-ties", "line-opacity", 0.95);
      map.setPaintProperty("plan-flow", "line-opacity", 0.55);
      map.setPaintProperty("plan-core", "line-opacity", 0.9);
    }
    refreshMarkers(plan);
  };

  // ------------------------------------------------------------------ hover / click
  function onLegHover(e) {
    if (!e.features || !e.features.length) return;
    map.getCanvas().style.cursor = "pointer";
    var k = e.features[0].properties.key, leg = legIndex[k];
    if (!leg) return;
    hoverKey = k;
    CX.UI.showTip(legTipHTML(leg), e.originalEvent);
  }
  function onLegLeave() {
    map.getCanvas().style.cursor = "";
    hoverKey = null;
    CX.UI.hideTip();
  }
  function onLegClick(e) {
    CX.UI.hideTip();
    if (!e.features || !e.features.length) return;
    var leg = legIndex[e.features[0].properties.key];
    if (!leg) return;
    var routes = leg.routes.slice().sort(function (a, b) { return b.dst_per_yr - a.dst_per_yr; });
    CX.select({ type: "route", sig: CX.routeSig(routes[0]), site: routes[0].site, siblings: routes.map(CX.routeSig) });
  }
  function onBaseHover(e) {
    // only when no plan leg is under the cursor
    var hits = map.queryRenderedFeatures(e.point, { layers: ["plan-hit"] });
    if (hits.length) return;
    var p = e.features && e.features[0] && e.features[0].properties;
    if (!p) return;
    var parts = String(p.key).split("|");
    var routes = (CX.D.baseline.routes || []).filter(function (r) {
      return (r.legs || []).some(function (l) { return l.from === parts[0] && l.to === parts[1] && l.mode === parts[2]; });
    });
    var html = '<div class="tt-sub">Today\'s network (ghost)</div>';
    routes.forEach(function (r) {
      html += '<div class="tt-route"><div class="tt-title">' + CX.esc(CX.label(r.supplier)) + " → " + CX.esc(CX.label(r.site)) + "</div>" +
        '<div class="tt-row"><span>Volume</span><b>' + CX.dst(r.dst_per_yr) + "</b></div>" +
        '<div class="tt-row"><span>Landed</span><b>' + CX.perUnit(r.landed_usd_per_dst) + " " + CX.unitSuffix() + "</b></div></div>";
    });
    CX.UI.showTip(html, e.originalEvent);
  }

  function legTipHTML(leg) {
    var html = '<div class="tt-sub">' + CX.UI.modePill(leg.mode) + " &nbsp;" + CX.esc(CX.label(leg.from)) + " → " + CX.esc(CX.label(leg.to)) + "</div>";
    var routes = leg.routes.slice().sort(function (a, b) { return b.dst_per_yr - a.dst_per_yr; });
    routes.slice(0, 4).forEach(function (r) {
      html += '<div class="tt-route"><div class="tt-title">' + CX.esc(CX.label(r.supplier)) + " → " + CX.esc(CX.label(r.site)) + "</div>" +
        '<div class="tt-row"><span>Volume</span><b>' + CX.dst(r.dst_per_yr) + "</b></div>" +
        '<div class="tt-row"><span>Landed</span><b>' + CX.perUnit(r.landed_usd_per_dst) + " " + CX.unitSuffix() + "</b></div></div>";
    });
    if (routes.length > 4) html += '<div class="tt-hint">+' + (routes.length - 4) + " more routes on this leg</div>";
    html += '<div class="tt-hint">Click for the cost breakdown</div>';
    return html;
  }

  function showNodeTip(n, e) {
    var plan = CX.current().plan;
    var vol = nodeVolumes(plan);
    if (!baseVol) baseVol = nodeVolumes(CX.D.baseline);
    var html = '<div class="tt-title">' + CX.esc(n.label || n.id) + "</div>" +
      '<div class="tt-sub">' + roleName(n) + " · " + CX.esc([n.city, n.region, n.country].filter(Boolean).join(", ")) + "</div>";
    if (n.role === "sink") {
      html += '<div class="tt-row"><span>Demand</span><b>' + CX.dst(n.demand_dst_per_yr) + "</b></div>";
      var bs = CX.baseSite(n.id), ps = CX.siteSummary(plan, n.id);
      html += '<div class="tt-row"><span>Landed today</span><b>' + CX.perUnit(bs.landed) + "</b></div>";
      html += '<div class="tt-row"><span>Landed in plan</span><b>' + CX.perUnit(ps.landed) + "</b></div>";
      html += '<div class="tt-row"><span>Saved at site</span><b>' + CX.savingsHTML(bs.total - ps.total, "/yr", "/yr") + "</b></div>";
    } else {
      html += '<div class="tt-row"><span>Volume in plan</span><b>' + CX.dst(vol[n.id] || 0) + "</b></div>";
      html += '<div class="tt-row"><span>Volume today</span><b>' + CX.dst(baseVol[n.id] || 0) + "</b></div>";
    }
    if (n.price_usd_per_dst != null) html += '<div class="tt-row"><span>List price</span><b>' + CX.perUnit(n.price_usd_per_dst) + " " + CX.unitSuffix() + "</b></div>";
    if (n.terminal_fee_usd_per_dst != null) html += '<div class="tt-row"><span>Terminal fee</span><b>' + CX.perUnit(n.terminal_fee_usd_per_dst) + " " + CX.unitSuffix() + "</b></div>";
    var modes = (n.modes || []).map(function (m) { return CX.UI.modePill(m); }).join(" ");
    var cand = (n.candidate_modes || []).map(function (m) { return CX.UI.modePill(m, true); }).join(" ");
    if (modes) html += '<div class="tt-row" style="margin-top:6px"><span>Modes</span><span>' + modes + "</span></div>";
    if (cand) html += '<div class="tt-row" style="margin-top:4px"><span>Needs build</span><span>' + cand + "</span></div>";
    html += '<div class="tt-hint">Click for details</div>';
    CX.UI.showTip(html, e);
  }

  // ------------------------------------------------------------------ off-map indicator
  function updateOffMap() {
    var btn = document.getElementById("offmap");
    if (!map || !btn) return;
    var b = map.getBounds(), off = null;
    Object.keys(planUsedNodes).forEach(function (id) {
      if (off) return;
      var p = CX.nodeLngLat(id);
      if (!p) return;
      var inLon = p[0] >= b.getWest() && p[0] <= b.getEast();
      var inLat = p[1] >= b.getSouth() && p[1] <= b.getNorth();
      if (!inLon || !inLat) {
        var dir = !inLon ? (p[0] < b.getWest() ? "◀" : "▶") : (p[1] > b.getNorth() ? "▲" : "▼");
        off = { id: id, dir: dir, lon: p[0] };
      }
    });
    if (!off) { btn.hidden = true; return; }
    btn.hidden = false;
    var left = off.dir === "◀", right = off.dir === "▶";
    btn.style.left = left ? "10px" : right ? "auto" : "50%";
    btn.style.right = right ? (document.getElementById("stage").classList.contains("drawer-open") ? "440px" : "60px") : "auto";
    btn.style.top = left || right || off.dir === "▲" ? "126px" : "auto";
    btn.style.bottom = off.dir === "▼" ? "60px" : "auto";
    btn.style.transform = left || right ? "none" : "translateX(-50%)";
    if (left) btn.style.left = "14px";
    btn.innerHTML = '<span class="arrow" aria-hidden="true">' + off.dir + "</span>" + CX.esc(CX.label(off.id)) + ' <span class="muted">is off-map · show</span>';
    btn.onclick = M.fitPlan;
  }
  M.fitPlan = function () {
    if (!map) return;
    var w = 999, e = -999, s = 99, n = -99;
    Object.keys(planUsedNodes).concat(CX.sinks.map(function (x) { return x.id; })).forEach(function (id) {
      var p = CX.nodeLngLat(id);
      if (!p) return;
      w = Math.min(w, p[0]); e = Math.max(e, p[0]); s = Math.min(s, p[1]); n = Math.max(n, p[1]);
    });
    map.fitBounds([[w - 4, s - 4], [e + 4, n + 4]], { padding: M.padding(), duration: 900 });
  };
  M.resize = function () { if (map) map.resize(); };

  // ------------------------------------------------------------------ flow animation
  var DASH = [[0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5], [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0],
    [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5], [0, 2, 3, 2], [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5]];
  var step = -1, raf = null;
  function startAnimation() {
    function frame(ts) {
      raf = requestAnimationFrame(frame);
      if (!CX.state.animate || !ready || document.hidden) return;
      var s = Math.floor(ts / 70) % DASH.length;
      if (s !== step) {
        step = s;
        map.setPaintProperty("plan-flow", "line-dasharray", DASH[step]);
      }
    }
    if (!raf) raf = requestAnimationFrame(frame);
  }
  M.setAnimate = function (on) {
    CX.state.animate = on;
    if (!ready) return;
    map.setLayoutProperty("plan-flow", "visibility", on ? "visible" : "none");
  };
})();
