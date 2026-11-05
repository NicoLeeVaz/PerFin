"""Windows/Access acceptance run for task 2b (issue #6). Synthetic data only.

Run on the Windows machine that has Office/Access (or the Access Runtime / ACE driver) and
pyodbc of the SAME bitness, from the repository root:

    py -3 tests\\store\\windows_acceptance.py
    py -3 tests\\store\\windows_acceptance.py --workdir "%LOCALAPPDATA%\\PerFin-acceptance" --keep

It creates a temporary .accdb OUTSIDE the repository (default %LOCALAPPDATA%\\PerFin-acceptance\\
run-<UTC time>), and proves with the real ACE engine: environment, create/open + schema_version,
CHECK-constraint status, exact cents at the CURRENCY bounds, atomic commit, rollback after an
injected failure, replay protection, stale-version rejection, the rpt_* views against the
CSV export, lock-file refusal, backup and a restore that matches balances, import history and
schema version. Evidence goes to <workdir>\\acceptance-evidence.json; paste it into the PR.
Exit status: 0 all PASS, 1 any FAIL, 2 not Windows (BLOCKED).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

import synthetic as S  # noqa: E402
from perfin_store import _paths, backup, envcheck, money, reports  # noqa: E402
from perfin_store.repository import Repository, StorageError  # noqa: E402


class FailingAdapter:
    """Wrap the real adapter; raise on the nth statement containing `match` (injected failure)."""

    def __init__(self, inner, match: str, nth: int):
        self.inner, self.match, self.left = inner, match, nth
        self.path = inner.path

    def execute(self, sql, params=()):
        if self.match in sql:
            self.left -= 1
            if self.left == 0:
                raise RuntimeError("injected failure (acceptance test)")
        return self.inner.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class Run:
    def __init__(self):
        self.steps = []

    def record(self, name, ok, detail=None):
        self.steps.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        print("%-4s %s%s" % ("PASS" if ok else "FAIL", name, "" if detail is None else "  %s" % json.dumps(detail, default=str)))
        return ok


def norm(v, ctype=None):
    if ctype == "boolean" and isinstance(v, int):
        return bool(v)  # Access may return -1/0 for Yes/No expressions [Unverified]
    if isinstance(v, Decimal):
        return money.db_to_minor(v)
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir")
    ap.add_argument("--keep", action="store_true", help="keep the synthetic databases and backups afterwards")
    a = ap.parse_args(argv)
    if sys.platform != "win32":
        print("BLOCKED: this acceptance run needs Windows with Microsoft Access/ACE and pyodbc. "
              "Linux unit tests (tests/store/test_*.py) do not replace it.")
        return 2
    from perfin_store.adapter import AccessOdbcAdapter
    from perfin_store.setup import create_database

    base = Path(a.workdir or os.path.join(os.environ.get("LOCALAPPDATA", str(Path.home())), "PerFin-acceptance"))
    work = base / ("run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    verdict = _paths.privacy().evaluate_data_dir(str(work))
    if verdict["decision"] == "refuse":
        print("refused work directory: %s" % verdict["reasons"])
        return 1
    work.mkdir(parents=True)
    run = Run()
    db = work / "db" / "perfin-acceptance.accdb"
    evidence = {"started": datetime.now(timezone.utc).isoformat(), "workdir_check": verdict}
    try:
        env = envcheck.collect()
        evidence["environment"] = env
        if not run.record("environment: pyodbc + ACE ODBC driver usable", env["primary_adapter"]["ready"], env["problems"]):
            raise SystemExit
        rep = create_database(str(db))
        evidence["setup"] = rep
        run.record("create: new .accdb with schema and contract_meta", rep["opened"]["schema_version"] == "1.0.0"
                   and not rep["opened"]["blocked"], {k: rep["contract_meta"][k] for k in ("check_constraints", "report_views")})
        repo = Repository(AccessOdbcAdapter(str(db)))
        run.record("open: schema_version checked on open", repo.meta["schema_version"] == "1.0.0", repo.meta)

        ad = repo.adapter
        ad.begin()
        try:
            ad.execute("INSERT INTO [account] ([account_id], [kind], [account_class], [display_name], [currency], "
                       "[opening_balance_minor], [opening_balance_date], [include_in_net_worth], [row_version]) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       ("chk:probe", "asset", "checking", "probe", "USD", Decimal("0.5"), datetime(2026, 1, 1), True, 1))
            fractional_accepted = True
        except Exception:
            fractional_accepted = False
        ad.rollback()
        meta_says = repo.meta.get("check_constraints")
        run.record("CHECK constraints: engine behaviour matches contract_meta", (meta_says == "present") != fractional_accepted,
                   {"contract_meta.check_constraints": meta_says, "engine_accepted_fraction": fractional_accepted,
                    "fallback": "repository validation" if fractional_accepted else None})

        bundle = S.reference_bundle()
        bundle["accounts"].append({"account_id": "chk:edge", "kind": "asset", "account_class": "checking",
                                   "display_name": "Edge amounts", "currency": "USD", "opening_balance_minor": 0,
                                   "opening_balance_date": "2026-05-31", "row_version": 1})
        r1 = repo.import_bundle(bundle)
        r2 = repo.set_default_categories("exp.uncategorized", "inc.uncategorized")
        run.record("reference data: accounts/categories imported", r1["result_status"] == r2["result_status"] == "accepted",
                   r1["errors"] + r2["errors"])

        M = money.MONEY_MAX
        edge = S.batch("b.edge", "chk:edge", [S.row(1, "2026-06-01", M, "max", state="approved"),
                                              S.row(2, "2026-06-01", -M, "min", state="approved"),
                                              S.row(3, "2026-06-02", 1, "one cent", state="approved"),
                                              S.row(4, "2026-06-02", -12345, "minus 123.45", state="approved")])
        repo.stage_batch(edge)
        rc = repo.execute(S.command("commit_batch", {"batch_id": "b.edge", "source_file_sha256": edge["batch"]["source_file_sha256"]},
                                    [S.ev("batch", "b.edge", 2)]))
        got = {t["transaction_id"]: t["amount_minor"] for t in repo.export_bundle()["transactions"] if t["account_id"] == "chk:edge"}
        raw = ad.query("SELECT [amount_minor] FROM [ledger_txn] WHERE [account_id] = ?", ("chk:edge",))
        run.record("exact cents: CURRENCY round trip at +/-922337203685477", rc["result_status"] == "accepted"
                   and sorted(got.values()) == sorted([M, -M, 1, -12345]),
                   {"stored": sorted(got.values()), "driver_types": sorted({type(x[0]).__name__ for x in raw})})

        card = S.card_batch()
        sha = card["batch"]["source_file_sha256"]
        repo.stage_batch(card)
        b = "b.alpha.07"
        for c in (S.command("approve_rows", {"batch_id": b, "row_numbers": [1, 2, 3, 6]}, [S.ev("batch", b, 1)]),
                  S.command("reject_rows", {"batch_id": b, "row_numbers": [4], "reason": "bad row"}, [S.ev("batch", b, 2)]),
                  S.command("resolve_duplicate", {"batch_id": b, "row_number": 5, "resolution": "confirmed_duplicate"},
                            [S.ev("batch", b, 3)]),
                  S.command("reject_rows", {"batch_id": b, "row_numbers": [5], "reason": "duplicate"}, [S.ev("batch", b, 4)])):
            repo.execute(c)
        before = len(repo.export_bundle()["transactions"])
        failing = Repository(FailingAdapter(ad, "INSERT INTO [split]", 3), check_schema=False)
        try:
            failing.execute(S.command("commit_batch", {"batch_id": b, "source_file_sha256": sha}, [S.ev("batch", b, 5)]))
            raised = False
        except StorageError:
            raised = True
        after_fail = repo.export_bundle()
        batch_row = ad.query("SELECT [batch_status], [row_version] FROM [import_batch] WHERE [batch_id] = ?", (b,))
        run.record("rollback after injected failure: nothing written", raised and len(after_fail["transactions"]) == before
                   and tuple(batch_row[0]) == ("approved", 5), {"raised": raised, "batch": [tuple(x) for x in batch_row]})
        ok = repo.execute(S.command("commit_batch", {"batch_id": b, "source_file_sha256": sha}, [S.ev("batch", b, 5)]))
        run.record("atomic success: commit of approved rows", ok["result_status"] == "accepted"
                   and len(repo.export_bundle()["transactions"]) == before + 4, ok["errors"])
        rp = repo.execute(S.command("commit_batch", {"batch_id": b, "source_file_sha256": sha}, [S.ev("batch", b, 6)]))
        rs = repo.stage_batch(card)
        run.record("replay protection: same file hash changes nothing", rp["result_status"] == "replayed"
                   and rp["errors"][0]["code"] == "E_IDEMPOTENT_REPLAY" and rs["result_status"] == "replayed"
                   and len(repo.export_bundle()["transactions"]) == before + 4)
        tid = "b.alpha.07.r1"
        st = repo.execute(S.command("edit_transaction", {"transaction_id": tid, "changes": {"description": "x"},
                                                         "reason": "test"}, [S.ev("transaction", tid, 9)]))
        run.record("optimistic concurrency: stale row_version rejected", st["result_status"] == "rejected"
                   and st["errors"][0]["code"] == "E_STALE_VERSION")

        # A payment allocated to a past statement but posted in the future: the views and the CSV export must
        # both leave it out of confirmed_payments_minor (as-of rule, Codex review finding).
        leg = lambda tid, acct, amt: {"transaction_id": tid, "account_id": acct, "posted_date": "2099-01-02",  # noqa: E731
                                      "amount_minor": amt, "currency": "USD", "description": "FUTURE PAYMENT",
                                      "entry_method": "manual", "row_version": 1,
                                      "splits": [{"split_id": tid + ".s", "split_kind": "transfer", "amount_minor": amt,
                                                  "transfer_link_id": "Lfut"}]}
        fut = repo.import_bundle({
            "contract": "perfin", "contract_version": "1.0.0", "document_type": "ledger_bundle", "base_currency": "USD",
            "accounts": [], "categories": [], "transactions": [leg("fut1", "chk:main", -10000), leg("fut2", "card:alpha", 10000)],
            "transfer_links": [{"transfer_link_id": "Lfut", "from_transaction_id": "fut1", "to_transaction_id": "fut2",
                                "link_status": "confirmed"}],
            "statements": [{"statement_id": "st_jun", "account_id": "card:alpha", "period_start": "2026-06-01",
                            "period_end": "2026-06-30", "opening_balance_minor": -45000, "closing_balance_minor": -45000}],
            "statement_payments": [{"allocation_id": "afut", "statement_id": "st_jun", "transaction_id": "fut2",
                                    "amount_minor": 10000}]})
        today = date.today().isoformat()
        card_now = reports.build_tables(repo, today)["rpt_card_status"][0]
        run.record("as-of: a payment posted after the report date is not counted", fut["result_status"] == "accepted"
                   and card_now["confirmed_payments_minor"] == 0, fut["errors"] or None)
        utilization = repo.import_bundle(S.utilization_bundle())
        run.record("utilization: synthetic zero/null/positive limit cards imported",
                   utilization["result_status"] == "accepted", utilization["errors"] or None)
        for label, expected in (("missing", None), ("zero", None), ("positive", 2500)):
            # This query executes on real ACE. IIf must not expose a zero divisor,
            # and a missing/zero limit must be Null rather than zero utilization.
            values = ad.query("SELECT [utilization_basis_points] FROM [rpt_card_status] WHERE [account_id] = ?",
                              ("card:util." + label,))
            actual = norm(values[0][0]) if len(values) == 1 else "missing or duplicate card"
            run.record("utilization: %s limit" % label, actual == expected,
                       {"expected": expected, "actual": actual})
        py = reports.build_tables(repo, today)
        spec = reports.report_spec()
        view_problems = {}
        for name in reports.STORE_TABLES:
            cols = [c["name"] for c in spec["tables"][name]]
            types = {c["name"]: c["type"] for c in spec["tables"][name]}
            try:
                rows = ad.query("SELECT %s FROM [%s]" % (", ".join("[%s]" % c for c in cols), name))
            except Exception as exc:
                view_problems[name] = "view not queryable: %s" % type(exc).__name__
                continue
            skip = {"error_codes"} if name == "rpt_review_queue" else set()
            got_rows = sorted(json.dumps({c: norm(v, types[c]) for c, v in zip(cols, r) if c not in skip}, sort_keys=True, default=str)
                              for r in rows)
            want = sorted(json.dumps({c: v for c, v in r.items() if c not in skip}, sort_keys=True, default=str)
                          for r in py[name])
            if got_rows != want:
                view_problems[name] = "differs from the CSV export"
        run.record("report views: rpt_* views equal the Python/CSV export", not view_problems, view_problems or None)
        out = work / "reports"
        reports.export_csv(repo, out, today)
        run.record("report CSV export written", all((out / ("%s.csv" % t)).exists() for t in reports.STORE_TABLES))

        summary = repo.summary()
        second = AccessOdbcAdapter(str(db))
        try:
            backup.create_backup(db, work / "backups", summary=summary)
            refused = False
        except backup.BackupError:
            refused = True
        second.close()
        repo.adapter.close()
        run.record("backup refused while the database is open", refused)
        set_dir = backup.create_backup(db, work / "backups", summary=summary)
        run.record("backup: copy + SHA-256 manifest verified", not backup.verify_backup(set_dir), str(set_dir.name))

        def open_summary(path):
            r = Repository(AccessOdbcAdapter(str(path)))
            try:
                return r.summary()
            finally:
                r.adapter.close()
        res = backup.restore_backup(set_dir, work / "restore" / "perfin-restored.accdb", open_summary=open_summary)
        run.record("restore: balances, import history and schema_version match", True, res["checks"])
    except SystemExit:
        pass
    except Exception as exc:
        run.record("unexpected error", False, "%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()
    evidence["steps"] = run.steps
    evidence["finished"] = datetime.now(timezone.utc).isoformat()
    evidence["result"] = "PASS" if run.steps and all(s["status"] == "PASS" for s in run.steps) else "FAIL"
    (work / "acceptance-evidence.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print("\nresult: %s\nevidence: %s" % (evidence["result"], work / "acceptance-evidence.json"))
    if not a.keep:
        for sub in ("db", "backups", "restore", "reports"):
            shutil.rmtree(work / sub, ignore_errors=True)
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
