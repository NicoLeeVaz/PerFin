"""Generated workbook: totals match the contract fixtures, failures are visible,
text stays text, report sheets are protected, and the build is reproducible."""
import datetime as dt
import os
import unittest

import _support
from formula_eval import Evaluator, serial
from openpyxl import load_workbook
from perfin_contracts.derive import account_balance, display_balance
from perfin_excel_core import workbook, spec
from perfin_privacy_checks import needs_formula_escape

AS_OF = "2026-06-30"
TODAY = dt.date(2026, 7, 2)


def build(d, name="core.xlsx", reports_dir=None, today_checked=_support.CHECKED_AT, modules=None, **kw):
    out = d / name
    workbook.build(out, report_dir=reports_dir, checked_at=today_checked if reports_dir else None,
                   modules_dir=modules, **kw)
    return load_workbook(out)


class Expected:
    """Figures computed straight from the synthetic contract documents (not from the CSVs)."""

    def __init__(self):
        self.b = _support.load_json(_support.FIXTURES / "ledger_bundle.synthetic.json")
        self.s = _support.load_json(_support.FIXTURES / "staging_batch.synthetic.json")
        accts = self.b["accounts"]
        disp = {a["account_id"]: display_balance(self.b, a["account_id"], AS_OF) for a in accts}
        self.assets = sum(disp[a["account_id"]] for a in accts if a["kind"] == "asset")
        self.owed = sum(disp[a["account_id"]] for a in accts if a["kind"] == "liability")
        self.cards = [a["account_id"] for a in accts if a["account_class"] == "credit_card"]
        self.cards_owed = sum(-account_balance(self.b, c, AS_OF) for c in self.cards)
        last = {}
        for st in self.b["statements"]:
            if st["period_end"] <= AS_OF and st["account_id"] in self.cards:
                last[st["account_id"]] = max(last.get(st["account_id"], st), st, key=lambda s: s["period_end"])
        self.min_due = sum(s["minimum_due_minor"] for s in last.values())
        self.stmt_owed = sum(-s["closing_balance_minor"] for s in last.values())
        paid = {s["statement_id"]: 0 for s in last.values()}
        for p in self.b["statement_payments"]:
            if p["statement_id"] in paid:
                paid[p["statement_id"]] += p["amount_minor"]
        self.unpaid = sum(max(-s["closing_balance_minor"] - paid[s["statement_id"]], 0) for s in last.values())
        self.txn_net = sum(t["amount_minor"] for t in self.b["transactions"])
        self.txn_in = sum(t["amount_minor"] for t in self.b["transactions"] if t["amount_minor"] > 0)
        self.txn_out = -sum(t["amount_minor"] for t in self.b["transactions"] if t["amount_minor"] < 0)
        rows = self.s["rows"]
        self.review_awaiting = sum(r["review_state"] in ("pending", "needs_review") for r in rows)
        self.review_errors = sum(bool(r["errors"]) for r in rows)
        self.review_dups = sum(r["duplicate"]["status"] == "possible" for r in rows)
        balanced = {i for r in self.b["reconciliations"] if r["recon_status"] == "balanced"
                    for i in r["included_transaction_ids"]}
        self.balanced_statements = sum(r["recon_status"] == "balanced" for r in self.b["reconciliations"])
        unrec = [t for st in self.b["statements"] for t in self.b["transactions"]
                 if t["account_id"] == st["account_id"] and st["period_start"] <= t["posted_date"] <= st["period_end"]
                 and t["transaction_id"] not in balanced]
        self.unrec_count, self.unrec_sum = len(unrec), sum(t["amount_minor"] for t in unrec)
        kinds = {a["account_id"]: a["kind"] for a in accts}
        self.opening_display = sum((-1 if kinds[s["account_id"]] == "liability" else 1) * s["opening_balance_minor"]
                                   for s in self.b["statements"])


