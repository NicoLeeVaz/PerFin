"""Approximate monthly forecast, not issuer-exact daily accrual.

One bucket per card. Interest (opening * APR / 12, half-up cents), fees and new
charges, minimums, then ranked extra payments. No new balance is written to a ledger.
"""
from __future__ import annotations

import calendar
import copy
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path
import sys

try:
    from perfin_contracts import CONTRACT_VERSION
    from perfin_contracts.semantic import validate_document
except ImportError:  # Source checkout; installed package supplies the same module.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "contracts" / "python"))
    from perfin_contracts import CONTRACT_VERSION
    from perfin_contracts.semantic import validate_document

BOUND = 922337203685477
MODEL = "m1_monthly_apr_div_12"
ENGINE_VERSION = "0.1.0"


class ScenarioError(ValueError):
    """Invalid inputs; safe diagnostic codes do not reproduce financial data."""


def _round(value):
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def payment_date(as_of, month):
    """Month 1 is one calendar month after as_of, clamped to the month's last day."""
    d = date.fromisoformat(as_of)
    y, m0 = divmod(d.year * 12 + d.month - 1 + month, 12)
    return date(y, m0 + 1, min(d.day, calendar.monthrange(y, m0 + 1)[1])).isoformat()


def _validate(document):
    if not isinstance(document, dict) or document.get("document_type") != "payoff_scenario":
        raise ScenarioError("E_DOCUMENT_TYPE: expected payoff_scenario")
    errors = validate_document(document)
    if errors:
        raise ScenarioError("; ".join(f"{c} {p}" for c, p, _ in errors))
    s = document["scenario"]
    for card in s["cards"]:
        if len({b["bucket_id"] for b in card["buckets"]}) != len(card["buckets"]):
            raise ScenarioError("E_DUPLICATE_ID: bucket identifiers must be unique within each card")
    overrides = s["cash_plan"].get("overrides", [])
    if len({x["month"] for x in overrides}) != len(overrides):
        raise ScenarioError("E_DUPLICATE_ID: one budget override per month")
    # Reject events outside the reported forecast rather than silently dropping them.
    events = overrides + s["cash_plan"].get("lump_sums", [])
    events += [e for c in s["cards"] for k in ("fees", "assumed_charges") for e in c.get(k, [])]
    if any(e["month"] > s["horizon_months"] for e in events):
        raise ScenarioError("E_RANGE: dated cash/charge/fee event is outside the forecast horizon")
    initial = sum(b["balance_minor"] for c in s["cards"] for b in c["buckets"])
    if initial > BOUND:
        raise ScenarioError("E_RANGE: aggregate debt exceeds the contract money bound")
    return s


def _events(items):
    result = {}
    for e in items:
        result[e["month"]] = result.get(e["month"], 0) + e["amount_minor"]
    return result


def _rank(ids, balances, rates, strategy):
    kind = strategy["kind"]
    if kind == "avalanche":
        return sorted(ids, key=lambda i: (-rates[i], i))
    if kind == "largest_balance":
        return sorted(ids, key=lambda i: (-balances[i], i))
    if kind == "snowball":
        return sorted(ids, key=lambda i: (balances[i], i))
    # Band is measured from the highest eligible APR; no pairwise chaining.
    top = max(rates[i] for i in ids)
    gap = Decimal(strategy["gap_pp"]) / 100
    eligible = [i for i in ids if top - rates[i] <= gap]
    sign = -1 if strategy["prefer"] == "largest" else 1
    return sorted(eligible, key=lambda i: (sign * balances[i], i))


def _minimum(rule, opening, charges, interest, fees, due):
    kind = rule["rule_type"]
    if kind == "fixed":
        required = rule["amount_minor"]
    elif kind == "pct":
        required = max(rule.get("floor_minor", 0), _round(Decimal(due) * Decimal(rule["pct"])))
    else:
        required = max(rule.get("floor_minor", 0),
                       _round(Decimal(opening + charges) * Decimal(rule["pct"])) + interest + fees)
    return min(due, required)


