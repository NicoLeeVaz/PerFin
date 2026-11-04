"""Run every PerFin payoff experiment and write results/results.md.

    python3 research/payoff/experiments/run_experiments.py

Standard library only; deterministic output (no dates, no randomness).
"""
from __future__ import annotations

import glob
import os
import sys
from datetime import date
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import daily  # noqa: E402
import oracle  # noqa: E402
from payoff_ref import Strategy, load_scenario, money, simulate, check_invariants, scenario_from_dict  # noqa: E402

BASE = [Strategy("largest"), Strategy("snowball"), Strategy("avalanche")]
GAPS = ["0", "0.5", "1", "2"]
HYB = [Strategy("hybrid", Decimal(g), p) for p in ("smallest", "largest") for g in GAPS]
LOCK = [Strategy("largest", lock_target=True), Strategy("snowball", lock_target=True)]
ALL = BASE + HYB + LOCK

out = []
checked = {"schedules": 0, "violations": []}


def p(line=""):
    out.append(line)


def months(x):
    return "—" if x is None else str(x)


def compare_fixture(path):
    scn = load_scenario(path)
    p(f"### {scn.name}")
    p()
    p(scn.notes)
    p()
    av = simulate(scn, Strategy("avalanche"))
    p("| Strategy | Status | Interest + fees | Δ vs avalanche | Debt-free month | Δ months | First card paid (month) | Unpaid at end |")
    p("| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |")
    for st in ALL:
        r = simulate(scn, st)
        bad = check_invariants(scn, r)
        checked["schedules"] += 1
        checked["violations"] += [f"{scn.name}/{r.strategy}: {b}" for b in bad]
        if r.status == "INFEASIBLE_BUDGET":
            p(f"| {r.strategy} | **{r.status}** | — | — | — | — | — | — |")
            continue
        dc = r.cost - av.cost
        dm = (r.debt_free_month - av.debt_free_month) if (r.debt_free_month and av.debt_free_month) else None
        fp = f"{r.first_payoff[1]} ({r.first_payoff[0]})" if r.first_payoff else "none"
        p(f"| {r.strategy} | {r.status} | {money(r.cost)} | {money(dc)} | {months(r.debt_free_month)} | "
          f"{'—' if dm is None else dm} | {fp} | {money(r.final_debt)} |")
    mo = simulate(scn, Strategy("avalanche"), minimum_only=True)
    checked["schedules"] += 1
    checked["violations"] += [f"{scn.name}/min-only: {b}" for b in check_invariants(scn, mo)]
    p()
    p(f"Minimum-only comparison (different cash schedule, not an allocation strategy): status {mo.status}, "
      f"interest + fees {money(mo.cost)} over {mo.months_simulated} months, unpaid at end {money(mo.final_debt)}, "
      f"total paid {money(mo.payments)} vs {money(av.payments)} under the fixed budget.")
    flags = sorted(set(f.split(":")[1].strip().split(" (")[0] for f in av.flags if "negative" in f))
    for f in av.flags[:3]:
        p(f"- avalanche flag: `{f}`")
    if len(av.flags) > 3:
        p(f"- … {len(av.flags) - 3} more flags")
    p()


def target_switches(scn, st):
    r = simulate(scn, st)
    prev, switches = None, 0
    for row in r.rows:
        if "cards" not in row:
            continue
        tgt = max(row["cards"].items(), key=lambda kv: (kv[1]["extra"], kv[0]))
        if tgt[1]["extra"] == 0:
            continue
        if prev and tgt[0] != prev and row["cards"][prev]["opening"] > 0 and r.rows[row["month"] - 2]["cards"][prev]["ending"] > 0:
            switches += 1
        prev = tgt[0]
    return switches, r


def marginal(scn_path, lump=10000):
    scn = load_scenario(scn_path)
    p(f"Fixture `{scn.name}`; extra lump sum {money(lump)} in month 1, everything else identical.")
    p()
    p("| Strategy | Cost without | Cost with | Saving per extra $1 | Debt-free month without → with |")
    p("| --- | ---: | ---: | ---: | --- |")
    for st in BASE:
        a = simulate(scn, st)
        scn2 = load_scenario(scn_path)
        scn2.lump_sums[1] = scn2.lump_sums.get(1, 0) + lump
        b = simulate(scn2, st)
        per = Decimal(a.cost - b.cost) / Decimal(lump)
        p(f"| {st.label} | {money(a.cost)} | {money(b.cost)} | ${per:.4f} | {a.debt_free_month} → {b.debt_free_month} |")
    p()
    p("One-month marginal value of $100 applied to each card (APR/12 approximation):")
    p()
    for c in scn.cards:
        apr = c.buckets[0].apr
        p(f"- {c.id}: APR {apr * 100}% → {money(round(Decimal(10000) * apr / 12))} per $100 per month; "
          f"monthly interest dollars on the whole balance {money(round(Decimal(c.balance) * apr / 12))}")
    p()


