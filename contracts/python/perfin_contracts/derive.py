"""Reference derivations used by conformance tests (not a ledger implementation)."""
from __future__ import annotations

from typing import Dict


def account_balance(bundle: Dict, account_id: str, as_of: str) -> int:
    """Ledger-sign balance: asset positive; liability negative when money is owed."""
    a = next(x for x in bundle["accounts"] if x["account_id"] == account_id)
    return a["opening_balance_minor"] + sum(t["amount_minor"] for t in bundle["transactions"]
                                            if t["account_id"] == account_id and t["posted_date"] <= as_of)


def display_balance(bundle: Dict, account_id: str, as_of: str) -> int:
    """Excel display: liabilities shown as a positive amount owed."""
    a = next(x for x in bundle["accounts"] if x["account_id"] == account_id)
    b = account_balance(bundle, account_id, as_of)
    return -b if a["kind"] == "liability" else b


def period_totals(bundle: Dict, start: str, end: str) -> Dict[str, int]:
    """Income and expense totals for start <= posted_date <= end, as positive numbers.

    Only category splits count. Transfer splits (card payments, savings moves) never count,
    so a card purchase is spending once and paying the card is not spending again.
    Refunds (positive splits on expense categories) reduce spending.
    """
    kinds = {c["category_id"]: c["category_kind"] for c in bundle["categories"]}
    out = {"income": 0, "spending": 0, "interest": 0, "fees": 0}
    key = {"income": "income", "expense": "spending", "interest": "interest", "fee": "fees"}
    for t in bundle["transactions"]:
        if not (start <= t["posted_date"] <= end):
            continue
        for s in t["splits"]:
            if s["split_kind"] != "category":
                continue
            k = kinds[s["category_id"]]
            out[key[k]] += s["amount_minor"] if k == "income" else -s["amount_minor"]
    return out
