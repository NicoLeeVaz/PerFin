"""Read-only rpt_* report tables and their CSV export in the contract dialect.

Columns and order come from contracts/schemas/report_tables.json (read at run time, never
copied). Values are computed from the stored ledger through the Repository; nothing here
writes to the database. The Access views in access/schema/040_report_views.sql produce the
same tables for Excel/Power Query refresh (see that file for the one documented difference).

CSV dialect (report_tables.json csv_dialect): UTF-8 without BOM, comma, RFC 4180 minimal
quoting, CRLF, exact header, empty field = null, TRUE/FALSE, integer minor units, YYYY-MM-DD.
Text columns get the privacy boundary's formula-injection prefix (config/privacy,
escape_spreadsheet_text) because CSV files are opened by spreadsheet programs; Access keeps
the original text.
"""
from __future__ import annotations

import csv
import io
import json
import os
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import _paths

STORE_TABLES = ("rpt_accounts", "rpt_transactions", "rpt_splits", "rpt_card_status", "rpt_statements",
                "rpt_reconciliation", "rpt_review_queue", "rpt_card_terms", "rpt_valuations", "rpt_statement_buckets")
# rpt_payoff_* and rpt_net_worth_* are produced by the payoff (3b) and statements (3c) modules.


class ExportLocationError(RuntimeError):
    pass


def report_spec() -> Dict[str, Any]:
    schema_dir = _paths.contracts()[1]
    with open(schema_dir / "report_tables.json", encoding="utf-8") as f:
        return json.load(f)


def _balance(opening: int, txns: List[Dict[str, Any]], as_of: str) -> int:
    return opening + sum(t["amount_minor"] for t in txns if t["posted_date"] <= as_of)


