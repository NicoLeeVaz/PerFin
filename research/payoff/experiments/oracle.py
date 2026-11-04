"""Independent brute-force oracle for small payoff cases.

Deliberately does NOT import payoff_ref. It re-implements the M1 month (interest on opening
balance at APR/12 rounded half-up, fees/charges ignored, minimum, then extra) for single-bucket
cards, and enumerates every allocation of each month's extra in whole `chunk`-cent units
(unallocated remainder is left unspent, which is allowed but never helps).

Objective: total interest over the horizon. With identical cash per month this is equivalent to
maximising (cash kept - final debt), so plans that leave money idle are correctly penalised.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from itertools import product
from typing import Dict, List, Optional, Tuple


def _r(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _min(rule: dict, stmt: int, interest: int) -> int:
    if stmt <= 0:
        return 0
    if rule["type"] == "fixed":
        m = int(rule["amount_cents"])
    elif rule["type"] == "pct":
        m = max(int(rule.get("floor_cents", 0)), _r(Decimal(str(rule["pct"])) * stmt))
    elif rule["type"] == "pct_plus_interest":
        m = max(int(rule.get("floor_cents", 0)), _r(Decimal(str(rule["pct"])) * stmt) + interest)
    else:
        raise ValueError(rule["type"])
    return m if m < stmt else stmt


class Card:
    def __init__(self, cid: str, balance: int, apr: str, rule: dict, post_apr: Optional[str] = None,
                 promo_end: Optional[int] = None, deferred: bool = False):
        self.cid, self.balance, self.apr, self.rule = cid, balance, Decimal(apr), rule
        self.post_apr = Decimal(post_apr) if post_apr is not None else None
        self.promo_end, self.deferred = promo_end, deferred


def step(state: Tuple, cards: List[Card], month: int, cash: int):
    """Return (statement balances, minimums, interest this month, new shadow-accruals) or None."""
    bals, shadows = state
    stmts, mins, ints, shs = [], [], [], []
    for c, b, sh in zip(cards, bals, shadows):
        promo = c.promo_end is not None and month <= c.promo_end
        rate = c.apr if (promo or c.post_apr is None) else c.post_apr
        if c.deferred and promo:
            sh += _r(Decimal(b) * c.post_apr / 12) if b > 0 else 0
            i = 0
        else:
            i = _r(Decimal(b) * rate / 12) if b > 0 else 0
        stmts.append(b + i); ints.append(i); shs.append(sh)
        mins.append(_min(c.rule, b + i, i))
    if sum(mins) > cash:
        return None
    return stmts, mins, ints, shs


def enumerate_best(cards: List[Card], cash_by_month: Dict[int, int], horizon: int, chunk: int,
                   keep_plans: bool = False):
    """Exhaustive search. Returns (best_cost, best_plan, plans_evaluated, all_costs if keep_plans)."""
    best = [None, None]
    count = [0]
    costs = []

    def rec(month: int, bals: Tuple[int, ...], shadows: Tuple[int, ...], cost: int, plan: list):
        if month > horizon:
            count[0] += 1
            if keep_plans:
                costs.append(cost)
            if best[0] is None or cost < best[0]:
                best[0], best[1] = cost, list(plan)
            return
        cash = cash_by_month[month]
        res = step((bals, shadows), cards, month, cash)
        if res is None:
            return
        stmts, mins, ints, shs = res
        extra = cash - sum(mins)
        caps = [s - m for s, m in zip(stmts, mins)]
        n = extra // chunk
        ranges = [range(0, min(n, (cap + chunk - 1) // chunk) + 1) for cap in caps]
        for ks in product(*ranges):
            if sum(ks) > n:
                continue
            alloc = [min(k * chunk, cap) for k, cap in zip(ks, caps)]
            new_b, new_s, add = [], [], sum(ints)
            for c, s, m, a, sh in zip(cards, stmts, mins, alloc, shs):
                nb = s - m - a
                if c.deferred and c.promo_end == month:
                    if nb > 0:
                        nb += sh
                        add += sh
                    sh = 0
                new_b.append(nb); new_s.append(sh)
            plan.append(alloc)
            rec(month + 1, tuple(new_b), tuple(new_s), cost + add, plan)
            plan.pop()

    rec(1, tuple(c.balance for c in cards), tuple(0 for _ in cards), 0, [])
    return best[0], best[1], count[0], costs


def replay(cards: List[Card], cash_by_month: Dict[int, int], horizon: int, plan: List[List[int]]) -> int:
    """Cost of a given per-month extra allocation (used to cross-check payoff_ref schedules)."""
    bals = tuple(c.balance for c in cards)
    shadows = tuple(0 for _ in cards)
    cost = 0
    for month in range(1, horizon + 1):
        stmts, mins, ints, shs = step((bals, shadows), cards, month, cash_by_month[month])
        cost += sum(ints)
        nb, ns = [], []
        for c, s, m, a, sh in zip(cards, stmts, mins, plan[month - 1], shs):
            b = s - m - a
            assert b >= 0
            if c.deferred and c.promo_end == month:
                if b > 0:
                    b += sh
                    cost += sh
                sh = 0
            nb.append(b); ns.append(sh)
        bals, shadows = tuple(nb), tuple(ns)
    return cost
