"""Write an Excel workbook of the model's sourced freight costs for XOM to check.

    python export_rate_check.py                       # config.OUTPUT_DIR / config.RATE_CHECK_NAME
    python export_rate_check.py --out some/file.xlsx

Sheets:
    Read me            what the workbook is, units, which cells to fill in
    Assumptions        rate inputs (blue = input); every cost below is a
                       live formula on these cells, so XOM can edit a rate and
                       see every lane update
    Current lanes      XOM's current lanes (10/07 sheet, base volumes)
    Rail lanes         existing and candidate rail lanes, with serving railroads,
                       likely route and interchanges (config.RAIL_LANES_FILE)
    Chicago hub        Gulf Coast -> Chicago (IMTT Lemont) -> Canada vs. direct rail,
                       with low / base / high inputs, break-even barge cost and a
                       two-way sensitivity grid (barge rate x rail discount)
    Site rail access   which railroad serves each site and terminal (config.SITE_RAIL_FILE)
    Questions for XOM
    Sources            every number's value, date, URL and page (config.RATE_SOURCES_FILE);
                       other sheets cite its ids in brackets

Each data block is an Excel table so Copilot in Excel can read it.

Costs are per wet (as-shipped, 50% solution) and per dry metric ton, the units
XOM asked for, plus per truck / rail car.

Nothing asks XOM for rates: they can't share real numbers. Rate tables get an
optional "Our estimate looks" dropdown (too low / about right / too high), and
XOM can type their own rates into the blue inputs on their copy.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

import config
from loader import load_current_flows, load_nodes, load_site_modes
from main import apply_exclusions
from network import build_network
from routing import lane_distance

LOAD_MT = {"truck": 21.0, "rail": 84.0}   # wet metric tons per load (XOM: 1 rail car = 84 MT = 4 trucks)

FONT = "Arial"
BLUE = "0000FF"
GREEN = "008000"                                         # link to another sheet
INPUT_FILL = PatternFill("solid", fgColor="FFFF00")      # XOM fills these in (optional)
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
ESTIMATE_COL = "Our estimate looks (optional)"
ESTIMATE_CHOICES = '"too low,about right,too high"'
DIFF_FMT = "+$0.00;-$0.00;$0.00"                         # sign matters: negative = Chicago cheaper

# Questions avoid asking for rates; XOM can't share real numbers.
QUESTIONS = [
    ("Units", "Are your freight rates per wet (as-shipped) or per dry metric ton? We assume wet, "
              "and 50% NaOH by weight."),
    ("Rail", "Which railroad serves each of your sites (see 'Site rail access')? Please correct any "
             "row marked unconfirmed, and note any site served only by a short line or switching carrier."),
    ("Rail", "For the USGC -> Edmonton move (~$12,000/car for suppliers, ~$8,250 quoted to XOM): which "
             "origin, railroads and interchange point does that rate use?"),
    ("Rail", "Which per-car charges apply on top of line haul (no amounts needed): switching / short-line "
             "handoff, interchange in Chicago, tank car lease or fleet cost, empty return, fuel surcharge, "
             "demurrage?"),
    ("Rail", "Joliet: is the refinery rail-served today (for any product), and by which railroad? What "
             "would it take to receive caustic by rail?"),
    ("Chicago", "On 'Chicago hub', is your barge cost to Lemont plus terminal fee above or below the "
                "break-even shown for each route? A yes/no is enough; no rate needed."),
    ("Terminals", "The Lemont source is a terminal resupplied from Plaquemine or Baytown. Should its cost "
                  "include the inbound barge leg, or is the Lemont price delivered to the terminal?"),
    ("Barge", "Barge rates: is pricing by tow (minimum barges per tow) or per ton? Is there a fleeting / "
              "terminal fee per move?"),
    ("Cross-border", "Which border costs apply on US -> Canada moves (customs brokerage, fees), and are "
                     "Canadian rates quoted in CAD?"),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(config.OUTPUT_DIR / config.RATE_CHECK_NAME))
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    nodes, site_modes = apply_exclusions(load_nodes(config.SITES_FILE), load_site_modes(config.MODES_FILE))
    sites = {n.name: n for n in nodes}
    current = build_network(nodes, site_modes, current=load_current_flows(config.CURRENT_FLOWS_FILE)).current
    if not current:
        raise SystemExit(f"{config.CURRENT_FLOWS_FILE.name} is missing or empty; nothing to export.")

    wb = Workbook()
    wb.remove(wb.active)
    read_me(wb.create_sheet("Read me"))
    refs = assumptions(wb.create_sheet("Assumptions"))
    current_lanes(wb.create_sheet("Current lanes"), current, sites, refs)
    rail_df = pd.read_csv(config.RAIL_LANES_FILE)
    rail_lanes(wb.create_sheet("Rail lanes"), rail_df, refs)
    chicago_hub(wb.create_sheet("Chicago hub"), rail_df, refs)
    site_rail(wb.create_sheet("Site rail access"), pd.read_csv(config.SITE_RAIL_FILE).fillna(""))
    questions(wb.create_sheet("Questions for XOM"))
    sources(wb.create_sheet("Sources"), pd.read_csv(config.RATE_SOURCES_FILE, dtype=str).fillna(""))

    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                c.font = Font(name=FONT, size=c.font.size or 10, bold=c.font.bold, italic=c.font.italic,
                              color=c.font.color)
    wb.calculation.fullCalcOnLoad = True   # formulas have no cached values until opened

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"Wrote {out} ({len(current)} current lanes, {len(rail_df)} rail lanes).")


# --- sheets --------------------------------------------------------------

def read_me(ws) -> None:
    lines = [
        ("Caustic soda freight rate check (Rice CMOR 492 / ExxonMobil)", True),
        ("", False),
        ("Purpose: the freight costs our model uses today, built from public tariffs and benchmarks. "
         "Every number cites an id in brackets (e.g. [R1]) that points to a row on 'Sources' with the "
         "value, date, URL and page. Ids starting with X are numbers XOM gave us.", False),
        ("Truck: Quality Carriers' published tariff for liquid chemicals plus its fuel surcharge. Rail: "
         "STB 2024 waybill data for caustic tank cars, scaled to the ~$12,000/car USGC -> Edmonton "
         "supplier rate XOM mentioned on 10/28. Barge: Kirby Inland Marine's Aug 2026 towing tariffs. "
         "These are list or benchmark rates, so XOM's contract rates are likely lower.", False),
        ("", False),
        ("Units", True),
        ("Volumes and prices: metric tons (MT). 'Wet MT' = MT of 50% solution as shipped; "
         "'dry MT' = MT of 100% NaOH. 1 wet MT carries 0.5 dry MT, so $/dry MT = 2 x $/wet MT.", False),
        ("Rail car = 84 wet MT; truck = 21 wet MT (XOM: 1 rail car = 4 trucks).", False),
        ("Rate parameters on 'Assumptions' are per wet SHORT ton, the unit the model uses internally; "
         "every lane converts them to metric tons.", False),
        ("", False),
        ("How to read / fill in", True),
        ("Blue numbers are inputs. Change one on 'Assumptions' and every lane recalculates.", False),
        ("Nothing needs to come back to us. To test your own rates, type them into the blue cells in "
         "your copy ('Assumptions', or the low / base / high inputs on 'Chicago hub') and keep the file.", False),
        ("Yellow cells are optional: an 'Our estimate looks' dropdown (too low / about right / too high) "
         "on each rate row, site corrections, and answers to 'Questions for XOM'. None ask for a rate.", False),
        ("'Chicago hub' compares Gulf Coast -> Chicago (barge) -> rail out with direct rail, over a range "
         "of barge rates and rail discounts, and shows the break-even barge cost for each route.", False),
        ("Costs include fuel surcharge and loading / unloading charges where carriers bill them. Not "
         "included yet: tank car lease (~$785/car-month [R9]), barge hire on short barge lanes, "
         "demurrage. US -> Canada caustic soda pays no duty or counter-tariff [G7, G8].", False),
        ("Rail lanes also count railroad handoffs (interchanges, short-line or plant switches) and add a "
         "per-car charge for each, because XOM noted the line serving a site can matter more than distance.", False),
        ("Rail miles are shortest paths on the US DOT North American rail network. They ignore railroad "
         "ownership, so a real route that stays on one carrier or interchanges at a hub can be longer.", False),
        ("'Site rail access' rows are from public sources; confidence and sources are listed per row.", False),
    ]
    for i, (text, bold) in enumerate(lines, start=1):
        c = ws.cell(row=i, column=1, value=text)
        c.font = Font(bold=bold, size=14 if i == 1 else 10)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 120


def assumptions(ws) -> dict[str, str]:
    """Write the rate inputs and return {name: absolute cell ref} for formulas."""
    ws["A1"] = "Rate assumptions (blue = input, edit freely; [ids] point to 'Sources')"
    ws["A1"].font = Font(bold=True, size=12)
    refs: dict[str, str] = {}

    def scalar(row, label, key, value, fmt, note):
        ws.cell(row=row, column=1, value=label)
        c = ws.cell(row=row, column=2, value=value)
        c.font, c.number_format = Font(color=BLUE), fmt
        ws.cell(row=row, column=3, value=note).alignment = Alignment(wrap_text=True)
        refs[key] = f"Assumptions!$B${row}"

    scalar(3, "Solution strength (dry MT per wet MT)", "strength", config.SOLUTION_STRENGTH, "0%",
           "[X3] XOM buys 50% NaOH by weight (9/23 meeting).")
    scalar(4, "Metric tons per short ton", "mt_per_st", config.METRIC_TONS_PER_SHORT_TON, "0.00000",
           "Exact conversion.")
    scalar(5, "Rail car payload (wet MT)", "car_mt", LOAD_MT["rail"], "0", "[X1] XOM: any caustic rail car in NA is 84 MT.")
    scalar(6, "Truck payload (wet MT)", "truck_mt", LOAD_MT["truck"], "0", "[X2] XOM: 1 rail car = 4 trucks.")

    ws["A8"] = "Mode rates (per wet short ton)"
    ws["A8"].font = Font(bold=True)
    header(ws, 9, ["Mode", "Fixed $/ton", "$/ton-mile", "Handling $/ton (each end)", "Upstream factor",
                   "Min billed miles", "Source"])
    for i, (mode, p) in enumerate(config.MODE_PARAMS.items(), start=10):
        vals = [mode, p["fixed_usd_per_ton"], p["usd_per_ton_mile"], config.HANDLING_USD_PER_TON[mode],
                p["upstream_factor"], p["min_miles"], MODE_SOURCES[mode]]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(row=i, column=j, value=v)
            if 2 <= j <= 6:
                c.font = Font(color=BLUE)
                c.number_format = "$0.0000" if j == 3 else ("0.000" if j == 5 else ("0" if j == 6 else "$0.00"))
    refs["mode_table"] = "Assumptions!$A$10:$F$13"
    as_table(ws, f"A9:G{9 + len(config.MODE_PARAMS)}", "ModeRates")

    ws["A16"] = "Rail per car: STB waybill fit scaled to XOM's supplier rate (handling included)"
    ws["A16"].font = Font(bold=True)
    scalar(17, "Waybill fit, fixed $ per car", "wb_fixed", 2062, "$#,##0",
           "[R1] STB 2024 Public Use Waybill Sample, 17,831 caustic tank-car waybills, median fit. "
           "Revenue is masked upward [R2], so the curve is scaled to row 20.")
    scalar(18, "Waybill fit, $ per car-mile", "wb_per_mile", 5.014, "$0.000", "[R1] same fit.")
    scalar(19, "Calibration miles: USGC -> Edmonton", "cal_mi", 2445, "#,##0",
           "Rail-network miles, Gulf Coast sources -> Strathcona (2,398-2,460), same basis as the waybill "
           "short-line miles.")
    scalar(20, "Supplier rate USGC -> Edmonton ($/car)", "cal_usd", 12000, "$#,##0",
           "[X4] XOM 10/28: rate suppliers pay. Includes current fuel surcharge.")
    scale = f"{refs['cal_usd']}/({refs['wb_fixed']}+{refs['wb_per_mile']}*{refs['cal_mi']})"
    ws["A21"], ws["B21"] = "Implied $ per car-mile", f"={refs['wb_per_mile']}*{scale}"
    ws["A22"], ws["B22"] = "Implied fixed $ per car", f"={refs['wb_fixed']}*{scale}"
    ws["B21"].number_format, ws["B22"].number_format = "$0.00", "$#,##0"
    ws["C21"] = "[D5, D6] Waybill curve x (supplier rate / waybill curve at the calibration miles)."
    ws["C22"] = "Covers switching, terminal and car costs that do not scale with distance."
    refs["cal_per_mile"], refs["cal_fixed"] = "Assumptions!$B$21", "Assumptions!$B$22"
    scalar(23, "XOM direct-rate factor", "xom_factor", 8250 / 12000, "0.00",
           "[D14] XOM's own quote / supplier rate on USGC -> Edmonton ($8,250 / $12,000).")

    ws["A25"] = "Switching add-ons (per rail car), to compare lanes by how many handoffs they need"
    ws["A25"].font = Font(bold=True)
    scalar(26, "Interchange between railroads ($/car)", "interchange_usd", 202, "$#,##0",
           "[R6] Belt Railway of Chicago tariff 8002-S (eff. 7/1/2026), Item 2003: hazmat loaded car $202.")
    scalar(27, "Terminal / short-line switch ($/car)", "switch_usd", 575, "$#,##0",
           "[R7] UP Tariff 6004 Item 9000, standard switching. Proxy for a short line or plant switcher "
           "(Watco, Cando, CSX at Sarnia), which publish no rates.")

    widths(ws, [44, 14, 12, 22, 14, 14, 70])
    return refs


# Gulf Coast -> IMTT Lemont by barge, routed on the USACE National Waterway Network with
# build_distances.route_barge (miles, upstream miles). XOM 10/28: "if barge to Chicago is
# relatively cheap, we can make Chicago a big intermediate node."
HUB = "IMTT Lemont"
HUB_BARGE = [("Olin Plaquemine Plant", HUB, 1260.8, 1195.3),
             ("Covestro Baytown Industrial Complex", HUB, 1579.4, 1100.6)]
# Destinations reachable both directly from each HUB_BARGE origin and from HUB on
# 'Rail lanes'. XOM 10/28: Joliet should move off truck; Sarnia and Edmonton are the
# Canada cases.
HUB_DESTS = ["Joliet Refinery", "Sarnia Refinery", "Strathcona Refinery"]
# Low / base / high sensitivity inputs. Base rail factor links to Assumptions (XOM's
# own quote vs. the supplier rate, 10/28); the rest are illustrative team ranges.
HUB_INPUTS = [
    ("Rail rate factor (share of supplier rail rate XOM pays)", "rail", 0.618, None, 1.00, "0.0%",
     "[D14] Base = XOM's quote / supplier rate on USGC -> Edmonton ($8,250 / $12,000), linked from "
     "'Assumptions'. [X4] High = supplier rate. [D15] Low = base x 25th-percentile / median waybill "
     "revenue for 2,200+ mi caustic moves."),
    ("Barge rate multiplier (x barge leg below)", "barge", 0.76, 1.00, 1.13, "0.00x",
     "[D17] Low = USDA Illinois River grain barge rate (Apr 2026) x upstream factor. High = TTI barge "
     "cost per ton-mile in 2025 dollars. Base leg is Kirby's towing tariff, which excludes barge hire."),
    ("Terminal fee at Lemont ($/wet MT)", "fee", 4.15, 5, 15, "$0.00",
     "Storage / throughput beyond barge unloading and rail loading. [D12] Base derived from IMTT revenue "
     "per bbl of capacity (2018) plus wharfage. [D16] Low = NS self-load cap $85/truck; high = top of "
     "a vendor's $5-15/ton transload range (low confidence). IMTT does not publish rates."),
]
# Grid points are scenario values for the sensitivity table, not data.
GRID_BARGE = [20, 30, 40, 50, 60, 70, 80, 90]             # $/wet MT, barge leg + nothing else
GRID_RAIL = [0.50, 0.60, 0.70, 0.80, 0.90, 1.00]          # rail rate factor
# Source ids (RATE_SOURCES_FILE) behind each MODE_PARAMS row, shown on 'Assumptions'.
MODE_SOURCES = {
    "truck": "[D1-D4, G1] Quality Carriers liquid-chemical distance tariff + 65% fuel surcharge, 21 MT/load",
    "rail": "[D5-D7, G1] STB 2024 waybill fit for caustic tank cars, scaled to XOM's $12,000/car supplier rate",
    "barge": "[D8-D11, G1, X6] Kirby Aug 2026 LMR towing tariff per 1,420-ton barge; XOM: flat within ~20-30 mi",
    "pipeline": "[D13] INGAA 4-inch line cost at the Baytown volume; not used by any site",
    "ocean": "[D19] Quote only: no rate formula; China -> Vancouver bulk parcel rate in lane_rates.csv",
}


def current_lanes(ws, current, sites, refs) -> None:
    """XOM's current lanes (CURRENT_FLOWS_FILE, from XOM's 10/07 sheet), not the model's optimum."""
    lanes = []
    for _, lane in sorted(current.items(), key=lambda kv: (kv[0][2].value, kv[0][0])):
        if lane.dst_per_yr <= 0:   # an alternative origin XOM named, not a lane in use
            continue
        for a, b, mode in lane.path:   # a lane through a terminal is listed leg by leg
            d = lane_distance(sites[a], sites[b], mode)
            lanes.append((a, b, mode.value, round(d.miles, 1), round(d.upstream_miles, 1),
                          round(lane.dst_per_yr * config.METRIC_TONS_PER_SHORT_TON)))
    end = lane_table(ws, "XOM's current lanes (10/07 sheet, base volumes), sourced costs", lanes, refs,
                     "CurrentLanes")
    note_row(ws, end + 1, "Barge has no per-load figure: barges carry ~1,500+ MT and pricing depends on tow size.")
    note_row(ws, end + 2, "Joliet's supply goes through the Olin Lemont Terminal, listed leg by leg. Its barge "
                          "leg shows the tariff formula; the model uses the lower rate implied by XOM's $450 "
                          "terminal price (D22).")