def oracle_cases():
    P1 = {"type": "pct_plus_interest", "pct": "0.01", "floor_cents": 2500}
    FX = lambda a: {"type": "fixed", "amount_cents": a}  # noqa: E731
    cases = [
        ("E1 two cards, fixed APR, fixed minimums, no payoff inside horizon", 4, 5000,
         [("A", 300000, "0.18", FX(5000)), ("B", 200000, "0.27", FX(4000))], 39000, "equal"),
        ("E2 three cards, 1%+interest minimums, no payoff", 3, 5000,
         [("A", 400000, "0.24", P1), ("B", 150000, "0.245", P1), ("C", 250000, "0.29", P1)], 40000, "le"),
        ("E3 payoff and spillover inside horizon", 4, 5000,
         [("A", 30000, "0.29", FX(2500)), ("B", 250000, "0.19", FX(5000))], 30000, "le"),
        ("E4 equal APRs", 3, 5000,
         [("A", 100000, "0.20", FX(2500)), ("B", 300000, "0.20", FX(2500)), ("C", 50000, "0.20", FX(2500))], 25000, "le"),
        ("E5 zero APRs", 3, 5000,
         [("A", 20000, "0", FX(2500)), ("B", 60000, "0", FX(2500))], 30000, "le"),
    ]
    p("| Case | Horizon | Grid | Plans enumerated | Avalanche cost (payoff_ref) | Oracle replay of avalanche | Best enumerated | Result |")
    p("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    results = []
    for name, H, chunk, cards, budget, expect in cases:
        d = {"name": name, "budget_cents": budget, "horizon": H,
             "cards": [{"id": i, "balance_cents": b, "apr": a, "min_rule": r} for i, b, a, r in cards]}
        scn = scenario_from_dict(d)
        av = simulate(scn, Strategy("avalanche"))
        ocards = [oracle.Card(i, b, a, r) for i, b, a, r in cards]
        cash = {m: budget for m in range(1, H + 1)}
        plan = [[row["cards"][c.cid]["extra"] for c in ocards] for row in av.rows]
        plan += [[0] * len(ocards)] * (H - len(plan))
        rep = oracle.replay(ocards, cash, H, plan)
        best, bplan, n, _ = oracle.enumerate_best(ocards, cash, H, chunk)
        if expect == "equal":
            ok = rep == av.interest and best == av.interest
            verdict = "PASS: equal" if ok else "FAIL"
        else:
            ok = rep == av.interest and av.interest <= best
            verdict = "PASS: avalanche ≤ grid optimum" if ok else f"FAIL ({money(av.interest - best)})"
        results.append(ok)
        p(f"| {name} | {H} | {money(chunk)} | {n} | {money(av.interest)} | {money(rep)} | {money(best)} | {verdict} |")
    # Counterexample: deferred interest
    H = 6
    cards = [oracle.Card("DEF", 120000, "0", {"type": "fixed", "amount_cents": 2500}, post_apr="0.2699",
                         promo_end=6, deferred=True),
             oracle.Card("HIGH", 300000, "0.2199", {"type": "fixed", "amount_cents": 8000})]
    budget = 30500
    d = {"name": "E6", "budget_cents": budget, "horizon": H, "cards": [
        {"id": "DEF", "min_rule": {"type": "fixed", "amount_cents": 2500},
         "buckets": [{"id": "promo", "balance_cents": 120000, "apr": "0", "post_apr": "0.2699", "promo_end_month": 6, "deferred": True}]},
        {"id": "HIGH", "balance_cents": 300000, "apr": "0.2199", "min_rule": {"type": "fixed", "amount_cents": 8000}}]}
    av = simulate(scenario_from_dict(d), Strategy("avalanche"))
    cash = {m: budget for m in range(1, H + 1)}
    plan = [[row["cards"][c.cid]["extra"] for c in cards] for row in av.rows]
    rep = oracle.replay(cards, cash, H, plan)
    best, bplan, n, _ = oracle.enumerate_best(cards, cash, H, 10000)
    ok = rep == av.interest and best < av.interest
    results.append(ok)
    p(f"| E6 deferred-interest deadline (counterexample expected) | {H} | $100.00 | {n} | {money(av.interest)} | "
      f"{money(rep)} | {money(best)} | {'PASS: grid plan beats avalanche by ' + money(av.interest - best) if ok else 'FAIL'} |")
    p()
    p(f"E6 best enumerated extra allocation by month (DEF, HIGH): {[[money(a) for a in m] for m in bplan]}")
    p()
    return results


def daily_table():
    D = Decimal
    rows = [
        ("Jan 2028, $3,000 opening, $500 paid on day 15", daily.daily_balance_interest(date(2028, 1, 1), date(2028, 1, 31), 300000, [(date(2028, 1, 15), -50000)], D("0.24")), daily.m1_interest(300000, D("0.24")), "55.56 = (3000×14 + 2500×17) × 0.24/365"),
        ("Feb 2028 (29 days, leap), no activity, /365", daily.daily_balance_interest(date(2028, 2, 1), date(2028, 2, 29), 300000, [], D("0.24")), daily.m1_interest(300000, D("0.24")), "57.21 = 3000 × 29 × 0.24/365"),
        ("Feb 2028, /366 day-count", daily.daily_balance_interest(date(2028, 2, 1), date(2028, 2, 29), 300000, [], D("0.24"), 366), daily.m1_interest(300000, D("0.24")), "57.05 = 3000 × 29 × 0.24/366"),
        ("Feb 2027 (28 days), /365", daily.daily_balance_interest(date(2027, 2, 1), date(2027, 2, 28), 300000, [], D("0.24")), daily.m1_interest(300000, D("0.24")), "55.23 = 3000 × 28 × 0.24/365"),
        ("Purchase $400 on day 20 of a 31-day cycle, no grace", daily.daily_balance_interest(date(2028, 3, 1), date(2028, 3, 31), 300000, [(date(2028, 3, 20), 40000)], D("0.24")), daily.m1_interest(300000, D("0.24")), "64.31 = (3000×31 + 400×12) × 0.24/365; M1 defers the purchase to next month"),
    ]
    p("| Cycle | Daily-balance interest | M1 APR/12 on opening | Difference | Hand calculation |")
    p("| --- | ---: | ---: | ---: | --- |")
    for name, dly, m1, hand in rows:
        p(f"| {name} | {money(dly)} | {money(m1)} | {money(m1 - dly)} | {hand} |")
    p()
    res = daily.residual_interest(100000, D("0.24"), 25)
    p(f"Residual (trailing) interest when paying a $1,000 statement in full 25 days after close with no grace period: "
      f"{money(res)} (= 1000 × 0.24/365 × 25). M1 cannot represent this; it would report the card as paid off a cycle early.")
    p()


def main():
    p("# Generated experiment results")
    p()
    p("Generated by `run_experiments.py` (deterministic). Simplified monthly model M1 unless stated: interest = "
      "opening balance × APR/12 rounded half-up per bucket — **an approximation, not issuer accrual**. "
      "Money is integer cents. Negative Δ means cheaper than avalanche.")
    p()
    p("## 1. Strategy comparison by fixture")
    p()
    for f in sorted(glob.glob(os.path.join(HERE, "fixtures", "*.json"))):
        compare_fixture(f)
    p("## 2. Marginal savings per extra dollar")
    p()
    marginal(os.path.join(HERE, "fixtures", "f02_big_low_vs_small_high.json"))
    p("## 3. Literal largest-first re-ranking behaviour")
    p()
    scn = load_scenario(os.path.join(HERE, "fixtures", "f14_largest_first_leveling.json"))
    for st in (Strategy("largest"), Strategy("largest", lock_target=True), Strategy("avalanche")):
        n, r = target_switches(scn, st)
        p(f"- {st.label}: {n} switches of extra-payment target while the previous target still had a balance; "
          f"cost {money(r.cost)}, debt-free month {r.debt_free_month}")
    p()
    p("## 4. Independent enumeration (oracle.py) versus payoff_ref.py")
    p()
    ores = oracle_cases()
    p("## 5. Daily accrual versus the M1 approximation")
    p()
    daily_table()
    p("## 6. Invariant checks")
    p()
    p(f"Schedules checked: {checked['schedules']}. Violations: {len(checked['violations'])}.")
    for v in checked["violations"]:
        p(f"- {v}")
    p()
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "results.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("\n".join(out))
    ok = not checked["violations"] and all(ores)
    print("\nOVERALL:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
