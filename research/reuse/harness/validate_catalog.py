"""Validate research/reuse/catalog.json against the 1b acceptance rules.

Run from the repository root:  python3 -I research/reuse/harness/validate_catalog.py

Checks:
* JSON parses, and every entry has the required fields and a known decision/copy value.
* Entries whose licence is unverified or non-permissive are never 'vendored'.
* Every 'vendored' entry has third_party/<dir>/LICENSE and SOURCE.md, and the
  sha256 of each listed file matches the file on disk.
* third_party/ contains no Office binaries (.xlsm .xlsx .accdb .accdt .mdb .xlsb).
Standard library only.
"""

import hashlib
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CATALOG = os.path.join(ROOT, "research", "reuse", "catalog.json")
REQUIRED = ("id", "name", "kind", "url", "pin", "license", "local_compatibility",
            "offline_behaviour", "usable_role", "inspected", "executed",
            "audit_gaps", "decision", "copy")
PERMISSIVE = {"MIT", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "PSF-2.0"}
BINARY_EXT = (".xlsm", ".xlsx", ".xlsb", ".xls", ".accdb", ".accdt", ".accde", ".mdb")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    errors = []
    with open(CATALOG, encoding="utf-8") as f:
        cat = json.load(f)
    decisions = set(cat["decision_vocabulary"])
    copies = set(cat["copy_vocabulary"])
    ids = set()
    for e in cat["entries"]:
        eid = e.get("id", "?")
        for k in REQUIRED:
            if k not in e:
                errors.append(f"{eid}: missing field {k}")
        if eid in ids:
            errors.append(f"{eid}: duplicate id")
        ids.add(eid)
        if e.get("decision") not in decisions:
            errors.append(f"{eid}: unknown decision {e.get('decision')}")
        if e.get("copy") not in copies:
            errors.append(f"{eid}: unknown copy {e.get('copy')}")
        lic = e.get("license", {})
        if e.get("copy") == "vendored":
            if not lic.get("verified") or lic.get("spdx") not in PERMISSIVE:
                errors.append(f"{eid}: vendored without a verified permissive licence")
            d = os.path.join(ROOT, e.get("vendored_path", ""))
            for req in ("LICENSE", "SOURCE.md"):
                if not os.path.isfile(os.path.join(d, req)):
                    errors.append(f"{eid}: {req} missing in {d}")
            for vf in e.get("vendored_files", []):
                p = os.path.join(d, vf["path"])
                if not os.path.isfile(p):
                    errors.append(f"{eid}: vendored file missing {p}")
                elif sha256(p) != vf["sha256"]:
                    errors.append(f"{eid}: sha256 mismatch {p}")
        if e.get("decision") == "link-only" and e.get("copy") != "none":
            errors.append(f"{eid}: link-only entry must have copy 'none'")
    rec = cat["dependency_recommendation"]
    for group, members in rec.items():
        if isinstance(members, list):
            for m in members:
                if m not in ids:
                    errors.append(f"dependency_recommendation.{group}: unknown id {m}")
    if cat["access_seed_decision"]["seed_considered"] not in ids:
        errors.append("access_seed_decision: unknown seed id")
    tp = os.path.join(ROOT, "third_party")
    vendored_dirs = {os.path.normpath(os.path.join(ROOT, e["vendored_path"]))
                     for e in cat["entries"] if e.get("copy") == "vendored"}
    for dirpath, _, files in os.walk(tp):
        for fn in files:
            if fn.lower().endswith(BINARY_EXT):
                errors.append(f"binary Office file in third_party: {os.path.join(dirpath, fn)}")
        if os.path.normpath(dirpath) != os.path.normpath(tp) and \
                os.path.dirname(os.path.normpath(dirpath)) == os.path.normpath(tp) and \
                os.path.normpath(dirpath) not in vendored_dirs:
            errors.append(f"third_party dir not in catalog: {dirpath}")
    n = len(cat["entries"])
    if errors:
        print("\n".join(errors))
        print(f"FAIL: {len(errors)} problem(s) in {n} entries")
        return 1
    print(f"OK: {n} entries; {len(vendored_dirs)} vendored directories verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
