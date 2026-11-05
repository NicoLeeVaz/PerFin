"""rpt_* report tables and CSV export in the contract dialect."""
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import synthetic as S  # noqa: E402
from fake_access import new_fake_store  # noqa: E402
from perfin_store import reports  # noqa: E402

SPEC = json.loads((ROOT / "contracts" / "schemas" / "report_tables.json").read_text(encoding="utf-8"))
REQUIRED = ("rpt_accounts", "rpt_transactions", "rpt_splits", "rpt_card_status", "rpt_statements",
            "rpt_reconciliation", "rpt_review_queue")


def populated():
    repo, ad, _ = new_fake_store()
    repo.import_bundle(S.reference_bundle())
    repo.set_default_categories("exp.uncategorized", "inc.uncategorized")
    b = "b.alpha.07"
    repo.stage_batch(S.card_batch())
    for ctype, payload in (("approve_rows", {"batch_id": b, "row_numbers": [1, 2, 3, 6]}),
                           ("reject_rows", {"batch_id": b, "row_numbers": [4], "reason": "bad"}),
                           ("resolve_duplicate", {"batch_id": b, "row_number": 5, "resolution": "confirmed_duplicate"}),
                           ("reject_rows", {"batch_id": b, "row_numbers": [5], "reason": "dup"})):
        v = repo._one("import_batch", {"batch_id": b})["row_version"]
        assert repo.execute(S.command(ctype, payload, [S.ev("batch", b, v)]))["result_status"] == "accepted"
    v = repo._one("import_batch", {"batch_id": b})["row_version"]
    assert repo.execute(S.command("commit_batch", {"batch_id": b, "source_file_sha256": S.card_batch()["batch"]["source_file_sha256"]},
                                  [S.ev("batch", b, v)]))["result_status"] == "accepted"
    repo.stage_batch(S.batch("b.chk.07", "chk:main", [S.row(1, "2026-07-03", -10000, "PAYMENT TO CARD"),
                                                      S.row(2, "2026-07-04", None, "BAD")]))
    cmds = [("record_statement", {"statement_id": "st7", "account_id": "card:alpha", "period_start": "2026-07-01",
                                  "period_end": "2026-07-31", "due_date": "2026-08-25", "opening_balance_minor": -45000,
                                  "closing_balance_minor": -41734, "minimum_due_minor": 2500,
                                  "bucket_balances": [{"bucket_id": "purchase", "balance_minor": -41734}]}),
            ("reconcile_statement", {"reconciliation_id": "rc7", "statement_id": "st7", "included_transaction_ids":
                                     ["b.alpha.07.r1", "b.alpha.07.r2", "b.alpha.07.r3", "b.alpha.07.r6"],
                                     "difference_minor": 0, "recon_status": "balanced"}),
            ("set_card_terms", {"terms_id": "ct1", "account_id": "card:alpha", "effective_from": "2026-01-01",
                                "terms_source": "user_estimate", "credit_limit_minor": 300000,
                                "min_payment_rule": {"rule_type": "fixed", "amount_minor": 2500},
                                "apr_buckets": [{"bucket_id": "purchase", "bucket_kind": "purchase", "apr": "0.2499",
                                                 "deferred_interest": False}]}),
            ("record_valuation", {"valuation_id": "v1", "account_id": "re:home", "as_of": "2026-06-30",
                                  "value_minor": 45000000, "currency": "USD", "valuation_source": "+synthetic estimate",
                                  "valuation_method": "owner_estimate"})]
    for ctype, payload in cmds:
        r = repo.execute(S.command(ctype, payload))
        assert r["result_status"] == "accepted", r
    return repo