def _run(s, strategy):
    cards = {c["account_id"]: c for c in s["cards"]}
    balances = {i: sum(b["balance_minor"] for b in c["buckets"]) for i, c in cards.items()}
    result = {"strategy": copy.deepcopy(strategy), "run_status": "horizon_reached",
              "total_interest_minor": 0, "total_fees_minor": 0, "total_payments_minor": 0,
              "unspent_minor": 0, "final_debt_minor": sum(balances.values()), "debt_free_month": None,
              "payoff_month_by_account": [], "flags": [], "schedule": []}
    unsupported = []
    for i, c in cards.items():
        if len(c["buckets"]) != 1:
            unsupported.append((i, "Multiple APR buckets require issuer-specific allocation rules."))
        if any(b["deferred_interest"] for b in c["buckets"]):
            unsupported.append((i, "Deferred interest is not supported by the monthly forecast."))
    if unsupported:
        result["run_status"] = "unsupported_terms"
        result["flags"] = [{"code": "unsupported", "month": None, "account_id": i, "detail": text}
                           for i, text in unsupported]
        result["payoff_month_by_account"] = [{"account_id": i, "payoff_month": None} for i in sorted(cards)]
        return result
    fees = {i: _events(c.get("fees", [])) for i, c in cards.items()}
    charges = {i: _events(c.get("assumed_charges", [])) for i, c in cards.items()}
    future_month = {i: max([m for events in (fees[i], charges[i]) for m, amount in events.items() if amount] or [0])
                    for i in cards}
    payoff = {i: 0 if balances[i] == 0 and future_month[i] == 0 else None for i in cards}
    overrides = {x["month"]: x["amount_minor"] for x in s["cash_plan"].get("overrides", [])}
    lump = _events(s["cash_plan"].get("lump_sums", []))
    locked = None
    if sum(balances.values()) == 0 and not any(future_month.values()):
        result.update(run_status="paid_off", debt_free_month=0)
    else:
        for month in range(1, s["horizon_months"] + 1):
            budget = overrides.get(month, s["cash_plan"]["monthly_minor"]) + lump.get(month, 0)
            rows, rates = {}, {}
            for i in sorted(cards):
                c, opening = cards[i], balances[i]
                bucket = c["buckets"][0]
                expired = bucket.get("promo_end_month") is not None and month > bucket["promo_end_month"]
                rates[i] = Decimal(bucket["post_promo_apr"] if expired else bucket["apr"])
                if expired and month == bucket["promo_end_month"] + 1 and opening:
                    result["flags"].append({"code": "promo_expired", "month": month, "account_id": i})
                interest = _round(Decimal(opening) * rates[i] / 12)
                fee, charge = fees[i].get(month, 0), charges[i].get(month, 0)
                due = opening + interest + fee + charge
                balances[i] = due
                rows[i] = {"month": month, "account_id": i, "opening_minor": opening,
                           "interest_minor": interest, "fees_minor": fee, "charges_minor": charge,
                           "minimum_minor": _minimum(c["min_payment_rule"], opening, charge, interest, fee, due),
                           "extra_minor": 0, "payment_minor": 0, "ending_minor": due}
            required = sum(r["minimum_minor"] for r in rows.values())
            if required > budget:
                result["run_status"] = "infeasible_budget"
                result["flags"].append({"code": "infeasible_budget", "month": month,
                                        "detail": "Available cash cannot cover all minimums; no payments simulated for this month."})
                remaining = budget
            else:
                for i, r in rows.items():
                    r["payment_minor"] = r["minimum_minor"]
                    balances[i] -= r["minimum_minor"]
                remaining = budget - required
                while remaining and any(balances.values()):
                    ids = [i for i in cards if balances[i] > 0]
                    if not strategy.get("lock_target") or locked not in ids:
                        locked = _rank(ids, balances, rates, strategy)[0]
                    extra = min(remaining, balances[locked])
                    rows[locked]["extra_minor"] += extra
                    rows[locked]["payment_minor"] += extra
                    balances[locked] -= extra
                    remaining -= extra
                for i, r in rows.items():
                    if balances[i] > r["opening_minor"]:
                        result["flags"].append({"code": "negative_amortization", "month": month, "account_id": i,
                                                "detail": "Ending debt exceeds opening debt, including assumed charges and fees."})
            for i, r in rows.items():
                r["ending_minor"] = balances[i]
                if balances[i] == 0 and future_month[i] <= month and payoff[i] is None:
                    payoff[i] = month
                result["total_interest_minor"] += r["interest_minor"]
                result["total_fees_minor"] += r["fees_minor"]
                result["total_payments_minor"] += r["payment_minor"]
            result["unspent_minor"] += remaining
            result["schedule"].extend(rows.values())
            result["final_debt_minor"] = sum(balances.values())
            if result["run_status"] == "infeasible_budget":
                break
            if not any(balances.values()) and max(future_month.values()) <= month:
                result.update(run_status="paid_off", debt_free_month=month)
                break
        if result["run_status"] == "horizon_reached":
            result["flags"].append({"code": "horizon_reached", "month": s["horizon_months"],
                                    "detail": "Outstanding debt remains; no debt-free date. Interest-only or growing debt may not amortize."})
    result["payoff_month_by_account"] = [{"account_id": i, "payoff_month": payoff[i]} for i in sorted(cards)]
    return result


