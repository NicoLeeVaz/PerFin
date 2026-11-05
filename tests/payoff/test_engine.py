"""Independent small examples and conservation properties of monthly payoff forecasts."""
import copy
import json
import math
import random
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "contracts/python")]
from perfin_payoff import ScenarioError, payment_date, simulate, sensitivity, from_ledger
from perfin_contracts.semantic import validate_document


def card(name, balance, apr="0", minimum=0):
    return {"account_id": "card:" + name, "source_statement_id": None,
            "buckets": [{"bucket_id": "purchase", "balance_minor": balance, "apr": apr, "deferred_interest": False}],
            "min_payment_rule": {"rule_type": "fixed", "amount_minor": minimum}}


def scenario(cards=None, budget=10000, horizon=120, strategies=None):
    return {"contract": "perfin", "contract_version": "1.0.1", "document_type": "payoff_scenario", "scenario": {
        "scenario_id": "synthetic_payoff", "as_of": "2026-01-31", "horizon_months": horizon,
        "accrual_model": "m1_monthly_apr_div_12", "cash_plan": {"monthly_minor": budget},
        "cards": cards or [card("a", 12000, "0.12")], "strategies": strategies or [{"kind": "avalanche"}],
        "tolerance": {"max_extra_cost_minor": None, "max_payoff_delay_months": None}}}