def build_tables(repo, as_of: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    as_of = as_of or date.today().isoformat()
    date.fromisoformat(as_of)
    s = repo.snapshot(repo_tables())
    by_acct = defaultdict(list)
    for t in s["ledger_txn"]:
        by_acct[t["account_id"]].append(t)
    balanced = {r["reconciliation_id"] for r in s["reconciliation"] if r["recon_status"] == "balanced"}
    reconciled = {i["transaction_id"] for i in s["reconciliation_item"] if i["reconciliation_id"] in balanced}
    cat_kind = {c["category_id"]: c["category_kind"] for c in s["category"]}
    sort = lambda rows, *keys: sorted(rows, key=lambda r: tuple(r[k] for k in keys))  # noqa: E731
    out: Dict[str, List[Dict[str, Any]]] = {}

    accounts = []
    for a in sort(s["account"], "account_id"):
        bal = _balance(a["opening_balance_minor"], by_acct[a["account_id"]], as_of)
        accounts.append({"account_id": a["account_id"], "display_name": a["display_name"], "kind": a["kind"],
                         "account_class": a["account_class"], "currency": a["currency"], "ledger_balance_minor": bal,
                         "display_balance_minor": -bal if a["kind"] == "liability" else bal, "balance_as_of": as_of,
                         "include_in_net_worth": a["include_in_net_worth"], "liquidity": a["liquidity"],
                         "ownership_pct": a["ownership_pct"], "legal_liability_pct": a["legal_liability_pct"],
                         "tax_status": a["tax_status"]})
    out["rpt_accounts"] = accounts
    out["rpt_transactions"] = [dict({k: t[k] for k in ("transaction_id", "account_id", "posted_date", "transaction_date",
                                                         "amount_minor", "currency", "description", "entry_method")},
                                    reconciled=t["transaction_id"] in reconciled, row_version=t["row_version"])
                               for t in sort(s["ledger_txn"], "posted_date", "transaction_id")]
    out["rpt_splits"] = [{"transaction_id": x["transaction_id"], "split_id": x["split_id"], "split_kind": x["split_kind"],
                          "amount_minor": x["amount_minor"], "category_id": x["category_id"],
                          "category_kind": cat_kind.get(x["category_id"]) if x["category_id"] else None,
                          "transfer_link_id": x["transfer_link_id"]}
                         for x in sort(s["split"], "transaction_id", "split_id")]

    stmts = sort(s["statement"], "statement_id")
    posted = {t["transaction_id"]: t["posted_date"] for t in s["ledger_txn"]}
    paid = defaultdict(int)
    for p in s["statement_payment"]:  # a payment counts only once it has posted (same rule as the balances)
        if posted[p["transaction_id"]] <= as_of:
            paid[p["statement_id"]] += p["amount_minor"]
    cards = []
    for a in accounts:
        if a["account_class"] != "credit_card":
            continue
        aid = a["account_id"]
        latest = max((st for st in stmts if st["account_id"] == aid and st["period_end"] <= as_of),
                     key=lambda st: (st["period_end"], st["statement_id"]), default=None)
        terms = max((ct for ct in s["card_terms"] if ct["account_id"] == aid and ct["effective_from"] <= as_of
                     and (ct["effective_to"] is None or ct["effective_to"] >= as_of)),
                    key=lambda ct: (ct["effective_from"], ct["terms_id"]), default=None)
        limit = terms["credit_limit_minor"] if terms else None
        owed = -a["ledger_balance_minor"]
        util = None
        if limit:  # null or 0 -> unknown, never computed
            util = int((Decimal(owed) * 10000 / Decimal(limit)).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))
        st_owed = -latest["closing_balance_minor"] if latest else None
        payments = paid[latest["statement_id"]] if latest else 0
        cards.append({"account_id": aid, "statement_id": latest["statement_id"] if latest else None,
                      "statement_closing_owed_minor": st_owed, "current_owed_minor": owed, "credit_limit_minor": limit,
                      "utilization_basis_points": util, "due_date": latest["due_date"] if latest else None,
                      "minimum_due_minor": latest["minimum_due_minor"] if latest else None,
                      "confirmed_payments_minor": payments,
                      "unpaid_statement_minor": max(0, st_owed - payments) if latest else None, "as_of": as_of})
    out["rpt_card_status"] = cards
    out["rpt_statements"] = [{k: st[k] for k in ("statement_id", "account_id", "period_start", "period_end", "due_date",
                                                  "opening_balance_minor", "closing_balance_minor", "minimum_due_minor")}
                             for st in stmts]
    counts = defaultdict(int)
    for i in s["reconciliation_item"]:
        counts[i["reconciliation_id"]] += 1
    out["rpt_reconciliation"] = [{"reconciliation_id": r["reconciliation_id"], "statement_id": r["statement_id"],
                                  "included_count": counts[r["reconciliation_id"]], "difference_minor": r["difference_minor"],
                                  "recon_status": r["recon_status"]} for r in sort(s["reconciliation"], "reconciliation_id")]
    open_batches = {b["batch_id"] for b in s["import_batch"] if b["batch_status"] in ("staged", "approved")}
    out["rpt_review_queue"] = [{"batch_id": r["batch_id"], "row_number": r["row_number"], "review_state": r["review_state"],
                                "duplicate_status": r["duplicate_status"],
                                "error_codes": ";".join(e["code"] for e in json.loads(r["errors_json"])) or None,
                                "posted_date": r["parsed_posted_date"], "amount_minor": r["parsed_amount_minor"],
                                "description": r["parsed_description"]}
                               for r in sort(s["staging_row"], "batch_id", "row_number") if r["batch_id"] in open_batches]
    terms_by_id = {ct["terms_id"]: ct for ct in s["card_terms"]}
    out["rpt_card_terms"] = []
    for bk in sort(s["card_apr_bucket"], "terms_id", "bucket_id"):
        ct = terms_by_id[bk["terms_id"]]
        out["rpt_card_terms"].append({
            "terms_id": ct["terms_id"], "account_id": ct["account_id"], "bucket_id": bk["bucket_id"],
            "bucket_kind": bk["bucket_kind"], "apr": bk["apr"], "promo_end_date": bk["promo_end_date"],
            "deferred_interest": bk["deferred_interest"], "effective_from": ct["effective_from"],
            "terms_source": ct["terms_source"], "effective_to": ct["effective_to"],
            "credit_limit_minor": ct["credit_limit_minor"], "min_rule_type": ct["min_rule_type"],
            "min_amount_minor": ct["min_amount_minor"], "min_pct": ct["min_pct"], "min_floor_minor": ct["min_floor_minor"],
            "post_promo_apr": bk["post_promo_apr"]})
    out["rpt_valuations"] = [{k: v[k] for k in ("valuation_id", "account_id", "as_of", "value_minor", "currency",
                                                 "valuation_method", "valuation_source", "cost_basis_minor")}
                             for v in sort(s["asset_valuation"], "valuation_id")]
    st_by_id = {st["statement_id"]: st for st in stmts}
    out["rpt_statement_buckets"] = [{"statement_id": b["statement_id"], "account_id": st_by_id[b["statement_id"]]["account_id"],
                                     "period_end": st_by_id[b["statement_id"]]["period_end"], "bucket_id": b["bucket_id"],
                                     "balance_minor": b["balance_minor"]}
                                    for b in sort(s["statement_bucket_balance"], "statement_id", "bucket_id")]
    return out


