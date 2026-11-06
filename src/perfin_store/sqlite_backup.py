"""Coherent SQLite snapshots and verified restore; never raw-copy a live WAL database."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import uuid

from .backup import BackupError, check_location, compare_summaries, sha256_file
from .sqlite_backend import database_path_occupied

MANIFEST_KIND = "perfin.sqlite.backup"
DATABASE_NAME = "snapshot.sqlite3"


def _read_connection(path):
    path = Path(path).resolve(strict=True)
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)


def _copy_snapshot(source, target):
    """Use SQLite's online backup API, including committed WAL pages."""
    deadline = time.monotonic() + 15

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise BackupError("SQLite backup timed out; retry when database activity settles")

    with closing(_read_connection(source)) as src, closing(sqlite3.connect(str(target))) as dst:
        src.backup(dst, pages=256, progress=progress, sleep=0.05)
        # A WAL source can transfer its persistent journal-mode flag. Make the
        # completed snapshot self-contained; never require sidecars in the set.
        if dst.execute("PRAGMA journal_mode = DELETE").fetchone() != ("delete",):
            raise BackupError("could not make SQLite backup self-contained")


def _summary(path):
    from .sqlite_backend import open_database
    repo = open_database(path, read_only=True)
    try:
        if repo.blocked_errors:
            raise BackupError("stored ledger fails contract validation")
        return repo.summary()
    finally:
        repo.adapter.close()


def _integrity(path):
    with closing(_read_connection(path)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise BackupError("SQLite integrity_check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupError("SQLite foreign_key_check failed")


def _remove_database(path):
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def _reserve_file(path):
    """Create only a new owner-readable file (best-effort mode semantics on Windows)."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)


def read_manifest(set_dir):
    root = Path(set_dir)
    path = root / "manifest.json"
    if root.is_symlink() or path.is_symlink():
        raise BackupError("backup paths must not be symbolic links")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError("backup manifest is missing or unreadable") from exc
    if (not isinstance(manifest, dict) or manifest.get("kind") != MANIFEST_KIND
            or manifest.get("manifest_version") != 1 or manifest.get("backend") != "sqlite"
            or not isinstance(manifest.get("ledger_summary"), dict)
            or not isinstance(manifest.get("database"), dict)
            or manifest["database"].get("path") != DATABASE_NAME):
        raise BackupError("unsupported or malformed SQLite backup manifest")
    return manifest


def verify_backup(set_dir):
    """Return problems; an empty list means hashes, integrity and summary all match."""
    root = Path(set_dir)
    try:
        manifest = read_manifest(root)
        if {p.name for p in root.iterdir()} != {"manifest.json", DATABASE_NAME}:
            raise BackupError("backup set contains missing or unlisted entries")
        db = root / DATABASE_NAME
        entry = manifest["database"]
        if db.is_symlink() or not db.is_file():
            raise BackupError("backup database is missing or is a symbolic link")
        if db.stat().st_size != entry.get("size") or sha256_file(db) != entry.get("sha256"):
            raise BackupError("backup database size or SHA-256 does not match")
        _integrity(db)
        actual = _summary(db)
        problems = compare_summaries(manifest["ledger_summary"], actual)
        if problems:
            raise BackupError("; ".join(problems))
        return []
    except (BackupError, OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        return [str(exc)]


def create_backup(db_path, backup_root, *, acknowledge_location=False, summary=None):
    """Capture a consistent snapshot, then derive and verify its own summary.

    An optional caller summary is a consistency assertion, never the authoritative
    snapshot metadata. Concurrent commits may make that assertion stale and refuse
    the backup; omit it when intentionally backing up an active database.
    """
    source, root = Path(db_path), Path(backup_root)
    if source.is_symlink() or not source.is_file():
        raise BackupError("source database is missing or is a symbolic link")
    check_location(source, acknowledge_location, "backup source")
    check_location(root, acknowledge_location, "backup destination")
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    dest = root / ("perfin-sqlite-" + stamp + "-" + uuid.uuid4().hex[:8])
    dest.mkdir(mode=0o700)
    try:
        target = dest / DATABASE_NAME
        _reserve_file(target)
        _copy_snapshot(source, target)
        _integrity(target)
        actual = _summary(target)
        if summary is not None:
            differences = compare_summaries(summary, actual)
            if differences:
                raise BackupError("supplied summary does not match captured snapshot: " + "; ".join(differences))
        manifest = {"kind": MANIFEST_KIND, "manifest_version": 1, "backend": "sqlite", "created_at": stamp,
                    "database": {"path": DATABASE_NAME, "size": target.stat().st_size,
                                 "sha256": sha256_file(target)}, "ledger_summary": actual,
                    "external_evidence": "Original statement files are external; this backup contains database history only."}
        manifest_path = dest / "manifest.json"
        _reserve_file(manifest_path)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        problems = verify_backup(dest)
        if problems:
            raise BackupError("; ".join(problems))
        return dest
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def restore_backup(set_dir, target_db, *, acknowledge_location=False, open_summary=None):
    """Restore only to a new file, verifying content and repository facts before success."""
    problems = verify_backup(set_dir)
    if problems:
        raise BackupError("backup verification failed; nothing restored: " + "; ".join(problems))
    manifest = read_manifest(set_dir)
    source, target = Path(set_dir) / DATABASE_NAME, Path(target_db)
    check_location(target, acknowledge_location, "restore target")
    if database_path_occupied(target):
        raise BackupError("restore target already exists; choose a new path")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also protects against another process racing our existence check.
    _reserve_file(target)
    try:
        # This is the verified, self-contained DELETE-mode snapshot, never the
        # live source database. Copy exact bytes and verify them before opening.
        shutil.copyfile(source, target)
        if sha256_file(target) != manifest["database"]["sha256"]:
            raise BackupError("restored database SHA-256 differs from verified snapshot")
        _integrity(target)
        actual = _summary(target)
        differences = compare_summaries(manifest["ledger_summary"], actual)
        if open_summary is not None:
            differences.extend(compare_summaries(actual, open_summary(target)))
        if differences:
            raise BackupError("; ".join(differences))
    except BaseException:
        _remove_database(target)
        raise
    return {"restored": str(target), "backend": "sqlite", "schema_version": actual["schema_version"],
            "contract_version": actual["contract_version"],
            "checks": "snapshot SHA-256, integrity, foreign keys, schema, balances, history and row counts verified"}
