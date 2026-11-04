"""Synthetic fixtures for the store tests and the Windows acceptance script. All data is invented."""
from __future__ import annotations

import hashlib
import itertools
import uuid
from typing import Any, Dict, List, Optional

CV = "1.0.0"
_counter = itertools.count(1)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def command_id() -> str:
    return str(uuid.UUID(int=next(_counter) + (0x5EED << 64)))


def reference_bundle() -> Dict[str, Any]:
    return {
        "contract": "perfin", "contract_version": CV, "document_type": "ledger_bundle", "base_currency": "USD",
        "accounts": [
            {"account_id": "chk:main", "kind": "asset", "account_class": "checking", "display_name": "Synthetic checking",
             "currency": "USD", "opening_balance_minor": 250000, "opening_balance_date": "2026-05-31", "row_version": 1,
             "liquidity": "liquid", "include_in_net_worth": True},
            {"account_id": "sav:reserve", "kind": "asset", "account_class": "savings", "display_name": "Synthetic savings",
             "currency": "USD", "opening_balance_minor": 1000000, "opening_balance_date": "2026-05-31", "row_version": 1},
            {"account_id": "card:alpha", "kind": "liability", "account_class": "credit_card",
             "display_name": "=Card Alpha (formula-looking name)", "currency": "USD", "opening_balance_minor": -45000,
             "opening_balance_date": "2026-05-31", "row_version": 1, "number_hint": "1111"},
            {"account_id": "re:home", "kind": "asset", "account_class": "real_estate", "display_name": "Synthetic home",
             "currency": "USD", "opening_balance_minor": 0, "opening_balance_date": "2026-05-31", "row_version": 1,
             "liquidity": "illiquid", "ownership_pct": 100},
        ],
        "categories": [
            {"category_id": "exp", "name": "Expenses", "category_kind": "expense"},
            {"category_id": "exp.groceries", "name": "Groceries", "category_kind": "expense", "parent_category_id": "exp"},
            {"category_id": "exp.household", "name": "Household", "category_kind": "expense", "parent_category_id": "exp"},
            {"category_id": "exp.card_interest", "name": "Card interest", "category_kind": "interest"},
            {"category_id": "exp.uncategorized", "name": "Uncategorized spending", "category_kind": "expense"},
            {"category_id": "inc.salary", "name": "Salary", "category_kind": "income"},
            {"category_id": "inc.uncategorized", "name": "Uncategorized income", "category_kind": "income"},
        ],
        "transactions": [],
    }


def row(n: int, posted: str, amount: Optional[int], desc: str, *, splits: Optional[List[Dict[str, Any]]] = None,
        errors: Optional[List[Dict[str, Any]]] = None, dup: str = "none", state: str = "pending",
        source_txn_id: Optional[str] = None) -> Dict[str, Any]:
    r: Dict[str, Any] = {"row_number": n, "raw_fields": [posted, desc, "" if amount is None else str(amount)],
                         "fingerprint": sha("fp:%d:%s:%s:%s" % (n, posted, amount, desc)),
                         "errors": errors or [], "duplicate": {"status": dup}, "review_state": state}
    if amount is None:
        r["parsed"] = None
        if not errors:
            r["errors"] = [{"code": "E_PARSE_AMOUNT", "path": "raw_fields[2]", "message": "synthetic bad amount"}]
    else:
        r["parsed"] = {"posted_date": posted, "amount_minor": amount, "description": desc}
        if source_txn_id:
            r["parsed"]["source_txn_id"] = source_txn_id
    if splits is not None:
        r["proposed_splits"] = splits
    return r


def batch(batch_id: str, account_id: str, rows: List[Dict[str, Any]], file_text: Optional[str] = None) -> Dict[str, Any]:
    return {"contract": "perfin", "contract_version": CV, "document_type": "staging_batch",
            "batch": {"batch_id": batch_id, "profile_id": "synthetic_profile", "profile_version": "1.0.0",
                      "account_id": account_id, "source_file_sha256": sha(file_text or batch_id),
                      "source_file_name": "%s.csv" % batch_id, "staged_at": "2026-07-02T10:00:00Z",
                      "importer_version": "0.1.0", "batch_status": "staged"},
            "rows": rows}


def cat(split_id: str, amount: int, category: str) -> Dict[str, Any]:
    return {"split_id": split_id, "split_kind": "category", "amount_minor": amount, "category_id": category}


def command(command_type: str, payload: Dict[str, Any], expected: Optional[List[Dict[str, Any]]] = None,
            issued_by: str = "cli:test") -> Dict[str, Any]:
    return {"contract": "perfin", "contract_version": CV, "document_type": "command", "command_id": command_id(),
            "command_type": command_type, "issued_at": "2026-07-02T11:00:00Z", "issued_by": issued_by,
            "payload": payload, "expected_versions": expected or []}


def ev(entity: str, entity_id: str, version: int) -> Dict[str, Any]:
    return {"entity": entity, "entity_id": entity_id, "row_version": version}


def card_batch(batch_id: str = "b.alpha.07", file_text: str = "synthetic alpha 2026-07 file") -> Dict[str, Any]:
    """Card batch: two purchases, a refund, a payment row, a parse error and a possible duplicate."""
    return batch(batch_id, "card:alpha", [
        row(1, "2026-07-01", -1234, "SYNTHETIC CAFE, \"DOWNTOWN\"", splits=[cat("p1", -1234, "exp.groceries")],
            source_txn_id="SYN-1"),
        row(2, "2026-07-02", -8000, "SYNTHETIC SUPERSTORE", splits=[cat("p1", -5000, "exp.groceries"),
                                                                  cat("p2", -3000, "exp.household")]),
        row(3, "2026-07-03", 10000, "PAYMENT RECEIVED"),
        row(4, "2026-07-04", None, "BROKEN ROW"),
        row(5, "2026-07-01", -1234, "SYNTHETIC CAFE, \"DOWNTOWN\"", dup="possible",
            splits=[cat("p1", -1234, "exp.groceries")]),
        row(6, "2026-07-05", 2500, "-REFUND starts with minus", splits=[cat("p1", 2500, "exp.groceries")]),
    ], file_text)
