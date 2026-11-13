# Webapp data contract

The webapp is a static site (`webapp/index.html`), no server. It reads two
optional-at-dev-time JavaScript data files, loaded with classic `<script>` tags
so the page works from `file://`:

| File | Global | Written by |
|---|---|---|
| `webapp/data/app_data.js` | `window.APP_DATA` | `build_webapp_data.py` (precomputed model grid) |
| `webapp/data/geometry.js` | `window.APP_GEOMETRY` | `scripts/build_route_geometry.py` (routed lane shapes) |

Money is US dollars. Volume is dry short tons (DST). "per yr" = per year.

## `window.APP_DATA`

```js
{
  meta: {
    title: "Caustic soda network",
    generated_at: "2026-11-13T04:00:00Z",
    scenario: "base",                 // demand scenario used for every run
    notes: ["...", "..."],            // short caveats shown in an "About the data" panel
    assumptions: [{ id: "A5", text: "..." }]
  },

  nodes: [{
    id: "Olin Plaquemine Plant",       // exact site name; every other reference uses this id
    label: "Plaquemine",               // short display name
    role: "source" | "intermediate" | "sink",
    kind: "producer" | "distributor" | "export" | "terminal" | "railhead" | "xom_site",
    lat: 30.268, lon: -91.223,
    city: "Plaquemine", region: "Louisiana", country: "USA",
    demand_dst_per_yr: 45856,          // sinks only, else null
    price_usd_per_dst: 400,            // sources only (list price), else null
    terminal_fee_usd_per_dst: 9.07,    // intermediates only, else null
    modes: ["barge", "truck"],         // modes available today
    candidate_modes: ["rail"]          // modes that need construction
  }],

  modes: [{ id: "truck", label: "Truck" }, { id: "rail", label: "Rail" },
          { id: "barge", label: "Barge" }, { id: "ocean", label: "Ocean" }],

  // Order matters: run keys index into this array.
  controls: [{
    id: "china_ocean",
    label: "China ocean freight",
    group: "Market" | "Switching costs" | "Capacity" | "Network decisions",
    kind: "slider" | "toggle",
    decision: false,      // true = something XOM chooses (build / open a hub).
                          // false = an assumption about the world.
    help: "One-sentence explanation shown on hover.",
    unit: "$/wet MT",     // optional
    stops: [{ label: "Off", value: null }, { label: "$185", value: 185 }, ...],
    default: 2            // index into stops
  }],

  cost_components: [      // display order and labels for every breakdown
    { id: "product",         label: "Caustic (product)" },
    { id: "line_haul",       label: "Freight" },
    { id: "handling",        label: "Loading / unloading" },
    { id: "terminal",        label: "Terminal fees" },
    { id: "build",           label: "Construction (annualized)" },
    { id: "supplier_switch", label: "Supplier switching" },
    { id: "mode_switch",     label: "Mode switching" }
  ],

  baseline: Plan,          // XOM's current network ("as-is")
  plans: { "p0": Plan, "p1": Plan, ... },   // unique optimal solutions (deduplicated)
  runs: {                  // one entry per combination of control stops
    "2-0-3-1-1-0-1-1": { plan: "p17", total_usd_per_yr: 104453345.8 }
  }
}
```

A run key is the stop index of every control, in `controls` order, joined by
`-`. Every combination exists in `runs`.

### Plan

```js
{
  total_usd_per_yr: 104453345.8,
  breakdown: { product, line_haul, handling, terminal, build, supplier_switch, mode_switch }, // $/yr
  routes: [Route],
  builds:            [{ site, mode, usd_per_yr }],
  supplier_switches: [{ supplier, site, usd_per_yr }],
  mode_switches:     [{ site, mode, usd_per_yr }]
}
```

### Route

One product path from a supplier to an XOM site.

```js
{
  id: "r3",
  supplier: "Olin Plaquemine Plant",   // node id
  site: "Joliet Refinery",              // node id (sink)
  dst_per_yr: 19260,
  current: false,          // true if XOM uses this exact supplier + path today
  legs: [{
    from: "Olin Plaquemine Plant", to: "IMTT Lemont", mode: "barge",
    miles: 1180.4,
    line_haul_usd_per_dst: 35.2,
    handling_usd_per_dst: 5.7,       // loading + unloading for this leg
    terminal_usd_per_dst: 9.07       // fee at the leg's destination if it is a terminal, else 0
  }, ...],
  product_usd_per_dst: 400,
  landed_usd_per_dst: 543.5,         // product + all leg costs
  usd_per_yr: 10467550.1             // landed x dst_per_yr
}
```

Site-level build and switching costs are in the plan's `builds`,
`supplier_switches` and `mode_switches` lists, not in the routes.

## What the frontend computes

* Savings vs. today = `baseline.total_usd_per_yr - run.total_usd_per_yr`
  (positive = cheaper than today).
* Best plan for the current assumptions = the minimum `total_usd_per_yr`
  over all runs whose non-decision control stops equal the current ones
  (vary only the `decision: true` controls). Loss vs. best = current run
  total minus that minimum.
* Site cost = sum of the site's route `usd_per_yr` plus the site's builds and
  switching costs.

## `window.APP_GEOMETRY`

```js
{
  lanes: {
    "Olin Plaquemine Plant|IMTT Lemont|barge": [[lon, lat], [lon, lat], ...],
    ...
  }
}
```

Key = `origin|destination|mode` with exact node ids. Longitudes are
continuous along a line (a trans-Pacific line may use values below -180), so
a map can draw it without a wrap-around jump. A missing key means "draw a
curved arc between the two nodes".
