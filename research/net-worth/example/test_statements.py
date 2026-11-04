"""Tests for the synthetic statements example.  python3 -m unittest discover -s research/net-worth/example -v"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from statements_demo import Entry, Line, build, run  # noqa: E402

D0, D1 = date(2026, 6, 30), date(2026, 7, 31)


def nw_delta(entry):
    led = build()
    before = led.balance_sheet(D1)["net_worth"]
    led.post(entry)
    return led.balance_sheet(D1)["net_worth"] - before


class Statements(unittest.TestCase):
    def test_bridge_reconciles(self):
        _, o = run(verbose=False)
        self.assertEqual(o["bridge_closing"], o["closing_net_worth"])
        self.assertEqual(o["opening_net_worth"], 20330000)
        self.assertEqual(o["closing_net_worth"] - o["opening_net_worth"], 625000 - 156500 + 45000)

    def test_principal_from_cash_is_net_worth_neutral(self):
        self.assertEqual(nw_delta(Entry(D1, "extra card principal", "principal",
                                        [Line("card:B", 50000), Line("cash:checking", -50000)])), 0)

    def test_interest_is_expense(self):
        self.assertEqual(nw_delta(Entry(D1, "interest", "expense",
                                        [Line("exp:card_interest", 1234), Line("card:B", -1234)])), -1234)

    def test_retirement_contribution_is_transfer(self):
        self.assertEqual(nw_delta(Entry(D1, "IRA contribution", "transfer",
                                        [Line("ret:401k", 10000), Line("cash:checking", -10000)])), 0)

    def test_employer_match_is_income(self):
        self.assertEqual(nw_delta(Entry(D1, "match", "income",
                                        [Line("ret:401k", 10000), Line("inc:employer_match", -10000)])), 10000)

    def test_cash_flow_reconciles_to_cash_change(self):
        led, o = run(verbose=False)
        cash = sum(led.balance(a, D1) - led.balance(a, D0) for a in ("cash:checking", "cash:savings"))
        self.assertEqual(sum(o["cash_flow"].values()), cash)
        self.assertEqual(o["cash_flow"], {"operating": 490000, "debt_principal": -260000,
                                          "investing_and_retirement": -50000, "internal_cash_transfer": 0})

    def test_unrealized_gain_not_cash(self):
        _, o = run(verbose=False)
        self.assertEqual(o["valuation_change"], 45000)
        self.assertNotIn(45000, o["cash_flow"].values())

    def test_holdings_not_double_counted(self):
        led, o = run(verbose=False)
        ids = [r[0] for r in led.balance_sheet(D1)["rows"]]
        self.assertNotIn("brk:taxable/FUND1", ids)
        self.assertTrue(o["holdings_reconcile"])
        with self.assertRaises(ValueError):
            led.post(Entry(D1, "bad", "valuation", [Line("brk:taxable/FUND1", 1), Line("val:unrealized", -1)]))

    def test_unbalanced_entry_rejected(self):
        with self.assertRaises(AssertionError):
            build().post(Entry(D1, "bad", "expense", [Line("exp:groceries", 100), Line("card:A", -99)]))

    def test_stale_and_missing_fx_flagged(self):
        _, o = run(verbose=False)
        self.assertTrue(any("stale" in w for w in o["warnings"]))
        self.assertTrue(any("EUR" in w and "not converted" in w for w in o["warnings"]))

    def test_liability_views_differ_and_are_labelled(self):
        _, o = run(verbose=False)
        self.assertEqual(o["economic_view_net_worth"] - o["closing_net_worth"], 10000000)  # 50% of $200,000

    def test_liquid_view(self):
        _, o = run(verbose=False)
        # checking 1,080,000 + savings 1,400,000 + brokerage 2,045,000 - card A 196,500 - card B 120,000
        self.assertEqual(o["closing_liquid_net_worth"], 1080000 + 1400000 + 2045000 - 196500 - 120000)


if __name__ == "__main__":
    unittest.main()
