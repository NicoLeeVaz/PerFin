"""PerFin payoff reference engine (research experiment, not production code).

Simplified monthly model "M1" defined in research/payoff/math-spec.md.
Every money value is an int number of US cents. Rates are Decimal.
APR/12 monthly interest is an APPROXIMATION of issuer daily accrual.

Standard library only. Deterministic: no clock, no randomness, no floats.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

TWELVE = Decimal(12)
PP = Decimal("0.01")  # one percentage point when APR is stored as a decimal


def round_cents(x: Decimal) -> int:
    """Round a Decimal amount of cents to an integer cent, half-up (declared rule R1)."""
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def monthly_interest(balance_cents: int, apr: Decimal) -> int:
    """M1 approximation: opening balance x APR / 12, rounded half-up to the cent."""
    if balance_cents <= 0 or apr == 0:
        return 0
    return round_cents(Decimal(balance_cents) * apr / TWELVE)


# --------------------------------------------------------------------------- model

@dataclass
class Bucket:
    id: str
    balance: int
    apr: Decimal                                    # rate charged now (0 for an intro/deferred promo)
    post_apr: Optional[Decimal] = None              # rate after promo_end_month
    promo_end_month: Optional[int] = None           # last month the promo rate applies
    deferred: bool = False                          # deferred-interest promo (retroactive charge)
    accrued_deferred: int = 0                       # shadow interest accrued during the promo

    def rate(self, month: int) -> Decimal:
        if self.promo_end_month is not None and month > self.promo_end_month:
            return self.post_apr if self.post_apr is not None else self.apr
        return self.apr

    def in_promo(self, month: int) -> bool:
        return self.promo_end_month is not None and month <= self.promo_end_month


@dataclass
class Card:
    id: str
    buckets: List[Bucket]
    min_rule: dict
    charges: Dict[int, int] = field(default_factory=dict)   # month -> cents, posted to buckets[0]
    fees: Dict[int, int] = field(default_factory=dict)      # month -> cents, posted to buckets[0]

    @property
    def balance(self) -> int:
        return sum(b.balance for b in self.buckets)


@dataclass
class Scenario:
    name: str
    cards: List[Card]
    budget: int                                   # default monthly cash for ALL card payments
    horizon: int
    budget_overrides: Dict[int, int] = field(default_factory=dict)
    lump_sums: Dict[int, int] = field(default_factory=dict)
    notes: str = ""

    def cash(self, month: int) -> int:
        return self.budget_overrides.get(month, self.budget) + self.lump_sums.get(month, 0)


def _dec(x) -> Decimal:
    return Decimal(str(x))


def scenario_from_dict(d: dict) -> Scenario:
    cards = []
    for c in d["cards"]:
        if "buckets" in c:
            bks = [Bucket(id=b["id"], balance=int(b["balance_cents"]), apr=_dec(b["apr"]),
                          post_apr=_dec(b["post_apr"]) if "post_apr" in b else None,
                          promo_end_month=b.get("promo_end_month"),
                          deferred=bool(b.get("deferred", False)))
                   for b in c["buckets"]]
        else:
            bks = [Bucket(id="main", balance=int(c["balance_cents"]), apr=_dec(c["apr"]))]
        cards.append(Card(id=c["id"], buckets=bks, min_rule=c["min_rule"],
                          charges={int(k): int(v) for k, v in c.get("charges", {}).items()},
                          fees={int(k): int(v) for k, v in c.get("fees", {}).items()}))
    return Scenario(name=d["name"], cards=cards, budget=int(d["budget_cents"]), horizon=int(d["horizon"]),
                    budget_overrides={int(k): int(v) for k, v in d.get("budget_overrides", {}).items()},
                    lump_sums={int(k): int(v) for k, v in d.get("lump_sums", {}).items()},
                    notes=d.get("notes", ""))


def load_scenario(path: str) -> Scenario:
    with open(path, encoding="utf-8") as f:
        return scenario_from_dict(json.load(f))


def minimum_due(rule: dict, statement_balance: int, interest: int, fees: int) -> int:
    """Forecast minimum (declared rule, not an issuer's actual formula)."""
    if statement_balance <= 0:
        return 0
    t = rule["type"]
    if t == "fixed":
        m = int(rule["amount_cents"])
    elif t == "pct":
        m = max(int(rule.get("floor_cents", 0)), round_cents(_dec(rule["pct"]) * statement_balance))
    elif t == "pct_plus_interest":
        m = max(int(rule.get("floor_cents", 0)),
                round_cents(_dec(rule["pct"]) * statement_balance) + interest + fees)
    else:
        raise ValueError(f"unsupported min rule {t!r}")
    return min(m, statement_balance)


# ------------------------------------------------------------- within-card allocation

def min_order(card: Card, month: int) -> List[Bucket]:
    """Assumption A6: issuer applies the MINIMUM to the lowest current rate first (adverse case)."""
    return sorted(card.buckets, key=lambda b: (b.rate(month), b.id))


def excess_order(card: Card, month: int) -> List[Bucket]:
    """Excess over the minimum: highest current rate first (12 CFR 1026.53(a) as modelled),
    except a deferred-interest bucket goes first in the two cycles before expiry (1026.53(b)(1))."""
    def key(b: Bucket):
        last_two = b.deferred and b.promo_end_month is not None and month in (b.promo_end_month - 1, b.promo_end_month)
        return (0 if last_two else 1, -b.rate(month), b.id)
    return sorted(card.buckets, key=key)


def _apply(order: List[Bucket], amount: int) -> Dict[str, int]:
    out = {}
    for b in order:
        if amount <= 0:
            break
        x = min(amount, b.balance)
        if x:
            b.balance -= x
            out[b.id] = out.get(b.id, 0) + x
            amount -= x
    assert amount == 0, "payment exceeded card balance"
    return out


# ------------------------------------------------------------------ strategies

STRATEGIES = ("largest", "snowball", "avalanche", "hybrid")


@dataclass
class Strategy:
    kind: str                      # largest | snowball | avalanche | hybrid
    gap_pp: Decimal = Decimal(0)   # hybrid: band below highest marginal APR, percentage points
    prefer: str = "smallest"       # hybrid: smallest | largest balance within the band
    lock_target: bool = False      # keep the current target until it is paid off

    @property
    def label(self) -> str:
        s = self.kind if self.kind != "hybrid" else f"hybrid-{self.prefer}-{self.gap_pp}pp"
        return s + ("+lock" if self.lock_target else "")


def allocate_extra(cards: List[Card], remaining_after_min: Dict[str, int], extra: int, month: int,
                   strat: Strategy, locked: Optional[str]) -> Tuple[Dict[str, int], Optional[str]]:
    """Distribute `extra` cents. Returns (per-card extra, new locked target).

    Capacity of a card = remaining statement balance after its minimum.
    Balance keys use a SNAPSHOT of remaining_after_min taken before any extra this month.
    APR keys use the card's current *marginal* APR: the rate of the bucket its next excess dollar hits.
    """
    snap = dict(remaining_after_min)
    cap = {c.id: remaining_after_min[c.id] for c in cards}
    # per-card queue of (bucket rate, bucket capacity) in excess-allocation order
    queues: Dict[str, List[List]] = {}
    for c in cards:
        # capacity per bucket after minimum was already applied to the live buckets
        queues[c.id] = [[b.rate(month), b.balance] for b in excess_order(c, month) if b.balance > 0]
    alloc = {c.id: 0 for c in cards}

    def marginal(cid: str) -> Optional[Decimal]:
        for q in queues[cid]:
            if q[1] > 0:
                return q[0]
        return None

    def choose() -> Optional[str]:
        live = [cid for cid in cap if cap[cid] > 0]
        if not live:
            return None
        if strat.lock_target and locked in live:
            return locked
        if strat.kind == "largest":
            return sorted(live, key=lambda c: (-snap[c], c))[0]
        if strat.kind == "snowball":
            return sorted(live, key=lambda c: (snap[c], c))[0]
        if strat.kind == "avalanche":
            return sorted(live, key=lambda c: (-marginal(c), c))[0]
        if strat.kind == "hybrid":
            top = max(marginal(c) for c in live)
            band = [c for c in live if marginal(c) >= top - strat.gap_pp * PP]
            if strat.prefer == "smallest":
                return sorted(band, key=lambda c: (snap[c], -marginal(c), c))[0]
            return sorted(band, key=lambda c: (-snap[c], -marginal(c), c))[0]
        raise ValueError(strat.kind)

    while extra > 0:
        cid = choose()
        if cid is None:
            break
        if strat.lock_target:
            locked = cid
        # APR-based rules fill one bucket segment, then re-choose; balance rules fill the whole card
        if strat.kind in ("avalanche", "hybrid") and not strat.lock_target:
            seg = next(q for q in queues[cid] if q[1] > 0)
            x = min(extra, seg[1])
            seg[1] -= x
        else:
            x = min(extra, cap[cid])
            left = x
            for q in queues[cid]:
                y = min(left, q[1]); q[1] -= y; left -= y
        alloc[cid] += x
        cap[cid] -= x
        extra -= x
    if locked is not None and cap.get(locked, 0) == 0:
        locked = None
    return alloc, locked


# ------------------------------------------------------------------ simulation

@dataclass
class Result:
    scenario: str
    strategy: str
    status: str                              # PAID_OFF | HORIZON_REACHED | INFEASIBLE_BUDGET
    months_simulated: int
    rows: List[dict]
    interest: int
    fees: int
    payments: int
    unspent: int
    charges: int
    initial_debt: int
    final_debt: int
    payoff_month: Dict[str, Optional[int]]
    debt_free_month: Optional[int]
    first_payoff: Optional[Tuple[int, str]]
    flags: List[str]

    @property
    def cost(self) -> int:
        return self.interest + self.fees


def _clone(s: Scenario) -> Scenario:
    return scenario_from_dict(to_dict(s))


def to_dict(s: Scenario) -> dict:
    return {"name": s.name, "budget_cents": s.budget, "horizon": s.horizon, "notes": s.notes,
            "budget_overrides": {str(k): v for k, v in s.budget_overrides.items()},
            "lump_sums": {str(k): v for k, v in s.lump_sums.items()},
            "cards": [{"id": c.id, "min_rule": c.min_rule,
                       "charges": {str(k): v for k, v in c.charges.items()},
                       "fees": {str(k): v for k, v in c.fees.items()},
                       "buckets": [dict({"id": b.id, "balance_cents": b.balance, "apr": str(b.apr)},
                                        **({"post_apr": str(b.post_apr)} if b.post_apr is not None else {}),
                                        **({"promo_end_month": b.promo_end_month} if b.promo_end_month is not None else {}),
                                        **({"deferred": True} if b.deferred else {}))
                                   for b in c.buckets]} for c in s.cards]}


def simulate(scn: Scenario, strat: Strategy, minimum_only: bool = False) -> Result:
    s = _clone(scn)
    cards = sorted(s.cards, key=lambda c: c.id)
    initial = sum(c.balance for c in cards)
    rows, flags = [], []
    tot = {"interest": 0, "fees": 0, "payments": 0, "unspent": 0, "charges": 0}
    locked = None
    status, last_month = "HORIZON_REACHED", 0
    future_activity = lambda m: any(k > m for c in cards for k in list(c.charges) + list(c.fees))

    for month in range(1, s.horizon + 1):
        if all(c.balance == 0 for c in cards) and not future_activity(month - 1):
            status = "PAID_OFF"
            break
        last_month = month
        st = {}
        # E1 interest on opening balances, E2 fees, E3 charges -> statement balance
        for c in cards:
            opening = c.balance
            interest = 0
            for b in c.buckets:
                if b.deferred and b.in_promo(month):
                    b.accrued_deferred += monthly_interest(b.balance, b.post_apr)
                else:
                    i = monthly_interest(b.balance, b.rate(month))
                    b.balance += i
                    interest += i
            fee = c.fees.get(month, 0)
            chg = c.charges.get(month, 0)
            c.buckets[0].balance += fee + chg
            stmt = c.balance
            m = minimum_due(c.min_rule, stmt, interest, fee)
            st[c.id] = dict(opening=opening, interest=interest, fee=fee, charge=chg, statement=stmt, minimum=m)
        cash = sum(st[c]["minimum"] for c in st) if minimum_only else s.cash(month)
        req = sum(v["minimum"] for v in st.values())
        if req > cash:
            # No plan is produced for this or later months; balances revert to the last completed month.
            status = "INFEASIBLE_BUDGET"
            flags.append(f"month {month}: required minimums {req} > cash {cash}")
            rows.append({"month": month, "infeasible": True, "required": req, "cash": cash})
            last_month = month - 1
            break
        # E4 minimums
        for c in cards:
            _apply(min_order(c, month), st[c.id]["minimum"])
        rem = {c.id: c.balance for c in cards}
        extra = cash - req
        # E5 extra by strategy
        alloc, locked = allocate_extra(cards, rem, extra, month, strat, locked)
        for c in cards:
            _apply(excess_order(c, month), alloc[c.id])
        # E6 deferred-interest deadline
        for c in cards:
            for b in c.buckets:
                if b.deferred and b.promo_end_month == month:
                    if b.balance > 0:
                        b.balance += b.accrued_deferred
                        st[c.id]["interest"] += b.accrued_deferred
                        flags.append(f"month {month}: {c.id}/{b.id} deferred interest {b.accrued_deferred} charged")
                    b.accrued_deferred = 0
                    b.deferred = False
        paid_month = 0
        for c in cards:
            v = st[c.id]
            v["payment"] = v["minimum"] + alloc[c.id]
            v["extra"] = alloc[c.id]
            v["ending"] = c.balance
            paid_month += v["payment"]
            for k, src in (("interest", "interest"), ("fees", "fee"), ("charges", "charge"), ("payments", "payment")):
                tot[k] += v[src]
            if v["ending"] > v["opening"] + v["charge"] + v["fee"] and v["charge"] == 0:
                flags.append(f"month {month}: {c.id} negative amortization ({v['opening']} -> {v['ending']})")
        unspent = cash - paid_month
        tot["unspent"] += unspent
        rows.append({"month": month, "cash": cash, "unspent": unspent, "cards": st})
    else:
        if all(c.balance == 0 for c in cards) and not future_activity(s.horizon):
            status = "PAID_OFF"

    final = sum(c.balance for c in cards)
    if status == "INFEASIBLE_BUDGET":
        complete = [r for r in rows if "cards" in r]
        final = sum(v["ending"] for v in complete[-1]["cards"].values()) if complete else initial
    # payoff month: last month a card's ending balance became 0 and stayed 0 through the end
    payoff = {}
    for c in cards:
        pm = None
        if c.balance == 0 and status != "INFEASIBLE_BUDGET":
            for r in rows:
                if "cards" not in r:
                    continue
                e = r["cards"][c.id]["ending"]
                if e == 0 and pm is None and r["cards"][c.id]["opening"] + r["cards"][c.id]["charge"] > 0:
                    pm = r["month"]
                elif e != 0:
                    pm = None
            if pm is None and initial == 0:
                pm = 0
        payoff[c.id] = pm
    dfm = max(payoff.values()) if status == "PAID_OFF" and all(v is not None for v in payoff.values()) else None
    fp = None
    paid = [(m, cid) for cid, m in payoff.items() if m is not None]
    if paid:
        fp = sorted(paid)[0]
    if status == "HORIZON_REACHED":
        flags.append(f"horizon {s.horizon} reached with {final} cents outstanding; no debt-free date")
    return Result(scenario=s.name, strategy="minimum-only" if minimum_only else strat.label, status=status,
                  months_simulated=last_month, rows=rows, interest=tot["interest"], fees=tot["fees"],
                  payments=tot["payments"], unspent=tot["unspent"], charges=tot["charges"],
                  initial_debt=initial, final_debt=final, payoff_month=payoff, debt_free_month=dfm,
                  first_payoff=fp, flags=flags)


# ------------------------------------------------------------------ invariants

def check_invariants(scn: Scenario, r: Result) -> List[str]:
    """Return violated invariants (empty list = all pass)."""
    bad = []
    if r.initial_debt + r.charges + r.interest + r.fees - r.payments != r.final_debt:
        bad.append("I1 aggregate conservation")
    for row in r.rows:
        if row.get("infeasible"):
            continue
        paid = 0
        for cid, v in row["cards"].items():
            if v["opening"] + v["interest"] + v["fee"] + v["charge"] - v["payment"] != v["ending"]:
                bad.append(f"I2 card conservation m{row['month']} {cid}")
            if v["ending"] < 0:
                bad.append(f"I3 negative balance m{row['month']} {cid}")
            if v["payment"] < v["minimum"]:
                bad.append(f"I4 minimum unpaid m{row['month']} {cid}")
            if v["payment"] > v["statement"]:
                bad.append(f"I5 overpayment m{row['month']} {cid}")
            paid += v["payment"]
        if paid + row["unspent"] != row["cash"] or row["unspent"] < 0:
            bad.append(f"I6 budget identity m{row['month']}")
        if row["unspent"] > 0 and any(v["ending"] > 0 for v in row["cards"].values()):
            bad.append(f"I7 idle cash while debt remains m{row['month']}")
    if r.status != "PAID_OFF" and r.debt_free_month is not None:
        bad.append("I8 debt-free date reported without payoff")
    for cid, m in r.payoff_month.items():
        if m is not None and r.status == "HORIZON_REACHED":
            end = r.rows[-1]["cards"][cid]["ending"]
            if end != 0:
                bad.append(f"I9 payoff reported for {cid} with balance")
    return bad


def money(c: Optional[int]) -> str:
    if c is None:
        return "—"
    sign = "-" if c < 0 else ""
    c = abs(c)
    return f"{sign}${c // 100:,}.{c % 100:02d}"