class Totals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = _support.temp_dir()
        d = cls.tmp.__enter__()
        cls.wb = build(d, reports_dir=_support.copy_reports(d / "reports"))
        cls.ev = Evaluator(cls.wb, TODAY)
        cls.x = Expected()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.__exit__(None, None, None)

    def money(self, name):
        return round(self.ev.name_ref(name) * 100)

    def test_account_and_card_summaries(self):
        x = self.x
        self.assertEqual(self.money("PerFin_TotalAssets"), x.assets)
        self.assertEqual(self.money("PerFin_TotalOwed"), x.owed)
        self.assertGreater(x.owed, 0)  # liabilities shown as positive owed amounts
        self.assertEqual(self.money("PerFin_NetBalance"), x.assets - x.owed)
        self.assertEqual(self.ev.name_ref("PerFin_AccountsCheck"), "OK")
        self.assertEqual(self.money("PerFin_CardsOwed"), x.cards_owed)
        self.assertEqual(self.money("PerFin_CardCurrentOwed"), x.cards_owed)
        self.assertEqual(self.money("PerFin_CardMinimumDue"), x.min_due)
        self.assertEqual(self.money("PerFin_CardStatementOwed"), x.stmt_owed)
        self.assertEqual(self.money("PerFin_CardUnpaid"), x.unpaid)
        self.assertEqual(self.ev.name_ref("PerFin_CardsUnknownLimit"), 1)
        self.assertAlmostEqual(self.ev.name_ref("PerFin_CardUtilization"), 55000 / 500000)
        self.assertEqual(self.ev.name_ref("PerFin_AccountCount"), len(x.b["accounts"]))

    def test_transaction_filters(self):
        x = self.x
        self.assertEqual(self.ev.name_ref("PerFin_TxnCount"), len(x.b["transactions"]))
        self.assertEqual(self.money("PerFin_TxnNet"), x.txn_net)
        self.assertEqual(self.money("PerFin_TxnIn"), x.txn_in)
        self.assertEqual(self.money("PerFin_TxnOut"), x.txn_out)
        cases = [
            ({"B5": "card:alpha"}, lambda t: t["account_id"] == "card:alpha"),
            ({"B6": serial(dt.date(2026, 6, 10)), "B7": serial(dt.date(2026, 6, 20))},
             lambda t: "2026-06-10" <= t["posted_date"] <= "2026-06-20"),
            ({"B8": "synthetic"}, lambda t: "synthetic" in t["description"].lower()),
            ({"B5": "card:beta", "B8": "refund"}, lambda t: t["account_id"] == "card:beta" and "REFUND" in t["description"]),
            ({"B8": "=SYN"}, lambda t: t["description"].startswith("=SYN")),
        ]
        for inputs, pred in cases:
            ev = Evaluator(self.wb, TODAY, {("Transactions", k): v for k, v in inputs.items()})
            want = [t for t in x.b["transactions"] if pred(t)]
            self.assertTrue(want, inputs)
            self.assertEqual(ev.name_ref("PerFin_TxnCount"), len(want), inputs)
            self.assertEqual(round(ev.name_ref("PerFin_TxnNet") * 100), sum(t["amount_minor"] for t in want), inputs)

    def test_review_and_reconciliation(self):
        x = self.x
        self.assertEqual(self.ev.name_ref("PerFin_ReviewRows"), len(x.s["rows"]))
        self.assertEqual(self.ev.name_ref("PerFin_ReviewAwaiting"), x.review_awaiting)
        self.assertEqual(self.ev.name_ref("PerFin_ReviewErrors"), x.review_errors)
        self.assertEqual(self.ev.name_ref("PerFin_ReviewPossibleDuplicates"), x.review_dups)
        self.assertEqual(self.ev.name_ref("PerFin_StatementCount"), len(x.b["statements"]))
        self.assertEqual(self.ev.name_ref("PerFin_StatementsBalanced"), x.balanced_statements)
        self.assertEqual(self.ev.name_ref("PerFin_StatementsOpen"), len(x.b["statements"]) - x.balanced_statements)
        self.assertEqual(self.ev.name_ref("PerFin_ReconDifferences"), 1)
        self.assertEqual(self.ev.name_ref("PerFin_UnreconciledCount"), x.unrec_count)
        self.assertEqual(self.money("PerFin_UnreconciledAmount"), x.unrec_sum)
        self.assertEqual(self.money("PerFin_StatementOpeningTotal"), x.opening_display)

    def test_status_and_as_of(self):
        self.assertEqual(self.ev.name_ref("PerFin_Status"), "OK")
        self.assertEqual(self.ev.name_ref("PerFin_DataAsOf"), serial(dt.date(2026, 6, 30)))
        self.assertEqual(self.ev.name_ref("PerFin_SourceProblems"), 0)
        for ws in self.wb.worksheets:
            if ws.title not in ("Status", "Settings"):
                self.assertEqual(ws["B2"].value, "=PerFin_Status", ws.title)
                self.assertEqual(ws["B3"].value, "=PerFin_DataAsOf", ws.title)
        # a week later without a refresh the banner says STALE
        late = Evaluator(self.wb, TODAY + dt.timedelta(days=9))
        self.assertTrue(late.name_ref("PerFin_Status").startswith("STALE"))

    def test_selftest_macro_expectations_match(self):
        text = (_support.CORE / "vba" / "PerFinSelfTest.bas").read_text(encoding="utf-8")
        import re
        pairs = re.findall(r'ExpectNumber "(PerFin_\w+)", (-?[0-9.]+)', text)
        self.assertGreaterEqual(len(pairs), 15)
        for name, value in pairs:
            self.assertAlmostEqual(self.ev.name_ref(name), float(value), msg=name)

    def test_money_cells_are_integer_minor_units(self):
        for ws in self.wb.worksheets:
            for name, ref in ws.tables.items():
                cols = dict((c[0], c[1]) for c in spec.columns(name))
                top = ws[ref.split(":")[0]].row
                for row in ws[ref][1:]:
                    for c in row:
                        header = ws.cell(row=top, column=c.column).value
                        if cols[header] in ("money_minor", "integer") and c.value is not None:
                            self.assertIs(type(c.value), int, (name, header))

    def test_text_cells_stay_text(self):
        seen = set()
        for ws in self.wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and c.data_type == "s" and needs_formula_escape(c.value):
                        self.assertTrue(c.quotePrefix, c.coordinate)
                        self.assertEqual(c.number_format, "@")
                        seen.add(c.value[0])
        self.assertTrue({"=", "+", "-", "@", "\t", "\r"} <= seen, seen)
        q = self.wb["Review"]
        desc = [c.value for c in q["H"] if isinstance(c.value, str)]
        self.assertIn("\rSYNTHETIC CR PREFIX, \"quoted\"", desc)   # exact value preserved

    def test_report_sheets_protected(self):
        self.assertTrue(self.wb.security.lockStructure)
        for ws in self.wb.worksheets:
            self.assertTrue(ws.protection.sheet, ws.title)
            for name, ref in ws.tables.items():
                for row in ws[ref]:
                    for c in row:
                        self.assertTrue(c.protection.locked, (ws.title, c.coordinate))
        self.assertFalse(self.wb["Transactions"]["B5"].protection.locked)
        self.assertFalse(self.wb["Settings"]["B4"].protection.locked)


