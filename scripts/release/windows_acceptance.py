"""Coordinate real Windows/ACE and desktop Excel acceptance; never infer unrun passes.

Outputs synthetic evidence outside the checkout. Exit 0 PASS, 1 FAIL, 2 BLOCKED.
Manual checklist evidence is explicitly operator-supplied, not automated proof.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_MANUAL = ("core_vba_compile", "core_powerquery_refresh", "core_privacy_guards", "core_offline_refresh",
                   "payoff_edit_recompute", "statements_valuation_refresh", "pdf_review_rejection", "fresh_install_restore")


def check_manual(doc, revision):
    if not isinstance(doc, dict) or doc.get("revision") != revision:
        return "BLOCKED", "manual evidence must name the tested revision"
    if not doc.get("operator") or not doc.get("windows_version") or not doc.get("office_bitness") or not doc.get("excel_build"):
        return "BLOCKED", "manual evidence needs operator and Windows/Office environment"
    checks = doc.get("checks", {})
    if not isinstance(checks, dict):
        return "BLOCKED", "manual checks must be keyed by check name"
    if any(checks.get(k) == "FAIL" for k in REQUIRED_MANUAL):
        return "FAIL", "operator reported a failed required check"
    if any(checks.get(k) != "PASS" for k in REQUIRED_MANUAL):
        return "BLOCKED", "manual checks remain pending"
    return "PASS", "operator-reported checklist; not independently automated"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workdir", type=Path, help="fresh directory outside checkout/sync folders")
    ap.add_argument("--manual-evidence", type=Path)
    args = ap.parse_args(argv)
    if sys.platform != "win32":
        print("BLOCKED: Windows, ACE and desktop Excel required. Local Python tests cannot replace this run.")
        return 2
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "excel/core"), str(ROOT / "config/privacy")]
    from perfin_privacy_checks import evaluate_data_dir
    work = (args.workdir or Path(os.environ["LOCALAPPDATA"]) / "PerFin-acceptance" /
            ("release-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))).resolve()
    verdict = evaluate_data_dir(str(work))
    if verdict["decision"] != "ok" or work.exists():
        ap.error("choose a fresh local work directory outside checkout and sync folders")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT, text=True).strip():
        print("BLOCKED: commit the reviewed source before recording revision-specific Windows evidence.")
        return 2
    work.mkdir(parents=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    evidence = {"revision": revision, "platform": sys.platform, "python": sys.version, "checks": []}

    def run(name, cmd, env=None):
        try:
            result = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True)
        except OSError as exc:
            evidence["checks"].append({"check": name, "status": "BLOCKED", "detail": type(exc).__name__})
            return
        evidence["checks"].append({"check": name, "status": "PASS" if result.returncode == 0 else
                                   "BLOCKED" if result.returncode == 2 else "FAIL", "returncode": result.returncode})
        (work / (name + ".txt")).write_text(result.stdout + result.stderr, encoding="utf-8")

    from perfin_store.envcheck import collect
    engine_environment = collect()
    evidence["engine_environment"] = engine_environment
    engine_ready = engine_environment.get("primary_adapter", {}).get("ready", False)
    if engine_ready:
        run("access", [sys.executable, "-B", "tests/store/windows_acceptance.py", "--workdir", str(work / "access"), "--keep"])
    else:
        evidence["checks"].append({"check": "access", "status": "BLOCKED", "detail": "ACE/Python environment is not ready"})
    integrated = ROOT / "tests/integration_core/windows_acceptance.py"
    if integrated.exists() and engine_ready:
        run("integrated", [sys.executable, "-B", str(integrated), "--workdir", str(work / "integrated")])
    else:
        evidence["checks"].append({"check": "integrated", "status": "BLOCKED", "detail": "integrated Windows harness or ACE prerequisites missing"})
    try:
        from perfin_excel_core.workbook import build
        template = work / "synthetic-core.xlsx"
        build(template, report_dir=ROOT / "fixtures/excel_core/reports", checked_at=datetime(2026, 7, 2, 9, 30))
        env = dict(os.environ, PerFin_SYNTHETIC_WORKBOOK=str(template), PerFin_EXCEL_EVIDENCE=str(work / "excel-evidence.json"))
        run("excel", ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/release/verify_excel.ps1")], env)
    except Exception as exc:
        evidence["checks"].append({"check": "excel", "status": "FAIL", "error": type(exc).__name__})
    manual = None
    if args.manual_evidence:
        try:
            manual = json.loads(args.manual_evidence.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            manual = None
    status, detail = check_manual(manual, revision)
    evidence["checks"].append({"check": "manual", "status": status, "detail": detail})
    evidence["manual_evidence"] = manual
    states = {c["status"] for c in evidence["checks"]}
    evidence["result"] = "FAIL" if "FAIL" in states else "BLOCKED" if "BLOCKED" in states else "PASS"
    path = work / "release-acceptance.json"
    path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(evidence["result"], path)
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[evidence["result"]]


if __name__ == "__main__":
    raise SystemExit(main())
