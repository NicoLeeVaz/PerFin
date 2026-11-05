"""Versioned full-table archives, preserving history beyond the exchange ledger bundle.

SQLite export and empty-SQLite import are implemented. Access schema mapping is
documented, but actual Access import is deliberately not claimed or enabled here.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from . import _paths, codec, ddl, migrations, sqlbuild
from .backup import check_location, compare_summaries
from .sqlite_backup import _integrity, _remove_database

KIND = "perfin.full-table.archive"


class PortabilityError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def schema_description():
    return json.loads(_canonical({name: asdict(table) for name, table in ddl.registry().items()}))


def export_snapshot(db_path, archive_path, *, acknowledge_location=False):
    """Read all 18 tables under one transaction and write an exclusive JSON archive."""
    from .sqlite_backend import open_database
    target = Path(archive_path)
    check_location(db_path, acknowledge_location, "archive source")
    check_location(target, acknowledge_location, "archive destination")
    if target.exists() or target.is_symlink():
        raise PortabilityError("archive destination already exists")
    repo = open_database(db_path, read_only=True)
    try:
        # A read-only adapter starts a read transaction, not BEGIN IMMEDIATE.
        repo.adapter.begin()
        try:
            # Re-read metadata and validate under the same read snapshot as every table.
            from .repository import Repository
            repo = Repository(repo.adapter)
            if repo.blocked_errors:
                raise PortabilityError("source ledger fails contract validation")
            tables = {name: repo._rows(name, order_by=list(table.primary_key))
                      for name, table in ddl.registry().items()}
            summary = repo.summary()
        finally:
            repo.adapter.rollback()
    finally:
        repo.adapter.close()
    payload = {"source_backend": "sqlite", "schema": schema_description(), "tables": tables,
               "summary": summary, "schema_version": summary["schema_version"],
               "contract_version": summary["contract_version"]}
    archive = {"kind": KIND, "archive_version": 1, "payload_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
               "payload": payload}
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(archive, stream, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"archive": str(target), "payload_sha256": archive["payload_sha256"],
            "table_counts": {name: len(rows) for name, rows in tables.items()}, "summary": summary}


def read_snapshot(archive_path):
    from .sqlite_backend import SQLITE_SCHEMA_VERSION
    path = Path(archive_path)
    if path.is_symlink():
        raise PortabilityError("archive must not be a symbolic link")
    try:
        archive = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(archive, dict) or archive.get("kind") != KIND or archive.get("archive_version") != 1:
            raise PortabilityError("unsupported archive kind/version")
        payload = archive["payload"]
        if not isinstance(payload, dict) or hashlib.sha256(_canonical(payload)).hexdigest() != archive.get("payload_sha256"):
            raise PortabilityError("archive payload SHA-256 mismatch")
        if payload.get("source_backend") != "sqlite" or payload.get("schema") != schema_description():
            raise PortabilityError("unsupported source backend or different table structure")
        if migrations.check_version(payload.get("schema_version")) != "current":
            raise PortabilityError("archive needs a schema migration")
        found_contract = migrations.parse_version(payload.get("contract_version"))
        supported_contract = migrations.parse_version(_paths.contracts()[2])
        if found_contract[0] != supported_contract[0] or found_contract[1] > supported_contract[1]:
            raise PortabilityError("incompatible archive contract version")
        tables = payload["tables"]
        if not isinstance(tables, dict) or set(tables) != set(ddl.registry()):
            raise PortabilityError("archive must contain exactly every canonical table")
        for name, table in ddl.registry().items():
            if not isinstance(tables[name], list):
                raise PortabilityError("table rows must be a list")
            for row in tables[name]:
                if not isinstance(row, dict) or set(row) != set(table.columns):
                    raise PortabilityError("archive row has missing or extra columns: " + name)
                codec.row_to_db(name, row)  # Validate exact cents, dates, booleans, lengths and nullability.
        meta = {r["meta_key"]: r["meta_value"] for r in tables["contract_meta"]}
        if meta.get("backend") != "sqlite" or meta.get("schema_version") != payload["schema_version"]:
            raise PortabilityError("archive metadata differs from its manifest")
        if meta.get("sqlite_schema_version") != SQLITE_SCHEMA_VERSION:
            raise PortabilityError("unsupported SQLite schema version")
        if meta.get("contract_version") != payload["contract_version"] or not isinstance(payload.get("summary"), dict):
            raise PortabilityError("archive contract metadata/summary is invalid")
        if (not isinstance(meta.get("base_currency"), str)
                or meta.get("base_currency") != payload["summary"].get("base_currency")):
            raise PortabilityError("archive base currency metadata differs from its summary")
        return archive
    except (KeyError, TypeError, OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, PortabilityError):
            raise
        raise PortabilityError("invalid archive: " + str(exc)) from exc


def import_snapshot(archive_path, target_db, *, acknowledge_location=False):
    """Restore complete SQLite history into a new database, never merge into existing data."""
    from .sqlite_backend import create_database, open_database
    payload = read_snapshot(archive_path)["payload"]
    target = Path(target_db)
    check_location(target, acknowledge_location, "archive import target")
    if target.exists() or target.is_symlink() or any(Path(str(target) + s).exists() for s in ("-wal", "-shm", "-journal")):
        raise PortabilityError("archive import requires a new database path")
    meta = {r["meta_key"]: r["meta_value"] for r in payload["tables"]["contract_meta"]}
    create_database(target, base_currency=meta["base_currency"], acknowledge_location=acknowledge_location)
    repo = None
    try:
        repo = open_database(target)
        adapter = repo.adapter
        adapter.begin()
        try:
            adapter.execute("PRAGMA defer_foreign_keys = ON")
            adapter.execute("DELETE FROM [contract_meta]")
            # Deferral covers self-references and cycles without disabling foreign keys.
            for name in ddl.registry():
                for row in payload["tables"][name]:
                    adapter.execute(*sqlbuild.insert(name, codec.row_to_db(name, row)))
            if adapter.query("PRAGMA foreign_key_check"):
                raise PortabilityError("archive contains invalid foreign keys")
            from .repository import Repository
            restored = Repository(adapter)
            if restored.blocked_errors:
                raise PortabilityError("archive ledger fails contract validation")
            differences = compare_summaries(payload["summary"], restored.summary())
            if differences:
                raise PortabilityError("; ".join(differences))
            for name, table in ddl.registry().items():
                if restored._rows(name, order_by=list(table.primary_key)) != payload["tables"][name]:
                    raise PortabilityError("restored table does not match archive: " + name)
            adapter.commit()
        except BaseException:
            adapter.rollback()
            raise
        adapter.close()
        repo = None
        _integrity(target)
        # Exercise the actual public open path after commit, including backend
        # metadata compatibility, rather than only constructing Repository.
        reopened = open_database(target, read_only=True)
        try:
            if reopened.blocked_errors or compare_summaries(payload["summary"], reopened.summary()):
                raise PortabilityError("committed archive did not reopen with the expected ledger")
        finally:
            reopened.adapter.close()
    except BaseException:
        if repo is not None:
            repo.adapter.close()
        _remove_database(target)
        raise
    return {"restored": str(target), "backend": "sqlite", "tables": len(payload["tables"]),
            "checks": "payload hash, schema, types, foreign keys, ledger and every table/history row verified"}


def main(argv=None):
    """Explicit local-only archive operations; never guess an Access conversion."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    export = sub.add_parser("export", help="export complete SQLite table history")
    export.add_argument("--db", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--acknowledge-location", action="store_true")
    restore = sub.add_parser("import", help="restore into a NEW SQLite database")
    restore.add_argument("--archive", required=True)
    restore.add_argument("--target", "--db", dest="target", required=True)
    restore.add_argument("--acknowledge-location", action="store_true")
    verify = sub.add_parser("verify", help="check archive hash, schema and value types")
    verify.add_argument("--archive", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "export":
            result = export_snapshot(args.db, args.out, acknowledge_location=args.acknowledge_location)
            result.pop("summary")  # CLI prints structural counts, not financial balances.
        elif args.action == "import":
            result = import_snapshot(args.archive, args.target, acknowledge_location=args.acknowledge_location)
        else:
            archive = read_snapshot(args.archive)
            result = {"verified": True, "tables": len(archive["payload"]["tables"]),
                      "checks": "hash, schema and value types; relationships and ledger checked during import"}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print("Portability operation refused: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