class Failures(unittest.TestCase):
    def test_missing_source_is_visible(self):
        with _support.temp_dir() as d:
            rep = _support.copy_reports(d / "reports")
            os.remove(rep / "rpt_accounts.csv")
            wb = build(d, reports_dir=rep)
            ev = Evaluator(wb, TODAY)
            self.assertTrue(ev.name_ref("PerFin_Status").startswith("ERROR: 1 of 6"))
            self.assertEqual(ev.name_ref("PerFin_TotalAssets"), 0)   # nothing old shown as current
            st = wb["Status"]
            rows = {r[0]: r for r in st.iter_rows(min_row=15, max_row=20, values_only=True)}
            self.assertEqual(rows["rpt_accounts"][2], "MISSING")

    def test_invalid_and_stale_are_visible(self):
        with _support.temp_dir() as d:
            rep = _support.copy_reports(d / "reports")
            text = (rep / "rpt_transactions.csv").read_text(encoding="utf-8")
            (rep / "rpt_transactions.csv").write_text(text.replace(",300000,", ",3000.00,"), encoding="utf-8",
                                                     newline="")
            ev = Evaluator(build(d, reports_dir=rep), TODAY)
            self.assertTrue(ev.name_ref("PerFin_Status").startswith("ERROR"))
            self.assertEqual(ev.name_ref("PerFin_TxnCount"), 0)
            rep2 = _support.copy_reports(d / "reports2")
            late = _support.CHECKED_AT + dt.timedelta(days=40)
            ev = Evaluator(build(d, "late.xlsx", reports_dir=rep2, today_checked=late), late.date())
            self.assertTrue(ev.name_ref("PerFin_Status").startswith("ERROR: 6 of 6"))

    def test_template_says_not_refreshed(self):
        with _support.temp_dir() as d:
            wb = build(d)
            ev = Evaluator(wb, TODAY)
            self.assertTrue(ev.name_ref("PerFin_Status").startswith("NOT REFRESHED"))
            self.assertEqual(ev.name_ref("PerFin_DataAsOf"), "")
            self.assertEqual(ev.name_ref("PerFin_TotalAssets"), 0)
            for ws in wb.worksheets:
                for name, ref in ws.tables.items():
                    header = [c.value for c in ws[ref][0]]
                    self.assertEqual(header, spec.column_names(name), name)