def chicago_hub(ws, rail_df: pd.DataFrame, refs) -> None:
    """Gulf Coast -> Chicago (barge) -> rail out vs. direct rail, with sensitivity ranges.

    Layout: inputs (rows 4-8), route comparison, two-way grid, then the barge legs.
    """
    pairs = set(zip(rail_df.origin, rail_df.destination))
    origins = [a for a, *_ in HUB_BARGE] + [HUB]
    missing = [(o, d) for o in origins for d in HUB_DESTS if (o, d) not in pairs]
    if missing:
        raise SystemExit(f"{config.RAIL_LANES_FILE.name} is missing lanes needed on 'Chicago hub': {missing}")

    title(ws, "Chicago hub: Gulf Coast -> Chicago (IMTT Lemont) -> destination, vs. direct rail")
    note_row(ws, 2, "All $ per wet MT (50% solution as shipped); x2 for $/dry MT. Via Chicago minus direct: "
                    "negative = routing through Chicago is cheaper.")

    # Sensitivity inputs: columns B / C / D = low / base / high.
    ws["A4"] = "Sensitivity inputs (blue = edit freely)"
    ws["A4"].font = Font(bold=True)
    header(ws, 5, ["Input", "Low", "Base", "High", "Note"])
    inp = {}
    for r, (label, key, lo, base, hi, fmt, note) in enumerate(HUB_INPUTS, start=6):
        base = f"={refs['xom_factor']}" if base is None else base
        write_row(ws, r, [label, lo, base, hi, note], fmts={2: fmt, 3: fmt, 4: fmt}, wrap=(1, 5))
        for j in (2, 3, 4):
            linked = isinstance(ws.cell(r, j).value, str)
            ws.cell(r, j).font = Font(color=GREEN if linked else BLUE)
        inp[key] = {"lo": f"$B${r}", "base": f"$C${r}", "hi": f"$D${r}"}
    rail, barge, fee = inp["rail"], inp["barge"], inp["fee"]
    as_table(ws, f"A5:E{r}", "HubInputs")

    # Barge legs go at the bottom; their rows are fixed so the comparison can point at them.
    routes_top = 6 + len(HUB_INPUTS) + 2
    first = routes_top + 2
    last = first + len(HUB_BARGE) * len(HUB_DESTS) - 1
    grid_top = last + 4
    legs_top = grid_top + 4 + len(GRID_BARGE) + 2
    leg_end = lane_table(ws, "Legs: Gulf Coast -> IMTT Lemont by barge (Kirby towing tariff, Aug 2026)",
                         [(a, b, "barge", mi, up, None) for a, b, mi, up in HUB_BARGE], refs, "HubBargeLegs",
                         top=legs_top)
    leg_cost = {a: f"$J${legs_top + 3 + i}" for i, (a, *_) in enumerate(HUB_BARGE)}
    note_row(ws, leg_end + 1, "Almost all barge miles are upstream (Mississippi + Illinois Waterway), billed at "
                              "the upstream factor. Gulf -> IMTT Lemont by rail is on 'Rail lanes' for comparison.")
    note_row(ws, leg_end + 2, "IMTT Lemont is CN-served with 3 barge berths, so barge in + CN rail out to Sarnia or "
                              "Edmonton needs no railroad interchange. Caustic storage there is unconfirmed.")

    # Route comparison.
    ws.cell(routes_top, 1, "Route comparison").font = Font(bold=True)
    header(ws, routes_top + 1, [
        "Origin", "Destination", "Direct rail, supplier rate ($/wet MT)", "Barge to Lemont ($/wet MT)",
        "Rail Lemont -> destination, supplier rate ($/wet MT)", "Direct rail at base", "Via Chicago at base",
        "Via Chicago minus direct (base)", "Best case for Chicago", "Worst case for Chicago",
        "Break-even barge + fee, low rail factor", "Break-even, base rail factor",
        "Break-even, high rail factor", ESTIMATE_COL, "Route"])
    lane = "SUMIFS('Rail lanes'!$O:$O,'Rail lanes'!$B:$B,{o},'Rail lanes'!$C:$C,{d})"
    r = first
    for o, *_ in HUB_BARGE:
        for d in HUB_DESTS:
            saved = f"(C{r}-E{r})"     # supplier-rate rail $ avoided by going via Chicago
            write_row(ws, r, [
                o, d, "=" + lane.format(o=f"A{r}", d=f"B{r}"), f"={leg_cost[o]}",
                "=" + lane.format(o=f'"{HUB}"', d=f"B{r}"),
                f"={rail['base']}*C{r}",
                f"={barge['base']}*D{r}+{fee['base']}+{rail['base']}*E{r}",
                f"=G{r}-F{r}",
                # Rail is the longer haul on the direct route, so pricier rail helps Chicago.
                f"={barge['lo']}*D{r}+{fee['lo']}-{rail['hi']}*{saved}",
                f"={barge['hi']}*D{r}+{fee['hi']}-{rail['lo']}*{saved}",
                f"={rail['lo']}*{saved}", f"={rail['base']}*{saved}", f"={rail['hi']}*{saved}",
                None, f'=A{r}&" -> "&B{r}',
            ], fmts={j: "$0.00" for j in range(3, 14)} | {8: DIFF_FMT, 9: DIFF_FMT, 10: DIFF_FMT},
                inputs=(14,), wrap=(1, 2))
            for j in (3, 5):
                ws.cell(r, j).font = Font(color=GREEN)
            r += 1
    estimate_dropdown(ws, f"N{first}:N{last}")
    as_table(ws, f"A{routes_top + 1}:O{last}", "HubRoutes")
    diff_colors(ws, f"H{first}:J{last}")
    note_row(ws, last + 1, "Best case = low barge, low fee, high rail factor; worst case = high barge, high fee, "
                           "low rail factor. Break-even = the most barge to Lemont + terminal fee can cost "
                           "before direct rail is cheaper; compare it with your own cost, no need to share it.")
    note_row(ws, last + 2, "Rail $/wet MT come from 'Rail lanes' (calibrated + switching), times the rail factor. "
                           "A deeper XOM rail discount lowers the break-even: it shrinks what Chicago saves on rail.")

    # Two-way grid for one route: barge $/wet MT (rows) x rail factor (columns), fee at base.
    ws.cell(grid_top, 1, "Two-way sensitivity: via Chicago minus direct ($/wet MT)").font = Font(bold=True)
    ws.cell(grid_top + 1, 1, "Route (pick from list)")
    pick = ws.cell(grid_top + 1, 2, f"{HUB_BARGE[0][0]} -> {HUB_DESTS[-1]}")
    pick.fill = INPUT_FILL
    pick.border = BOX
    routes = DataValidation(type="list", formula1=f"$O${first}:$O${last}", allow_blank=False)
    ws.add_data_validation(routes)
    routes.add(pick.coordinate)
    ws.cell(grid_top + 1, 5, "Supplier-rate rail $ saved via Chicago")
    saved = ws.cell(grid_top + 1, 6, f"=INDEX($C${first}:$C${last},MATCH($B${grid_top + 1},$O${first}:$O${last},0))"
                                     f"-INDEX($E${first}:$E${last},MATCH($B${grid_top + 1},$O${first}:$O${last},0))")
    saved.number_format = "$0.00"
    note_row(ws, grid_top + 2, "Rows: barge to Lemont, $/wet MT. Columns: rail rate factor. Terminal fee held at "
                               "base. Blue headers are editable.")
    head = grid_top + 3
    write_row(ws, head, ["Barge $/wet MT \\ rail factor"] + GRID_RAIL, fmts={j: "0%" for j in range(2, 8)})
    for j in range(2, 2 + len(GRID_RAIL)):
        ws.cell(head, j).font = Font(color=BLUE, bold=True)
    for i, b in enumerate(GRID_BARGE, start=head + 1):
        row = [b] + [f"=$A{i}+{fee['base']}-{get_column_letter(j)}${head}*${saved.column_letter}${saved.row}"
                     for j in range(2, 2 + len(GRID_RAIL))]
        write_row(ws, i, row, fmts={1: "$0"} | {j: DIFF_FMT for j in range(2, 8)})
        ws.cell(i, 1).font = Font(color=BLUE, bold=True)
    diff_colors(ws, f"B{head + 1}:{get_column_letter(1 + len(GRID_RAIL))}{head + len(GRID_BARGE)}")

    widths(ws, [36, 30, 13, 14, 14, 12, 12, 13, 12, 12, 13, 13, 13, 16, 44])


