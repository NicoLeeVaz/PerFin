"""Run a synthetic SQLite -> reviewed import -> XLSX demonstration without Office.

Usage: python scripts/core/portable_demo.py --out /tmp/perfin-portable-demo
Use a new directory outside the checkout. No private input files are accepted.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import html
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[2]
for folder in ("src", "contracts/python", "excel/core", "excel/payoff", "excel/statements"):
    sys.path.insert(0, str(ROOT / folder))

from perfin_app.paths import checked_root, child, initialize_layout
from perfin_app.service import FinanceApp, accepted
from perfin_app.__main__ import demo_bundle
from perfin_import.profiles import profile_from_mapping

AS_OF = "2026-03-28"
EXPECTED_BALANCES = {"chk:main": 234000, "card:a": -17600, "card:b": -6200}


def _check(evidence, name, passed, detail=None):
    evidence["checks"].append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})
    if not passed:
        raise AssertionError(name)


def _two_cycles(repo, root, evidence):
    accepted(repo.import_bundle(demo_bundle(repo.contract_version)))
    accepted(repo.set_default_categories("expenses", "income"))
    app = FinanceApp(repo, root)
    all_ids = {}
    for month in (2, 3):
        for account, amounts in (("chk:main", (-5000, -3000)),
                                 ("card:a", (-4000, 5000, 200)),
                                 ("card:b", (-1000, 3000, -100))):
            profile = profile_from_mapping({"date": "posted_date", "text": "description", "amount": "amount"},
                profile_id="synthetic-" + account.replace(":", "-"), profile_version="1.0.0",
                account_class="checking" if account == "chk:main" else "credit_card",
                date_format="YYYY-MM-DD", sign_rule="as_is", decimal_separator=".")
            # Decimal display formatting keeps this fixture free of binary-float money.
            data = ("date,text,amount\r\n" + "".join(
                f"2026-{month:02d}-{i + 1:02d},SYNTHETIC {account},{Decimal(amount).scaleb(-2):.2f}\r\n"
                for i, amount in enumerate(amounts))).encode("utf-8")
            before = repo.export_bundle()
            preview = app.import_csv(data, "synthetic.csv", profile, account)
            _check(evidence, f"stage only: {month}/{account}", repo.export_bundle() == before)
            bid = preview["document"]["batch"]["batch_id"]
            app.review(bid, approve=[r["row_number"] for r in preview["document"]["rows"]])
            app.commit(bid)
            all_ids[month, account] = [t["transaction_id"] for t in repo.export_bundle()["transactions"]
                                      if t.get("source", {}).get("batch_id") == bid]
            before = repo.summary()
            replay = app.import_csv(data, "synthetic.csv", profile, account)
            _check(evidence, f"replay no-op: {month}/{account}",
                   replay["result_status"] == "replayed" and repo.summary() == before)
        app.link_transfer(all_ids[month, "chk:main"][0], all_ids[month, "card:a"][1])
        app.link_transfer(all_ids[month, "chk:main"][1], all_ids[month, "card:b"][1])
        for account, opening, activity in (("chk:main", 250000 - 8000 * (month - 2), -8000),
                                          ("card:a", -20000 + 1200 * (month - 2), 1200),
                                          ("card:b", -10000 + 1900 * (month - 2), 1900)):
            sid = f"statement-{month}-{account}"
            app.run("record_statement", {"statement_id": sid, "account_id": account,
                "period_start": f"2026-{month:02d}-01", "period_end": f"2026-{month:02d}-28",
                "opening_balance_minor": opening, "closing_balance_minor": opening + activity})
            app.run("reconcile_statement", {"reconciliation_id": "rec-" + sid, "statement_id": sid,
                "included_transaction_ids": all_ids[month, account], "difference_minor": 0,
                "recon_status": "balanced"})
    summary = repo.summary()
    _check(evidence, "hand-calculated closing balances", summary["account_balances_minor"] == EXPECTED_BALANCES,
           summary["account_balances_minor"])
    _check(evidence, "six balanced statement reconciliations", len(summary["reconciliations"]) == 6)
    _check(evidence, "six imports, sixteen transactions, four transfers",
           len(repo._rows("import_batch")) == 6 and len(repo._rows("ledger_txn")) == 16
           and len(repo._rows("transfer_link")) == 4)
    return app


def _payoff_document(version):
    # Deliberately zero APR: independent arithmetic is 23800 / 10000 -> 3 months,
    # with zero interest, irrespective of payoff order. This is an invented scenario.
    return {"contract": "perfin", "contract_version": version, "document_type": "payoff_scenario",
        "scenario": {"scenario_id": "synthetic_portable", "as_of": AS_OF, "horizon_months": 12,
            "accrual_model": "m1_monthly_apr_div_12", "cash_plan": {"monthly_minor": 10000},
            "cards": [{"account_id": account, "source_statement_id": f"statement-3-{account}",
                "buckets": [{"bucket_id": "purchase", "balance_minor": -EXPECTED_BALANCES[account],
                             "apr": "0", "deferred_interest": False}],
                "min_payment_rule": {"rule_type": "fixed", "amount_minor": 500}}
                for account in ("card:a", "card:b")],
            "strategies": [{"kind": "avalanche"}, {"kind": "snowball"}],
            "tolerance": {"max_extra_cost_minor": None, "max_payoff_delay_months": None}}}


def _inspect_workbooks(paths, evidence):
    from openpyxl import load_workbook
    from perfin_excel_core.offline_check import check_workbook
    for name, path in paths.items():
        failures = [f._asdict() for f in check_workbook(path) if f.severity != "INFO"]
        _check(evidence, f"static offline workbook inspection: {name}", not failures, failures)
        wb = load_workbook(path, data_only=False)
        try:
            _check(evidence, f"no external workbook links: {name}", not wb._external_links)
            if name == "core":
                _check(evidence, "core summary formula preserved", wb["Accounts"]["B7"].value == "=B5-B6")
                _check(evidence, "core import and reconciliation tables present",
                       "rpt_accounts" in wb["Accounts"].tables and "Reconciliation" in wb.sheetnames)
            elif name == "statements":
                _check(evidence, "statements net-worth formula preserved", wb["Summary"]["B11"].value == "=B9-B10")
                included = {r[0]: int(Decimal(str(r[4])) * 100)
                            for r in wb["Accounts"].iter_rows(min_row=4, values_only=True) if r[0]}
                _check(evidence, "statement values agree with ledger",
                       included == EXPECTED_BALANCES and sum(included.values()) == 210200)
            else:
                _check(evidence, "payoff workbook stores zero interest and no remaining debt",
                       wb["Plan"]["C5"].value == 0 and wb["Plan"]["F5"].value == 0)
        finally:
            wb.close()


def _write_index(root, evidence):
    links = "".join(f'<li><a href="{html.escape(a["path"], quote=True)}">{html.escape(a["label"])}</a></li>'
                    for a in evidence.get("artifacts", []) if a["path"].endswith(".xlsx"))
    (root / "index.html").write_text("""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PerFin synthetic demonstration</title>
