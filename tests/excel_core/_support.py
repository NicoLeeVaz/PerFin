"""Shared paths for the 2c tests (run: python3 -B -W error -m unittest discover -s tests/excel_core -v)."""
import contextlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "excel" / "core"
FIXTURES = REPO / "fixtures" / "excel_core"
REPORTS = FIXTURES / "reports"
MODULES = FIXTURES / "modules"
for p in (CORE, REPO / "contracts" / "python", REPO / "config" / "privacy"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@contextlib.contextmanager
def temp_dir():
    """A temporary directory outside the Git checkout (synthetic data only)."""
    d = tempfile.mkdtemp(prefix="perfin-2c-")
    try:
        with open(os.path.join(d, "perfin-data-dir.json"), "w", encoding="utf-8") as f:
            json.dump({"kind": "synthetic", "created": "2026-11-04"}, f)
        yield Path(d)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def copy_reports(dst):
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for p in sorted(REPORTS.glob("*.csv")):
        shutil.copyfile(p, dst / p.name)
        os.utime(dst / p.name, (FIXED_MTIME, FIXED_MTIME))
    return dst


# File times of copied fixtures (2026-07-01 12:00 local) and the simulated refresh.
import datetime as _dt  # noqa: E402

FIXED_MTIME = _dt.datetime(2026, 7, 1, 12, 0, 0).timestamp()
CHECKED_AT = _dt.datetime(2026, 7, 2, 9, 30, 0)
