"""Generate fixtures/excel_core/reports/*.csv from the synthetic contract documents.

Stands in for the 2b repository's report export so 2c is independent of 2a/2b.
Run `python3 tests/excel_core/fixture_gen.py` to rewrite; a test checks no drift.
The workbook tests compute their expected figures separately (perfin_contracts.derive).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _support  # noqa: E402,F401
from perfin_contracts.derive import account_balance  # noqa: E402
from perfin_excel_core.reports import write_report_csv  # noqa: E402

AS_OF = "2026-06-30"
BUNDLE = _support.FIXTURES / "ledger_bundle.synthetic.json"
STAGING = _support.FIXTURES / "staging_batch.synthetic.json"


def report_rows(bundle, staging):
    balanced = {i for r in bundle["reconciliations"] if r["recon_status"] == "balanced"
                for i in r["included_transaction_ids"]}
    accounts = []
    for a in bundle["accounts"]:
        bal = account_balance(bundle, a["account_id"], AS_OF)
        accounts.append({
            "account_id": a["account_id"], "display_name": a["display_name"], "kind": a["kind"],
            "account_class": a["account_class"], "currency": a["currency"], "ledger_balance_minor": bal,
            "display_balance_minor": -bal if a["kind"] == "liability" else bal, "balance_as_of": AS_OF,
            "include_in_net_worth": a.get("include_in_net_worth", True), "liquidity": a.get("liquidity"),
            "ownership_pct": a.get("ownership_pct"), "legal_liability_pct": a.get("legal_liability_pct"),
            "tax_status": a.get("tax_status")})
    txns = [{"transaction_id": t["transaction_id"], "account_id": t["account_id"], "posted_date": t["posted_date"],
             "transaction_date": t.get("transaction_date"), "amount_minor": t["amount_minor"],
             "currency": t["currency"], "description": t["description"], "entry_method": t["entry_method"],
             "reconciled": t["transaction_id"] in balanced, "row_version": t["row_version"]}
            for t in sorted(bundle["transactions"], key=lambda t: (t["posted_date"], t["transaction_id"]))]
    statements = [{k: s.get(k) for k in ("statement_id", "account_id", "period_start", "period_end", "due_date",
                                          "opening_balance_minor", "closing_balance_minor", "minimum_due_minor")}
                  for s in bundle["statements"]]
    recon = [{"reconciliation_id": r["reconciliation_id"], "statement_id": r["statement_id"],
              "included_count": len(r["included_transaction_ids"]), "difference_minor": r["difference_minor"],
              "recon_status": r["recon_status"]} for r in bundle["reconciliations"]]
    cards = []
    for a in bundle["accounts"]:
        if a["account_class"] != "credit_card":
            continue
        sts = sorted((s for s in bundle["statements"] if s["account_id"] == a["account_id"]
                      and s["period_end"] <= AS_OF), key=lambda s: s["period_end"])
        st = sts[-1] if sts else None
        terms = sorted((c for c in bundle["card_terms"] if c["account_id"] == a["account_id"]),
                       key=lambda c: c["effective_from"])
        limit = terms[-1]["credit_limit_minor"] if terms else None
        owed = -account_balance(bundle, a["account_id"], AS_OF)
        paid = sum(p["amount_minor"] for p in bundle["statement_payments"] if st and p["statement_id"] == st["statement_id"])
        closing_owed = -st["closing_balance_minor"] if st else None
        cards.append({"account_id": a["account_id"], "statement_id": st and st["statement_id"],
                      "statement_closing_owed_minor": closing_owed, "current_owed_minor": owed,
                      "credit_limit_minor": limit,
                      "utilization_basis_points": None if not limit else owed * 10000 // limit,
                      "due_date": st and st.get("due_date"), "minimum_due_minor": st and st.get("minimum_due_minor"),
                      "confirmed_payments_minor": paid,
                      "unpaid_statement_minor": None if st is None else max(closing_owed - paid, 0), "as_of": AS_OF})
    b = staging["batch"]
    queue = [{"batch_id": b["batch_id"], "row_number": r["row_number"], "review_state": r["review_state"],
              "duplicate_status": r["duplicate"]["status"],
              "error_codes": ";".join(e["code"] for e in r["errors"]) or None,
              "posted_date": (r["parsed"] or {}).get("posted_date"),
              "amount_minor": (r["parsed"] or {}).get("amount_minor"),
              "description": (r["parsed"] or {}).get("description")} for r in staging["rows"]]
    return {"rpt_accounts": accounts, "rpt_transactions": txns, "rpt_card_status": cards,
            "rpt_statements": statements, "rpt_reconciliation": recon, "rpt_review_queue": queue}


def generate(out_dir):
    rows = report_rows(_support.load_json(BUNDLE), _support.load_json(STAGING))
    for table, data in rows.items():
        write_report_csv(os.path.join(out_dir, table + ".csv"), table, data)
    return sorted(rows)


if __name__ == "__main__":
    print(generate(_support.REPORTS))
