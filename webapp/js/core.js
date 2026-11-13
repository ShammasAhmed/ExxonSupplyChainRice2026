/*
 * core.js -- data indexing, state, formatting. No DOM work here.
 * Everything is driven by window.APP_DATA (see webapp/DATA_SCHEMA.md); nothing
 * about sites, controls or stops is hard-coded.
 */
(function () {
  "use strict";
  var CX = (window.CX = window.CX || {});
  var D = window.APP_DATA;
  CX.D = D;
  if (!D) return;

  var DST_PER_DMT = 1.10231;

  // ------------------------------------------------------------------ lookups
  CX.nodes = D.nodes || [];
  CX.nodeById = {};
  CX.nodes.forEach(function (n) { CX.nodeById[n.id] = n; });
  CX.sinks = CX.nodes.filter(function (n) { return n.role === "sink"; });
  CX.controls = D.controls || [];
  CX.components = D.cost_components || [];
  CX.modes = D.modes || [];
  CX.modeById = {};
  CX.modes.forEach(function (m) { CX.modeById[m.id] = m; });

  CX.label = function (id) {
    var n = CX.nodeById[id];
    return n ? (n.label || n.id) : id;
  };
  CX.modeLabel = function (id) {
    var m = CX.modeById[id];
    return m ? m.label : (id ? id.charAt(0).toUpperCase() + id.slice(1) : "");
  };

  // Mode palette: validated categorical steps for the dark surface. Known
  // modes get fixed colours; any other mode id takes the next free slot.
  var MODE_COLORS = { truck: "#c98500", rail: "#3987e5", barge: "#199e70", ocean: "#d55181" };
  var SPARE = ["#9085e9", "#d95926", "#e66767", "#008300"];
  var spareI = 0;
  CX.modes.forEach(function (m) { if (!MODE_COLORS[m.id]) MODE_COLORS[m.id] = SPARE[spareI++ % SPARE.length]; });
  CX.modeColor = function (id) {
    if (!MODE_COLORS[id]) MODE_COLORS[id] = SPARE[spareI++ % SPARE.length];
    return MODE_COLORS[id];
  };

  // Cost-component palette (product is the neutral base; the rest categorical).
  var COMP_COLORS = ["#8c8c94", "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9", "#e66767"];
  CX.compColor = function (id) {
    for (var i = 0; i < CX.components.length; i++) if (CX.components[i].id === id) return COMP_COLORS[i % COMP_COLORS.length];
    return "#777";
  };

  // ------------------------------------------------------------------ run index
  CX.decisionIdx = [];
  CX.assumptionIdx = [];
  CX.controls.forEach(function (c, i) { (c.decision ? CX.decisionIdx : CX.assumptionIdx).push(i); });

  CX.key = function (idx) { return idx.join("-"); };
  CX.run = function (idx) { return D.runs[CX.key(idx)] || null; };
  CX.plan = function (run) { return run ? D.plans[run.plan] || null : null; };

  function ndKey(parts) {
    var out = [];
    for (var i = 0; i < CX.assumptionIdx.length; i++) out.push(parts[CX.assumptionIdx[i]]);
    return out.join("-");
  }
  // One pass: for every setting of the non-decision controls, the run with the
  // lowest total over all decision combinations.
  CX.bestByAssumptions = {};
  (function () {
    var runs = D.runs || {};
    for (var k in runs) {
      if (!Object.prototype.hasOwnProperty.call(runs, k)) continue;
      var parts = k.split("-");
      var nk = ndKey(parts);
      var r = runs[k], b = CX.bestByAssumptions[nk];
      if (!b || r.total_usd_per_yr < b.total) CX.bestByAssumptions[nk] = { total: r.total_usd_per_yr, key: k };
    }
  })();
  CX.best = function (idx) {
    return CX.bestByAssumptions[ndKey(idx.map(String))] || null;
  };

  // ------------------------------------------------------------------ state
  function defaults() {
    return CX.controls.map(function (c) {
      var d = typeof c["default"] === "number" ? c["default"] : 0;
      return Math.max(0, Math.min(c.stops.length - 1, d));
    });
  }
  CX.defaults = defaults;
  CX.state = {
    idx: defaults(),
    unit: "dst",
    showBaseline: true,
    animate: !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches),
    sel: null // {type:'route', sig, site} | {type:'site', id} | {type:'node', id}
  };

  var listeners = {};
  CX.on = function (ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); };
  CX.emit = function (ev, arg) { (listeners[ev] || []).forEach(function (fn) { fn(arg); }); };

  CX.setIdx = function (idx) {
    CX.state.idx = idx.slice();
    CX.emit("change");
  };
  CX.setControl = function (ci, si) {
    var idx = CX.state.idx.slice();
    idx[ci] = si;
    CX.setIdx(idx);
  };
  CX.select = function (sel) { CX.state.sel = sel; CX.emit("select"); };

  CX.current = function () {
    var run = CX.run(CX.state.idx);
    return { run: run, plan: CX.plan(run), key: CX.key(CX.state.idx) };
  };

  // ------------------------------------------------------------------ units & formatting
  CX.UNITS = [
    { id: "dst", label: "$/DST", f: 1 },
    { id: "dmt", label: "$/DMT", f: DST_PER_DMT },
    { id: "wet", label: "$/wet MT", f: DST_PER_DMT * 0.5 }
  ];
  CX.unit = function () {
    for (var i = 0; i < CX.UNITS.length; i++) if (CX.UNITS[i].id === CX.state.unit) return CX.UNITS[i];
    return CX.UNITS[0];
  };
  // value given in $/DST -> formatted in the selected unit
  CX.perUnit = function (vPerDst, opts) {
    if (vPerDst == null || isNaN(vPerDst)) return "–";
    var v = vPerDst * CX.unit().f;
    var a = Math.abs(v);
    var s = a < 10 ? a.toFixed(2) : Math.round(a).toLocaleString("en-US");
    var sign = v < 0 ? "−" : (opts && opts.plus && v > 0 ? "+" : "");
    return sign + "$" + s;
  };
  CX.unitLabel = function () { return CX.unit().label; };
  CX.unitSuffix = function () { return CX.unit().label.replace("$", ""); };

  // $/yr: $104.5M, $753k, $950
  CX.usd = function (v, opts) {
    if (v == null || isNaN(v)) return "–";
    var a = Math.abs(v), s;
    if (a >= 1e9) s = (a / 1e9).toFixed(2) + "B";
    else if (a >= 999500) { var m = a / 1e6; s = (m >= 10 ? m.toFixed(1) : m.toFixed(2)) + "M"; }
    else if (a >= 1e3) s = Math.round(a / 1e3) + "k";
    else s = Math.round(a).toString();
    var sign = v < 0 ? "−" : (opts && opts.plus && v > 0 ? "+" : "");
    return sign + "$" + s;
  };
  CX.num = function (v, d) {
    if (v == null || isNaN(v)) return "–";
    return Number(v).toLocaleString("en-US", { maximumFractionDigits: d == null ? 0 : d, minimumFractionDigits: 0 });
  };
  CX.dst = function (v) { return CX.num(v) + " DST/yr"; };

  // Savings (positive = cheaper than today) -> {text, cls, arrow}
  CX.savings = function (s, tiny) {
    var eps = tiny == null ? 0.5 : tiny;
    if (s == null || isNaN(s)) return { text: "–", cls: "", arrow: "" };
    if (Math.abs(s) < eps) return { text: "$0", cls: "", arrow: "=" };
    if (s > 0) return { text: CX.usd(s), cls: "good", arrow: "▼" };
    return { text: CX.usd(-s), cls: "bad", arrow: "▲" };
  };
  CX.savingsHTML = function (s, suffixSave, suffixLoss) {
    var o = CX.savings(s);
    if (!o.cls) return '<span class="num">' + o.arrow + " " + o.text + "</span>";
    return '<span class="num ' + o.cls + '">' + o.arrow + " " + o.text + (o.cls === "good" ? (suffixSave || "") : (suffixLoss || "")) + "</span>";
  };

  CX.esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  // ------------------------------------------------------------------ plan helpers
  CX.routeSig = function (r) {
    return r.supplier + "|" + r.site + "|" + (r.legs || []).map(function (l) { return l.from + ">" + l.to + ":" + l.mode; }).join(",");
  };
  CX.legCost = function (l) {
    return (l.line_haul_usd_per_dst || 0) + (l.handling_usd_per_dst || 0) + (l.terminal_usd_per_dst || 0);
  };
  CX.lastMode = function (r) { var l = r.legs || []; return l.length ? l[l.length - 1].mode : null; };

  // Per-site cost summary for a plan. Site cost = routes + site builds + switching.
  CX.siteSummary = function (plan, siteId) {
    var s = { site: siteId, routes: [], dst: 0, total: 0, routeUsd: 0, comp: {}, builds: [], supplier_switches: [], mode_switches: [] };
    CX.components.forEach(function (c) { s.comp[c.id] = 0; });
    ["product", "line_haul", "handling", "terminal", "build", "supplier_switch", "mode_switch"].forEach(function (k) { if (s.comp[k] == null) s.comp[k] = 0; });
    if (!plan) return s;
    (plan.routes || []).forEach(function (r) {
      if (r.site !== siteId) return;
      s.routes.push(r);
      var q = r.dst_per_yr || 0;
      s.dst += q;
      s.routeUsd += r.usd_per_yr || 0;
      s.comp.product += (r.product_usd_per_dst || 0) * q;
      (r.legs || []).forEach(function (l) {
        s.comp.line_haul += (l.line_haul_usd_per_dst || 0) * q;
        s.comp.handling += (l.handling_usd_per_dst || 0) * q;
        s.comp.terminal += (l.terminal_usd_per_dst || 0) * q;
      });
    });
    (plan.builds || []).forEach(function (b) { if (b.site === siteId) { s.builds.push(b); s.comp.build += b.usd_per_yr || 0; } });
    (plan.supplier_switches || []).forEach(function (b) { if (b.site === siteId) { s.supplier_switches.push(b); s.comp.supplier_switch += b.usd_per_yr || 0; } });
    (plan.mode_switches || []).forEach(function (b) { if (b.site === siteId) { s.mode_switches.push(b); s.comp.mode_switch += b.usd_per_yr || 0; } });
    s.extras = s.comp.build + s.comp.supplier_switch + s.comp.mode_switch;
    s.total = s.routeUsd + s.extras;
    s.landed = s.dst > 0 ? s.routeUsd / s.dst : null;
    return s;
  };

  // Builds / switches not attached to a sink (hubs, railheads...).
  CX.sharedExtras = function (plan) {
    var sinkSet = {};
    CX.sinks.forEach(function (n) { sinkSet[n.id] = 1; });
    var out = { builds: [], supplier_switches: [], mode_switches: [], total: 0 };
    if (!plan) return out;
    ["builds", "supplier_switches", "mode_switches"].forEach(function (k) {
      (plan[k] || []).forEach(function (b) { if (!sinkSet[b.site]) { out[k].push(b); out.total += b.usd_per_yr || 0; } });
    });
    return out;
  };

  // Chips describing what changed at a site (switches / builds), plan vs today.
  CX.siteChips = function (plan, siteId) {
    var chips = [];
    if (!plan) return chips;
    (plan.supplier_switches || []).forEach(function (b) {
      if (b.site === siteId) chips.push({ cls: "chip-new", text: "new supplier: " + CX.label(b.supplier), usd: b.usd_per_yr });
    });
    (plan.mode_switches || []).forEach(function (b) {
      if (b.site === siteId) chips.push({ cls: "chip-new", text: "starts " + CX.modeLabel(b.mode).toLowerCase(), usd: b.usd_per_yr });
    });
    (plan.builds || []).forEach(function (b) {
      if (b.site === siteId) chips.push({ cls: "chip-build", text: "builds " + CX.modeLabel(b.mode).toLowerCase() + (CX.nodeById[siteId] && CX.nodeById[siteId].role === "sink" ? " spur" : " access"), usd: b.usd_per_yr });
    });
    return chips;
  };
  // Chips for one route (relative to today's network)
  CX.routeChips = function (plan, r) {
    var chips = [];
    if (r.current) chips.push({ cls: "chip-same", text: "today's lane" });
    (plan && plan.supplier_switches || []).forEach(function (b) {
      if (b.site === r.site && b.supplier === r.supplier) chips.push({ cls: "chip-new", text: "new supplier", usd: b.usd_per_yr });
    });
    (plan && plan.mode_switches || []).forEach(function (b) {
      if (b.site === r.site && b.mode === CX.lastMode(r)) chips.push({ cls: "chip-new", text: "starts " + CX.modeLabel(b.mode).toLowerCase(), usd: b.usd_per_yr });
    });
    var touched = {};
    (r.legs || []).forEach(function (l) { touched[l.from] = 1; touched[l.to] = 1; });
    (plan && plan.builds || []).forEach(function (b) {
      if (touched[b.site]) chips.push({ cls: "chip-build", text: "uses new " + CX.modeLabel(b.mode).toLowerCase() + " at " + CX.label(b.site), usd: b.usd_per_yr });
    });
    return chips;
  };

  // Today's (baseline) summary per site, cached
  var baseCache = {};
  CX.baseSite = function (siteId) {
    if (!baseCache[siteId]) baseCache[siteId] = CX.siteSummary(D.baseline, siteId);
    return baseCache[siteId];
  };

  // Nominal displayed longitude: shift by 360 so the whole network is contiguous
  // (e.g. Qingdao drawn at lon - 360, west of North America).
  CX.refLon = (function () {
    var ls = CX.sinks.length ? CX.sinks : CX.nodes;
    if (!ls.length) return -95;
    var sx = 0, sy = 0;
    ls.forEach(function (n) { sx += Math.cos(n.lon * Math.PI / 180); sy += Math.sin(n.lon * Math.PI / 180); });
    return Math.atan2(sy, sx) * 180 / Math.PI;
  })();
  CX.wrapLon = function (lon, ref) {
    var r = ref == null ? CX.refLon : ref;
    while (lon - r > 180) lon -= 360;
    while (lon - r < -180) lon += 360;
    return lon;
  };
  CX.nodeLngLat = function (id) {
    var n = CX.nodeById[id];
    if (!n) return null;
    return [CX.wrapLon(n.lon), n.lat];
  };
})();