def lane_table(ws, heading: str, lanes: list[tuple], refs, table: str, top: int = 1) -> int:
    """Lane rows (origin, destination, mode, miles, upstream miles, dry MT/yr or None) with
    live cost formulas, headed at row `top`, as Excel table `table`. Returns the last row written."""
    cols = ["Origin", "Destination", "Mode", "Route miles", "Upstream miles", "Billed miles",
            "Base volume (dry MT/yr)", "Line haul $/wet ST", "Handling $/wet ST", "Total $/wet MT",
            "Total $/dry MT", "Per load ($)", ESTIMATE_COL]
    ws.cell(top, 1, heading).font = Font(bold=True, size=12 if top == 1 else 10)
    header(ws, top + 2, cols)
    t = refs["mode_table"]
    for r, (a, b, mode, miles, upstream, volume) in enumerate(lanes, start=top + 3):
        row = [a, b, mode, miles, upstream,
               f"=MAX(D{r}+(VLOOKUP(C{r},{t},5,FALSE)-1)*E{r},VLOOKUP(C{r},{t},6,FALSE))",
               volume,
               f"=VLOOKUP(C{r},{t},2,FALSE)+VLOOKUP(C{r},{t},3,FALSE)*F{r}",
               f"=2*VLOOKUP(C{r},{t},4,FALSE)",
               f"=(H{r}+I{r})/{refs['mt_per_st']}",
               f"=J{r}/{refs['strength']}",
               f'=IF(C{r}="rail",J{r}*{refs["car_mt"]},IF(C{r}="truck",J{r}*{refs["truck_mt"]},""))',
               None]
        write_row(ws, r, row, fmts={4: "#,##0", 5: "#,##0", 6: "#,##0", 7: "#,##0", 8: "$0.00", 9: "$0.00",
                                    10: "$0.00", 11: "$0.00", 12: "$#,##0"}, inputs=(13,))
    estimate_dropdown(ws, f"M{top + 3}:M{r}")
    as_table(ws, f"A{top + 2}:M{r}", table)
    widths(ws, [34, 30, 8, 10, 10, 10, 14, 12, 12, 12, 12, 12, 16])
    if top == 1:   # only freeze when the table starts the sheet
        ws.freeze_panes = "C4"
    return r


