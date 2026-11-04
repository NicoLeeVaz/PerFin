"""Quiescent backup and verified restore of the Access database.

Strategy (docs/privacy/privacy-boundary.md, "Backup and restore"):

* Backup only a quiescent database: refuse while a lock file (<name>.laccdb / .ldb) exists or
  while the file cannot be opened exclusively. The caller closes every connection first.
* Hash the source, copy it, hash the copy and the source again; any difference aborts.
* Write manifest.json: each file's relative path, size and SHA-256, the PerFin, schema and
  contract versions, and the ledger summary (balances, import history, statements) taken from
  the database before the copy. Then re-verify the whole set.
* Destinations get the data-root location checks: never inside a git checkout; sync, network
  and redirected folders need explicit acknowledgement.
* Restore verifies every hash first and stops before writing on any mismatch, copies to a NEW
  path, opens it (schema_version and contract major are checked on open), and compares the
  restored ledger summary with the manifest. A mismatch removes the restored copy.
* Statement PDFs are never inside the database (statement.evidence_ref is an opaque
  reference). Extra files from the data root (originals, profiles, settings) may be listed.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import SCHEMA_VERSION, STORE_VERSION, _paths, migrations

MANIFEST = "manifest.json"
MANIFEST_KIND = "perfin.backup.manifest"


class BackupError(RuntimeError):
    pass


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lock_files(db_path) -> List[Path]:
    p = Path(db_path)
    return [c for c in (p.with_suffix(".laccdb"), p.with_suffix(".ldb")) if c.exists()]


def windows_exclusive_probe(path) -> bool:
    """True when the file can be opened with no sharing (nobody else has it open). Windows only."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    GENERIC_READ, OPEN_EXISTING = 0x80000000, 3
    handle = kernel32.CreateFileW(str(path), GENERIC_READ, 0, None, OPEN_EXISTING, 0, None)
    if handle in (None, wintypes.HANDLE(-1).value):
        return False
    kernel32.CloseHandle(handle)
    return True


def default_probe(path) -> bool:
    if sys.platform == "win32":
        return windows_exclusive_probe(path)
    return True  # POSIX has no Access lock semantics; the lock-file check still applies


def check_location(path, acknowledge_location: bool, what: str) -> Dict[str, Any]:
    verdict = _paths.privacy().evaluate_data_dir(str(path))
    if verdict["decision"] == "refuse":
        raise BackupError("%s refused: %s" % (what, "; ".join(verdict["reasons"])))
    if verdict["decision"] == "warn" and not acknowledge_location:
        raise BackupError("%s needs acknowledgement (sync, network or redirected folder; use an encrypted "
                          "container): %s" % (what, "; ".join(verdict["reasons"])))
    return verdict


def assert_quiescent(db_path, probe: Callable[[Any], bool] = default_probe) -> None:
    locks = lock_files(db_path)
    if locks:
        raise BackupError("database is open (lock file %s exists); close Access/Excel/PerFin and retry" % locks[0].name)
    if not probe(db_path):
        raise BackupError("database cannot be opened exclusively; another process is using it")


def _safe_rel(rel: str) -> PurePosixPath:
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts or "\\" in rel or ":" in rel:
        raise BackupError("unsafe path in manifest: %r" % rel)
    return p


