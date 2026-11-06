"""Real local SQLite storage using the canonical PerFin tables and repository.

The schema is generated from ddl.registry(), not copied from the test fake.
SQLite >= 3.37 is required for STRICT tables. Money stays integer minor units;
foreign keys are enabled and checked on every connection. Access report SQL is
not guessed/translated: perfin_store.reports is the shared report implementation.

SQLite references: https://www.sqlite.org/foreignkeys.html,
https://www.sqlite.org/lang_transaction.html, https://www.sqlite.org/stricttables.html.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from contextlib import contextmanager
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Sequence

from . import SCHEMA_VERSION, STORE_VERSION, _paths, codec, ddl, money, sqlbuild
from .adapter import AdapterError
from .migrations import SchemaVersionError

SQLITE_SCHEMA_VERSION = "1"
SUFFIXES = {".sqlite3", ".sqlite", ".db"}
_FROM = re.compile(r"\bFROM\s+\[?([a-z][a-z0-9_]*)\]?", re.I)


def database_path_occupied(path):
    """A new database must not reuse recovery files, including dangling links."""
    return any(candidate.exists() or candidate.is_symlink()
               for candidate in (Path(str(path) + suffix)
                                 for suffix in ("", "-wal", "-shm", "-journal")))


def _q(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("invalid schema identifier")
    return '"' + name + '"'


def schema_statements() -> tuple[str, ...]:
    """Deterministic DDL with canonical names, keys, FKs and bounded types."""
    statements = []
    for table in ddl.registry().values():
        definitions = []
        for col in table.columns.values():
            name = _q(col.name)
            integer = col.type in {"CURRENCY", "LONG", "INTEGER", "YESNO"}
            declaration = name + (" INTEGER" if integer else " TEXT")
            if col.type == "TEXT":
                # Contract IDs are ASCII; SQLite NOCASE is not full ACE locale collation.
                declaration += " COLLATE NOCASE"
            if col.not_null or col.name in table.primary_key or col.type == "YESNO":
                declaration += " NOT NULL"
            checks = []
            if col.type == "CURRENCY":
                checks.append("typeof(%s) = 'integer' AND %s BETWEEN %d AND %d" %
                              (name, name, money.MONEY_MIN, money.MONEY_MAX))
            elif col.type in {"LONG", "INTEGER"}:
                checks.append("typeof(%s) = 'integer' AND %s BETWEEN %d AND %d" %
                              (name, name, *codec.INT32))
            elif col.type == "YESNO":
                checks.append("typeof(%s) = 'integer' AND %s IN (0, 1)" % (name, name))
            elif col.type in {"TEXT", "MEMO", "DATETIME"}:
                checks.append("typeof(%s) = 'text'" % name)
                if col.length:
                    checks.append("length(%s) <= %d" % (name, col.length))
            else:
                raise ValueError("unsupported canonical type: %s" % col.type)
            declaration += " CHECK (%s IS NULL OR (%s))" % (name, " AND ".join(checks))
            definitions.append(declaration)
        definitions.append("PRIMARY KEY (%s)" % ", ".join(map(_q, table.primary_key)))
        for columns in table.uniques:
            definitions.append("UNIQUE (%s)" % ", ".join(map(_q, columns)))
        for column, target, target_column in table.foreign_keys:
            definitions.append("FOREIGN KEY (%s) REFERENCES %s (%s)" %
                               (_q(column), _q(target), _q(target_column)))
        for name, expression in table.checks:
            expression = re.sub(r"\bInt\((\w+)\)", r"CAST(\1 AS INTEGER)", expression)
            definitions.append("CONSTRAINT %s CHECK (%s)" % (_q(name), expression))
        statements.append("CREATE TABLE %s (\n  %s\n) STRICT" % (_q(table.name), ",\n  ".join(definitions)))
    for index in ddl.indexes():
        # SQLite unique indexes allow multiple NULLs, matching IGNORE NULL here.
        statements.append("CREATE %sINDEX %s ON %s (%s)" %
                          ("UNIQUE " if index.unique else "", _q(index.name), _q(index.table),
                           ", ".join(map(_q, index.columns))))
    return tuple(statements)


def _bind(value: Any) -> Any:
    if value is None or isinstance(value, (str, int)):
        return int(value) if isinstance(value, bool) else value
    if isinstance(value, Decimal):
        return money.db_to_minor(value)
    if isinstance(value, datetime):
        if value.tzinfo is not None or value.microsecond:
            raise AdapterError("database timestamps must be naive UTC whole seconds")
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day).isoformat(timespec="seconds")
    raise AdapterError("unsupported SQLite parameter type: %s" % type(value).__name__)


class SQLiteAdapter:
    """One real file connection; repository commands are explicit transactions."""
    backend = "sqlite"

    def __init__(self, path, *, read_only=False, timeout=5.0):
        if sqlite3.sqlite_version_info < (3, 37, 0):
            raise AdapterError("SQLite 3.37 or newer is required for STRICT tables")
        target = Path(path).expanduser().absolute()
        if not target.is_file():
            raise AdapterError("SQLite database does not exist; create it explicitly")
        self.path = str(target)
        self.read_only = read_only
        self._conn = sqlite3.connect(target.as_uri() + ("?mode=ro" if read_only else "?mode=rw"),
                                     uri=True, isolation_level=None, timeout=timeout)
        try:
            self._conn.execute("PRAGMA foreign_keys = ON")
            if self._conn.execute("PRAGMA foreign_keys").fetchone() != (1,):
                raise AdapterError("SQLite foreign key enforcement is unavailable")
            self._conn.execute("PRAGMA trusted_schema = OFF")
        except Exception:
            self._conn.close()
            raise

    def begin(self):
        if self._conn.in_transaction:
            raise AdapterError("transaction already open")
        self._conn.execute("BEGIN" if self.read_only else "BEGIN IMMEDIATE")

    @contextmanager
    def read_snapshot(self):
        """Keep multi-query reads consistent without nesting command transactions.

        BEGIN is deferred: the first SELECT fixes the snapshot. In rollback-journal
        mode writers wait for the reader; in WAL mode they can commit while this
        reader continues to see the earlier complete snapshot. Release only a
        transaction this context owns, including when a read/validation raises.
        """
        owned = not self._conn.in_transaction
        if owned:
            self._conn.execute("BEGIN")
        try:
            yield
        finally:
            if owned:
                self._conn.rollback()

    def execute(self, sql: str, params: Sequence[Any] = ()):
        if not self._conn.in_transaction:
            raise AdapterError("writes require an explicit transaction")
        self._conn.execute(sql, tuple(_bind(v) for v in params)).close()

    def query_storage(self, sql: str, params: Sequence[Any] = ()):
        """Raw storage tuples for schema inspection and lossless portability."""
        cur = self._conn.execute(sql, tuple(_bind(v) for v in params))
        try:
            return [tuple(row) for row in cur.fetchall()]
        finally:
            cur.close()

    def query(self, sql: str, params: Sequence[Any] = ()):
        cur = self._conn.execute(sql, tuple(_bind(v) for v in params))
        try:
            rows = [tuple(row) for row in cur.fetchall()]
            match = _FROM.search(sql)
            table = ddl.registry().get(match.group(1).lower()) if match else None
            if table and cur.description:
                dates = [i for i, description in enumerate(cur.description)
                         if description[0] in table.columns and table.columns[description[0]].type == "DATETIME"]
                rows = [tuple(datetime.fromisoformat(v) if i in dates and v is not None else v
                              for i, v in enumerate(row)) for row in rows]
            return rows
        finally:
            cur.close()

    def commit(self):
        if not self._conn.in_transaction:
            raise AdapterError("no transaction to commit")
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def execute_ddl(self, sql: str):
        if self._conn.in_transaction:
            raise AdapterError("standalone DDL cannot run inside a command transaction")
        self._conn.execute(sql).close()

    def close(self):
        self._conn.close()


def create_database(path, *, base_currency="USD", acknowledge_location=False):
    """Create a new file only, respecting the same private-location policy as ACE."""
    from .repository import Repository, utc_now
    target = Path(path).expanduser().absolute()
    if target.suffix.lower() not in SUFFIXES:
        raise AdapterError("SQLite database must end in .sqlite3, .sqlite or .db")
    if not re.fullmatch(r"[A-Z]{3}", base_currency):
        raise AdapterError("base currency must be a three-letter uppercase currency code")
    verdict = _paths.privacy().evaluate_data_dir(str(target))
    if verdict["decision"] == "refuse" or (verdict["decision"] == "warn" and not acknowledge_location):
        raise AdapterError("database location refused: " + "; ".join(verdict["reasons"]))
    if database_path_occupied(target):
        raise FileExistsError("database or associated SQLite sidecar already exists; choose a new path")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive file creation refuses existing files, symlinks and racing creators.
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    adapter = None
    try:
        adapter = SQLiteAdapter(target)
        adapter.begin()
        for statement in schema_statements():
            adapter.execute(statement)
        meta = {"schema_version": SCHEMA_VERSION, "contract_version": _paths.contracts()[2],
                "backend": "sqlite", "sqlite_schema_version": SQLITE_SCHEMA_VERSION,
                "base_currency": base_currency, "created_at": utc_now(),
                "created_by": "perfin_store %s sqlite" % STORE_VERSION,
                "check_constraints": "present", "report_views": "python_export"}
        for key, value in meta.items():
            adapter.execute(*sqlbuild.insert("contract_meta", {"meta_key": key, "meta_value": value}))
        adapter.commit()
        repo = Repository(adapter)
        if repo.blocked_errors:
            raise AdapterError("new SQLite database failed ledger validation")
        return {"backend": "sqlite", "tables": len(ddl.registry()), "indexes": len(ddl.indexes()),
                "contract_meta": meta, "path_check": verdict,
                "opened": {"schema_version": SCHEMA_VERSION, "blocked": False}}
    except Exception:
        if adapter is not None:
            adapter.close()
            adapter = None
        target.unlink(missing_ok=True)
        raise
    finally:
        if adapter is not None:
            adapter.close()


def open_database(path, *, read_only=False):
    """Open an existing PerFin SQLite file, validate metadata and relationships."""
    from .repository import Repository
    adapter = SQLiteAdapter(path, read_only=read_only)
    try:
        with adapter.read_snapshot():
            repo = Repository(adapter)
            if repo.meta.get("backend") != "sqlite" or repo.meta.get("sqlite_schema_version") != SQLITE_SCHEMA_VERSION:
                raise SchemaVersionError("not a supported PerFin SQLite database")
            if adapter.query_storage("PRAGMA quick_check") != [("ok",)] or adapter.query_storage("PRAGMA foreign_key_check"):
                raise AdapterError("SQLite integrity or foreign key check failed")
        return repo
    except Exception:
        adapter.close()
        raise
