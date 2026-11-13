/*
 * ui.js -- control panel, KPI strip, legend, detail drawer, data drawer,
 * tooltips, About modal. Reads state from CX (core.js).
 */
(function () {
  "use strict";
  var CX = window.CX;
  var UI = (CX.UI = {});
  var $ = function (id) { return document.getElementById(id); };
  var esc = CX.esc;

  // ------------------------------------------------------------------ icons
  var ICON = {
    truck: '<path d="M1.5 4.5h8v6h-8z"/><path d="M9.5 6.5h2.8l2.2 2.6v1.4h-5"/><circle cx="4.2" cy="11.6" r="1.3"/><circle cx="11.8" cy="11.6" r="1.3"/>',
    rail: '<rect x="2" y="4.5" width="12" height="5.5" rx="2.2"/><circle cx="4.8" cy="11.7" r="1.1"/><circle cx="11.2" cy="11.7" r="1.1"/><path d="M1 14h14"/>',
    barge: '<path d="M1.5 9h13l-2 3.5h-9z"/><path d="M4 6.2h8V9H4z"/>',
    ocean: '<path d="M1.5 9.2h13l-2.2 3h-8.6z"/><path d="M9 4.8h3v4.4H9z"/><path d="M1 14.6c1.5-.9 3-.9 4.5 0s3 .9 4.5 0 3-.9 4.5 0"/>'
  };
  UI.modeIcon = function (mode, size, color) {
    var s = size || 14, body = ICON[mode] || '<circle cx="8" cy="8" r="4"/>';
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 16 16" fill="none" stroke="' + (color || CX.modeColor(mode)) +
      '" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + "</svg>";
  };
  UI.modePill = function (mode, candidate) {
    return '<span class="mode-pill"' + (candidate ? ' style="border-style:dashed"' : "") + ">" + UI.modeIcon(mode, 13) + esc(CX.modeLabel(mode)) + "</span>";
  };
  function chipHTML(c) {
    return '<span class="chip ' + c.cls + '">' + esc(c.text) + (c.usd ? ' <span class="muted">' + CX.usd(c.usd) + "/yr</span>" : "") + "</span>";
  }

  // ------------------------------------------------------------------ tooltip
  var tip = null;
  UI.showTip = function (html, evt) {
    tip = tip || $("tooltip");
    tip.innerHTML = html;
    tip.hidden = false;
    UI.moveTip(evt);
  };
  UI.moveTip = function (evt) {
    if (!tip || tip.hidden || !evt) return;
    var st = $("stage").getBoundingClientRect();
    var x = evt.clientX - st.left + 16, y = evt.clientY - st.top + 14;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    if (x + w > st.width - 8) x = evt.clientX - st.left - w - 16;
    if (y + h > st.height - 50) y = Math.max(8, evt.clientY - st.top - h - 12);
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  };
  UI.hideTip = function () { if (tip) tip.hidden = true; };

  // help popovers
  var helpPop = null;
  function showHelp(btn) {
    if (!helpPop) { helpPop = document.createElement("div"); helpPop.className = "help-pop"; helpPop.setAttribute("role", "tooltip"); document.body.appendChild(helpPop); }
    helpPop.textContent = btn.getAttribute("data-help");
    helpPop.hidden = false;
    var r = btn.getBoundingClientRect();
    helpPop.style.left = Math.min(window.innerWidth - 270, r.left) + "px";
    helpPop.style.top = (r.bottom + 6) + "px";
  }
  function hideHelp() { if (helpPop) helpPop.hidden = true; }

  // ------------------------------------------------------------------ header
  UI.initHeader = function () {
    var meta = CX.D.meta || {};
    if (meta.title) { $("app-title").textContent = meta.title; }
    $("scenario-chip").textContent = "Scenario · " + (meta.scenario || "base");
    var us = $("unit-switch");
    us.innerHTML = CX.UNITS.map(function (u) {
      return '<button type="button" data-u="' + u.id + '" aria-pressed="' + (u.id === CX.state.unit) + '">' + u.label + "</button>";
    }).join("");
    us.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-u]");
      if (!b) return;
      CX.state.unit = b.getAttribute("data-u");
      us.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      CX.emit("units");
    });
    $("about-btn").addEventListener("click", UI.openAbout);
    $("about-close").addEventListener("click", UI.closeAbout);
    $("about-modal").addEventListener("click", function (e) { if (e.target.id === "about-modal") UI.closeAbout(); });
    $("reset-btn").addEventListener("click", function () { CX.setIdx(CX.defaults()); });
  };

  // ------------------------------------------------------------------ controls
  UI.initControls = function () {
    var host = $("controls"), groups = [], byGroup = {};
    CX.controls.forEach(function (c, i) {
      var g = c.group || "Settings";
      if (!byGroup[g]) { byGroup[g] = []; groups.push(g); }
      byGroup[g].push(i);
    });
    var html = "";
    groups.forEach(function (g) {
      html += '<section class="cgroup"><span class="eyebrow">' + esc(g) + "</span>";
      byGroup[g].forEach(function (i) { html += controlHTML(CX.controls[i], i); });
      html += "</section>";
    });
    host.innerHTML = html;

    host.addEventListener("input", function (e) {
      var t = e.target;
      if (t.matches("input[type=range][data-ci]")) CX.setControl(+t.getAttribute("data-ci"), +t.value);
    });
    host.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-ci][data-si]");
      if (b) CX.setControl(+b.getAttribute("data-ci"), +b.getAttribute("data-si"));
    });
    host.querySelectorAll(".help").forEach(function (h) {
      h.addEventListener("mouseenter", function () { showHelp(h); });
      h.addEventListener("focus", function () { showHelp(h); });
      h.addEventListener("mouseleave", hideHelp);
      h.addEventListener("blur", hideHelp);
      h.addEventListener("click", function () { showHelp(h); });
    });
  };

  function controlHTML(c, i) {
    var id = "ctl-" + i;
    var head = '<div class="ctrl-head"><span class="ctrl-label" id="' + id + '-lbl">' + esc(c.label) + "</span>" +
      (c.help ? '<button type="button" class="help" data-help="' + esc(c.help) + '" aria-label="About ' + esc(c.label) + '" aria-describedby="' + id + '-help">?</button><span class="sr-only" id="' + id + '-help">' + esc(c.help) + "</span>" : "") +
      (c.kind !== "toggle" ? '<span class="ctrl-value" id="' + id + '-val"></span>' : "") + "</div>" +
      (c.unit ? '<div class="ctrl-caption">' + esc(c.unit) + "</div>" : '<div class="ctrl-caption"></div>');
    var body;
    if (c.kind === "toggle") {
      body = '<div class="toggle-row"><div class="seg" role="group" aria-labelledby="' + id + '-lbl">' +
        c.stops.map(function (s, si) {
          return '<button type="button" data-ci="' + i + '" data-si="' + si + '" aria-pressed="false">' + esc(s.label) + "</button>";
        }).join("") + "</div></div>";
    } else {
      var n = c.stops.length;
      body = '<div class="slider"><input type="range" id="' + id + '" data-ci="' + i + '" min="0" max="' + (n - 1) + '" step="1" value="0" aria-labelledby="' + id + '-lbl"></div>' +
        '<div class="ticks" aria-hidden="true">' + c.stops.map(function (s, si) {
          var show = n <= 8 || si === 0 || si === n - 1 || si % Math.ceil(n / 6) === 0;
          return '<button type="button" tabindex="-1" data-ci="' + i + '" data-si="' + si + '">' + (show ? esc(s.label) : "·") + "</button>";
        }).join("") + "</div>";
    }
    var impact = c.decision ? '<div><span class="impact" id="' + id + '-impact"></span></div>' : "";
    return '<div class="ctrl" data-ctrl="' + i + '">' + head + body + impact + "</div>";
  }

  UI.renderControls = function () {
    var idx = CX.state.idx, cur = CX.run(idx);
    CX.controls.forEach(function (c, i) {
      var id = "ctl-" + i, si = idx[i], stop = c.stops[si];
      if (c.kind === "toggle") {
        document.querySelectorAll('[data-ctrl="' + i + '"] .seg button').forEach(function (b) {
          b.setAttribute("aria-pressed", String(+b.getAttribute("data-si") === si));
        });
      } else {
        var inp = $(id);
        inp.value = si;
        inp.setAttribute("aria-valuetext", stop.label + (c.unit ? " " + c.unit : ""));
        var pct = c.stops.length > 1 ? (si / (c.stops.length - 1)) * 100 : 0;
        inp.style.setProperty("--pct", pct + "%");
        $(id + "-val").textContent = stop.label;
        document.querySelectorAll('[data-ctrl="' + i + '"] .ticks button').forEach(function (b) {
          b.classList.toggle("on", +b.getAttribute("data-si") === si);
        });
      }
      if (c.decision) renderImpact(c, i, idx, cur);
    });
    $("run-key").textContent = "run " + CX.key(idx) + (cur ? " · plan " + cur.plan : " · missing");
  };

  // What happens to the total if this decision is flipped (neighbouring run keys).
  function renderImpact(c, i, idx, cur) {
    var el = $("ctl-" + i + "-impact");
    if (!el) return;
    if (!cur) { el.textContent = ""; return; }
    var best = null;
    c.stops.forEach(function (s, si) {
      if (si === idx[i]) return;
      var alt = idx.slice(); alt[i] = si;
      var r = CX.run(alt);
      if (!r) return;
      var d = r.total_usd_per_yr - cur.total_usd_per_yr;
      var btn = document.querySelector('[data-ctrl="' + i + '"] button[data-si="' + si + '"]');
      if (btn) btn.title = "Total " + (d <= 0 ? "falls by " + CX.usd(-d) : "rises by " + CX.usd(d)) + "/yr";
      if (!best || d < best.d) best = { d: d, label: s.label };
    });
    var curBtn = document.querySelector('[data-ctrl="' + i + '"] button[data-si="' + idx[i] + '"]');
    if (curBtn) curBtn.title = "Current choice";
    if (!best) { el.textContent = ""; el.className = "impact"; return; }
    var name = c.stops.length === 2 ? "Switching to “" + best.label + "”" : "Best other: “" + best.label + "”";
    if (Math.abs(best.d) < 1) {
      el.className = "impact";
      el.innerHTML = name + ": no change";
    } else if (best.d < 0) {
      el.className = "impact good";
      el.innerHTML = name + ': <b class="num">▼ ' + CX.usd(-best.d) + "/yr</b>";
    } else {
      el.className = "impact bad";
      el.innerHTML = name + ': <span class="num">▲ +' + CX.usd(best.d) + "/yr</span>";
    }
  }

  // ------------------------------------------------------------------ KPIs
  function totalDemand() {
    var t = 0;
    CX.sinks.forEach(function (n) { t += n.demand_dst_per_yr || 0; });
    return t;
  }
  UI.renderKPIs = function () {
    var cur = CX.current(), run = cur.run, base = CX.D.baseline;
    var kT = $("kpi-total"), kS = $("kpi-today"), kB = $("kpi-best");
    var dem = totalDemand();
    if (!run) {
      kT.querySelector("[data-v]").textContent = "No run";
      kT.querySelector("[data-s]").textContent = "This combination is missing from the data.";
      kS.querySelector("[data-v]").textContent = "–"; kS.querySelector("[data-s]").textContent = "";
      kB.querySelector("[data-v]").textContent = "–"; kB.querySelector("[data-s]").textContent = "";
      return;
    }
    var total = run.total_usd_per_yr;
    kT.className = "kpi is-total";
    kT.querySelector("[data-v]").innerHTML = CX.usd(total) + "<small>/yr</small>";
    kT.querySelector("[data-s]").innerHTML = '<span class="num">' + CX.perUnit(dem ? total / dem : null) + " " + esc(CX.unitSuffix()) + "</span><span class=\"muted\">average landed · " + CX.num(dem) + " DST/yr</span>";

    var sav = base.total_usd_per_yr - total, o = CX.savings(sav);
    var pct = base.total_usd_per_yr ? Math.abs(sav) / base.total_usd_per_yr * 100 : 0;
    kS.className = "kpi " + (o.cls === "good" ? "is-good" : o.cls === "bad" ? "is-bad" : "");
    kS.querySelector("[data-v]").innerHTML = '<span class="' + o.cls + '">' + o.arrow + " " + o.text + "</span><small>" + (o.cls === "good" ? "saved /yr" : o.cls === "bad" ? "more /yr" : "/yr") + "</small>";
    kS.querySelector("[data-s]").innerHTML = '<span class="num ' + o.cls + '">' + pct.toFixed(1) + "% " + (sav >= 0 ? "below" : "above") + '</span><span class="muted">today\'s ' + CX.usd(base.total_usd_per_yr) + "/yr</span>";

    var best = CX.best(CX.state.idx), loss = best ? total - best.total : 0;
    if (!best || loss < 1) {
      kB.className = "kpi is-good";
      kB.querySelector("[data-v]").innerHTML = '<span>$0</span><small>lost /yr</small>';
      kB.querySelector("[data-s]").innerHTML = CX.decisionIdx.length ? '<span class="good">✓ You\'re on the best plan</span><span class="muted">for these assumptions</span>' : '<span class="muted">No network decisions to choose</span>';
    } else {
      var bk = best.key.split("-").map(Number), changes = [];
      CX.decisionIdx.forEach(function (i) {
        if (bk[i] !== CX.state.idx[i]) changes.push(CX.controls[i].label + ": " + CX.controls[i].stops[bk[i]].label);
      });
      kB.className = "kpi is-warn";
      kB.querySelector("[data-v]").innerHTML = '<span class="warn">⚠ ' + CX.usd(loss) + "</span><small>lost /yr</small>";
      kB.querySelector("[data-s]").innerHTML = '<button type="button" class="btn btn-primary btn-sm" id="apply-best">Apply best</button><span class="muted" title="' + esc(changes.join("; ")) + '">' + esc(changes.join(" · ")) + "</span>";
      $("apply-best").onclick = function () { CX.setIdx(bk); };
    }
  };

  // ------------------------------------------------------------------ legend
  UI.initLegend = function () {
    var el = $("legend");
    var modes = CX.modes.map(function (m) {
      return '<div class="legend-row">' + legendLineSVG(m.id) + UI.modeIcon(m.id, 13) + "<span>" + esc(m.label) + "</span></div>";
    }).join("");
    var wk = [0.1, 0.4, 1].map(function (f) {
      var q = CX.Map.REF * f, w = CX.Map.widthFor(q);
      return '<span><svg width="30" height="14" aria-hidden="true"><line x1="2" y1="7" x2="28" y2="7" stroke="#d9d9de" stroke-width="' + w.toFixed(1) + '" stroke-linecap="round"/></svg>' + kfmt(q) + "</span>";
    }).join("");
    var nodesKey = [
      { role: "source", label: "Supplier" }, { role: "intermediate", label: "Terminal" }, { role: "sink", label: "XOM site" }
    ].map(function (r) {
      return '<div class="legend-row"><span style="width:18px;display:flex;justify-content:center">' + CX.Map.markerSVG({ role: r.role }, 13) + "</span><span>" + r.label + "</span></div>";
    }).join("");
    el.innerHTML =
      '<button type="button" class="icon-btn legend-collapse" id="legend-toggle" aria-expanded="true" aria-label="Collapse legend" style="font-size:14px">–</button>' +
      '<div class="legend-sec"><h3>Legend</h3></div>' +
      '<div class="legend-body">' +
      '<div class="legend-sec" style="margin-top:0;padding-top:0;border:0"><div class="legend-modes">' + modes + "</div></div>" +
      '<div class="legend-sec"><h3>Line width = DST/yr</h3><div class="width-key">' + wk + "</div></div>" +
      '<div class="legend-sec"><div class="legend-modes">' + nodesKey + '</div><div class="legend-row muted small">Faded = available but unused</div></div>' +
      '<div class="legend-sec">' +
      '<label class="legend-check"><input type="checkbox" id="lg-base" checked><svg width="26" height="8" aria-hidden="true"><line x1="1" y1="4" x2="25" y2="4" stroke="#b4b4bb" stroke-width="2" stroke-dasharray="4 4"/></svg>Today\'s network (ghost)</label>' +
      '<label class="legend-check"><input type="checkbox" id="lg-anim"' + (CX.state.animate ? " checked" : "") + '>Animate flow direction</label>' +
      '<button type="button" class="link" id="lg-home" style="margin-top:4px">Reset view</button>' +
      "</div></div>";
    $("lg-base").addEventListener("change", function (e) { CX.state.showBaseline = e.target.checked; CX.Map.setBaselineVisible(e.target.checked); });
    $("lg-anim").addEventListener("change", function (e) { CX.Map.setAnimate(e.target.checked); });
    $("lg-home").addEventListener("click", function () { CX.Map.home(); });
    $("legend-toggle").addEventListener("click", function () {
      var c = el.classList.toggle("collapsed");
      this.setAttribute("aria-expanded", String(!c));
      this.textContent = c ? "+" : "–";
      this.setAttribute("aria-label", c ? "Expand legend" : "Collapse legend");
    });
  };
  function kfmt(q) { return q >= 1000 ? Math.round(q / 1000) + "k" : Math.round(q); }
  function legendLineSVG(mode) {
    var c = CX.modeColor(mode), extra = "";
    if (mode === "rail") extra = '<line x1="2" y1="6" x2="24" y2="6" stroke="' + c + '" stroke-width="8" stroke-dasharray="1.5 4"/>';
    if (mode === "barge") extra = '<line x1="2" y1="6" x2="24" y2="6" stroke="#06231a" stroke-width="1.6"/>';
    if (mode === "ocean") extra = '<line x1="2" y1="6" x2="24" y2="6" stroke="' + c + '" stroke-width="9" stroke-opacity=".3" stroke-linecap="round"/>';
    return '<svg width="26" height="12" aria-hidden="true">' + (mode === "ocean" ? extra : "") +
      '<line x1="2" y1="6" x2="24" y2="6" stroke="' + c + '" stroke-width="4" stroke-linecap="round"/>' + (mode !== "ocean" ? extra : "") + "</svg>";
  }

  // ------------------------------------------------------------------ detail drawer
  UI.initDrawer = function () {
    $("drawer-close").addEventListener("click", function () { CX.select(null); });
    $("drawer-tabs").addEventListener("click", function (e) {
      var b = e.target.closest("button[data-sel]");
      if (!b) return;
      CX.select(JSON.parse(b.getAttribute("data-sel")));
    });
    $("drawer-body").addEventListener("click", function (e) {
      var b = e.target.closest("[data-sel]");
      if (!b) return;
      CX.select(JSON.parse(b.getAttribute("data-sel")));
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (!$("about-modal").hidden) UI.closeAbout();
      else if (CX.state.sel) CX.select(null);
    });
  };

  function selAttr(o) { return esc(JSON.stringify(o)); }

  UI.renderDrawer = function () {
    var sel = CX.state.sel, drawer = $("drawer"), stage = $("stage");
    var plan = CX.current().plan;
    if (!sel) {
      if (!drawer.hidden) { drawer.hidden = true; stage.classList.remove("drawer-open"); CX.Map.resize(); }
      return;
    }
    var html = "", tabs = "", siteId = null;
    if (sel.type === "route") {
      var r = findRoute(plan, sel.sig);
      if (!r) {
        // route no longer in this plan -> show its site instead
        siteId = sel.site;
        html = '<p class="muted small" style="margin:0 0 12px">That route is not used in the current plan. Showing the site instead.</p>' + siteHTML(plan, siteId);
      } else {
        siteId = r.site;
        html = routeHTML(plan, r, sel);
      }
    } else if (sel.type === "site") {
      siteId = sel.id;
      html = siteHTML(plan, siteId);
    } else if (sel.type === "node") {
      html = nodeHTML(plan, sel.id);
    }
    if (siteId) {
      tabs += '<button type="button" aria-pressed="' + (sel.type === "site" || (sel.type === "route" && !findRoute(plan, sel.sig))) + '" data-sel="' + selAttr({ type: "site", id: siteId }) + '">' + esc(CX.label(siteId)) + " · site</button>";
      var routes = (plan && plan.routes || []).filter(function (x) { return x.site === siteId; });
      routes.forEach(function (x, k) {
        var sig = CX.routeSig(x);
        tabs += '<button type="button" aria-pressed="' + (sel.type === "route" && sel.sig === sig) + '" data-sel="' + selAttr({ type: "route", sig: sig, site: siteId }) + '">Route ' + (k + 1) + " · " + esc(CX.label(x.supplier)) + "</button>";
      });
    } else {
      tabs = '<span class="eyebrow" style="align-self:center">' + esc(CX.Map.roleName(CX.nodeById[sel.id] || {})) + "</span>";
    }
    $("drawer-tabs").innerHTML = tabs;
    $("drawer-body").innerHTML = html;
    UI.hideTip();
    if (drawer.hidden) { drawer.hidden = false; stage.classList.add("drawer-open"); CX.Map.resize(); }
  };

  function findRoute(plan, sig) {
    var rs = plan && plan.routes || [];
    for (var i = 0; i < rs.length; i++) if (CX.routeSig(rs[i]) === sig) return rs[i];
    return null;
  }

  function chainHTML(r) {
    var legs = r.legs || [], html = '<div class="chain">';
    var first = legs.length ? legs[0].from : r.supplier;
    html += chainNode(first, r.supplier === first ? "supplier" : "");
    legs.forEach(function (l) {
      html += '<div class="chain-leg"><span class="rail"><i style="background:' + CX.modeColor(l.mode) + '"></i></span><span class="leg-info">' +
        UI.modePill(l.mode) + '<span class="num">' + (l.miles != null ? CX.num(l.miles) + " mi" : "") + "</span>" +
        '<span class="muted">· ' + CX.perUnit(CX.legCost(l)) + " " + esc(CX.unitSuffix()) + "</span></span></div>";
      html += chainNode(l.to, l.to === r.site ? "XOM site" : "");
    });
    return html + "</div>";
  }
  function chainNode(id, tag) {
    var n = CX.nodeById[id] || { role: "source" };
    return '<div class="chain-node"><span class="dot">' + CX.Map.markerSVG(n, 14) + "</span><span>" + esc(CX.label(id)) +
      ' <span class="meta">' + esc(tag || CX.Map.roleName(n)) + "</span></span></div>";
  }

  // Waterfall: caustic price, then each leg's freight / handling / terminal, to landed.
  function waterfallHTML(r) {
    var rows = [], q = r.dst_per_yr || 0;
    var product = r.product_usd_per_dst || 0;
    rows.push({ grp: "Product" });
    rows.push({ label: "Caustic · " + CX.label(r.supplier), v: product, comp: "product" });
    (r.legs || []).forEach(function (l, i) {
      rows.push({ grp: "Leg " + (i + 1) + " · " + CX.modeLabel(l.mode) + " · " + CX.label(l.from) + " → " + CX.label(l.to) });
      rows.push({ label: "Freight", v: l.line_haul_usd_per_dst || 0, comp: "line_haul" });
      rows.push({ label: "Loading / unloading", v: l.handling_usd_per_dst || 0, comp: "handling" });
      if (l.terminal_usd_per_dst) rows.push({ label: "Terminal fee · " + CX.label(l.to), v: l.terminal_usd_per_dst, comp: "terminal" });
    });
    var landed = r.landed_usd_per_dst != null ? r.landed_usd_per_dst : rows.reduce(function (a, x) { return a + (x.v || 0); }, 0);
    var transport = Math.max(0, landed - product);
    // Broken axis: start the scale below the product price so the fees are visible.
    var lo = product > 0 && transport > 0 ? Math.max(0, product - transport * 0.6) : 0;
    var span = Math.max(1e-9, landed - lo);
    var cum = 0, html = '<table class="wf"><tbody>';
    rows.forEach(function (x) {
      if (x.grp) { html += '<tr class="grp"><td colspan="4">' + esc(x.grp) + "</td></tr>"; return; }
      var a = cum, b = cum + x.v; cum = b;
      var l = Math.max(0, (a - lo) / span * 100), w = Math.max(0, (b - lo) / span * 100) - l;
      var brk = x.comp === "product" && lo > 0 ? '<span class="brk" style="left:12%"></span>' : "";
      html += '<tr><td class="lbl">' + esc(x.label) + '</td><td class="bar"><div class="track"><span class="seg-bar" style="left:' + l.toFixed(2) + "%;width:" + w.toFixed(2) + "%;background:" + CX.compColor(x.comp) + '"></span>' + brk + "</div></td>" +
        '<td class="val">' + CX.perUnit(x.v) + '</td><td class="yr">' + CX.usd(x.v * q) + "</td></tr>";
    });
    html += '<tr class="total"><td class="lbl">Landed cost</td><td class="bar"><div class="track"><span class="seg-bar" style="left:0;width:100%;background:linear-gradient(90deg,#2424f5,#ab7dc5)"></span><span class="brk" style="left:12%"></span></div></td>' +
      '<td class="val">' + CX.perUnit(landed) + '</td><td class="yr">' + CX.usd(r.usd_per_yr != null ? r.usd_per_yr : landed * q) + "</td></tr>";
    html += "</tbody></table>";
    html += '<div class="wf-note">' + esc(CX.unitLabel()) + " and $/yr. " + (lo > 0 ? "Bars use a broken axis (starting near the caustic price) so freight and fees stay visible." : "") + "</div>";
    return html;
  }

  function routeHTML(plan, r, sel) {
    var chips = CX.routeChips(plan, r).map(chipHTML).join("");
    var miles = 0;
    (r.legs || []).forEach(function (l) { miles += l.miles || 0; });
    var bs = CX.baseSite(r.site), ps = CX.siteSummary(plan, r.site);
    var html = '<span class="eyebrow">Route</span>' +
      '<div class="d-title">' + esc(CX.label(r.supplier)) + " → " + esc(CX.label(r.site)) + "</div>" +
      '<div class="d-sub">' + CX.dst(r.dst_per_yr) + " · " + (r.legs || []).length + " leg" + ((r.legs || []).length === 1 ? "" : "s") + " · " + CX.num(miles) + " mi</div>" +
      (chips ? '<div class="d-chips">' + chips + "</div>" : "");
    html += '<div class="d-stats">' +
      stat("Landed", CX.perUnit(r.landed_usd_per_dst), CX.unitSuffix()) +
      stat("Per year", CX.usd(r.usd_per_yr), "this route") +
      stat("vs today", perUnitDelta(bs.landed, r.landed_usd_per_dst), "per " + CX.unitSuffix().replace("/", "")) + "</div>";
    html += '<div class="d-sec"><span class="eyebrow">Path</span>' + chainHTML(r) + "</div>";
    html += '<div class="d-sec"><span class="eyebrow">Landed cost build-up</span>' + waterfallHTML(r) + "</div>";
    html += '<div class="d-sec"><span class="eyebrow">Compared with today at ' + esc(CX.label(r.site)) + "</span>" + compareHTML(bs, ps, r) + "</div>";
    if (sel.siblings && sel.siblings.length > 1) {
      var others = sel.siblings.filter(function (s) { return s !== sel.sig; }).map(function (s) { return findRoute(plan, s); }).filter(Boolean);
      if (others.length) {
        html += '<div class="d-sec"><span class="eyebrow">Also on this leg</span>' + others.map(function (o) { return routeCard(o, false); }).join("") + "</div>";
      }
    }
    return html;
  }
  function stat(lbl, val, sub) {
    return '<div class="d-stat"><span class="eyebrow">' + esc(lbl) + "</span><b>" + val + '</b><span class="small">' + esc(sub || "") + "</span></div>";
  }
  function perUnitDelta(today, plan) {
    if (today == null || plan == null) return "–";
    var d = today - plan;
    if (Math.abs(d) < 0.005) return "=";
    return '<span class="' + (d > 0 ? "good" : "bad") + '">' + (d > 0 ? "▼ " : "▲ ") + CX.perUnit(Math.abs(d)) + "</span>";
  }
  function siteTodayText(siteId) {
    var bs = CX.baseSite(siteId);
    return bs.routes.map(function (x) { return CX.label(x.supplier) + " (" + (x.legs || []).map(function (l) { return CX.modeLabel(l.mode).toLowerCase(); }).join(" → ") + ")"; }).join(", ");
  }
  function compareHTML(bs, ps, r) {
    var sav = bs.total - ps.total;
    var html = '<div class="compare">' +
      '<div class="compare-row"><span>Today · ' + esc(siteTodayText(bs.site)) + "</span><b>" + CX.perUnit(bs.landed) + "</b></div>";
    if (r) html += '<div class="compare-row"><span>This route</span><b>' + CX.perUnit(r.landed_usd_per_dst) + "</b></div>";
    if (!r || ps.routes.length > 1) html += '<div class="compare-row"><span>Plan, all routes into site</span><b>' + CX.perUnit(ps.landed) + "</b></div>";
    if (ps.extras > 0) html += '<div class="compare-row"><span>Switching &amp; construction at site</span><b>' + CX.usd(ps.extras) + "/yr</b></div>";
    html += '<div class="compare-row big"><span>' + (sav >= 0 ? "Saved at this site" : "Extra cost at this site") + "</span><b>" + CX.savingsHTML(sav, " /yr", " /yr") + "</b></div>";
    return html + "</div>";
  }
  function routeCard(r, ghost) {
    var modes = (r.legs || []).map(function (l, i) {
      return (i ? '<span aria-hidden="true">›</span>' : "") + UI.modeIcon(l.mode, 13) + "<span>" + esc(CX.modeLabel(l.mode)) + (l.to !== r.site ? " to " + esc(CX.label(l.to)) : "") + "</span>";
    }).join(" ");
    var inner = '<div class="rcard-top"><span>' + esc(CX.label(r.supplier)) + " → " + esc(CX.label(r.site)) + '</span><span class="num">' + CX.perUnit(r.landed_usd_per_dst) + "</span></div>" +
      '<div class="rcard-modes">' + modes + ' <span style="margin-left:auto" class="num">' + CX.num(r.dst_per_yr) + " DST/yr</span></div>";
    if (ghost) return '<div class="rcard ghost">' + inner + "</div>";
    return '<button type="button" class="rcard" data-sel="' + selAttr({ type: "route", sig: CX.routeSig(r), site: r.site }) + '">' + inner + "</button>";
  }

  function compRows(sumA, sumB, divA, divB, perUnit) {
    var html = '<table class="mini"><thead><tr><th>Component</th><th>Today</th><th>Plan</th><th>Δ</th></tr></thead><tbody>';
    CX.components.forEach(function (c) {
      var a = sumA[c.id] || 0, b = sumB[c.id] || 0;
      if (Math.abs(a) < 0.5 && Math.abs(b) < 0.5) return;
      var fa = perUnit ? CX.perUnit(divA ? a / divA : 0) : CX.usd(a);
      var fb = perUnit ? CX.perUnit(divB ? b / divB : 0) : CX.usd(b);
      var d = perUnit ? (divA ? a / divA : 0) - (divB ? b / divB : 0) : a - b;
      var cls = Math.abs(d) < (perUnit ? 0.005 : 0.5) ? "" : d > 0 ? "good" : "bad";
      var fd = !cls ? "=" : (d > 0 ? "▼ " : "▲ ") + (perUnit ? CX.perUnit(Math.abs(d)) : CX.usd(Math.abs(d)));
      html += '<tr><td><span class="sw" style="background:' + CX.compColor(c.id) + '"></span> ' + esc(c.label) + "</td><td>" + fa + "</td><td>" + fb + '</td><td class="' + cls + '">' + fd + "</td></tr>";
    });
    return html + "</tbody></table>";
  }
  function stackHTML(rows) {
    var max = 0;
    rows.forEach(function (r) { var t = 0; CX.components.forEach(function (c) { t += Math.max(0, r.vals[c.id] || 0); }); r.t = t; max = Math.max(max, t); });
    var html = '<div class="stack-chart">';
    rows.forEach(function (r) {
      var segs = CX.components.map(function (c) {
        var v = Math.max(0, r.vals[c.id] || 0);
        if (v <= 0) return "";
        return '<i style="width:' + (v / max * 100).toFixed(3) + "%;background:" + CX.compColor(c.id) + '" title="' + esc(c.label) + ": " + esc(r.fmt(v)) + '"></i>';
      }).join("");
      html += '<div class="stack-row"><span class="nm">' + esc(r.name) + '</span><div class="stack" style="width:' + (r.t / max * 100).toFixed(2) + '%">' + segs + '</div><span class="tot">' + r.fmt(r.t) + "</span></div>";
    });
    html += "</div>";
    html += '<div class="comp-legend">' + CX.components.filter(function (c) {
      return rows.some(function (r) { return (r.vals[c.id] || 0) > 0; });
    }).map(function (c) { return '<span><i class="sw" style="background:' + CX.compColor(c.id) + '"></i>' + esc(c.label) + "</span>"; }).join("") + "</div>";
    return html;
  }

  function siteHTML(plan, siteId) {
    var n = CX.nodeById[siteId] || { id: siteId };
    var bs = CX.baseSite(siteId), ps = CX.siteSummary(plan, siteId);
    var dem = n.demand_dst_per_yr || ps.dst || bs.dst;
    var chips = CX.siteChips(plan, siteId).map(chipHTML).join("");
    var unchanged = sameAsToday(bs, ps);
    var rebal = !unchanged && ps.extras === 0 && ps.routes.every(function (r) { return r.current; });
    var html = '<span class="eyebrow">XOM site</span><div class="d-title">' + esc(n.label || n.id) + "</div>" +
      '<div class="d-sub">' + esc([n.city, n.region, n.country].filter(Boolean).join(", ")) + " · demand " + CX.dst(dem) + "</div>" +
      '<div class="d-chips">' + (chips || (unchanged ? '<span class="chip chip-same">same as today</span>' : rebal ? '<span class="chip chip-same">volumes shifted between today\'s lanes</span>' : "")) + "</div>";
    html += '<div class="d-stats">' + stat("Today", CX.perUnit(bs.landed), CX.unitSuffix()) + stat("Plan", CX.perUnit(ps.landed), CX.unitSuffix()) +
      stat("Saved", CX.savingsHTML(bs.total - ps.total), "per year, incl. switching") + "</div>";
    var fmtU = function (v) { return CX.perUnit(v); };
    var perA = {}, perB = {};
    CX.components.forEach(function (c) { perA[c.id] = bs.dst ? (bs.comp[c.id] || 0) / bs.dst : 0; perB[c.id] = ps.dst ? (ps.comp[c.id] || 0) / ps.dst : 0; });
    html += '<div class="d-sec"><span class="eyebrow">Cost per ' + esc(CX.unitSuffix().replace("/", "")) + ", today vs plan</span>" +
      stackHTML([{ name: "Today", vals: perA, fmt: fmtU }, { name: "Plan", vals: perB, fmt: fmtU }]) +
      compRows(bs.comp, ps.comp, bs.dst, ps.dst, true) + "</div>";
    html += '<div class="d-sec"><span class="eyebrow">Plan routes (' + ps.routes.length + ")</span>" + (ps.routes.map(function (r) { return routeCard(r, false); }).join("") || '<p class="muted small">No routes into this site in this plan.</p>') + "</div>";
    html += '<div class="d-sec"><span class="eyebrow">Today\'s routes</span>' + bs.routes.map(function (r) { return routeCard(r, true); }).join("") + "</div>";
    return html;
  }

  function nodeHTML(plan, id) {
    var n = CX.nodeById[id] || { id: id };
    var vol = CX.Map.nodeVolumes(plan), bvol = CX.Map.nodeVolumes(CX.D.baseline);
    var routes = (plan && plan.routes || []).filter(function (r) {
      return r.supplier === id || (r.legs || []).some(function (l) { return l.from === id || l.to === id; });
    });
    var html = '<span class="eyebrow">' + esc(CX.Map.roleName(n)) + '</span><div class="d-title">' + esc(n.label || n.id) + "</div>" +
      '<div class="d-sub">' + esc([n.city, n.region, n.country].filter(Boolean).join(", ")) + "</div>";
    html += '<div class="d-stats">' + stat("Plan volume", CX.num(vol[id] || 0), "DST/yr") + stat("Today", CX.num(bvol[id] || 0), "DST/yr") +
      (n.price_usd_per_dst != null ? stat("List price", CX.perUnit(n.price_usd_per_dst), CX.unitSuffix()) :
        n.terminal_fee_usd_per_dst != null ? stat("Terminal fee", CX.perUnit(n.terminal_fee_usd_per_dst), CX.unitSuffix()) : stat("", "", "")) + "</div>";
    var modes = (n.modes || []).map(function (m) { return UI.modePill(m); }).join(" ");
    var cand = (n.candidate_modes || []).map(function (m) { return UI.modePill(m, true); }).join(" ");
    html += '<div class="d-sec"><span class="eyebrow">Modes</span><div class="d-chips" style="margin-top:0">' + (modes || '<span class="muted small">none listed</span>') + "</div>" +
      (cand ? '<div class="small muted" style="margin-top:8px">Needs construction:</div><div class="d-chips" style="margin-top:4px">' + cand + "</div>" : "") + "</div>";
    html += '<div class="d-sec"><span class="eyebrow">Routes through here in this plan (' + routes.length + ")</span>" +
      (routes.map(function (r) { return routeCard(r, false); }).join("") || '<p class="muted small">Not used in this plan.</p>') + "</div>";
    return html;
  }

  // ------------------------------------------------------------------ data drawer
  var sortKey = "savings", sortDir = -1;
  var COLS = [
    { k: "site", t: "Site", r: false },
    { k: "demand", t: "DST/yr", r: true },
    { k: "todayU", t: "Today $", r: true, unit: true },
    { k: "planU", t: "Plan $", r: true, unit: true },
    { k: "savings", t: "Savings $/yr", r: true },
    { k: "extras", t: "Switch + build $/yr", r: true },
    { k: "today", t: "Today's supply", r: false },
    { k: "plan", t: "Plan supply", r: false }
  ];
  UI.initData = function () {
    $("dd-toggle").addEventListener("click", function () {
      var dd = $("datadrawer"), open = !dd.classList.contains("open");
      dd.classList.toggle("open", open);
      $("stage").classList.toggle("dd-open", open);
      $("dd-content").hidden = !open;
      this.setAttribute("aria-expanded", String(open));
      if (open) UI.renderData();
    });
    $("site-table").addEventListener("click", function (e) {
      var th = e.target.closest("button[data-sort]");
      if (th) {
        var k = th.getAttribute("data-sort");
        if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = k === "site" || k === "today" || k === "plan" ? 1 : -1; }
        UI.renderData();
        return;
      }
      var tr = e.target.closest("tr[data-site]");
      if (tr) CX.select({ type: "site", id: tr.getAttribute("data-site") });
    });
    $("site-table").addEventListener("keydown", function (e) {
      var tr = e.target.closest("tr[data-site]");
      if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); CX.select({ type: "site", id: tr.getAttribute("data-site") }); }
    });
    $("csv-btn").addEventListener("click", downloadCSV);
  };

  function siteRows(plan) {
    return CX.sinks.map(function (n) {
      var bs = CX.baseSite(n.id), ps = CX.siteSummary(plan, n.id);
      var todaySup = uniq(bs.routes.map(function (r) { return CX.label(r.supplier); }));
      var planSup = uniq(ps.routes.map(function (r) { return CX.label(r.supplier); }));
      return {
        id: n.id, site: n.label || n.id, demand: n.demand_dst_per_yr || ps.dst,
        today: todaySup.join(", "), todayRoutes: bs.routes,
        plan: planSup.join(", "), planRoutes: ps.routes,
        todayU: bs.landed, planU: ps.landed, extras: ps.extras,
        savings: bs.total - ps.total, chips: CX.siteChips(plan, n.id),
        unchanged: sameAsToday(bs, ps),
        rebalanced: !sameAsToday(bs, ps) && ps.extras === 0 && ps.routes.every(function (r) { return r.current; })
      };
    });
  }
  function sameAsToday(bs, ps) {
    if (ps.extras !== 0 || bs.routes.length !== ps.routes.length) return false;
    var m = {};
    bs.routes.forEach(function (r) { m[CX.routeSig(r)] = r.dst_per_yr; });
    return ps.routes.every(function (r) { var q = m[CX.routeSig(r)]; return q != null && Math.abs(q - r.dst_per_yr) < 0.5; });
  }
  UI.sameAsToday = sameAsToday;
  function uniq(a) { var s = {}, o = []; a.forEach(function (x) { if (!s[x]) { s[x] = 1; o.push(x); } }); return o; }
  function modesInline(routes) {
    var seen = {}, out = [];
    routes.forEach(function (r) {
      var m = (r.legs || []).map(function (l) { return l.mode; }).join(">");
      if (seen[m]) return; seen[m] = 1;
      out.push((r.legs || []).map(function (l) { return UI.modeIcon(l.mode, 12) + esc(CX.modeLabel(l.mode).toLowerCase()); }).join(" › "));
    });
    return out.join(" &nbsp;·&nbsp; ");
  }

  UI.renderData = function () {
    var cur = CX.current(), plan = cur.plan, run = cur.run, base = CX.D.baseline;
    var rows = siteRows(plan);
    var changed = rows.filter(function (r) { return !r.unchanged; }).length;
    $("dd-summary").textContent = rows.length + " sites · " + changed + " changed vs today";
    if (!$("datadrawer").classList.contains("open")) return;

    rows.sort(function (a, b) {
      var x = a[sortKey], y = b[sortKey];
      if (typeof x === "string" || typeof y === "string") return sortDir * String(x).localeCompare(String(y));
      return sortDir * ((x == null ? -Infinity : x) - (y == null ? -Infinity : y));
    });
    var head = "<thead><tr>" + COLS.map(function (c) {
      var s = sortKey === c.k ? ' aria-sort="' + (sortDir > 0 ? "ascending" : "descending") + '"' : "";
      var arrow = sortKey === c.k ? (sortDir > 0 ? " ↑" : " ↓") : "";
      var t = c.unit ? c.t.replace("$", CX.unitLabel()) : c.t;
      return '<th class="' + (c.r ? "r" : "") + '"' + s + '><button type="button" data-sort="' + c.k + '">' + esc(t) + arrow + "</button></th>";
    }).join("") + "</tr></thead>";
    var selSite = CX.state.sel && (CX.state.sel.type === "site" ? CX.state.sel.id : CX.state.sel.site);
    var body = "<tbody>" + rows.map(function (r) {
      return '<tr data-site="' + esc(r.id) + '" tabindex="0" class="' + (selSite === r.id ? "sel" : "") + '">' +
        '<td class="sitecell"><b>' + esc(r.site) + "</b></td>" +
        '<td class="r">' + CX.num(r.demand) + "</td>" +
        '<td class="r">' + CX.perUnit(r.todayU) + "</td>" +
        '<td class="r">' + CX.perUnit(r.planU) + "</td>" +
        '<td class="r">' + CX.savingsHTML(r.savings) + "</td>" +
        '<td class="r">' + (r.extras ? CX.usd(r.extras) : '<span class="muted">–</span>') + "</td>" +
        '<td class="wrap">' + esc(r.today) + '<div class="via">' + modesInline(r.todayRoutes) + "</div></td>" +
        '<td class="wrap">' + esc(r.plan) + '<div class="via">' + modesInline(r.planRoutes) + "</div>" +
        '<div class="chips">' + (r.chips.length ? r.chips.map(function (c) { return '<span class="chip ' + c.cls + '">' + esc(c.text) + "</span>"; }).join("") : (r.unchanged ? '<span class="chip chip-same">same as today</span>' : r.rebalanced ? '<span class="chip chip-same">volumes shifted</span>' : "")) + "</div></td></tr>";
    }).join("");
    var shared = CX.sharedExtras(plan);
    if (shared.total > 0) {
      var what = shared.builds.map(function (b) { return CX.modeLabel(b.mode).toLowerCase() + " at " + CX.label(b.site); });
      body += '<tr class="shared"><td class="sitecell"><b>Shared infrastructure</b></td><td></td><td></td><td></td><td class="r">' + CX.savingsHTML(-shared.total) + '</td><td class="r">' + CX.usd(shared.total) +
        '</td><td class="muted">–</td><td class="wrap">' + esc(what.join(", ")) + '<div class="chips"><span class="chip chip-build">builds</span></div></td></tr>';
    }
    body += "</tbody>";
    var dem = rows.reduce(function (a, r) { return a + (r.demand || 0); }, 0);
    var foot = '<tfoot><tr><td>Total</td><td class="r">' + CX.num(dem) + "</td>" +
      '<td class="r">' + CX.perUnit(dem ? base.total_usd_per_yr / dem : null) + "</td>" +
      '<td class="r">' + (run ? CX.perUnit(dem ? run.total_usd_per_yr / dem : null) : "–") + "</td>" +
      '<td class="r">' + (run ? CX.savingsHTML(base.total_usd_per_yr - run.total_usd_per_yr) : "–") + "</td>" +
      '<td class="r">' + CX.usd(rows.reduce(function (a, r) { return a + r.extras; }, 0) + shared.total) + "</td><td></td><td></td></tr></tfoot>";
    $("site-table").innerHTML = head + body + foot;

    // side: network cost breakdown, today vs plan
    var fmt = function (v) { return CX.usd(v); };
    var side = '<span class="eyebrow">Network cost by component · $/yr</span><div style="margin-top:10px">' +
      stackHTML([{ name: "Today", vals: base.breakdown || {}, fmt: fmt }, { name: "Plan", vals: (plan && plan.breakdown) || {}, fmt: fmt }]) + "</div>" +
      compRows(base.breakdown || {}, (plan && plan.breakdown) || {}, 1, 1, false);
    $("dd-side").innerHTML = side;
  };

  function downloadCSV() {
    var plan = CX.current().plan, rows = siteRows(plan), u = CX.unit();
    var head = ["site", "demand_dst_per_yr", "today_suppliers", "today_modes", "plan_suppliers", "plan_routes", "changes",
      "today_landed_" + u.id, "plan_landed_" + u.id, "switch_build_usd_per_yr", "savings_usd_per_yr"];
    var lines = [head.join(",")];
    function q(s) { s = String(s == null ? "" : s); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }
    function pathTxt(routes) {
      return routes.map(function (r) { return CX.label(r.supplier) + ": " + (r.legs || []).map(function (l) { return l.mode + " to " + CX.label(l.to); }).join(" > "); }).join(" | ");
    }
    rows.forEach(function (r) {
      lines.push([r.id, r.demand && r.demand.toFixed(2), r.today, uniq(r.todayRoutes.map(function (x) { return (x.legs || []).map(function (l) { return l.mode; }).join(">"); })).join(" | "),
        r.plan, pathTxt(r.planRoutes), r.chips.map(function (c) { return c.text; }).join("; "),
        r.todayU != null ? (r.todayU * u.f).toFixed(2) : "", r.planU != null ? (r.planU * u.f).toFixed(2) : "",
        r.extras.toFixed(2), r.savings.toFixed(2)].map(q).join(","));
    });
    var shared = CX.sharedExtras(plan);
    if (shared.total > 0) lines.push(["Shared infrastructure", "", "", "", "", "", shared.builds.map(function (b) { return b.mode + " at " + b.site; }).join("; "), "", "", shared.total.toFixed(2), (-shared.total).toFixed(2)].map(q).join(","));
    var blob = new Blob([lines.join("\n") + "\n"], { type: "text/csv" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "caustic_plan_" + CX.key(CX.state.idx) + ".csv";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }

  // ------------------------------------------------------------------ About
  var lastFocus = null;
  UI.openAbout = function () {
    var meta = CX.D.meta || {};
    var html = "";
    html += "<p>Each combination of the left-hand settings was solved in advance by the optimization model. The map shows the cheapest plan for the settings you picked; the grey dashed lines are XOM's network today.</p>";
    html += "<p><b>Savings</b> = today's total minus the plan's total (▼ green = cheaper than today, ▲ red = more expensive). <b>Loss vs. best</b> compares your network decisions with the best decisions for the same market, switching-cost and capacity assumptions.</p>";
    if (meta.notes && meta.notes.length) html += "<h3>Notes</h3><ul>" + meta.notes.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") + "</ul>";
    if (meta.assumptions && meta.assumptions.length) html += "<h3>Assumptions</h3><dl>" + meta.assumptions.map(function (a) { return "<dt>" + esc(a.id) + "</dt><dd>" + esc(a.text) + "</dd>"; }).join("") + "</dl>";
    html += '<h3>Units</h3><p class="small">DST = dry short ton. $/DMT = $/DST × 1.10231. $/wet MT (50% solution) = $/DMT × 0.5. $/yr figures are unaffected by the unit switch.</p>';
    html += '<p class="small muted">Generated ' + esc(meta.generated_at || "–") + " · scenario " + esc(meta.scenario || "–") + " · " + Object.keys(CX.D.runs || {}).length.toLocaleString() + " runs · " + Object.keys(CX.D.plans || {}).length.toLocaleString() + " distinct plans" + (window.APP_GEOMETRY ? " · routed lane shapes" : " · lanes drawn as arcs (no geometry.js)") + "</p>";
    $("about-body").innerHTML = html;
    lastFocus = document.activeElement;
    $("about-modal").hidden = false;
    $("about-close").focus();
  };
  UI.closeAbout = function () {
    $("about-modal").hidden = true;
    if (lastFocus) lastFocus.focus();
  };
})();