class ReportTables(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = populated()
        cls.data = reports.build_tables(cls.repo, "2026-08-01")

    def test_columns_exactly_match_report_tables_json(self):
        for name in reports.STORE_TABLES:
            header = next(csv.reader(io.StringIO(reports.to_csv(name, self.data[name]))))
            self.assertEqual(header, [c["name"] for c in SPEC["tables"][name]], name)
        for name in REQUIRED:
            self.assertIn(name, reports.STORE_TABLES)

    def test_values(self):
        accts = {r["account_id"]: r for r in self.data["rpt_accounts"]}
        self.assertEqual(accts["card:alpha"]["ledger_balance_minor"], -41734)
        self.assertEqual(accts["card:alpha"]["display_balance_minor"], 41734)
        self.assertTrue(accts["sav:reserve"]["include_in_net_worth"])
        card = self.data["rpt_card_status"][0]
        self.assertEqual((card["statement_id"], card["statement_closing_owed_minor"], card["current_owed_minor"]),
                         ("st7", 41734, 41734))
        self.assertEqual(card["utilization_basis_points"], 1391)  # 41734 / 300000 = 13.911%
        self.assertEqual((card["confirmed_payments_minor"], card["unpaid_statement_minor"]), (0, 41734))
        txns = {r["transaction_id"]: r for r in self.data["rpt_transactions"]}
        self.assertTrue(txns["b.alpha.07.r1"]["reconciled"])
        queue = self.data["rpt_review_queue"]
        self.assertEqual([(r["batch_id"], r["row_number"]) for r in queue], [("b.chk.07", 1), ("b.chk.07", 2)])
        self.assertEqual(queue[1]["error_codes"], "E_PARSE_AMOUNT")
        self.assertEqual(self.data["rpt_reconciliation"][0]["included_count"], 4)

    def test_csv_dialect(self):
        text = reports.to_csv("rpt_transactions", self.data["rpt_transactions"])
        self.assertTrue(text.endswith("\r\n"))
        self.assertNotIn("\n", text.replace("\r\n", ""))
        self.assertFalse(text.startswith("﻿"))
        self.assertIn('"SYNTHETIC CAFE, ""DOWNTOWN"""', text)  # RFC 4180 quoting with doubled quotes
        self.assertIn(",TRUE,", text)
        self.assertIn("'-REFUND starts with minus", text)  # formula-injection prefix on text
        self.assertIn(",2500,", text)  # money stays an integer, never prefixed
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[1][3], "")  # null transaction_date -> empty field
        accts = reports.to_csv("rpt_accounts", self.data["rpt_accounts"])
        self.assertIn("'=Card Alpha", accts)
        self.assertIn(",FALSE,", reports.to_csv("rpt_card_terms", self.data["rpt_card_terms"]))
        self.assertIn("'+synthetic estimate", reports.to_csv("rpt_valuations", self.data["rpt_valuations"]))

    def test_type_and_null_enforcement(self):
        with self.assertRaises(TypeError):
            reports.to_csv("rpt_statements", [dict(self.data["rpt_statements"][0], opening_balance_minor=1.0)])
        with self.assertRaises(ValueError):
            reports.to_csv("rpt_statements", [dict(self.data["rpt_statements"][0], account_id=None)])
        with self.assertRaises(ValueError):
            reports.to_csv("rpt_statements", [dict(self.data["rpt_statements"][0], extra=1)])

    def test_export_is_read_only_and_location_checked(self):
        before = json.dumps(self.repo.export_bundle(), sort_keys=True)
        with tempfile.TemporaryDirectory() as d:
            paths = reports.export_csv(self.repo, Path(d) / "out", "2026-08-01")
            self.assertEqual(sorted(p.name for p in paths), sorted("%s.csv" % t for t in reports.STORE_TABLES))
            with open(paths[0], "rb") as f:
                self.assertTrue(f.read().startswith(b"account_id,display_name,"))
            with self.assertRaises(reports.ExportLocationError):
                reports.export_csv(self.repo, Path(d) / "Dropbox" / "out", "2026-08-01")
        self.assertEqual(before, json.dumps(self.repo.export_bundle(), sort_keys=True))
        with self.assertRaises(reports.ExportLocationError):
            reports.export_csv(self.repo, ROOT / "tmp-reports", "2026-08-01")
        self.assertFalse((ROOT / "tmp-reports").exists())


