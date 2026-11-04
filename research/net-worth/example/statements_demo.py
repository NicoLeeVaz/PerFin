"""Synthetic personal-statements example (research only; all data fictional).

    python3 research/net-worth/example/statements_demo.py

Tiny double-entry ledger in integer cents. Debit-positive convention: asset balances > 0,
liability balances < 0, income lines < 0, expense lines > 0, valuation gains < 0 (credit).
Net worth = sum of included balance-sheet account balances. Demonstrates the identities
specified in research/net-worth/module-spec.md.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))


@dataclass
class Account:
    id: str
    kind: str                 # asset | liability
    cls: str                  # cash | card | retirement | brokerage | real_estate | mortgage | vehicle | loan | business
    currency: str = "USD"
    liquidity: str = "liquid"  # liquid | restricted | illiquid
    ownership_pct: int = 100   # household economic share, whole percent
    legal_liability_pct: int = 100  # share of the obligation the household is legally responsible for
    include: bool = True
    parent: Optional[str] = None    # holdings roll up to a parent account; never summed separately


@dataclass
class Line:
    acct: str
    amount: int


@dataclass
class Entry:
    date: date
    memo: str
    kind: str                  # opening | income | expense | transfer | principal | valuation | purchase
    lines: List[Line]

    def check(self):
        assert sum(l.amount for l in self.lines) == 0, f"unbalanced entry: {self.memo}"


@dataclass
class Valuation:
    acct: str
    as_of: date
    value: int
    source: str
    method: str
    currency: str = "USD"


CATEGORIES = {  # income/expense/valuation categories (not balance-sheet accounts)
    "inc:salary": "income", "inc:employer_match": "income",
    "exp:groceries": "expense", "exp:card_interest": "expense", "exp:mortgage_interest": "expense",
    "exp:property_tax": "expense", "val:unrealized": "valuation", "eq:opening": "opening",
}


class Ledger:
    def __init__(self, accounts: List[Account]):
        self.accounts = {a.id: a for a in accounts}
        self.entries: List[Entry] = []
        self.valuations: List[Valuation] = []

    def post(self, e: Entry):
        e.check()
        for l in e.lines:
            if l.acct not in self.accounts and l.acct not in CATEGORIES:
                raise KeyError(l.acct)
            if l.acct in self.accounts and self.accounts[l.acct].parent:
                raise ValueError(f"post to parent account, not holding {l.acct}")
        self.entries.append(e)

    def balance(self, acct: str, as_of: date) -> int:
        return sum(l.amount for e in self.entries if e.date <= as_of for l in e.lines if l.acct == acct)

    def balance_sheet(self, as_of: date, stale_days: int = 120, fx: Optional[Dict[str, str]] = None,
                      liability_view: str = "legal"):
        rows, warnings, nw, liquid = [], [], 0, 0
        for a in self.accounts.values():
            if a.parent:
                continue  # holdings are detail of the parent account
            bal = self.balance(a.id, as_of)
            vals = [v for v in self.valuations if v.acct == a.id and v.as_of <= as_of]
            if vals:
                v = max(vals, key=lambda v: v.as_of)
                age = (as_of - v.as_of).days
                if age > stale_days:
                    warnings.append(f"{a.id}: valuation {v.as_of} is {age} days old (stale)")
            if a.currency != "USD" and (not fx or a.currency not in fx):
                warnings.append(f"{a.id}: no {a.currency}->USD rate; excluded from total, not converted at 1.0")
                rows.append((a.id, a.kind, bal, None))
                continue
            share = a.ownership_pct if a.kind == "asset" else (
                a.legal_liability_pct if liability_view == "legal" else a.ownership_pct)
            incl = bal * share // 100 if a.include else 0
            rows.append((a.id, a.kind, bal, incl))
            nw += incl
            if (a.kind == "asset" and a.liquidity == "liquid") or (a.kind == "liability" and a.cls in ("card", "loan")):
                liquid += incl
        return {"rows": rows, "net_worth": nw, "liquid_net_worth": liquid, "warnings": warnings}

    def period(self, start: date, end: date):
        """Income/expense, valuation and cash-flow totals for (start, end]."""
        inc = exp = val = 0
        cf = {"operating": 0, "debt_principal": 0, "investing_and_retirement": 0, "internal_cash_transfer": 0}
        cash_ids = {a.id for a in self.accounts.values() if a.cls == "cash"}
        for e in self.entries:
            if not (start < e.date <= end) or e.kind == "opening":
                continue
            for l in e.lines:
                k = CATEGORIES.get(l.acct)
                if k == "income":
                    inc -= l.amount
                elif k == "expense":
                    exp += l.amount
                elif k == "valuation":
                    val -= l.amount
            touches_cash = any(l.acct in cash_ids for l in e.lines)
            if not touches_cash:
                continue
            cash_move = sum(l.amount for l in e.lines if l.acct in cash_ids)
            others = [l for l in e.lines if l.acct not in cash_ids]
            if not others:
                cf["internal_cash_transfer"] += cash_move
            elif e.kind == "principal":
                cf["debt_principal"] += cash_move
            elif any(CATEGORIES.get(l.acct) in ("income", "expense") for l in others):
                cf["operating"] += cash_move
            else:
                cf["investing_and_retirement"] += cash_move
        return {"income": inc, "expenses": exp, "valuation_change": val, "cash_flow": cf}


def build() -> Ledger:
    A = Account
    led = Ledger([
        A("cash:checking", "asset", "cash"), A("cash:savings", "asset", "cash"),
        A("card:A", "liability", "card"), A("card:B", "liability", "card"),
        A("ret:401k", "asset", "retirement", liquidity="restricted"),
        A("brk:taxable", "asset", "brokerage"),
        A("brk:taxable/FUND1", "asset", "brokerage", parent="brk:taxable"),
        A("re:home", "asset", "real_estate", liquidity="illiquid"),
        A("mtg:home", "liability", "mortgage"),
        A("re:rental_50pct", "asset", "real_estate", liquidity="illiquid", ownership_pct=50),
        A("mtg:rental_joint", "liability", "mortgage", ownership_pct=50, legal_liability_pct=100),
        A("fx:eur_savings", "asset", "cash", currency="EUR"),
    ])
    d0, d1 = date(2026, 6, 30), date(2026, 7, 31)
    E, L = Entry, Line
    led.post(E(d0, "opening balances (setup, not income)", "opening", [
        L("cash:checking", 800000), L("cash:savings", 1500000), L("card:A", -350000), L("card:B", -120000),
        L("ret:401k", 6500000), L("brk:taxable", 2000000), L("re:home", 45000000), L("mtg:home", -30000000),
        L("re:rental_50pct", 30000000), L("mtg:rental_joint", -20000000), L("fx:eur_savings", 100000),
        L("eq:opening", -(800000 + 1500000 - 350000 - 120000 + 6500000 + 2000000 + 45000000 - 30000000
                          + 30000000 - 20000000 + 100000))]))
    led.post(E(date(2026, 7, 1), "salary", "income", [L("cash:checking", 600000), L("inc:salary", -600000)]))
    led.post(E(date(2026, 7, 1), "401k contribution from pay (transfer between included assets)", "transfer",
               [L("ret:401k", 50000), L("cash:checking", -50000)]))
    led.post(E(date(2026, 7, 1), "employer match (income)", "income", [L("ret:401k", 25000), L("inc:employer_match", -25000)]))
    led.post(E(date(2026, 7, 5), "groceries on card A (expense, liability up)", "expense",
               [L("exp:groceries", 40000), L("card:A", -40000)]))
    led.post(E(date(2026, 7, 10), "card A interest charged", "expense", [L("exp:card_interest", 6500), L("card:A", -6500)]))
    led.post(E(date(2026, 7, 20), "card A principal payment from checking", "principal",
               [L("card:A", 200000), L("cash:checking", -200000)]))
    led.post(E(date(2026, 7, 1), "mortgage payment: principal part", "principal", [L("mtg:home", 60000), L("cash:checking", -60000)]))
    led.post(E(date(2026, 7, 1), "mortgage payment: interest part", "expense",
               [L("exp:mortgage_interest", 110000), L("cash:checking", -110000)]))
    led.post(E(date(2026, 7, 15), "move savings to checking (internal)", "transfer",
               [L("cash:checking", 100000), L("cash:savings", -100000)]))
    led.post(E(d1, "brokerage mark-to-market (unrealized, not cash)", "valuation",
               [L("brk:taxable", 45000), L("val:unrealized", -45000)]))
    led.valuations += [
        Valuation("brk:taxable", d1, 2045000, "synthetic statement", "market close"),
        Valuation("ret:401k", d1, 6575000, "synthetic statement", "market close"),
        Valuation("re:home", date(2026, 1, 15), 45000000, "synthetic estimate", "automated estimate"),
        Valuation("re:rental_50pct", d1, 30000000, "synthetic appraisal", "appraisal"),
    ]
    # holdings detail of brk:taxable (not posted; reconciled to the parent)
    led.holdings = {"brk:taxable": [("FUND1", 2045000)]}
    return led


def run(verbose=True):
    led = build()
    d0, d1 = date(2026, 6, 30), date(2026, 7, 31)
    b0, b1 = led.balance_sheet(d0), led.balance_sheet(d1)
    per = led.period(d0, d1)
    bridge = b0["net_worth"] + per["income"] - per["expenses"] + per["valuation_change"]
    out = {
        "opening_net_worth": b0["net_worth"], "closing_net_worth": b1["net_worth"],
        "income": per["income"], "expenses": per["expenses"], "valuation_change": per["valuation_change"],
        "bridge_closing": bridge, "cash_flow": per["cash_flow"],
        "closing_liquid_net_worth": b1["liquid_net_worth"], "warnings": b1["warnings"],
        "economic_view_net_worth": led.balance_sheet(d1, liability_view="economic")["net_worth"],
        "holdings_reconcile": sum(v for _, v in led.holdings["brk:taxable"]) == led.balance("brk:taxable", d1),
    }
    if verbose:
        print(json.dumps(out, indent=1, default=str))
    return led, out


if __name__ == "__main__":
    _, o = run()
    sys.exit(0 if o["bridge_closing"] == o["closing_net_worth"] else 1)
