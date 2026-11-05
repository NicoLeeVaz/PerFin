"""Editable assumptions and engine-computed results in an independent Excel module.

No macros, network links, account writes or hidden recalculation of financial rules.
Use recompute after editing. Every financial forecast is produced by perfin_payoff.
"""
from __future__ import annotations
import copy
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

from openpyxl import Workbook, load_workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill, Protection, Alignment
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT / "src", ROOT / "contracts/python", ROOT / "excel/core", ROOT / "config/privacy"):
    if p.is_dir() and str(p) not in sys.path:
        sys.path.append(str(p))
from perfin_payoff import simulate, payment_date
from perfin_contracts import CONTRACT_VERSION
from perfin_contracts.semantic import validate_document
from perfin_excel_core.commands import check_data_root, write_to_outbox

MONEY = '#,##0.00;(#,##0.00);"-"'
BLUE = "203864"
INPUT = "E8F0FE"
MAX_ROWS = 1000
CARD_HEADERS = ["Account ID", "Bucket ID", "Balance ($)", "APR", "Minimum rule", "Fixed minimum ($)",
                "Minimum percent", "Minimum floor ($)", "Statement ID", "Deferred interest", "Promo end month", "Post-promo APR"]
EVENT_HEADERS = ["Event", "Month", "Amount ($)", "Account ID (charge/fee only)"]
STRATEGIES = ("largest_balance", "snowball", "avalanche", "near_apr_hybrid")


def _text(cell, value):
    cell.value = value
    if isinstance(value, str):
        cell.data_type = "s"
        cell.number_format = "@"
        cell.quotePrefix = value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))


def _style(ws, title, note, headers=None):
    ws.sheet_view.showGridLines = False
    ws["A1"] = title
    ws["A1"].font = Font(size=16, bold=True, color=BLUE)
    ws.row_dimensions[1].height = 28
    ws["A2"] = note
    ws.merge_cells("A2:L2")
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[2].height = 34
    ws.freeze_panes = "C5"
    for col in "ABCDEFGHIJKLMN":
        ws.column_dimensions[col].width = 20
    ws.column_dimensions["A"].width = 40
    if headers:
        for j, h in enumerate(headers, 1):
            c = ws.cell(4, j, h)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=BLUE)
            c.alignment = Alignment(wrap_text=True)
        ws.row_dimensions[4].height = 32
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0


def _checked_output(path, data_root=None):
    path = Path(path).expanduser()
    root = Path(data_root).expanduser().resolve() if data_root else path.parent.resolve()
    check_data_root(root)
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Workbook path escapes the local data root")
    check_data_root(resolved)
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Payoff workbook must be .xlsx")
    return path


def _append(ws, row):
    ws.append(row)
    for c in ws[ws.max_row]:
        if isinstance(c.value, str):
            _text(c, c.value)


def _strategy_label(s):
    if s["kind"] == "near_apr_hybrid":
        return f'near APR {s["gap_pp"]} pp, {s["prefer"]}' + (" locked" if s.get("lock_target") else "")
    return s["kind"] + (" locked" if s.get("lock_target") else "")


