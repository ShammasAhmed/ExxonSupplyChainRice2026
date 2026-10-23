
# Exxon Supply Chain Rice 2026

Rice University CMOR 492 Senior Design Project with ExxonMobil

## Project Plan

ExxonMobil (EM) currently sources 100% of its caustic soda domestically. Rising
exports from India, China, and other global partners — driven by growing PVC
pipe demand (and therefore Chlorine/caustic-soda co-production) in those
construction markets — suggest EM may now be able to source caustic soda more
cheaply from abroad than from the US. This project's goal is to challenge EM's
current domestic-only caustic soda supply chain network and produce evidence
for or against the hypothesis that EM can source cheaper caustic soda
globally.

The work runs September 2026 - December 2026 in three levels:

### Level 1 - Regional U.S. Pricing Model (current phase)

Map, and ideally replicate, EM's existing regional supply chain network so it
can serve as the baseline for a later global comparison. Built from:

- **Demand nodes** - EM plant locations and approximate demand.
- **Supply nodes** - domestic caustic soda producers: locations, production
  capacity ranges, and estimated price (index + markup).
- **Node costs** - a transport cost model connecting supply and demand nodes,
  expressed as one of: $/mile transported, $/dry short ton (DST) moved,
  $/mile-ton, or a fixed $ amount per lane.
- **Nodal flow** (optional) - actual EM flow data, to cross-reference the
  model's output against reality.

All data is modeled with low/high/mean range scenarios (bear/base/bull), and
weights are converted to dry short tons (DST), with metric tons kept for
reference.

**Level 1 timeline:**

| Window | Milestone |
| --- | --- |
| Sept 24 - Oct 12 | Data wrangling: receive and standardize all data from EM |
| Oct 12 - Oct 19 | Build the model (Supply Chain Guru / Lyric preferred, Gurobi as fallback); the optimal solution should reproduce EM's current network |
| Oct 19 - Nov 2 | Present the solution to EM for sign-off to proceed to the global sourcing study |

Levels 2 and 3 (the global sourcing study and beyond) are gated on EM
approving the Level 1 model.

## Current State (as of 2026-10-07)

The repo implements a working single-commodity min-cost-flow (transportation
problem) model, solved with Gurobi:

- `network.xlsx` - source/sink workbook with `Sources` and `Sinks` sheets
  (name, city, state, country, lat/lon, bear/base/bull volumes in DMT/yr).
- `modes.csv` - which transport modes (truck/rail/barge/pipeline) each site
  has, `existing` or `candidate` to build (annualized build cost), plus
  optional throughput caps and forced mode shares. Built from EM's
  `Rice caustic model data` sheet.
- `loader.py` - reads the workbook into `Node` objects and `modes.csv` into
  `SiteMode` rows.
- `node.py` - the `Node` dataclass (location, category, scenario volumes),
  the `Mode` enum, and `SiteMode`.
- `network.py` - expands each site into a hub node plus one node per mode,
  joined by load/unload (handling cost) and transport (line-haul) arcs.
- `routing.py` - line-haul $/ton per mode from great-circle distance x a
  per-mode circuity factor. Rates in `config.py` are placeholders.
- `model.py` - multimodal min-cost flow MILP per scenario: minimize freight +
  handling + build cost, choosing which candidate modes to build.
- `main.py` - CLI entry point; runs all three scenarios and writes network
  maps to `output/`.
- `visualize.py` / `visualize1.py` - Plotly map rendering (HTML + PNG).

**Gap vs. the Level 1 plan:** the model currently optimizes **drive time**,
not dollar cost, and has no supplier price data. The "Node costs" piece of
Level 1 ($/mile, $/DST, $/mile-ton, or fixed $ per lane) and supplier
index-based pricing still need to be added before the model reflects real
transport economics.

## Setup

Requires Python 3.11+ and a Gurobi license (academic licenses are free for
Rice students/faculty).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run all three scenarios:

```bash
python main.py
```