def simulate(document):
    """Validate a scenario and return a validated payoff_result, including avalanche.

    The baseline is added if not explicitly requested. Comparisons are available
    only for complete paid-off runs. Unset tolerances never mean approval.
    """
    s = _validate(document)
    with localcontext() as ctx:
        ctx.prec = 50
        strategies = copy.deepcopy(s["strategies"])
        baseline_spec = {"kind": "avalanche"}
        if not any(x["kind"] == "avalanche" and not x.get("lock_target") for x in strategies):
            strategies.append(baseline_spec)
        runs = [_run(s, strategy) for strategy in strategies]
        baseline = next(r for r in runs if r["strategy"]["kind"] == "avalanche" and not r["strategy"].get("lock_target"))
        tolerance = s["tolerance"]
        for r in runs:
            complete = r["run_status"] == baseline["run_status"] == "paid_off"
            cost = r["total_interest_minor"] + r["total_fees_minor"]
            base_cost = baseline["total_interest_minor"] + baseline["total_fees_minor"]
            r["delta_cost_vs_avalanche_minor"] = cost - base_cost if complete else None
            r["delta_months_vs_avalanche"] = r["debt_free_month"] - baseline["debt_free_month"] if complete else None
            known = complete and all(v is not None for v in tolerance.values())
            r["within_tolerance"] = ("yes" if r["delta_cost_vs_avalanche_minor"] <= tolerance["max_extra_cost_minor"]
                                      and r["delta_months_vs_avalanche"] <= tolerance["max_payoff_delay_months"] else "no") if known else "unset"
    result = {"contract": "perfin", "contract_version": CONTRACT_VERSION, "document_type": "payoff_result",
              "scenario_id": s["scenario_id"], "engine_version": ENGINE_VERSION, "accrual_model": MODEL, "results": runs}
    errors = validate_document(result)
    if errors:
        raise ScenarioError("E_RANGE: calculated output exceeds the contract or violates its schema")
    return result


def sensitivity(document, extra_monthly_minor):
    """Compare an explicit extra monthly amount; never label an incomplete delta lifetime savings."""
    if type(extra_monthly_minor) is not int or extra_monthly_minor < 0:
        raise ScenarioError("E_RANGE: extra monthly cash must be nonnegative integer cents")
    changed = copy.deepcopy(document)
    cp = changed["scenario"]["cash_plan"]
    cp["monthly_minor"] += extra_monthly_minor
    for override in cp.get("overrides", []):
        override["amount_minor"] += extra_monthly_minor
    before, after = simulate(document), simulate(changed)
    rows = []
    for a, b in zip(before["results"], after["results"]):
        complete = a["run_status"] == b["run_status"] == "paid_off"
        rows.append({"strategy": a["strategy"], "extra_monthly_minor": extra_monthly_minor,
                     "interest_saved_minor": a["total_interest_minor"] - b["total_interest_minor"] if complete else None,
                     "months_saved": a["debt_free_month"] - b["debt_free_month"] if complete else None,
                     "base_status": a["run_status"], "increased_budget_status": b["run_status"]})
    return rows