def build(document, path, *, data_root=None, overwrite=False):
    path = _checked_output(path, data_root)
    if path.exists() and not overwrite:
        raise FileExistsError("Output already exists; use explicit recompute")
    results = simulate(document)
    s = document["scenario"]
    wb = Workbook()
    wb.remove(wb.active)
    plan, inputs, cards, events, schedule, baseline = [wb.create_sheet(n) for n in
        ("Plan", "Inputs", "Cards", "Cash events", "Schedule", "_Baseline")]
    _style(plan, "Credit-card payoff comparison", "Approximate APR / 12 forecast. Edit the blue input cells, save and close Excel, then run recompute.",
           ["Strategy", "Result", "Interest ($)", "Fees ($)", "Payments ($)", "Remaining ($)", "Debt-free date",
            "Extra cost vs avalanche ($)", "Delay (months)", "Tolerance", "Flags"])
    plan["A3"] = "Last computed from saved inputs. See status at L3."
    plan["L3"] = '=IF(OR(SUMPRODUCT(--(Inputs!B4:B13<>_Baseline!B4:B13))>0,SUMPRODUCT(--(Cards!A5:L1004<>_Baseline!A20:L1019))>0,SUMPRODUCT(--(\'Cash events\'!A5:D1004<>_Baseline!A1030:D2029))>0),"INPUTS CHANGED: recompute","CURRENT saved inputs")'
    plan["L3"].font = Font(bold=True, color="333333")
    plan.conditional_formatting.add("L3", FormulaRule(formula=['LEFT(L3,7)<>"CURRENT"'], font=Font(color="9C0006", bold=True)))
    plan.column_dimensions["L"].width = 40
    for r in results["results"]:
        _append(plan, [_strategy_label(r["strategy"]), r["run_status"], r["total_interest_minor"] / 100,
                       r["total_fees_minor"] / 100, r["total_payments_minor"] / 100, r["final_debt_minor"] / 100,
                       date.fromisoformat(payment_date(s["as_of"], r["debt_free_month"])) if r["debt_free_month"] is not None else None,
                       None if r["delta_cost_vs_avalanche_minor"] is None else r["delta_cost_vs_avalanche_minor"] / 100,
                       r["delta_months_vs_avalanche"], r["within_tolerance"], ", ".join(sorted({f["code"] for f in r["flags"]}))])
        plan.row_dimensions[plan.max_row].height = 30
        for cell in plan[plan.max_row]: cell.alignment = Alignment(wrap_text=True, vertical="center")
        for j in (3, 4, 5, 6, 8): plan.cell(plan.max_row, j).number_format = MONEY
        plan.cell(plan.max_row, 7).number_format = "yyyy-mm-dd"
    _style(inputs, "Scenario inputs", "All scenarios use identical debts and budgets. Tolerance blank means unset; it never means approved.")
    selected = s["strategies"][0]
    values = [("Scenario ID", s["scenario_id"]), ("As of", date.fromisoformat(s["as_of"])),
              ("Monthly payment budget ($)", s["cash_plan"]["monthly_minor"] / 100), ("Horizon (months)", s["horizon_months"]),
              ("Selected strategy", selected["kind"]), ("Near APR gap (percentage points)", float(selected.get("gap_pp", "0.5"))),
              ("Near APR balance preference", selected.get("prefer", "largest")), ("Lock target until paid", "TRUE" if selected.get("lock_target", False) else "FALSE"),
              ("Maximum extra cost ($)", None if s["tolerance"]["max_extra_cost_minor"] is None else s["tolerance"]["max_extra_cost_minor"] / 100),
              ("Maximum delay (months)", s["tolerance"]["max_payoff_delay_months"])]
    for row, (label, value) in enumerate(values, 4):
        _text(inputs.cell(row, 1), label)
        _text(inputs.cell(row, 2), value)
    inputs.column_dimensions["A"].width = 43
    inputs.column_dimensions["B"].width = 28
    inputs["B5"].number_format = "yyyy-mm-dd"
    for ref in ("B6", "B12"): inputs[ref].number_format = MONEY
    for cell in inputs["B4:B13"]:
        cell[0].fill = PatternFill("solid", fgColor=INPUT)
        cell[0].font = Font(color="0000FF")
        cell[0].protection = Protection(locked=False)
    for ref, choices in [("B8", STRATEGIES), ("B10", ("largest", "smallest")), ("B11", ("TRUE", "FALSE"))]:
        validation = DataValidation(type="list", formula1='"' + ",".join(choices) + '"')
        validation.errorTitle = "Choose a listed value"
        validation.showErrorMessage = True
        inputs.add_data_validation(validation)
        validation.add(ref)
    _style(cards, "Card balances and terms", "Positive amounts mean debt owed. APR is a percent. Multiple buckets and deferred interest are explicitly unsupported.", CARD_HEADERS)
    for c in s["cards"]:
        rule = c["min_payment_rule"]
        for b in c["buckets"]:
            _append(cards, [c["account_id"], b["bucket_id"], b["balance_minor"] / 100, float(b["apr"]), rule["rule_type"],
                            None if "amount_minor" not in rule else rule["amount_minor"] / 100,
                            None if "pct" not in rule else float(rule["pct"]),
                            None if "floor_minor" not in rule else rule["floor_minor"] / 100,
                            c["source_statement_id"], "TRUE" if b["deferred_interest"] else "FALSE", b.get("promo_end_month"),
                            None if b.get("post_promo_apr") is None else float(b["post_promo_apr"])])
            for j in (3, 6, 8): cards.cell(cards.max_row, j).number_format = MONEY
            for j in (4, 7, 12): cards.cell(cards.max_row, j).number_format = "0.00%"
    _style(events, "Dated cash and card events", "Month 1 is one calendar month after As of. Override replaces that month's budget; lump sums add to it.", EVENT_HEADERS)
    for kind, key in (("override", "overrides"), ("lump_sum", "lump_sums")):
        for e in s["cash_plan"].get(key, []): _append(events, [kind, e["month"], e["amount_minor"] / 100, None])
    for c in s["cards"]:
        for kind, key in (("charge", "assumed_charges"), ("fee", "fees")):
            for e in c.get(key, []): _append(events, [kind, e["month"], e["amount_minor"] / 100, c["account_id"]])
    for ws in (cards, events):
        for row in ws.iter_rows(min_row=5):
            for cell in row:
                cell.fill = PatternFill("solid", fgColor=INPUT)
                cell.font = Font(color="0000FF")
                cell.protection = Protection(locked=False)
    _style(schedule, "Payment schedule", "Payments are projections only. No payments are executed. Opening + interest + fees + charges - payment = ending.",
           ["Strategy", "Month", "Payment date", "Account", "Opening ($)", "Interest ($)", "Fees ($)", "Charges ($)",
            "Minimum due ($)", "Extra ($)", "Payment ($)", "Ending ($)"])
    for r in results["results"]:
        for x in r["schedule"]:
            _append(schedule, [_strategy_label(r["strategy"]), x["month"], date.fromisoformat(payment_date(s["as_of"], x["month"])),
                               x["account_id"], *[x[k] / 100 for k in ("opening_minor", "interest_minor", "fees_minor", "charges_minor", "minimum_minor", "extra_minor", "payment_minor", "ending_minor")]])
            schedule.cell(schedule.max_row, 3).number_format = "yyyy-mm-dd"
            for j in range(5, 13): schedule.cell(schedule.max_row, j).number_format = MONEY
    schedule.auto_filter.ref = f"A4:L{schedule.max_row}"
    # Chart source aggregated by month/strategy, separated from the displayed comparison.
    start = max(12, plan.max_row + 3)
    plan.cell(start, 1, "Month")
    horizon = max([x["month"] for r in results["results"] for x in r["schedule"]] or [0])
    for j, r in enumerate(results["results"], 2):
        plan.cell(start, j, _strategy_label(r["strategy"]))
        monthly = {}
        for row in r["schedule"]: monthly[row["month"]] = monthly.get(row["month"], 0) + row["ending_minor"]
        for m in range(1, horizon + 1):
            plan.cell(start + m, 1, m)
            # An infeasible run ends early; never extend it as zero debt.
            value = monthly.get(m, 0 if r["run_status"] == "paid_off" else None)
            plan.cell(start + m, j, value / 100 if value is not None else None).number_format = MONEY
    if horizon:
        chart = LineChart()
        chart.title = "Remaining debt"
        chart.y_axis.title = "Dollars"
        chart.x_axis.title = "Forecast month"
        chart.add_data(Reference(plan, min_col=2, max_col=1 + len(results["results"]), min_row=start, max_row=start + horizon), titles_from_data=True)
        chart.set_categories(Reference(plan, min_col=1, min_row=start + 1, max_row=start + horizon))
        chart.width, chart.height = 24, 12
        plan.add_chart(chart, f"A{start + horizon + 3}")
    # Save a baseline of user-editable fields for Excel's visible stale-input formula.
    for row in range(4, 14): baseline.cell(row, 2, inputs.cell(row, 2).value)
    for source, offset, columns in ((cards, 15, 12), (events, 1025, 4)):
        if source.max_row > MAX_ROWS + 4:
            raise ValueError("Workbook supports at most 1000 card/event rows")
        for row in source.iter_rows(min_row=5, max_col=columns):
            for c in row: _text(baseline.cell(c.row + offset, c.column), c.value)
    baseline["N1"] = "perfin_payoff_workbook/1"
    baseline["N2"] = json.dumps(s["strategies"], separators=(",", ":"))
    baseline.sheet_state = "veryHidden"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".payoff-", suffix=".xlsx", dir=path.parent)
    os.close(fd)
    try:
        wb.save(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return results


def _value(ws, row, col):
    c = ws.cell(row, col)
    if c.data_type == "f" or c.data_type == "e":
        raise ValueError("Formula/error cells are not accepted as payoff inputs")
    return c.value


def _number(value, *, minor=False, integer=False, optional=False):
    if value is None and optional: return None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("A numeric input is missing or invalid")
    d = Decimal(str(value))
    if not d.is_finite() or d < 0: raise ValueError("Numbers must be finite and nonnegative")
    scale = 100 if minor else 1
    scaled = d * scale
    if (minor or integer) and scaled != scaled.to_integral_value():
        raise ValueError("Amounts need whole cents; month counts need whole numbers")
    return int(scaled) if minor or integer else format(d, "f")


def _boolean(value):
    if isinstance(value, bool): return value
    if value in ("TRUE", "FALSE"): return value == "TRUE"
    raise ValueError("Boolean input must be TRUE or FALSE")


def read_scenario(path):
    wb = load_workbook(path, data_only=False, read_only=True)
    try:
        if wb["_Baseline"]["N1"].value != "perfin_payoff_workbook/1": raise ValueError("Not a PerFin payoff workbook")
        ws = wb["Inputs"]
        v = [_value(ws, r, 2) for r in range(4, 14)]
        d = v[1]
        if isinstance(d, datetime): d = d.date()
        if not isinstance(d, date): raise ValueError("As of must be an Excel date")
        selected = {"kind": v[4], "lock_target": _boolean(v[7])}
        if selected["kind"] == "near_apr_hybrid":
            selected.update(gap_pp=_number(v[5]), prefer=v[6])
        strategies = [selected]
        for other in json.loads(wb["_Baseline"]["N2"].value)[1:]:
            if other != selected: strategies.append(other)
        if not any(x["kind"] == "avalanche" and not x.get("lock_target") for x in strategies): strategies.append({"kind": "avalanche"})
        s = {"scenario_id": v[0], "as_of": d.isoformat(), "horizon_months": _number(v[3], integer=True),
             "accrual_model": "m1_monthly_apr_div_12", "cash_plan": {"monthly_minor": _number(v[2], minor=True), "overrides": [], "lump_sums": []},
             "cards": [], "strategies": strategies, "tolerance": {"max_extra_cost_minor": _number(v[8], minor=True, optional=True),
             "max_payoff_delay_months": _number(v[9], integer=True, optional=True)}}
        by = {}
        ws = wb["Cards"]
        if ws.max_row > MAX_ROWS + 4: raise ValueError("Too many card rows")
        for row in range(5, ws.max_row + 1):
            vals = [_value(ws, row, c) for c in range(1, 13)]
            if all(x is None for x in vals): continue
            account, bid, balance, apr, kind, fixed, pct, floor, statement, deferred, end, post = vals
            rule = {"rule_type": kind}
            if fixed is not None: rule["amount_minor"] = _number(fixed, minor=True)
            if pct is not None: rule["pct"] = _number(pct)
            if floor is not None: rule["floor_minor"] = _number(floor, minor=True)
            c = {"account_id": account, "source_statement_id": statement, "min_payment_rule": rule, "buckets": []}
            if account in by and (by[account]["min_payment_rule"] != rule or by[account]["source_statement_id"] != statement):
                raise ValueError("Conflicting terms for the same card")
            target = by.setdefault(account, c)
            bucket = {"bucket_id": bid, "balance_minor": _number(balance, minor=True), "apr": _number(apr), "deferred_interest": _boolean(deferred)}
            if end is not None: bucket["promo_end_month"] = _number(end, integer=True)
            if post is not None: bucket["post_promo_apr"] = _number(post)
            target["buckets"].append(bucket)
        s["cards"] = list(by.values())
        ws = wb["Cash events"]
        if ws.max_row > MAX_ROWS + 4: raise ValueError("Too many event rows")
        for row in range(5, ws.max_row + 1):
            vals = [_value(ws, row, c) for c in range(1, 5)]
            if all(x is None for x in vals): continue
            kind, month, amount, account = vals
            e = {"month": _number(month, integer=True), "amount_minor": _number(amount, minor=True)}
            if kind in ("override", "lump_sum") and account is None:
                s["cash_plan"]["overrides" if kind == "override" else "lump_sums"].append(e)
            elif kind in ("charge", "fee") and account in by:
                by[account].setdefault("assumed_charges" if kind == "charge" else "fees", []).append(e)
            else: raise ValueError("Unknown event or account")
        doc = {"contract": "perfin", "contract_version": CONTRACT_VERSION, "document_type": "payoff_scenario", "scenario": s}
        simulate(doc)  # Includes semantic and engine input checks, no writes.
        return doc
    finally:
        wb.close()


def recompute(path, output_path=None, *, data_root=None):
    """Read edited assumptions and atomically replace only the explicit destination."""
    doc = read_scenario(path)
    return build(doc, output_path or path, data_root=data_root, overwrite=True)


def save_command(document):
    simulate(document)
    doc = {"contract": "perfin", "contract_version": CONTRACT_VERSION, "document_type": "command",
           "command_id": str(uuid.uuid4()), "command_type": "save_payoff_scenario",
           "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "issued_by": "excel_payoff:scenario",
           "expected_versions": [], "payload": copy.deepcopy(document["scenario"])}
    if validate_document(doc): raise ValueError("Scenario save command violates contract")
    return doc


def install(document, data_root):
    """Install the workbook and bundled manifest for the core module launcher."""
    root = Path(data_root).expanduser().resolve()
    check_data_root(root)
    folder = root / "workbooks" / "excel_payoff"
    path = _checked_output(folder / "PerFin-Payoff.xlsx", root)
    manifest = folder / "module_manifest.json"
    resolved = manifest.resolve()
    if root not in resolved.parents:
        raise ValueError("Module manifest escapes the local data root")
    check_data_root(resolved)
    content = (Path(__file__).parent / "module_manifest.json").read_text(encoding="utf-8")
    if validate_document(json.loads(content)):
        raise ValueError("Bundled manifest does not validate")
    result = build(document, path, data_root=root)
    fd, tmp = tempfile.mkstemp(prefix=".payoff-manifest-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(content)
        os.replace(tmp, manifest)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return result