def snapshot(path):
    wb = load_workbook(path)
    out = {"sheets": [ws.title for ws in wb.worksheets],
           "names": sorted((n, d.attr_text) for n, d in wb.defined_names.items()),
           "structure": wb.security.lockStructure}
    for ws in wb.worksheets:
        out[ws.title] = {
            "cells": sorted((c.coordinate, repr(c.value), c.data_type, c.number_format, bool(c.quotePrefix),
                             c.protection.locked) for row in ws.iter_rows() for c in row if c.value is not None
                            or not c.protection.locked),
            "tables": sorted((t.name, t.ref, tuple(col.name for col in t.tableColumns))
                             for t in ws.tables.values()),
            "protection": ws.protection.sheet,
            "cf": sorted((str(r.sqref), tuple(rule.formula)) for r in ws.conditional_formatting for rule in r.rules),
            "dv": sorted((str(v.sqref), v.type, v.formula1, v.formula2) for v in ws.data_validations.dataValidation),
            "links": sorted((c.coordinate, c.hyperlink.location, c.hyperlink.target) for row in ws.iter_rows()
                            for c in row if c.hyperlink),
        }
    return out


class Reproducible(unittest.TestCase):
    def test_build_twice_same_content(self):
        with _support.temp_dir() as d:
            rep = _support.copy_reports(d / "reports")
            for kw in ({}, {"report_dir": rep, "checked_at": _support.CHECKED_AT}):
                workbook.build(d / "a.xlsx", **kw)
                workbook.build(d / "b.xlsx", **kw)
                self.assertEqual(snapshot(d / "a.xlsx"), snapshot(d / "b.xlsx"))
            tpl = snapshot(d / "a.xlsx")
            self.assertGreater(len(tpl["names"]), 30)

    def test_cli_build(self):
        from perfin_excel_core.__main__ import main
        with _support.temp_dir() as d:
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["build", "--out", str(d / "PerFin-Core.xlsx")]), 0)
            self.assertTrue((d / "PerFin-Core.xlsx").is_file())


if __name__ == "__main__":
    unittest.main()
