"""Module registry and launcher for separate PerFin module workbooks.

Layout scanned (one level deep, sorted, deterministic):

    <modules dir>/<module_dir>/module_manifest.json
    <modules dir>/<module_dir>/<workbook_file>

Each manifest is validated with the frozen contract validator (which also enforces
`writes_ledger: false`). An Excel module must name its own workbook file; the core
workbook is never a module target. The core workbook lists the registry through
perfin_modules.csv and opens a module's own file; it never edits module workbooks,
and module agents never edit the core workbook.
"""
import json
import hashlib
import os
import re
import sys
from pathlib import Path

from . import CORE_WORKBOOK_MACRO, CORE_WORKBOOK_TEMPLATE, spec
from ._deps import validate_document
from .reports import write_report_csv

MANIFEST_NAME = "module_manifest.json"
_DIR = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
CORE_NAMES = {CORE_WORKBOOK_TEMPLATE.casefold(), CORE_WORKBOOK_MACRO.casefold()}


class LaunchError(Exception):
    pass


def scan(modules_dir):
    """Return registry entries sorted by module_id (then folder)."""
    entries = []
    root = Path(modules_dir)
    if not root.is_dir():
        return entries
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        mf = sub / MANIFEST_NAME
        if not mf.is_file():
            continue
        entries.append(_entry(sub, mf))
    seen = {}
    for e in entries:
        seen.setdefault(e["module_id"], []).append(e)
    for mid, group in seen.items():
        if len(group) > 1:
            for e in group:
                e.update(status="INVALID", launchable=False,
                         message="duplicate module_id %s in %d folders" % (mid, len(group)))
    return sorted(entries, key=lambda e: (e["module_id"], e["module_dir"]))


def _entry(sub, mf):
    # Diagnostics must themselves conform to the registry CSV, even when the
    # untrusted folder or manifest identity does not conform to its contract.
    fallback_id = (sub.name if _ID.fullmatch(sub.name) else
                   "invalid." + hashlib.sha256(sub.name.encode("utf-8")).hexdigest()[:32])
    e = {"module_id": fallback_id, "module_version": None, "module_kind": "unknown", "module_dir": sub.name,
         "workbook_file": None, "launchable": False, "status": "INVALID", "message": None,
         "reads": None, "commands": None}
    if not _DIR.fullmatch(sub.name):
        e["message"] = "module folder name is not a plain name"
        return e
    try:
        with open(mf, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        e["message"] = "manifest is not readable JSON (%s)" % type(exc).__name__
        return e
    if not isinstance(doc, dict) or doc.get("document_type") != "module_manifest":
        e["message"] = "E_DOCUMENT_TYPE: expected module_manifest"
        return e
    errs = validate_document(doc)
    if isinstance(doc, dict):
        for k in ("module_version", "workbook_file"):
            if isinstance(doc.get(k), str):
                e[k] = doc[k]
        if isinstance(doc.get("module_id"), str) and _ID.fullmatch(doc["module_id"]):
            e["module_id"] = doc["module_id"]
        if doc.get("module_kind") in ("import_profile", "calculation_module", "excel_workbook"):
            e["module_kind"] = doc["module_kind"]
        if isinstance(doc.get("reads"), list):
            e["reads"] = " ".join(str(x) for x in doc["reads"])
        if isinstance(doc.get("commands"), list):
            e["commands"] = " ".join(str(x) for x in doc["commands"])
    if errs:
        e["message"] = "; ".join("%s %s" % (code, path) for code, path, _ in errs[:5])
        return e
    if doc["module_kind"] == "excel_workbook":
        wb = doc.get("workbook_file")
        if wb.casefold() in CORE_NAMES:
            e["message"] = "a module must ship its own workbook, not the core workbook"
            return e
        if not (sub / wb).is_file():
            e.update(status="MISSING_FILE", message="workbook file not found in module folder")
            return e
        e["launchable"] = True
    e["status"] = "OK"
    return e


def export_csv(modules_dir, out_path):
    """Write perfin_modules.csv for the core workbook (Power Query loads it read-only)."""
    rows = scan(modules_dir)
    write_report_csv(out_path, spec.MODULES_TABLE, rows)
    return rows


def resolve(modules_dir, module_id):
    """Return the absolute path of a launchable module's own workbook."""
    for e in scan(modules_dir):
        if e["module_id"] == module_id:
            if not e["launchable"] or e["status"] != "OK":
                raise LaunchError("module %s is not launchable: %s" % (module_id, e["message"] or e["status"]))
            root = Path(modules_dir).resolve()
            path = (root / e["module_dir"] / e["workbook_file"]).resolve()
            if root not in path.parents:
                raise LaunchError("module workbook escapes the modules folder")
            return path
    raise LaunchError("unknown module %s" % module_id)


def default_opener(path):
    """Open a local workbook with its registered desktop application (Windows only)."""
    if sys.platform != "win32":
        raise LaunchError("opening workbooks needs desktop Excel on Windows")
    os.startfile(str(path))  # noqa: S606 - local file path, validated above


def launch(modules_dir, module_id, opener=default_opener):
    path = resolve(modules_dir, module_id)
    opener(path)
    return path
