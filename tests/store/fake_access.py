"""TEST-ONLY in-memory fake of the low-level Access adapter. Never a production backend.

It proves repository logic only: that the repository issues well-formed, fully parameterized
statements of the shapes in perfin_store.sqlbuild, against the tables and columns declared in
access/schema/*.sql, and that its transactions are atomic. It does NOT prove anything about
Access/ACE: SQL dialect, driver type mapping, locking, CHECK constraints or view behaviour are
covered only by tests/store/windows_acceptance.py on a real Windows machine.

What it does model:
* the schema, by executing the real creation scripts (CREATE TABLE / CREATE INDEX are parsed
  with perfin_store.ddl); ALTER TABLE ... CHECK and CREATE VIEW are accepted only when
  ansi92=True, otherwise they fail as ANSI-89 DAO DDL would;
* NOT NULL, primary keys, UNIQUE constraints, unique indexes WITH IGNORE NULL, and
  relationships (insert/update need the parent; delete is refused while children exist);
* parameter types per column: CURRENCY needs Decimal with at most 4 places within the
  CURRENCY range (returned with 4 places, like a scaled integer), DATETIME needs datetime,
  LONG/INTEGER need 32-bit int, YESNO needs bool and cannot be Null, TEXT(n) is length-checked;
* case-insensitive text comparison and keys, as Access does by default [Unverified];
* begin/commit/rollback with snapshot isolation of one connection, writes outside a transaction
  are refused, and failures can be injected on the Nth matching statement or on commit;
* an optional file: the database is saved as JSON on each commit and a <name>.laccdb lock
  file exists while an adapter is open, so backup/restore logic can be exercised.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from perfin_store import ddl  # noqa: E402

CURRENCY_LIMIT = Decimal("922337203685477.5807")
FOUR = Decimal("0.0001")


class FakeSQLError(Exception):
    """Statement rejected (bad shape, constraint or type violation)."""


class FakeEngineError(Exception):
    """Injected engine failure."""


def _key(v: Any) -> Any:
    return v.casefold() if isinstance(v, str) else v


class FakeAccessDatabase:
    def __init__(self, ansi92: bool = True):
        self.ansi92 = ansi92
        self.tables: Dict[str, ddl.Table] = {}
        self.rows: Dict[str, List[Dict[str, Any]]] = {}
        self.indexes: List[ddl.Index] = []
        self.checks: List[Tuple[str, str, str]] = []
        self.views: Dict[str, str] = {}

    # ---------------------------------------------------------------- persistence
    def dump(self) -> Dict[str, Any]:
        def enc(v):
            if isinstance(v, Decimal):
                return {"$dec": str(v)}
            if isinstance(v, datetime):
                return {"$dt": v.isoformat()}
            return v
        return {"ansi92": self.ansi92, "ddl": self.ddl_log, "rows": {t: [{k: enc(v) for k, v in r.items()} for r in rows]
                                                                        for t, rows in self.rows.items()}}

    @property
    def ddl_log(self) -> List[str]:
        return getattr(self, "_ddl_log", [])

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.dump(), sort_keys=True), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "FakeAccessDatabase":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        db = cls(ansi92=data["ansi92"])
        for stmt in data["ddl"]:
            db.apply_ddl(stmt)

        def dec(v):
            if isinstance(v, dict) and "$dec" in v:
                return Decimal(v["$dec"])
            if isinstance(v, dict) and "$dt" in v:
                return datetime.fromisoformat(v["$dt"])
            return v
        db.rows = {t: [{k: dec(v) for k, v in r.items()} for r in rows] for t, rows in data["rows"].items()}
        return db

    # ---------------------------------------------------------------- DDL
    def apply_ddl(self, stmt: str) -> None:
        kind, obj = ddl.parse_statement(stmt)
        if kind == "table":
            if obj.name in self.tables:
                raise FakeSQLError("table %s already exists" % obj.name)
            for col, ref_t, ref_c in obj.foreign_keys:
                if ref_t != obj.name and ref_t not in self.tables:
                    raise FakeSQLError("relationship to unknown table %s" % ref_t)
            self.tables[obj.name] = obj
            self.rows[obj.name] = []
        elif kind == "index":
            if obj.table not in self.tables or any(c not in self.tables[obj.table].columns for c in obj.columns):
                raise FakeSQLError("index on unknown table/column")
            self.indexes.append(obj)
        elif kind == "check":
            if not self.ansi92:
                raise FakeSQLError("Syntax error in CONSTRAINT clause (ANSI-89 mode)")
            self.checks.append(obj)
        elif kind == "view":
            if not self.ansi92:
                raise FakeSQLError("Syntax error in CREATE TABLE statement (ANSI-89 mode)")
            self.views[obj[0]] = obj[1]
        self._ddl_log = self.ddl_log + [stmt]

    # ---------------------------------------------------------------- values
    def coerce(self, table: str, col: str, value: Any) -> Any:
        c = self.tables[table].columns.get(col)
        if c is None:
            raise FakeSQLError("unknown column %s.%s" % (table, col))
        if value is None:
            if c.type == "YESNO":
                raise FakeSQLError("Yes/No column %s.%s cannot be Null" % (table, col))
            return None
        if c.type == "CURRENCY":
            if not isinstance(value, Decimal) or not value.is_finite():
                raise FakeSQLError("CURRENCY parameter %s.%s must be a finite Decimal, got %s"
                                   % (table, col, type(value).__name__))
            q = value.quantize(FOUR)
            if q != value:
                raise FakeSQLError("CURRENCY holds 4 decimal places")
            if abs(q) > CURRENCY_LIMIT:
                raise FakeSQLError("numeric field overflow")
            return q
        if c.type == "DATETIME":
            if not isinstance(value, datetime):
                raise FakeSQLError("DATETIME parameter must be datetime")
            return value
        if c.type in ("LONG", "INTEGER"):
            if isinstance(value, bool) or not isinstance(value, int) or not -2 ** 31 <= value < 2 ** 31:
                raise FakeSQLError("LONG parameter must be a 32-bit int")
            return value
        if c.type == "YESNO":
            if not isinstance(value, bool):
                raise FakeSQLError("YESNO parameter must be bool")
            return value
        if not isinstance(value, str):
            raise FakeSQLError("text parameter must be str")
        if c.type == "TEXT" and len(value) > (c.length or 255):
            raise FakeSQLError("text too long for %s.%s" % (table, col))
        return value

    # ---------------------------------------------------------------- constraints
    def _unique_sets(self, table: str):
        t = self.tables[table]
        sets = [(t.primary_key, False)] + [(u, False) for u in t.uniques]
        sets += [(i.columns, True) for i in self.indexes if i.table == table and i.unique]
        return sets

    def check_row(self, table: str, row: Dict[str, Any], others: List[Dict[str, Any]]) -> None:
        t = self.tables[table]
        for name, col in t.columns.items():
            if col.not_null and row.get(name) is None:
                raise FakeSQLError("%s.%s cannot be Null" % (table, name))
        for cols, ignore_null in self._unique_sets(table):
            if not cols:
                continue
            vals = tuple(_key(row.get(c)) for c in cols)
            if any(v is None for v in vals):
                continue
            for o in others:
                if tuple(_key(o.get(c)) for c in cols) == vals:
                    raise FakeSQLError("duplicate value in key or unique index %s(%s)" % (table, ",".join(cols)))
        for col, ref_t, ref_c in t.foreign_keys:
            v = row.get(col)
            if v is None:
                continue
            pool = self.rows[ref_t] + ([row] if ref_t == table else [])
            if not any(_key(r.get(ref_c)) == _key(v) for r in pool):
                raise FakeSQLError("relationship %s.%s -> %s.%s: related record required" % (table, col, ref_t, ref_c))

    def check_delete(self, table: str, doomed: List[Dict[str, Any]]) -> None:
        for other, t in self.tables.items():
            for col, ref_t, ref_c in t.foreign_keys:
                if ref_t != table:
                    continue
                keys = {_key(r.get(ref_c)) for r in doomed}
                for r in self.rows[other]:
                    if r in doomed:
                        continue
                    if r.get(col) is not None and _key(r.get(col)) in keys:
                        raise FakeSQLError("record is related to %s.%s; cannot delete" % (other, col))


_INSERT = re.compile(r"^INSERT INTO \[(\w+)\] \(([\[\]\w, ]+)\) VALUES \(([?, ]+)\)$")
_UPDATE = re.compile(r"^UPDATE \[(\w+)\] SET (.+?) WHERE (.+)$")
_DELETE = re.compile(r"^DELETE FROM \[(\w+)\] WHERE (.+)$")
_SELECT = re.compile(r"^SELECT ([\[\]\w, ]+) FROM \[(\w+)\](?: WHERE (.+?))?(?: ORDER BY ([\[\]\w, ]+))?$")
_ASSIGN = re.compile(r"^\[(\w+)\] = \?$")
_COND = re.compile(r"^\[(\w+)\] (= \?|IS NULL)$")
_COL = re.compile(r"^\[(\w+)\]$")


def _cols(text: str) -> List[str]:
    out = []
    for part in text.split(", "):
        m = _COL.match(part)
        if not m:
            raise FakeSQLError("identifiers must be bracketed: %r" % part)
        out.append(m.group(1))
    return out


def _conds(text: str) -> List[Tuple[str, bool]]:
    out = []
    for part in text.split(" AND "):
        m = _COND.match(part)
        if not m:
            raise FakeSQLError("unsupported or non-parameterized condition: %r" % part)
        out.append((m.group(1), m.group(2) == "IS NULL"))
    return out


class FakeAccessAdapter:
    """DB-API-like adapter over FakeAccessDatabase, with failure injection."""

    def __init__(self, db: Optional[FakeAccessDatabase] = None, path: Optional[str] = None, *,
                 autocommit: bool = False, **_ignored):
        self.path = str(path) if path else None
        if db is None:
            db = FakeAccessDatabase.load(Path(path)) if path and Path(path).exists() else FakeAccessDatabase()
        self.db = db
        self._snapshot: Optional[Dict[str, List[Dict[str, Any]]]] = None
        self._fail: List[Tuple[Callable[[str], bool], int, Exception]] = []
        self.fail_commit: Optional[Exception] = None
        self.statements: List[Tuple[str, Tuple[Any, ...]]] = []
        self.closed = False
        if self.path:
            self.lock_path = Path(self.path).with_suffix(".laccdb")
            self.lock_path.write_text("fake lock", encoding="utf-8")

    # ---------------------------------------------------------------- failure injection
    def fail_on(self, match: Any = None, *, nth: int = 1, exc: Optional[Exception] = None) -> None:
        """Raise exc on the nth execute() whose SQL matches (substring or predicate; None = any write)."""
        pred = match if callable(match) else (lambda sql, m=match: m is None or m in sql)
        self._fail.append((pred, nth, exc or FakeEngineError("injected engine failure")))

    def _maybe_fail(self, sql: str) -> None:
        for i, (pred, nth, exc) in enumerate(self._fail):
            if pred(sql):
                nth -= 1
                self._fail[i] = (pred, nth, exc)
                if nth == 0:
                    del self._fail[i]
                    raise exc

    # ---------------------------------------------------------------- DB-API-like surface
    def _check_open(self) -> None:
        if self.closed:
            raise FakeSQLError("connection is closed")

    def begin(self) -> None:
        self._check_open()
        if self._snapshot is not None:
            raise FakeSQLError("transaction already open")
        self._snapshot = copy.deepcopy(self.db.rows)

    def commit(self) -> None:
        self._check_open()
        if self._snapshot is None:
            raise FakeSQLError("no transaction")
        if self.fail_commit is not None:
            exc, self.fail_commit = self.fail_commit, None
            raise exc
        self._snapshot = None
        self._persist()

    def rollback(self) -> None:
        self._check_open()
        if self._snapshot is not None:
            self.db.rows = self._snapshot
        self._snapshot = None

    def close(self) -> None:
        if self.closed:
            return
        if self._snapshot is not None:
            self.rollback()
        self.closed = True
        if self.path and self.lock_path.exists():
            self.lock_path.unlink()

    def _persist(self) -> None:
        if self.path:
            self.db.save(Path(self.path))

    def execute_ddl(self, sql: str) -> None:
        self._check_open()
        if self._snapshot is not None:
            raise FakeSQLError("DDL inside a transaction is not supported by this fake")
        self.db.apply_ddl(sql)
        self._persist()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        self._check_open()
        params = tuple(params)
        self.statements.append((sql, params))
        if self._snapshot is None:
            raise FakeSQLError("writes must run inside begin()/commit()")
        if sql.count("?") != len(params):
            raise FakeSQLError("parameter count mismatch")
        self._maybe_fail(sql)
        db = self.db
        m = _INSERT.match(sql)
        if m:
            table, cols = m.group(1), _cols(m.group(2))
            self._table(table)
            row = {c: None for c in db.tables[table].columns}
            for c, v in zip(cols, params):
                row[c] = db.coerce(table, c, v)
            db.check_row(table, row, db.rows[table])
            db.rows[table].append(row)
            return
        m = _UPDATE.match(sql)
        if m:
            table = m.group(1)
            self._table(table)
            assigns = []
            for part in m.group(2).split(", "):
                am = _ASSIGN.match(part)
                if not am:
                    raise FakeSQLError("unsupported or non-parameterized assignment: %r" % part)
                assigns.append(am.group(1))
            conds = _conds(m.group(3))
            values = [db.coerce(table, c, v) for c, v in zip(assigns, params[:len(assigns)])]
            pk = set(db.tables[table].primary_key)
            if pk & set(assigns):
                raise FakeSQLError("primary key updates are not used by PerFin")
            targets = self._match(table, conds, params[len(assigns):])
            new_rows = []
            for r in db.rows[table]:
                if any(r is t for t in targets):
                    r = dict(r, **dict(zip(assigns, values)))
                new_rows.append(r)
            changed = [r for r, old in zip(new_rows, db.rows[table]) if r is not old]
            for r in changed:
                db.check_row(table, r, [o for o in new_rows if o is not r])
            db.rows[table] = new_rows
            return
        m = _DELETE.match(sql)
        if m:
            table = m.group(1)
            self._table(table)
            targets = self._match(table, _conds(m.group(2)), params)
            db.check_delete(table, targets)
            db.rows[table] = [r for r in db.rows[table] if not any(r is t for t in targets)]
            return
        raise FakeSQLError("unsupported statement shape: %r" % sql[:80])

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]:
        self._check_open()
        params = tuple(params)
        self.statements.append((sql, params))
        if sql.count("?") != len(params):
            raise FakeSQLError("parameter count mismatch")
        m = _SELECT.match(sql)
        if not m:
            raise FakeSQLError("unsupported SELECT shape: %r" % sql[:80])
        cols, table = _cols(m.group(1)), m.group(2)
        self._table(table)
        for c in cols:
            if c not in self.db.tables[table].columns:
                raise FakeSQLError("unknown column %s.%s" % (table, c))
        rows = self._match(table, _conds(m.group(3)) if m.group(3) else [], params)
        if m.group(4):
            order = _cols(m.group(4))
            rows = sorted(rows, key=lambda r: tuple((r[c] is not None, _key(r[c])) for c in order))
        return [tuple(copy.deepcopy(r[c]) for c in cols) for r in rows]

    def _table(self, table: str) -> None:
        if table not in self.db.tables:
            raise FakeSQLError("no such table %s" % table)

    def _match(self, table: str, conds: List[Tuple[str, bool]], params: Sequence[Any]) -> List[Dict[str, Any]]:
        values, i = [], 0
        for col, is_null in conds:
            if is_null:
                values.append(None)
            else:
                values.append(self.db.coerce(table, col, params[i]))
                i += 1
        out = []
        for r in self.db.rows[table]:
            if all((r[c] is None) if is_null else (r[c] is not None and _key(r[c]) == _key(v))
                   for (c, is_null), v in zip(conds, values)):
                out.append(r)
        return out


def new_fake_store(*, ansi92: bool = True, base_currency: str = "USD", clock=None, path: Optional[str] = None):
    """Create schema via the real setup code on a fresh fake and return (Repository, adapter, report)."""
    from perfin_store.repository import Repository
    from perfin_store.setup import create_schema

    adapter = FakeAccessAdapter(FakeAccessDatabase(ansi92=ansi92), path=path)
    report = create_schema(adapter, base_currency=base_currency, now="2026-11-04T00:00:00Z")
    repo = Repository(adapter, clock=clock or (lambda: "2026-11-04T12:00:00Z"))
    return repo, adapter, report