def from_ledger(bundle, *, as_of, monthly_minor, scenario_id="ledger_payoff", horizon_months=240, strategies=None):
    """Read-only forecast snapshot of USD posted card balances with reviewed provenance.

    The latest statement is an anchor, not a claim that its closing balance equals
    today's debt. Subsequent posted activity is included. Active terms and a balanced
    latest statement are required; unsupported terms are refused, never flattened.
    """
    from perfin_contracts.derive import account_balance
    if not isinstance(bundle, dict) or bundle.get("document_type") != "ledger_bundle" or validate_document(bundle):
        raise ScenarioError("E_SCHEMA: expected a valid ledger bundle")
    try:
        if date.fromisoformat(as_of).isoformat() != as_of: raise ValueError()
    except (ValueError, TypeError):
        raise ScenarioError("E_DATE_INVALID: as_of must be an ISO date") from None
    if bundle["base_currency"] != "USD":
        raise ScenarioError("E_CURRENCY_MISMATCH: live payoff snapshot currently supports USD only")
    cards = []
    for account in sorted(bundle["accounts"], key=lambda a: a["account_id"]):
        if account["account_class"] != "credit_card" or account["opening_balance_date"] > as_of:
            continue
        aid = account["account_id"]
        if account["currency"] != "USD":
            raise ScenarioError("E_CURRENCY_MISMATCH: card snapshot cannot mix currencies")
        balance = max(0, -account_balance(bundle, aid, as_of))
        if not balance:
            continue
        statements = [x for x in bundle.get("statements", []) if x["account_id"] == aid and x["period_end"] <= as_of]
        if not statements:
            raise ScenarioError("E_REQUIRED: each owed card needs a source statement before forecasting")
        statement = max(statements, key=lambda x: (x["period_end"], x["statement_id"]))
        if not any(r["statement_id"] == statement["statement_id"] and r["recon_status"] == "balanced"
                   for r in bundle.get("reconciliations", [])):
            raise ScenarioError("E_RECON_MISMATCH: reconcile the latest card statement before forecasting")
        terms = [x for x in bundle.get("card_terms", []) if x["account_id"] == aid and x["effective_from"] <= as_of
                 and (x.get("effective_to") is None or x["effective_to"] >= as_of)]
        if len(terms) != 1:
            raise ScenarioError("E_REQUIRED: each owed card needs exactly one active set of APR/minimum terms")
        term = terms[0]
        if len(term["apr_buckets"]) != 1:
            raise ScenarioError("E_UNSUPPORTED: multiple APR buckets cannot be flattened")
        b = term["apr_buckets"][0]
        if b["deferred_interest"] or b.get("promo_end_date") is not None or b.get("post_promo_apr") is not None:
            raise ScenarioError("E_UNSUPPORTED: calendar promotion/deferred terms need an explicitly reviewed what-if scenario")
        cards.append({"account_id": aid, "source_statement_id": statement["statement_id"],
                      "min_payment_rule": copy.deepcopy(term["min_payment_rule"]),
                      "buckets": [{"bucket_id": b["bucket_id"], "balance_minor": balance, "apr": b["apr"], "deferred_interest": False}]})
    if not cards:
        raise ScenarioError("E_REQUIRED: no posted card debt exists at the requested date")
    document = {"contract": "perfin", "contract_version": CONTRACT_VERSION, "document_type": "payoff_scenario",
                "scenario": {"scenario_id": scenario_id, "as_of": as_of, "horizon_months": horizon_months,
                "accrual_model": MODEL, "cash_plan": {"monthly_minor": monthly_minor}, "cards": cards,
                "strategies": copy.deepcopy(strategies or [{"kind": "largest_balance"}, {"kind": "snowball"}, {"kind": "avalanche"},
                                                          {"kind": "near_apr_hybrid", "gap_pp": "0.5", "prefer": "largest"}]),
                "tolerance": {"max_extra_cost_minor": None, "max_payoff_delay_months": None}}}
    _validate(document)
    return document