class EngineTests(unittest.TestCase):
    def run_result(self, doc):
        result = simulate(doc)
        self.assertEqual(validate_document(result), [])
        for run in result["results"]:
            self.assertEqual(run["total_payments_minor"], sum(x["payment_minor"] for x in run["schedule"]))
            if run["schedule"]:
                opening = sum(b["balance_minor"] for c in doc["scenario"]["cards"] for b in c["buckets"])
                added = sum(r[k] for r in run["schedule"] for k in ("interest_minor", "fees_minor", "charges_minor"))
                self.assertEqual(opening + added - run["total_payments_minor"], run["final_debt_minor"])
            for row in run["schedule"]:
                self.assertEqual(row["opening_minor"] + row["interest_minor"] + row["fees_minor"] + row["charges_minor"]
                                 - row["payment_minor"], row["ending_minor"])
                self.assertGreaterEqual(row["ending_minor"], 0)
                if run["run_status"] != "infeasible_budget":
                    self.assertEqual(row["minimum_minor"] + row["extra_minor"], row["payment_minor"])
        return result["results"][0]

    def test_hand_calculated_two_month_schedule(self):
        r = self.run_result(scenario())
        # 12000 * 1% = 120; after 10000 payment, 2120. Next interest 21, payment 2141.
        self.assertEqual([x["interest_minor"] for x in r["schedule"]], [120, 21])
        self.assertEqual(r["total_payments_minor"], 12141)
        self.assertEqual(r["total_interest_minor"], 141)
        self.assertEqual(r["unspent_minor"], 7859)
        self.assertEqual(r["debt_free_month"], 2)

    def test_zero_rate_final_payment_spills(self):
        r = self.run_result(scenario([card("a", 70, minimum=20), card("b", 130, minimum=20)], 150))
        self.assertEqual([x["payment_minor"] for x in r["schedule"][:2]], [70, 80])
        self.assertEqual(r["total_payments_minor"], 200)
        self.assertEqual(r["unspent_minor"], 100)
        self.assertEqual(r["total_interest_minor"], 0)

    def test_largest_and_avalanche_rank_differ(self):
        doc = scenario([card("large", 100000, "0.12", 1000), card("small", 20000, "0.24", 1000)], 10000,
                       strategies=[{"kind": "largest_balance"}, {"kind": "avalanche"}])
        a, b = simulate(doc)["results"]
        self.assertEqual(next(x["extra_minor"] for x in a["schedule"] if x["account_id"] == "card:large"), 8000)
        self.assertEqual(next(x["extra_minor"] for x in b["schedule"] if x["account_id"] == "card:small"), 8000)
        self.assertGreater(a["delta_cost_vs_avalanche_minor"], 0)
        self.assertEqual(a["within_tolerance"], "unset")

    def test_equal_rate_exact_example(self):
        d = scenario([card("a", 10000, "0.12"), card("b", 10000, "0.12")], 10100,
                     strategies=[{"kind": "snowball"}, {"kind": "largest_balance"}, {"kind": "avalanche"}])
        runs = simulate(d)["results"]
        self.assertEqual({r["total_interest_minor"] for r in runs}, {302})

    def test_hybrid_band_uses_max_not_chaining(self):
        cards = [card("a", 10000, "0.24"), card("b", 20000, "0.245"), card("c", 30000, "0.25")]
        d = scenario(cards, 1000, horizon=1, strategies=[{"kind": "near_apr_hybrid", "gap_pp": "0.5", "prefer": "smallest"}])
        r = self.run_result(d)
        self.assertEqual([x["account_id"] for x in r["schedule"] if x["extra_minor"]], ["card:b"])

    def test_band_sweep(self):
        d = scenario([card("a", 10000, "0.24"), card("b", 20000, "0.245"), card("c", 30000, "0.26")], 10000,
                     strategies=[{"kind": "near_apr_hybrid", "gap_pp": str(g), "prefer": "smallest"} for g in (0, .5, 1, 2)])
        runs = simulate(d)["results"]
        self.assertEqual(len(runs), 5)  # Avalanche baseline added.
        self.assertEqual(runs[0]["delta_cost_vs_avalanche_minor"], 0)
        self.assertTrue(all(r["debt_free_month"] is not None for r in runs))

    def test_budget_under_minimums(self):
        r = self.run_result(scenario([card("a", 10000, "0.12", 1500), card("b", 10000, "0.12", 1500)], 2000))
        self.assertEqual(r["run_status"], "infeasible_budget")
        self.assertEqual(r["total_payments_minor"], 0)
        self.assertEqual(r["final_debt_minor"], 20200)
        self.assertIsNone(r["debt_free_month"])
        self.assertIsNone(r["delta_cost_vs_avalanche_minor"])

    def test_negative_amortization_and_horizon(self):
        r = self.run_result(scenario([card("a", 12000, "0.12")], 100, horizon=2))
        self.assertEqual(r["run_status"], "horizon_reached")
        self.assertGreater(r["final_debt_minor"], 12000)
        self.assertIn("negative_amortization", [x["code"] for x in r["flags"]])
        self.assertIsNone(r["debt_free_month"])
        self.assertIsNone(r["payoff_month_by_account"][0]["payoff_month"])

    def test_zero_debt_and_future_charge(self):
        c = card("a", 0)
        c["assumed_charges"] = [{"month": 3, "amount_minor": 120}]
        r = self.run_result(scenario([c], 100))
        self.assertEqual(r["debt_free_month"], 4)
        self.assertEqual(r["total_payments_minor"], 120)
        self.assertEqual(r["payoff_month_by_account"][0]["payoff_month"], 4)
        self.assertEqual(self.run_result(scenario([card("a", 0)]))["debt_free_month"], 0)

    def test_budget_override_lump_fee_and_charge(self):
        c = card("a", 10000)
        c["fees"] = [{"month": 1, "amount_minor": 500}]
        c["assumed_charges"] = [{"month": 1, "amount_minor": 1000}]
        d = scenario([c], 1000)
        d["scenario"]["cash_plan"].update(overrides=[{"month": 1, "amount_minor": 500}], lump_sums=[{"month": 1, "amount_minor": 11000}])
        r = self.run_result(d)
        self.assertEqual(r["debt_free_month"], 1)
        self.assertEqual(r["total_fees_minor"], 500)
        self.assertEqual(r["total_payments_minor"], 11500)

    def test_promotion_expires_after_declared_month(self):
        c = card("a", 12000)
        c["buckets"][0].update(promo_end_month=1, post_promo_apr="0.12")
        r = self.run_result(scenario([c], 1000, horizon=2))
        self.assertEqual([x["interest_minor"] for x in r["schedule"]], [0, 110])
        self.assertIn("promo_expired", [x["code"] for x in r["flags"]])

    def test_unsupported_deferred_and_buckets(self):
        d = json.loads((ROOT / "contracts/examples/valid/payoff_scenario.json").read_text())
        runs = simulate(d)["results"]
        self.assertTrue(all(r["run_status"] == "unsupported_terms" for r in runs))
        self.assertTrue(all(not r["schedule"] and r["final_debt_minor"] == 180500 for r in runs))
        self.assertTrue(all(r["within_tolerance"] == "unset" for r in runs))

    def test_percentage_minimums(self):
        for rule, expected in [(dict(rule_type="pct", pct="0.02", floor_minor=0), 242),
                               (dict(rule_type="pct_plus_interest", pct="0.01", floor_minor=0), 240)]:
            c = card("a", 12000, "0.12")
            c["min_payment_rule"] = rule
            r = self.run_result(scenario([c], 1000, horizon=1))
            self.assertEqual(r["schedule"][0]["minimum_minor"], expected)

    def test_tolerance_requires_both_limits_and_complete_runs(self):
        d = scenario(strategies=[{"kind": "largest_balance"}])
        d["scenario"]["tolerance"] = {"max_extra_cost_minor": 0, "max_payoff_delay_months": 0}
        self.assertEqual(self.run_result(d)["within_tolerance"], "yes")
        d["scenario"]["horizon_months"] = 1
        self.assertEqual(self.run_result(d)["within_tolerance"], "unset")

    def test_marginal_budget_reduces_interest(self):
        d = scenario([card("a", 100000, "0.24")], 10000)
        r = sensitivity(d, 1000)[0]
        self.assertGreater(r["interest_saved_minor"], 0)
        self.assertGreater(r["months_saved"], 0)

    def test_exact_decimal_round_half_up(self):
        r = self.run_result(scenario([card("a", 50, "0.12")], 100))
        self.assertEqual(r["total_interest_minor"], 1)

    def test_minimums_paid_before_extra(self):
        d = scenario([card("a", 10000, "0.12", 900), card("b", 10000, "0.24", 900)], 1900, horizon=1)
        rows = self.run_result(d)["schedule"]
        self.assertEqual([r["minimum_minor"] for r in rows], [900, 900])
        self.assertEqual([r["extra_minor"] for r in rows], [0, 100])

    def test_input_not_mutated_and_deterministic(self):
        d = scenario()
        before = copy.deepcopy(d)
        self.assertEqual(simulate(d), simulate(d))
        self.assertEqual(d, before)

    def test_invalid_duplicate_override_and_outside_horizon(self):
        d = scenario()
        d["scenario"]["cash_plan"]["overrides"] = [{"month": 1, "amount_minor": 100}] * 2
        with self.assertRaises(ScenarioError): simulate(d)
        d = scenario(horizon=1)
        d["scenario"]["cash_plan"]["lump_sums"] = [{"month": 2, "amount_minor": 100}]
        with self.assertRaises(ScenarioError): simulate(d)
        with self.assertRaises(ScenarioError): simulate({"document_type": "command"})
        with self.assertRaises(ScenarioError): sensitivity(scenario(), -1)

    def test_zero_apr_portfolios_match_independent_algebra(self):
        rng = random.Random(20261105)
        strategies = [{"kind": "largest_balance"}, {"kind": "snowball"}, {"kind": "avalanche"},
                      {"kind": "near_apr_hybrid", "gap_pp": "1", "prefer": "largest"}]
        for _ in range(60):
            balances = [rng.randrange(1, 30000) for _ in range(rng.randrange(1, 6))]
            budget = rng.randrange(500, 10000)
            d = scenario([card(chr(97 + i), amount) for i, amount in enumerate(balances)], budget, 600, strategies)
            for run in simulate(d)["results"]:
                self.assertEqual(run["run_status"], "paid_off")
                self.assertEqual(run["debt_free_month"], math.ceil(sum(balances) / budget))
                self.assertEqual(run["total_payments_minor"], sum(balances))
                self.assertEqual(run["total_interest_minor"], 0)

    def test_small_rate_and_fractional_minimum_rounding(self):
        c = card("a", 150, "0.04")  # 150 cents * 4% / 12 = half a cent -> 1.
        c["min_payment_rule"] = {"rule_type": "pct", "pct": "0.015"}
        row = self.run_result(scenario([c], 10, horizon=1))["schedule"][0]
        self.assertEqual((row["interest_minor"], row["minimum_minor"]), (1, 2))

    def test_lock_survives_promo_rate_switch_and_budget_override(self):
        a, b = card("a", 10000, "0.24"), card("b", 10000, "0")
        b["buckets"][0].update(promo_end_month=1, post_promo_apr="0.36")
        d = scenario([a, b], 3000, horizon=2, strategies=[{"kind": "avalanche", "lock_target": True}])
        d["scenario"]["cash_plan"]["overrides"] = [{"month": 2, "amount_minor": 1000}]
        locked, dynamic = simulate(d)["results"]
        self.assertEqual([r["account_id"] for r in locked["schedule"] if r["extra_minor"]], ["card:a", "card:a"])
        self.assertEqual([r["account_id"] for r in dynamic["schedule"] if r["extra_minor"]], ["card:a", "card:b"])

    def live_bundle(self):
        b = json.loads((ROOT / "contracts/examples/valid/ledger_household.json").read_text())
        b["accounts"] = [a for a in b["accounts"] if a["account_id"] != "card:beta"]
        b["transactions"] = [t for t in b["transactions"] if t["account_id"] != "card:beta"]
        b["card_terms"] = [t for t in b["card_terms"] if t["account_id"] == "card:alpha"]
        b["card_terms"][0]["apr_buckets"] = b["card_terms"][0]["apr_buckets"][:1]
        self.assertEqual(validate_document(b), [])
        return b

    def test_readonly_ledger_snapshot_uses_posted_date_and_statement_anchor(self):
        b = self.live_bundle()
        t = copy.deepcopy(next(t for t in b["transactions"] if t["transaction_id"] == "t002"))
        t.update(transaction_id="future_purchase", posted_date="2026-07-15", transaction_date=None,
                 amount_minor=-1000, entry_method="manual")
        t.pop("source", None)
        t["splits"] = [{"split_id": "future.split", "split_kind": "category", "amount_minor": -1000,
                       "category_id": t["splits"][0]["category_id"]}]
        b["transactions"].append(t)
        original = copy.deepcopy(b)
        for as_of, expected in [("2026-07-01", 55000), ("2026-07-15", 56000)]:
            d = from_ledger(b, as_of=as_of, monthly_minor=10000)
            c = d["scenario"]["cards"][0]
            self.assertEqual(c["buckets"][0]["balance_minor"], expected)
            self.assertEqual(c["source_statement_id"], "st_alpha_2026_06")
            self.assertEqual(c["buckets"][0]["apr"], "0.2499")
        self.assertEqual(b, original)

    def test_snapshot_refuses_missing_unreconciled_and_complex_terms(self):
        b = self.live_bundle()
        for change in (lambda x: x.update(card_terms=[]), lambda x: x.update(reconciliations=[]),
                       lambda x: x["card_terms"][0]["apr_buckets"].append(dict(x["card_terms"][0]["apr_buckets"][0], bucket_id="other"))):
            altered = copy.deepcopy(b)
            change(altered)
            with self.assertRaises(ScenarioError): from_ledger(altered, as_of="2026-07-01", monthly_minor=10000)

    def test_calendar_clamping_and_leap_year(self):
        self.assertEqual(payment_date("2024-01-31", 1), "2024-02-29")
        self.assertEqual(payment_date("2026-01-31", 1), "2026-02-28")
        self.assertEqual(payment_date("2026-01-31", 2), "2026-03-31")

    def test_lock_target_persists_until_paid(self):
        d = scenario([card("a", 10000), card("b", 9500)], 3000, horizon=2,
                     strategies=[{"kind": "largest_balance", "lock_target": True}, {"kind": "largest_balance"}])
        locked, ranked, _ = simulate(d)["results"]
        self.assertEqual([r["account_id"] for r in locked["schedule"] if r["extra_minor"]], ["card:a", "card:a"])
        self.assertEqual([r["account_id"] for r in ranked["schedule"] if r["extra_minor"]], ["card:a", "card:b"])


if __name__ == "__main__":
    unittest.main()
