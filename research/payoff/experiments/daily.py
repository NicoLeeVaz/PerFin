"""Daily-accrual comparison experiments (research only).

Daily balance method, as commonly disclosed: interest = sum over days of end-of-day balance x APR/days_in_year,
summed unrounded and rounded once per cycle (rule R2, an ASSUMPTION; issuers disclose their own method).
Used to measure how far the M1 APR/12-on-opening-balance approximation can drift.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Tuple


def daily_balance_interest(start: date, end: date, opening_cents: int, txns: List[Tuple[date, int]],
                           apr: Decimal, days_in_year: int = 365) -> int:
    """Interest for the cycle [start, end] inclusive. txns: (posting date, signed cents; payments negative).
    A transaction posted on day d affects that day's end-of-day balance."""
    bal = opening_cents
    acc = Decimal(0)
    d = start
    by_day = {}
    for t, a in txns:
        by_day[t] = by_day.get(t, 0) + a
    while d <= end:
        bal += by_day.get(d, 0)
        if bal > 0:
            acc += Decimal(bal) * apr / Decimal(days_in_year)
        d += timedelta(days=1)
    return int(acc.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def residual_interest(statement_cents: int, apr: Decimal, days_from_close_to_payment: int,
                      days_in_year: int = 365) -> int:
    """Interest accrued between statement close and full payment when no grace period applies
    ("residual"/"trailing" interest). It appears on the NEXT statement even after the statement balance is paid."""
    x = Decimal(statement_cents) * apr / Decimal(days_in_year) * days_from_close_to_payment
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def m1_interest(opening_cents: int, apr: Decimal) -> int:
    return int((Decimal(opening_cents) * apr / 12).quantize(Decimal(1), rounding=ROUND_HALF_UP))
