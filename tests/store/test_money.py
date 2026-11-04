"""Exact money: Decimal <-> integer minor units at the Access CURRENCY bounds."""
import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))

import synthetic as S  # noqa: E402
from fake_access import new_fake_store  # noqa: E402
from perfin_store import codec, money, reports  # noqa: E402

M = money.MONEY_MAX


class MoneyConversion(unittest.TestCase):
    def test_bound_is_the_contract_bound(self):
        self.assertEqual(M, 922337203685477)
        self.assertLess(M, 2 ** 53)  # every in-range value is exact in an Excel/VBA double

    def test_round_trip_at_bounds(self):
        for v in (0, 1, -1, 12345, -12345, M, -M, M - 1, -(M - 1)):
            d = money.minor_to_db(v)
            self.assertIsInstance(d, Decimal)
            self.assertEqual(money.db_to_minor(d), v)
            self.assertEqual(money.db_to_minor(d.quantize(Decimal("0.0001"))), v)  # CURRENCY 4-place form

    def test_out_of_range_and_wrong_types_rejected(self):
        for bad in (M + 1, -M - 1, 1.0, Decimal("1"), "100", True, None):
            with self.assertRaises(money.MoneyError):
                money.minor_to_db(bad)

    def test_fractional_engine_values_rejected(self):
        for bad in (Decimal("1.5"), Decimal("0.0001"), 1.5, float("nan"), Decimal("NaN"), Decimal("Infinity"),
                    Decimal(M + 1)):
            with self.assertRaises(money.MoneyError):
                money.db_to_minor(bad)

    def test_integral_float_from_driver_is_exact(self):
        self.assertEqual(money.db_to_minor(float(M)), M)
        self.assertEqual(money.db_to_minor(-12345.0), -12345)

    def test_display_helpers_use_decimal(self):
        self.assertEqual(money.minor_to_major(-1234), Decimal("-12.34"))
        self.assertEqual(money.major_to_minor("0.10"), 10)
        self.assertEqual(money.major_to_minor("0.1") + money.major_to_minor("0.2"), money.major_to_minor("0.3"))
        with self.assertRaises(money.MoneyError):
            money.major_to_minor("1.005")
        with self.assertRaises(money.MoneyError):
            money.major_to_minor(1.5)


class Codec(unittest.TestCase):
    def test_currency_and_dates(self):
        self.assertEqual(codec.to_db("ledger_txn", "amount_minor", -M), Decimal(-M))
        self.assertEqual(codec.to_db("ledger_txn", "posted_date", "2028-02-29"), datetime(2028, 2, 29))
        self.assertEqual(codec.from_db("ledger_txn", "posted_date", datetime(2028, 2, 29)), "2028-02-29")
        self.assertEqual(codec.to_db("import_batch", "staged_at", "2026-07-02T10:00:00Z"), datetime(2026, 7, 2, 10, 0, 0))
        self.assertEqual(codec.from_db("import_batch", "staged_at", datetime(2026, 7, 2, 10, 0, 0)), "2026-07-02T10:00:00Z")

    def test_refusals(self):
        with self.assertRaises(codec.CodecError):
            codec.to_db("ledger_txn", "posted_date", "2026-02-29")
        with self.assertRaises(codec.CodecError):
            codec.from_db("ledger_txn", "posted_date", datetime(2026, 1, 1, 12, 0))
        with self.assertRaises(codec.CodecError):
            codec.to_db("account", "number_hint", "12345")  # TEXT(4): never truncated
        with self.assertRaises(codec.CodecError):
            codec.to_db("account", "include_in_net_worth", None)  # Yes/No cannot be Null
        with self.assertRaises(codec.CodecError):
            codec.to_db("ledger_txn", "row_version", True)
        with self.assertRaises(codec.CodecError):
            codec.to_db("ledger_txn", "account_id", None)


class StoreRoundTrip(unittest.TestCase):
    def test_bounds_through_repository_and_csv(self):
        repo, ad, _ = new_fake_store()
        bundle = S.reference_bundle()
        bundle["accounts"].append({"account_id": "chk:edge", "kind": "asset", "account_class": "checking",
                                   "display_name": "Edge", "currency": "USD", "opening_balance_minor": 0,
                                   "opening_balance_date": "2026-05-31", "row_version": 1})
        self.assertEqual(repo.import_bundle(bundle)["result_status"], "accepted")
        self.assertEqual(repo.set_default_categories("exp.uncategorized", "inc.uncategorized")["result_status"], "accepted")
        b = S.batch("b.edge", "chk:edge", [S.row(1, "2026-06-01", M, "max", state="approved"),
                                           S.row(2, "2026-06-01", -M, "min", state="approved"),
                                           S.row(3, "2026-06-02", 1, "cent", state="approved")])
        self.assertEqual(repo.stage_batch(b)["result_status"], "accepted")
        r = repo.execute(S.command("commit_batch", {"batch_id": "b.edge", "source_file_sha256": b["batch"]["source_file_sha256"]},
                                   [S.ev("batch", "b.edge", 2)]))
        self.assertEqual(r["result_status"], "accepted", r["errors"])
        stored = sorted(t["amount_minor"] for t in repo.export_bundle()["transactions"])
        self.assertEqual(stored, [-M, 1, M])
        raw = ad.db.rows["ledger_txn"]
        self.assertTrue(all(isinstance(x["amount_minor"], Decimal) for x in raw))
        csv_text = reports.to_csv("rpt_transactions", reports.build_tables(repo, "2026-12-31")["rpt_transactions"])
        self.assertIn(",%d," % M, csv_text)
        self.assertIn(",-%d," % M, csv_text)
        self.assertNotIn("E+", csv_text)

    def test_out_of_range_rejected_before_storage(self):
        repo, ad, _ = new_fake_store()
        repo.import_bundle(S.reference_bundle())
        b = S.batch("b.over", "chk:main", [S.row(1, "2026-06-01", M + 1, "too big")])
        r = repo.stage_batch(b)
        self.assertEqual(r["result_status"], "rejected")
        self.assertEqual(ad.db.rows["import_batch"], [])


if __name__ == "__main__":
    unittest.main()