def repo_tables():
    from .repository import LEDGER_TABLES
    return LEDGER_TABLES + ("import_batch", "staging_row")


def _cell(value: Any, ctype: str, escape) -> str:
    if value is None:
        return ""
    if ctype == "boolean":
        if not isinstance(value, bool):
            raise TypeError("boolean column needs bool")
        return "TRUE" if value else "FALSE"
    if ctype in ("money_minor", "integer"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("integer column needs int, never float")
        return str(value)
    value = str(value)
    return escape(value) if ctype == "text" else value


def to_csv(table: str, rows: List[Dict[str, Any]], spec: Optional[Dict[str, Any]] = None,
           escape_formulas: bool = True) -> str:
    spec = spec or report_spec()
    columns = spec["tables"][table]
    escape = _paths.privacy().escape_spreadsheet_text if escape_formulas else (lambda v: v)
    buf = io.StringIO(newline="")
    w = csv.writer(buf, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n", doublequote=True)
    w.writerow([c["name"] for c in columns])
    for row in rows:
        if set(row) != {c["name"] for c in columns}:
            raise ValueError("%s row columns differ from report_tables.json" % table)
        cells = []
        for c in columns:
            if row[c["name"]] is None and not c["nullable"]:
                raise ValueError("%s.%s is not nullable" % (table, c["name"]))
            cells.append(_cell(row[c["name"]], c["type"], escape))
        w.writerow(cells)
    return buf.getvalue()


def check_export_dir(path, acknowledge_location: bool = False) -> Dict[str, Any]:
    verdict = _paths.privacy().evaluate_data_dir(str(path))
    if verdict["decision"] == "refuse":
        raise ExportLocationError("refusing to write reports here: " + "; ".join(verdict["reasons"]))
    if verdict["decision"] == "warn" and not acknowledge_location:
        raise ExportLocationError("location needs acknowledgement (--acknowledge-location): " + "; ".join(verdict["reasons"]))
    return verdict


def export_csv(repo, out_dir, as_of: Optional[str] = None, tables=STORE_TABLES,
               acknowledge_location: bool = False) -> List[Path]:
    """Write <out_dir>/<table>.csv for each table. Report CSVs hold financial data: the target
    gets the same location checks as the data root (never inside a checkout)."""
    check_export_dir(out_dir, acknowledge_location)
    os.makedirs(out_dir, exist_ok=True)
    spec = report_spec()
    data = build_tables(repo, as_of)
    paths = []
    for t in tables:
        p = Path(out_dir) / ("%s.csv" % t)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(to_csv(t, data[t], spec))
        paths.append(p)
    return paths