def create_backup(db_path, dest_root, *, summary: Dict[str, Any], extra_files: Iterable = (), data_root=None,
                  acknowledge_location: bool = False, probe: Callable[[Any], bool] = default_probe,
                  now: Optional[datetime] = None) -> Path:
    """Copy a closed database into a new backup set under dest_root and return the set directory.

    `summary` is Repository.summary() taken from this database just before it was closed.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        raise BackupError("database file not found")
    check_location(dest_root, acknowledge_location, "backup destination")
    assert_quiescent(db_path, probe)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    set_dir = Path(dest_root) / ("perfin-backup-%s" % stamp)
    if set_dir.exists():
        raise BackupError("backup set already exists: %s" % set_dir.name)
    files: List[Dict[str, Any]] = []
    try:
        (set_dir / "db").mkdir(parents=True)
        before = sha256_file(db_path)
        target = set_dir / "db" / db_path.name
        shutil.copy2(db_path, target)
        after = sha256_file(db_path)
        copied = sha256_file(target)
        if not (before == after == copied) or lock_files(db_path):
            raise BackupError("database changed or was opened during the copy; backup aborted")
        files.append({"path": "db/" + db_path.name, "size": target.stat().st_size, "sha256": copied, "role": "database"})
        for extra in extra_files:
            extra = Path(extra)
            if data_root is None:
                raise BackupError("extra files need data_root so their relative paths can be recorded")
            rel = extra.resolve().relative_to(Path(data_root).resolve()).as_posix()
            _safe_rel(rel)
            dst = set_dir / "files" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(extra, dst)
            files.append({"path": "files/" + rel, "size": dst.stat().st_size, "sha256": sha256_file(dst), "role": "data_file"})
        manifest = {"kind": MANIFEST_KIND, "manifest_version": 1, "created_at": stamp, "perfin_store_version": STORE_VERSION,
                    "schema_version": summary.get("schema_version"), "contract_version": summary.get("contract_version"),
                    "expected_schema_version": SCHEMA_VERSION, "files": files, "ledger_summary": summary,
                    "statement_evidence": "statement PDFs are external; statements carry only evidence_ref"}
        (set_dir / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        problems = verify_backup(set_dir)
        if problems:
            raise BackupError("backup verification failed: " + "; ".join(problems))
        return set_dir
    except BaseException:
        shutil.rmtree(set_dir, ignore_errors=True)
        raise


def read_manifest(set_dir) -> Dict[str, Any]:
    path = Path(set_dir) / MANIFEST
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("manifest.json is missing or unreadable") from exc
    if m.get("kind") != MANIFEST_KIND or m.get("manifest_version") != 1 or not isinstance(m.get("files"), list):
        raise BackupError("not a PerFin backup manifest (or an unsupported manifest version)")
    return m


def verify_backup(set_dir) -> List[str]:
    """Return a list of problems (empty = every listed file is present with its size and hash)."""
    set_dir = Path(set_dir)
    try:
        m = read_manifest(set_dir)
    except BackupError as exc:
        return [str(exc)]
    problems, listed = [], set()
    for f in m["files"]:
        try:
            rel = _safe_rel(f["path"])
        except (BackupError, KeyError, TypeError) as exc:
            problems.append(str(exc))
            continue
        listed.add(rel.as_posix())
        p = set_dir.joinpath(*rel.parts)
        if not p.is_file():
            problems.append("missing %s" % rel)
        elif p.stat().st_size != f.get("size"):
            problems.append("size mismatch %s" % rel)
        elif sha256_file(p) != f.get("sha256"):
            problems.append("hash mismatch %s" % rel)
    for p in set_dir.rglob("*"):
        if p.is_file() and p.name != MANIFEST and p.relative_to(set_dir).as_posix() not in listed:
            problems.append("unlisted file %s" % p.relative_to(set_dir).as_posix())
    if not any(f.get("role") == "database" for f in m["files"]):
        problems.append("manifest lists no database")
    return problems


def compare_summaries(expected: Dict[str, Any], actual: Dict[str, Any]) -> List[str]:
    out = []
    for key in ("schema_version", "contract_version", "base_currency", "account_balances_minor", "import_history",
                "statements", "reconciliations", "row_counts"):
        if expected.get(key) != actual.get(key):
            out.append("restored %s differs from the backup manifest" % key)
    return out


def restore_backup(set_dir, target_db, *, open_summary: Callable[[Path], Dict[str, Any]],
                   acknowledge_location: bool = False) -> Dict[str, Any]:
    """Restore the set's database to target_db (a new path) and prove it matches the manifest.

    open_summary(path) opens the restored database with schema checks (Repository) and returns
    Repository.summary(); it raises if schema_version or the contract major is unsupported.
    """
    set_dir, target_db = Path(set_dir), Path(target_db)
    problems = verify_backup(set_dir)
    if problems:
        raise BackupError("backup set failed verification; nothing was restored: " + "; ".join(problems))
    m = read_manifest(set_dir)
    migrations.check_version(m.get("schema_version"))  # newer major/minor: refuse before writing
    contract_major = _paths.contracts()[3]
    if migrations.parse_version(m.get("contract_version"))[0] != contract_major:
        raise BackupError("backup contract_version %s is not contract major %d" % (m.get("contract_version"), contract_major))
    if target_db.exists() or lock_files(target_db):
        raise BackupError("restore target already exists; restore into a new path")
    check_location(target_db, acknowledge_location, "restore target")
    db_entry = next(f for f in m["files"] if f.get("role") == "database")
    src = set_dir.joinpath(*_safe_rel(db_entry["path"]).parts)
    target_db.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src, target_db)
        if sha256_file(target_db) != db_entry["sha256"]:
            raise BackupError("restored copy does not match the manifest hash")
        actual = open_summary(target_db)
        mismatches = compare_summaries(m["ledger_summary"], actual)
        if mismatches:
            raise BackupError("; ".join(mismatches))
    except BaseException:
        try:
            target_db.unlink()
        except OSError:
            pass
        raise
    return {"restored": str(target_db), "schema_version": actual.get("schema_version"),
            "contract_version": actual.get("contract_version"), "checks": "hashes, schema version, balances, import "
            "history, statements, reconciliations and row counts match the manifest"}
