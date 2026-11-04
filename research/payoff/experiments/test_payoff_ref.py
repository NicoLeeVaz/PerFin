"""Hand-calculated and property tests for payoff_ref.py, oracle.py and daily.py.

    python3 -m unittest discover -s research/payoff/experiments -p "test_*.py" -v
Expected values are derived by hand in research/payoff/experiments.md, section "Hand calculations".
"""
import glob
import os
import sys
import unittest
from datetime import date
from decimal import Decimal as D

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import daily  # noqa: E402
import oracle  # noqa: E402
from payoff_ref import (Strategy, check_invariants, load_scenario, monthly_interest,  # noqa: E402
                        scenario_from_dict, simulate)

FX = lambda a: {"type": "fixed", "amount_cents": a}  # noqa: E731
P1 = {"type": "pct_plus_interest", "pct": "0.01", "floor_cents": 2500}
AV, LG, SB = Strategy("avalanche"), Strategy("largest"), Strategy("snowball")


def fx(name):
    return load_scenario(os.path.join(HERE, "fixtures", name + ".json"))


def two_card():
    return scenario_from_dict({"name": "hand", "budget_cents": 30000, "horizon": 2, "cards": [
        {"id": "A", "balance_cents": 100000, "apr": "0.24", "min_rule": FX(2500)},
        {"id": "B", "balance_cents": 50000, "apr": "0.12", "min_rule": FX(2500)}]})


class Rounding(unittest.TestCase):
    def test_interest_rounding(self):
        self.assertEqual(monthly_interest(100000, D("0.24")), 2000)
        self.assertEqual(monthly_interest(12345, D("0.1999")), 206)   # 205.647 -> 206
        self.assertEqual(monthly_interest(300, D("0.02")), 1)         # exactly 0.5 -> 1 (half-up)
        self.assertEqual(monthly_interest(0, D("0.29")), 0)
        self.assertEqual(monthly_interest(500000, D("0")), 0)


class HandSchedules(unittest.TestCase):
    def test_two_card_avalanche(self):
        r = simulate(two_card(), AV)
        m1, m2 = r.rows[0]["cards"], r.rows[1]["cards"]
        self.assertEqual((m1["A"]["interest"], m1["B"]["interest"]), (2000, 500))
        self.assertEqual((m1["A"]["ending"], m1["B"]["ending"]), (74500, 48000))
        self.assertEqual((m2["A"]["interest"], m2["B"]["interest"]), (1490, 480))
        self.assertEqual((m2["A"]["ending"], m2["B"]["ending"]), (48490, 45980))
        self.assertEqual(r.interest, 4470)
        self.assertEqual(r.status, "HORIZON_REACHED")
        self.assertIsNone(r.debt_free_month)

    def test_two_card_largest_equals_avalanche_here(self):
        self.assertEqual(simulate(two_card(), LG).interest, 4470)

    def test_two_card_snowball_spill(self):
        r = simulate(two_card(), SB)
        m2 = r.rows[1]["cards"]
        self.assertEqual(r.rows[0]["cards"]["B"]["ending"], 23000)
        self.assertEqual(m2["B"]["payment"], 23230)                   # 2500 minimum + 20730 payoff
        self.assertEqual(m2["A"]["extra"], 4270)                      # residual capacity spilled
        self.assertEqual(m2["A"]["ending"], 94720)
        self.assertEqual(r.interest, 4720)
        self.assertEqual(r.payoff_month["B"], 2)
        self.assertIsNone(r.payoff_month["A"])

    def test_oracle_replay_matches(self):
        r = simulate(two_card(), SB)
        cards = [oracle.Card("A", 100000, "0.24", FX(2500)), oracle.Card("B", 50000, "0.12", FX(2500))]
        plan = [[row["cards"]["A"]["extra"], row["cards"]["B"]["extra"]] for row in r.rows]
        self.assertEqual(oracle.replay(cards, {1: 30000, 2: 30000}, 2, plan), r.interest)

    def test_final_payment_spillover_month1(self):
        r = simulate(fx("f07_final_payment_spillover"), AV)
        c = r.rows[0]["cards"]
        self.assertEqual((c["A"]["statement"], c["B"]["statement"], c["C"]["statement"]), (12200, 13238, 405000))
        self.assertEqual(c["C"]["minimum"], 9050)                     # 1% of 405000 + 5000 interest
        self.assertEqual((c["A"]["ending"], c["B"]["ending"]), (0, 0))
        self.assertEqual(c["C"]["extra"], 15512)
        self.assertEqual(sum(v["payment"] for v in c.values()), 50000)
        self.assertEqual((r.payoff_month["A"], r.payoff_month["B"]), (1, 1))

    def test_zero_apr_conservation(self):
        r = simulate(fx("f04_zero_apr"), AV)
        self.assertEqual((r.interest, r.payments, r.final_debt), (0, 130000, 0))
        self.assertEqual(r.rows[0]["cards"]["A"]["ending"], 0)
        self.assertEqual(r.rows[0]["cards"]["B"]["ending"], 80000)
        self.assertEqual(r.rows[2]["unspent"], 20000)
        self.assertEqual(r.debt_free_month, 3)


