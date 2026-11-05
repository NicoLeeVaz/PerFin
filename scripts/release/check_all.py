"""Run every local suite in an isolated interpreter; optional Python network denial.

A pass verifies Python/local synthetic behavior, not Windows, ACE or desktop Excel.
Evidence may contain test names and synthetic values. Keep the report outside the repo.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
SUITES = (
    "contracts/tests", "config/privacy", "research/reuse/harness", "tests/import",
    "tests/store", "tests/excel_core", "tests/integration_core", "tests/payoff",
    "tests/statements", "tests/excel_payoff", "tests/excel_statements", "tests/pdf",
    "tests/acceptance", "tests/database", "tests/sqlite", "tests/portability", "tests/portable_demo", "tests/extras",
)
# sitecustomize is loaded in each subprocess. Audit hooks reject socket access,
# including a socket created before a test replaces socket.socket. This is a
# Python-level test guard, not an operating-system firewall guarantee.
NETWORK_GUARD = '''import sys

def _deny(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.gethostbyname", "socket.sendto", "socket.bind"}:
        raise PermissionError("PerFin acceptance: Python network access disabled")
sys.addaudithook(_deny)
'''


def commands(root=ROOT, suites=SUITES):
    result = []
    for suite in suites:
        path = root / suite
        if not path.is_dir() or not list(path.glob("test*.py")):
            raise ValueError("required test suite missing or empty: " + suite)
        result.append((suite, [sys.executable, "-B", "-W", "error", "-m", "unittest", "discover", "-s", suite, "-q"]))
    result.append(("privacy-scan", [sys.executable, "-B", "config/privacy/perfin_privacy_checks.py", "scan-repo", "."]))
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true", help="deny Python socket connections/resolution in each suite")
    ap.add_argument("--report", type=Path, help="optional JSON report outside the checkout")
    args = ap.parse_args(argv)
    if args.report and (args.report.resolve() == ROOT or ROOT in args.report.resolve().parents):
        ap.error("write acceptance reports outside the checkout")
    try:
        work = commands()
    except ValueError as exc:
        print("BLOCKED:", exc)
        return 2
    evidence = {"scope": "Python, real SQLite and synthetic workbook checks; native Access/Excel unverified", "offline_guard": args.offline,
                "python": sys.version.split()[0], "platform": sys.platform, "checks": []}
    with tempfile.TemporaryDirectory(prefix="perfin-network-guard-") as guard:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        if args.offline:
            Path(guard, "sitecustomize.py").write_text(NETWORK_GUARD, encoding="utf-8")
            env["PYTHONPATH"] = guard + os.pathsep + env.get("PYTHONPATH", "")
        for name, cmd in work:
            start = time.monotonic()
            process = subprocess.run(cmd, cwd=ROOT, env=env, text=True, capture_output=True)
            status = "PASS" if process.returncode == 0 else "FAIL"
            evidence["checks"].append({"check": name, "status": status, "returncode": process.returncode,
                                       "seconds": round(time.monotonic() - start, 3),
                                       "tests": sum(int(n) for n in re.findall(r"Ran (\d+) tests?", process.stdout + process.stderr)),
                                       "stdout": process.stdout, "stderr": process.stderr})
            print(status, name)
            print(process.stdout + process.stderr, end="", flush=True)
    evidence["tests_run"] = sum(c["tests"] for c in evidence["checks"])
    evidence["result"] = "PASS" if all(c["status"] == "PASS" for c in evidence["checks"]) else "FAIL"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
