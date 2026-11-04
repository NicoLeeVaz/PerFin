"""Command line for the Access store. Small by design; 3a builds the full workflow on top.

    python -m perfin_store envcheck [--json]
    python -m perfin_store review --db DB --batch ID [--approve 1,2] [--reject 3 --reason TEXT]
                                  [--resolve 4=confirmed_distinct] [--commit] [--json]
    python -m perfin_store stage --db DB --file staging_batch.json
    python -m perfin_store import-bundle --db DB --file ledger_bundle.json
    python -m perfin_store set-defaults --db DB --outflow CAT --inflow CAT
    python -m perfin_store command --db DB --file command.json
    python -m perfin_store export-reports --db DB --out DIR [--as-of YYYY-MM-DD] [--acknowledge-location]
    python -m perfin_store export-bundle --db DB
    python -m perfin_store backup --db DB --dest DIR [--acknowledge-location]
    python -m perfin_store restore --set DIR --target NEW.accdb [--acknowledge-location]

Every write builds a contract `command` (issued_by "cli:...") and prints its command_result.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any, Callable, Dict, List, Optional

from . import backup, envcheck, money, reports
from .repository import Repository, utc_now


def open_access(path: str, **kw) -> Repository:
    from .adapter import AccessOdbcAdapter
    return Repository(AccessOdbcAdapter(path, **kw))


def _numbers(text: Optional[str]) -> List[int]:
    return [int(x) for x in text.split(",") if x.strip()] if text else []


def make_command(repo: Repository, command_type: str, payload: Dict[str, Any], expected: List[Dict[str, Any]],
                 issued_by: str = "cli:review") -> Dict[str, Any]:
    return {"contract": "perfin", "contract_version": repo.contract_version, "document_type": "command",
            "command_id": str(uuid.uuid4()), "command_type": command_type, "issued_at": utc_now(),
            "issued_by": issued_by, "payload": payload, "expected_versions": expected}


def batch_version(repo: Repository, batch_id: str) -> List[Dict[str, Any]]:
    row = repo._one("import_batch", {"batch_id": batch_id})
    return [{"entity": "batch", "entity_id": batch_id, "row_version": row["row_version"]}] if row else []


def print_queue(repo: Repository, batch_id: str, out) -> None:
    doc = repo.export_staging_batch(batch_id)
    if doc is None:
        print("unknown batch %s" % batch_id, file=out)
        return
    b = doc["batch"]
    print("batch %s  account %s  status %s  file %s" % (b["batch_id"], b["account_id"], b["batch_status"],
                                                        b["source_file_name"]), file=out)
    print("%5s  %-12s %-20s %-24s %-10s %14s  %s" % ("row", "review", "duplicate", "errors", "posted", "amount", "description"),
          file=out)
    for r in doc["rows"]:
        p = r.get("parsed") or {}
        amt = "" if p.get("amount_minor") is None else str(money.minor_to_major(p["amount_minor"]))
        print("%5d  %-12s %-20s %-24s %-10s %14s  %s" % (
            r["row_number"], r["review_state"], r["duplicate"]["status"], ";".join(e["code"] for e in r["errors"]) or "-",
            p.get("posted_date", ""), amt, p.get("description", "")), file=out)


def _emit(result: Dict[str, Any], out) -> bool:
    print(json.dumps(result, indent=2, sort_keys=True), file=out)
    return result["result_status"] == "accepted"


def cmd_review(repo: Repository, a, out) -> int:
    actions = []
    if a.resolve:
        for item in a.resolve:
            n, _, res = item.partition("=")
            actions.append(("resolve_duplicate", {"batch_id": a.batch, "row_number": int(n), "resolution": res}))
    if a.approve:
        actions.append(("approve_rows", {"batch_id": a.batch, "row_numbers": _numbers(a.approve)}))
    if a.reject:
        if not a.reason:
            print("--reject needs --reason", file=sys.stderr)
            return 2
        actions.append(("reject_rows", {"batch_id": a.batch, "row_numbers": _numbers(a.reject), "reason": a.reason}))
    if a.commit:
        row = repo._one("import_batch", {"batch_id": a.batch})
        sha = row["source_file_sha256"] if row else "0" * 64
        actions.append(("commit_batch", {"batch_id": a.batch, "source_file_sha256": sha}))
    for ctype, payload in actions:
        if not _emit(repo.execute(make_command(repo, ctype, payload, batch_version(repo, a.batch))), out):
            return 1
    if not actions or not a.json:
        print_queue(repo, a.batch, out)
    return 0


def main(argv: Optional[List[str]] = None, *, open_repo: Callable[..., Repository] = open_access, out=None) -> int:
    out = out or sys.stdout
    ap = argparse.ArgumentParser(prog="python -m perfin_store")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("envcheck")
    e.add_argument("--json", action="store_true")
    r = sub.add_parser("review")
    r.add_argument("--db", required=True)
    r.add_argument("--batch", required=True)
    r.add_argument("--approve")
    r.add_argument("--reject")
    r.add_argument("--reason")
    r.add_argument("--resolve", action="append", metavar="ROW=confirmed_duplicate|confirmed_distinct")
    r.add_argument("--commit", action="store_true")
    r.add_argument("--json", action="store_true", help="print only command results")
    for name in ("stage", "import-bundle", "command"):
        p = sub.add_parser(name)
        p.add_argument("--db", required=True)
        p.add_argument("--file", required=True)
    d = sub.add_parser("set-defaults")
    d.add_argument("--db", required=True)
    d.add_argument("--outflow")
    d.add_argument("--inflow")
    x = sub.add_parser("export-reports")
    x.add_argument("--db", required=True)
    x.add_argument("--out", required=True)
    x.add_argument("--as-of")
    x.add_argument("--acknowledge-location", action="store_true")
    b = sub.add_parser("export-bundle")
    b.add_argument("--db", required=True)
    k = sub.add_parser("backup")
    k.add_argument("--db", required=True)
    k.add_argument("--dest", required=True)
    k.add_argument("--acknowledge-location", action="store_true")
    s = sub.add_parser("restore")
    s.add_argument("--set", required=True)
    s.add_argument("--target", required=True)
    s.add_argument("--acknowledge-location", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "envcheck":
        return envcheck.main(["--json"] if a.json else [])
    if a.cmd == "restore":
        def summary_of(path):
            repo = open_repo(str(path))
            try:
                return repo.summary()
            finally:
                repo.adapter.close()
        try:
            print(json.dumps(backup.restore_backup(a.set, a.target, open_summary=summary_of,
                                                   acknowledge_location=a.acknowledge_location), indent=2), file=out)
        except Exception as exc:
            print("restore failed: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
            return 1
        return 0
    repo = open_repo(a.db)
    try:
        if a.cmd == "review":
            return cmd_review(repo, a, out)
        if a.cmd in ("stage", "import-bundle", "command"):
            with open(a.file, encoding="utf-8") as f:
                doc = json.load(f)
            fn = {"stage": repo.stage_batch, "import-bundle": repo.import_bundle, "command": repo.execute}[a.cmd]
            return 0 if _emit(fn(doc), out) else 1
        if a.cmd == "set-defaults":
            return 0 if _emit(repo.set_default_categories(a.outflow, a.inflow), out) else 1
        if a.cmd == "export-reports":
            for p in reports.export_csv(repo, a.out, a.as_of, acknowledge_location=a.acknowledge_location):
                print(p.name, file=out)
            return 0
        if a.cmd == "export-bundle":
            print(json.dumps(repo.export_bundle(), indent=2, sort_keys=True), file=out)
            return 0
        if a.cmd == "backup":
            summary = repo.summary()
            repo.adapter.close()
            repo = None
            try:
                set_dir = backup.create_backup(a.db, a.dest, summary=summary, acknowledge_location=a.acknowledge_location)
            except backup.BackupError as exc:
                print("backup refused: %s" % exc, file=sys.stderr)
                return 1
            print(str(set_dir), file=out)
            return 0
    finally:
        if repo is not None:
            repo.adapter.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