class FailureStates(unittest.TestCase):
    def test_infeasible(self):
        for st in (AV, LG, SB):
            r = simulate(fx("f05_insufficient_budget"), st)
            self.assertEqual(r.status, "INFEASIBLE_BUDGET")
            self.assertIsNone(r.debt_free_month)
            self.assertTrue(all(v is None for v in r.payoff_month.values()))
            self.assertEqual(check_invariants(fx("f05_insufficient_budget"), r), [])

    def test_horizon_never_reports_payoff(self):
        r = simulate(fx("f12_horizon_truncation"), AV)
        self.assertEqual(r.status, "HORIZON_REACHED")
        self.assertGreater(r.final_debt, 0)
        self.assertIsNone(r.debt_free_month)
        self.assertTrue(all(v is None for v in r.payoff_month.values()))

    def test_negative_amortization_flagged(self):
        r = simulate(fx("f06_negative_amortization"), AV)
        self.assertGreater(r.final_debt, r.initial_debt)
        self.assertTrue(any("negative amortization" in f for f in r.flags))


class Ranking(unittest.TestCase):
    def test_band_is_measured_from_top_not_chained(self):
        r = simulate(fx("f03_near_rates"), Strategy("hybrid", D("2"), "smallest"))
        c = r.rows[0]["cards"]
        self.assertGreater(c["C"]["extra"], 0)                        # 29% card; 24.5% is 4.5 pp below
        self.assertEqual(c["B"]["extra"], 0)

    def test_band_half_point(self):
        scn = fx("f03b_near_rates_close_top")                         # A 26.99, B 26.59 (0.40 pp), C 25.49
        self.assertGreater(simulate(scn, Strategy("hybrid", D("0.5"), "smallest")).rows[0]["cards"]["B"]["extra"], 0)
        self.assertGreater(simulate(scn, Strategy("hybrid", D("0"), "smallest")).rows[0]["cards"]["A"]["extra"], 0)
        self.assertEqual(simulate(scn, Strategy("hybrid", D("1"), "smallest")).rows[0]["cards"]["C"]["extra"], 0)

    def test_gap_zero_hybrid_equals_avalanche_without_ties(self):
        for f in ("f02_big_low_vs_small_high", "f03_near_rates", "f03b_near_rates_close_top"):
            self.assertEqual(simulate(fx(f), Strategy("hybrid", D("0"), "largest")).cost, simulate(fx(f), AV).cost)

    def test_tie_break_by_id(self):
        r = simulate(fx("f01_equal_apr"), AV)
        c = r.rows[0]["cards"]
        self.assertGreater(c["A"]["extra"], 0)
        self.assertEqual(c["B"]["extra"] + c["C"]["extra"], 0)

    def test_equal_apr_costs_agree_up_to_rounding(self):
        costs = [simulate(fx("f01_equal_apr"), s).cost for s in (AV, LG, SB)]
        self.assertLessEqual(max(costs) - min(costs), 2)

    def test_largest_is_not_avalanche(self):
        scn = fx("f02_big_low_vs_small_high")
        self.assertGreater(simulate(scn, LG).cost, simulate(scn, AV).cost)
        self.assertGreater(simulate(scn, LG).rows[0]["cards"]["BIG"]["extra"], 0)
        self.assertGreater(simulate(scn, AV).rows[0]["cards"]["SMALL"]["extra"], 0)

    def test_lock_prevents_alternation(self):
        r = simulate(fx("f14_largest_first_leveling"), Strategy("largest", lock_target=True))
        targets = [max(row["cards"], key=lambda k: row["cards"][k]["extra"]) for row in r.rows if "cards" in row]
        self.assertEqual(targets[:10], ["A"] * 10)