class UtilizationLimits(unittest.TestCase):
    def test_missing_zero_and_positive_limits_in_export(self):
        repo, adapter, _ = new_fake_store()
        self.addCleanup(adapter.close)
        result = repo.import_bundle(S.utilization_bundle())
        self.assertEqual(result["result_status"], "accepted", result["errors"])
        rows = reports.build_tables(repo, "2026-07-01")["rpt_card_status"]
        self.assertEqual({r["account_id"]: r["utilization_basis_points"] for r in rows},
                         {"card:util.missing": None, "card:util.zero": None, "card:util.positive": 2500})
        csv_rows = list(csv.DictReader(io.StringIO(reports.to_csv("rpt_card_status", rows))))
        self.assertEqual({r["account_id"]: r["utilization_basis_points"] for r in csv_rows},
                         {"card:util.missing": "", "card:util.zero": "", "card:util.positive": "2500"})

    def test_view_guards_the_divisor_not_only_the_result(self):
        # Source-level regression only: the fake cannot execute Access report queries.
        # Real zero/null/positive-limit checks live in windows_acceptance.py.
        from perfin_store import ddl
        sql = " ".join(dict(ddl.views())["rpt_card_status"].split())
        self.assertIn("/ IIf(q.credit_limit_minor = 0, Null, q.credit_limit_minor)", sql)
        self.assertNotIn("/ q.credit_limit_minor", sql)


class AsOfPayments(unittest.TestCase):
    """Codex P2: a historical report must not count an allocated payment that posts after as_of."""

    def setUp(self):
        self.repo, _, _ = new_fake_store()
        self.repo.import_bundle(S.reference_bundle())
        leg = lambda tid, acct, amt: {"transaction_id": tid, "account_id": acct, "posted_date": "2026-07-12",  # noqa: E731
                                      "amount_minor": amt, "currency": "USD", "description": "SYNTHETIC PAYMENT",
                                      "entry_method": "manual", "row_version": 1,
                                      "splits": [{"split_id": tid + ".s", "split_kind": "transfer", "amount_minor": amt,
                                                  "transfer_link_id": "L1"}]}
        r = self.repo.import_bundle({
            "contract": "perfin", "contract_version": "1.0.0", "document_type": "ledger_bundle", "base_currency": "USD",
            "accounts": [], "categories": [], "transactions": [leg("m1", "chk:main", -10000), leg("m2", "card:alpha", 10000)],
            "transfer_links": [{"transfer_link_id": "L1", "from_transaction_id": "m1", "to_transaction_id": "m2",
                                "link_status": "confirmed"}],
            "statements": [{"statement_id": "st6", "account_id": "card:alpha", "period_start": "2026-06-01",
                            "period_end": "2026-06-30", "opening_balance_minor": -45000, "closing_balance_minor": -45000}],
            "statement_payments": [{"allocation_id": "a1", "statement_id": "st6", "transaction_id": "m2", "amount_minor": 10000}]})
        assert r["result_status"] == "accepted", r

    def card(self, as_of):
        return reports.build_tables(self.repo, as_of)["rpt_card_status"][0]

    def test_payment_after_as_of_not_counted(self):
        c = self.card("2026-07-01")
        self.assertEqual((c["current_owed_minor"], c["confirmed_payments_minor"], c["unpaid_statement_minor"]),
                         (45000, 0, 45000))
        c = self.card("2026-07-11")
        self.assertEqual(c["confirmed_payments_minor"], 0)

    def test_payment_counted_from_its_posted_date(self):
        c = self.card("2026-07-12")
        self.assertEqual((c["current_owed_minor"], c["confirmed_payments_minor"], c["unpaid_statement_minor"]),
                         (35000, 10000, 35000))

    def test_statement_after_as_of_not_used(self):
        self.assertIsNone(reports.build_tables(self.repo, "2026-06-29")["rpt_card_status"][0]["statement_id"])

    def test_view_filters_payments_by_posted_date(self):
        from perfin_store import ddl
        sql = " ".join(dict(ddl.views())["rpt_card_status"].split())
        self.assertIn("INNER JOIN [ledger_txn] AS pt ON sp.transaction_id = pt.transaction_id WHERE pt.posted_date <= Date()",
                      sql)


if __name__ == "__main__":
    unittest.main()