def rail_lanes(ws, df: pd.DataFrame, refs) -> None:
    cols = ["Status", "Origin", "Destination", "Rail miles", "Origin railroad", "Destination railroad",
            "Likely route / interchange", "Switching or access notes", "Interchanges (est.)",
            "Terminal / short-line switches (est.)", "Model formula $/car", "Calibrated $/car",
            "Switching add-on $/car", "Calibrated + switching $/car", "$/wet MT", "$/dry MT",
            "At XOM direct rate $/car", ESTIMATE_COL]
    title(ws, "Rail lanes: existing and candidate, with serving railroads")
    header(ws, 3, cols)
    t = refs["mode_table"]
    for r, x in enumerate(df.fillna("").itertuples(index=False), start=4):
        model_per_car = (f"=(VLOOKUP(\"rail\",{t},2,FALSE)+VLOOKUP(\"rail\",{t},3,FALSE)*D{r}"
                         f"+2*VLOOKUP(\"rail\",{t},4,FALSE))*{refs['car_mt']}/{refs['mt_per_st']}")
        row = [x.status, x.origin, x.destination, float(x.miles), x.origin_railroad, x.destination_railroad,
               x.likely_route, x.access_notes, int(x.interchanges), int(x.terminal_switches), model_per_car,
               f"={refs['cal_fixed']}+{refs['cal_per_mile']}*D{r}",
               f"=I{r}*{refs['interchange_usd']}+J{r}*{refs['switch_usd']}",
               f"=L{r}+M{r}", f"=N{r}/{refs['car_mt']}", f"=O{r}/{refs['strength']}",
               f"=N{r}*{refs['xom_factor']}", None]
        write_row(ws, r, row, fmts={4: "#,##0", 9: "0", 10: "0", 11: "$#,##0", 12: "$#,##0", 13: "$#,##0",
                                    14: "$#,##0", 15: "$0.00", 16: "$0.00", 17: "$#,##0"},
                  inputs=(18,), wrap=(5, 6, 7, 8))
    estimate_dropdown(ws, f"R4:R{r}")
    as_table(ws, f"A3:R{r}", "RailLanes")
    end = r + 2
    note_row(ws, end, "Model formula = the model's rail rate (Assumptions rows 10-13) incl. loading and "
                      "unloading. Calibrated = waybill fit scaled to XOM's supplier rate, Assumptions rows 17-22. "
                      "Switching add-on = handoffs x Assumptions rows 26-27; $/MT columns use calibrated + switching.")
    note_row(ws, end + 1, "Rail miles: shortest path on the US DOT North American rail network; it does not "
                          "follow railroad ownership, so carrier-specific routes can be longer.")
    widths(ws, [11, 26, 24, 9, 22, 22, 40, 46, 11, 12, 12, 12, 12, 13, 10, 10, 13, 16])
    ws.freeze_panes = "D4"