class Promotions(unittest.TestCase):
    def test_deferred_interest_charged_or_waived(self):
        av = simulate(fx("f09_deferred_interest_deadline"), AV)
        sb = simulate(fx("f09_deferred_interest_deadline"), SB)
        self.assertTrue(any("deferred interest" in f for f in av.flags))
        self.assertFalse(any("deferred interest" in f for f in sb.flags))
        self.assertLess(sb.cost, av.cost)                             # counterexample to avalanche optimality

    def test_bucket_allocation(self):
        scn = scenario_from_dict({"name": "bk", "budget_cents": 40000, "horizon": 1, "cards": [
            {"id": "X", "min_rule": FX(10000), "buckets": [
                {"id": "purchase", "balance_cents": 100000, "apr": "0.20"},
                {"id": "cash", "balance_cents": 50000, "apr": "0.30"},
                {"id": "promo", "balance_cents": 100000, "apr": "0", "post_apr": "0.20", "promo_end_month": 12}]}]})
        r = simulate(scn, AV)
        self.assertEqual(r.rows[0]["cards"]["X"]["interest"], 1667 + 1250)
        self.assertEqual(r.rows[0]["cards"]["X"]["ending"], 250000 + 2917 - 40000)

    def test_bucket_balances_detail(self):
        from payoff_ref import Card, Bucket, _apply, min_order, excess_order
        c = Card("X", [Bucket("purchase", 101667, D("0.20")), Bucket("cash", 51250, D("0.30")),
                       Bucket("promo", 100000, D("0"), D("0.20"), 12)], FX(10000))
        _apply(min_order(c, 1), 10000)
        _apply(excess_order(c, 1), 30000)
        self.assertEqual([b.balance for b in c.buckets], [101667, 21250, 90000])

    def test_deferred_last_two_cycles_exception(self):
        from payoff_ref import Card, Bucket, excess_order
        c = Card("X", [Bucket("purchase", 100000, D("0.25")),
                       Bucket("def", 50000, D("0"), D("0.25"), 6, deferred=True)], FX(5000))
        self.assertEqual([b.id for b in excess_order(c, 4)], ["purchase", "def"])
        self.assertEqual([b.id for b in excess_order(c, 5)], ["def", "purchase"])
        self.assertEqual([b.id for b in excess_order(c, 6)], ["def", "purchase"])

    def test_lump_and_budget_override(self):
        r = simulate(fx("f08_lump_sum_and_budget_change"), AV)
        self.assertEqual(r.rows[2]["cash"], 250000)
        self.assertEqual(r.rows[6]["cash"], 35000)
        self.assertEqual(r.rows[9]["cash"], 50000)


class Properties(unittest.TestCase):
    def test_all_fixtures_all_strategies_invariants(self):
        strats = [AV, LG, SB, Strategy("largest", lock_target=True)] + [
            Strategy("hybrid", D(g), p) for g in ("0", "0.5", "1", "2") for p in ("smallest", "largest")]
        for f in glob.glob(os.path.join(HERE, "fixtures", "*.json")):
            scn = load_scenario(f)
            for st in strats:
                self.assertEqual(check_invariants(scn, simulate(scn, st)), [], f"{f} {st.label}")

    def test_deterministic(self):
        a = simulate(fx("f11_multi_bucket"), AV)
        b = simulate(fx("f11_multi_bucket"), AV)
        self.assertEqual(a.rows, b.rows)

    def test_small_enumeration_never_beats_avalanche_fixed_terms(self):
        cards = [oracle.Card("A", 300000, "0.18", FX(5000)), oracle.Card("B", 200000, "0.27", FX(4000))]
        best, _, _, _ = oracle.enumerate_best(cards, {m: 39000 for m in range(1, 4)}, 3, 5000)
        scn = scenario_from_dict({"name": "e", "budget_cents": 39000, "horizon": 3, "cards": [
            {"id": "A", "balance_cents": 300000, "apr": "0.18", "min_rule": FX(5000)},
            {"id": "B", "balance_cents": 200000, "apr": "0.27", "min_rule": FX(4000)}]})
        self.assertEqual(simulate(scn, AV).interest, best)


class Daily(unittest.TestCase):
    def test_hand_values(self):
        self.assertEqual(daily.daily_balance_interest(date(2028, 1, 1), date(2028, 1, 31), 300000,
                                                      [(date(2028, 1, 15), -50000)], D("0.24")), 5556)
        self.assertEqual(daily.daily_balance_interest(date(2028, 2, 1), date(2028, 2, 29), 300000, [], D("0.24")), 5721)
        self.assertEqual(daily.daily_balance_interest(date(2028, 2, 1), date(2028, 2, 29), 300000, [], D("0.24"), 366), 5705)
        self.assertEqual(daily.residual_interest(100000, D("0.24"), 25), 1644)


if __name__ == "__main__":
    unittest.main()