<style>body{font:18px system-ui;max-width:850px;margin:4rem auto;padding:0 1.5rem;line-height:1.6;color:#17365d}
a{color:#175cb3}table{border-collapse:collapse}td,th{padding:.6rem;border-bottom:1px solid #ccd}small{color:#526}</style>
<h1>PerFin — synthetic SQLite demonstration</h1><p>Two reviewed statement cycles, backed by a real local SQLite
database. All numbers are invented. Open the generated files in Excel or another XLSX viewer.</p>
<table><tr><th>Measure</th><th>Verified amount</th></tr><tr><td>Checking</td><td>$2,340.00</td></tr>
<tr><td>Card debt</td><td>$238.00</td></tr><tr><td>Net worth</td><td>$2,102.00</td></tr>
<tr><td>Statements reconciled</td><td>6</td></tr></table><h2>Workbooks</h2><ul>""" + links + """</ul>
<p>The payoff illustration assumes 0% APR and $100 monthly payments: $238 is paid off in three months.
It is a calculation example, not an estimate for real card terms.</p>
<h2>What was checked</h2><p>Real SQLite persistence, review/commit, replay, reconciliation, CSV totals,
XLSX structure and stored formulas. Python engines calculate statement and payoff values.</p>
<p><strong>Desktop Excel recalculation, Power Query, VBA and Access/ACE remain pending native release checks.</strong>
XLSX generation and static inspection do not prove those features work.</p>
<p><a href="portable-demo-evidence.json">Detailed test evidence</a></p></html>""", encoding="utf-8")


def run_demo(output_dir):
    """Create a fresh synthetic data root and return evidence. Never overwrite a run."""
    from perfin_store.sqlite_backend import create_database, open_database
    root = checked_root(output_dir)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise FileExistsError("use a new or empty directory for the synthetic demo")
    root = initialize_layout(root, synthetic=True)
    marker = child(root, "perfin-data-dir.json")
    metadata = json.loads(marker.read_text(encoding="utf-8"))
    metadata["backend"] = "sqlite"
    metadata["database"] = "db/perfin.sqlite"
    marker.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    evidence = {"scope": "synthetic SQLite integration and generated XLSX inspection",
        "backend": "sqlite", "python": platform.python_version(), "platform": sys.platform,
        "synthetic": True, "as_of": AS_OF, "native_excel": "PENDING", "native_access": "PENDING",
        "checks": [], "artifacts": [], "result": "FAIL"}
    repo = None
    try:
        database = child(root, "db/perfin.sqlite")
        create_database(database)
        repo = open_database(database)
        _check(evidence, "real SQLite file", database.read_bytes()[:16] == b"SQLite format 3\x00")
        app = _two_cycles(repo, root, evidence)
        payoff = app.payoff(_payoff_document(repo.contract_version))
        _check(evidence, "independent zero-interest payoff example",
               all(r["total_interest_minor"] == 0 and r["final_debt_minor"] == 0
                   and r["debt_free_month"] == 3 for r in payoff["result"]["results"]))
        statements = app.statements(AS_OF, "2026-02-01")
        _check(evidence, "statements complete", statements["complete"])
        core = app.refresh(AS_OF)
        paths = {"core": Path(core["workbook"]), "payoff": Path(payoff["workbook"]),
                 "statements": Path(statements["workbook"])}
        with child(root, "reports/rpt_accounts.csv").open(newline="", encoding="utf-8") as stream:
            balances = {r["account_id"]: int(r["ledger_balance_minor"]) for r in csv.DictReader(stream)}
        _check(evidence, "report CSV balances", balances == EXPECTED_BALANCES, balances)
        _inspect_workbooks(paths, evidence)
        summary = repo.summary()
        repo.adapter.close()
        repo = open_database(database)
        _check(evidence, "reopened SQLite retains ledger and history", repo.summary() == summary)
        evidence["summary"] = {"account_balances_minor": balances, "net_worth_minor": sum(balances.values()),
                               "reconciliations": 6, "transaction_count": 16}
        for name, path in paths.items():
            evidence["artifacts"].append({"label": "PerFin " + name.title(), "path": str(path.relative_to(root)),
                                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        evidence["result"] = "PASS"
    except Exception as exc:
        evidence["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if repo is not None:
            repo.adapter.close()
    child(root, "portable-demo-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if evidence["result"] == "PASS":
        _write_index(root, evidence)
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="new synthetic directory outside the checkout")
    args = parser.parse_args(argv)
    try:
        evidence = run_demo(args.out)
    except (OSError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(evidence, indent=2))
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