def site_rail(ws, df: pd.DataFrame) -> None:
    cols = ["Site", "Role", "Location", "Class I railroad(s)", "Rail access", "Switching / short line",
            "Notes", "Confidence", "Sources", "XOM correction"]
    title(ws, "Which railroad serves each site and terminal (public sources; please correct)")
    header(ws, 3, cols)
    for r, x in enumerate(df.itertuples(index=False), start=4):
        row = [x.site, x.role, x.location, x.class1_railroads, x.rail_access, x.switching,
               x.notes, x.confidence, x.sources, None]
        write_row(ws, r, row, inputs=(10,), wrap=tuple(range(1, 10)))
    as_table(ws, f"A3:J{r}", "SiteRailAccess")
    widths(ws, [30, 16, 20, 20, 22, 26, 60, 11, 50, 30])
    ws.freeze_panes = "B4"


def questions(ws) -> None:
    title(ws, "Questions for XOM (all optional; none ask for rates)")
    header(ws, 3, ["Topic", "Question", "XOM answer (optional)"])
    for r, (topic, q) in enumerate(QUESTIONS, start=4):
        write_row(ws, r, [topic, q, None], inputs=(3,), wrap=(2,))
    as_table(ws, f"A3:C{r}", "Questions")
    widths(ws, [14, 100, 50])


