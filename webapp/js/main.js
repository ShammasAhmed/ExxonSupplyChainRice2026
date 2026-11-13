/* main.js -- boot + wiring between state, map and panels. */
(function () {
  "use strict";
  var CX = window.CX;

  function fail(msg) {
    var el = document.getElementById("boot-error");
    el.hidden = false;
    el.innerHTML = "<h2>Can't start the app</h2><p>" + msg + "</p>";
  }
  if (!CX || !CX.D) { fail("<code>data/app_data.js</code> did not load (window.APP_DATA is missing)."); return; }
  if (!CX.controls.length || !CX.D.runs || !CX.D.plans || !CX.D.baseline) { fail("APP_DATA is missing controls, runs, plans or baseline. See webapp/DATA_SCHEMA.md."); return; }

  // Restore state from the URL hash (#run=2-0-...&u=dmt) so views are shareable.
  function readHash() {
    var h = (location.hash || "").replace(/^#/, ""), out = {};
    h.split("&").forEach(function (kv) { var p = kv.split("="); if (p[0]) out[p[0]] = decodeURIComponent(p[1] || ""); });
    if (out.run) {
      var idx = out.run.split("-").map(Number);
      var ok = idx.length === CX.controls.length && idx.every(function (v, i) { return v >= 0 && v < CX.controls[i].stops.length; });
      if (ok && CX.D.runs[out.run]) CX.state.idx = idx;
    }
    if (out.v === "today") CX.state.view = "today";
    if (out.u && CX.UNITS.some(function (u) { return u.id === out.u; })) CX.state.unit = out.u;
  }
  var hashTimer = null;
  function writeHash() {
    clearTimeout(hashTimer);
    hashTimer = setTimeout(function () {
      var h = "#run=" + CX.key(CX.state.idx) + (CX.state.unit !== "dst" ? "&u=" + CX.state.unit : "") + (CX.isToday() ? "&v=today" : "");
      if (location.hash !== h) {
        try { history.replaceState(null, "", h); } catch (e) { /* file:// in some browsers */ }
      }
    }, 150);
  }
  readHash();

  CX.UI.initHeader();
  CX.UI.initControls();
  CX.UI.initLegend();
  CX.UI.initDrawer();
  CX.UI.initData();
  CX.Map.init(document.getElementById("map"));

  function renderAll() {
    var cur = CX.current();
    CX.UI.renderControls();
    CX.UI.renderKPIs();
    CX.Map.update(cur.plan);
    CX.UI.renderDrawer();
    CX.UI.renderData();
    writeHash();
  }
  CX.on("change", renderAll);
  CX.on("units", function () {
    CX.UI.renderKPIs();
    CX.UI.renderDrawer();
    CX.UI.renderData();
    writeHash();
  });
  CX.on("select", function () {
    CX.UI.renderDrawer();
    CX.Map.applySelection();
    CX.UI.renderData();
  });
  window.addEventListener("resize", function () { CX.Map.resize(); });
  renderAll();
})();
