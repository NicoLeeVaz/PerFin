"""Command line for the core Excel shell (PYTHONPATH=excel/core).

  build --out FILE.xlsx [--reports DIR --checked-at YYYY-MM-DDTHH:MM:SS] [--modules DIR] [--stale-days N]
  check FILE.xlsx|.xlsm [--vba DIR] [--powerquery DIR]
  powerquery --out DIR
  registry --modules DIR --out <data root>/reports/perfin_modules.csv
  command approve|reject --data-root DIR --batch-id ID --rows 1,2 [--reason TEXT] [--batch-version N]
  command promote --data-root DIR
"""
import argparse
import datetime as dt
import json
import sys

from . import commands, offline_check, powerquery, registry, workbook


def main(argv=None):
    ap = argparse.ArgumentParser(prog="perfin_excel_core")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", required=True)
    b.add_argument("--reports")
    b.add_argument("--checked-at")
    b.add_argument("--modules")
    b.add_argument("--stale-days", type=int, default=7)
    c = sub.add_parser("check")
    c.add_argument("workbook")
    c.add_argument("--vba")
    c.add_argument("--powerquery")
    p = sub.add_parser("powerquery")
    p.add_argument("--out", required=True)
    r = sub.add_parser("registry")
    r.add_argument("--modules", required=True)
    r.add_argument("--out", required=True)
    m = sub.add_parser("command")
    m.add_argument("action", choices=["approve", "reject", "promote"])
    m.add_argument("--data-root", required=True)
    m.add_argument("--batch-id")
    m.add_argument("--rows")
    m.add_argument("--reason")
    m.add_argument("--batch-version", type=int)
    m.add_argument("--acknowledged", action="store_true", help="user acknowledged a sync/network data-root warning")
    a = ap.parse_args(argv)

    if a.cmd == "build":
        checked = dt.datetime.fromisoformat(a.checked_at) if a.checked_at else None
        workbook.build(a.out, report_dir=a.reports, modules_dir=a.modules, checked_at=checked,
                       stale_days=a.stale_days)
        print("built", a.out)
        return 0
    if a.cmd == "check":
        findings = offline_check.check_workbook(a.workbook)
        if a.vba:
            findings += offline_check.check_vba_dir(a.vba)
        if a.powerquery:
            findings += offline_check.check_powerquery_dir(a.powerquery)
        for f in findings:
            print("%s %s %s: %s" % (f.severity, f.rule, f.where, f.detail))
        bad = [f for f in findings if f.severity == "ERROR"]
        print("OK" if not bad else "%d problem(s)" % len(bad))
        return 1 if bad else 0
    if a.cmd == "powerquery":
        for name in powerquery.write(a.out):
            print(name)
        return 0
    if a.cmd == "registry":
        for e in registry.export_csv(a.modules, a.out):
            print(e["module_id"], e["status"], e["message"] or "")
        return 0
    if a.action == "promote":
        report = commands.promote_drafts(a.data_root, a.acknowledged)
        print(json.dumps(report, indent=1))
        return 1 if report["rejected"] else 0
    try:
        doc = commands.build_review_command("approve_rows" if a.action == "approve" else "reject_rows",
                                            a.batch_id, [int(x) for x in a.rows.split(",")], reason=a.reason,
                                            batch_row_version=a.batch_version)
        print(commands.write_to_outbox(doc, a.data_root, a.acknowledged))
    except commands.CommandError as e:
        print("refused:", e, e.errors, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