def sources(ws, df: pd.DataFrame) -> None:
    """Every number's source (RATE_SOURCES_FILE), cited elsewhere by id in brackets."""
    title(ws, "Sources: one row per number used (ids are cited in brackets on the other sheets)")
    note_row(ws, 2, "X = given by XOM; D = derived (formula in 'source', inputs in 'reference'); A = team "
                    "assumption; others are public sources.")
    cols = list(df.columns)
    header(ws, 3, [c.replace("_", " ").capitalize() for c in cols])
    for r, x in enumerate(df.itertuples(index=False), start=4):
        write_row(ws, r, list(x), wrap=tuple(range(2, len(cols) + 1)))
    as_table(ws, f"A3:{get_column_letter(len(cols))}{r}", "Sources")
    widths(ws, [6, 11, 40, 18, 24, 11, 40, 40, 50, 18, 30])
    ws.freeze_panes = "B4"


# --- formatting helpers ----------------------------------------------------

def as_table(ws, ref: str, name: str) -> None:
    """Make a block an Excel table, which Copilot in Excel reads as one dataset."""
    tbl = Table(displayName=name, ref=ref)
    tbl.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=False)
    ws.add_table(tbl)



def title(ws, text: str) -> None:
    ws["A1"] = text
    ws["A1"].font = Font(bold=True, size=12)


def header(ws, row: int, cols: list[str]) -> None:
    for j, name in enumerate(cols, start=1):
        c = ws.cell(row=row, column=j, value=name)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEADER_FILL
        c.alignment = Alignment(wrap_text=True, vertical="center")
        c.border = BOX


def write_row(ws, r: int, values: list, fmts: dict[int, str] | None = None,
              inputs: tuple[int, ...] = (), wrap: tuple[int, ...] = ()) -> None:
    for j, v in enumerate(values, start=1):
        c = ws.cell(row=r, column=j, value=v)
        c.border = BOX
        c.alignment = Alignment(vertical="top", wrap_text=j in wrap)
        if fmts and j in fmts:
            c.number_format = fmts[j]
        if j in inputs:
            c.fill = INPUT_FILL


def estimate_dropdown(ws, cells: str) -> None:
    dv = DataValidation(type="list", formula1=ESTIMATE_CHOICES, allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(cells)


def diff_colors(ws, cells: str) -> None:
    """Green where Chicago is cheaper (negative), red where direct rail is."""
    ws.conditional_formatting.add(cells, CellIsRule(operator="lessThan", formula=["0"],
                                                    fill=PatternFill("solid", fgColor="C6EFCE")))
    ws.conditional_formatting.add(cells, CellIsRule(operator="greaterThan", formula=["0"],
                                                    fill=PatternFill("solid", fgColor="FFC7CE")))


def note_row(ws, r: int, text: str) -> None:
    c = ws.cell(row=r, column=1, value=text)
    c.font = Font(italic=True)


def widths(ws, ws_widths: list[float]) -> None:
    for j, w in enumerate(ws_widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w


if __name__ == "__main__":
    main()
