"""Read the access/schema/*.sql creation scripts.

The scripts are the single source of the schema. This module splits them into statements
for setup, and parses the CREATE TABLE / CREATE INDEX / ALTER TABLE forms they use into a
table registry. The registry lets the SQL builder refuse unknown identifiers and lets the
codec convert values by declared column type.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import _paths

SCHEMA_FILES = ("010_tables.sql", "020_checks.sql", "030_indexes.sql", "040_report_views.sql")
TYPES = {"TEXT", "MEMO", "CURRENCY", "DATETIME", "LONG", "INTEGER", "YESNO"}
_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass
class Column:
    name: str
    type: str
    length: Optional[int]
    not_null: bool


@dataclass
class Table:
    name: str
    columns: Dict[str, Column] = field(default_factory=dict)
    primary_key: Tuple[str, ...] = ()
    uniques: List[Tuple[str, ...]] = field(default_factory=list)
    foreign_keys: List[Tuple[str, str, str]] = field(default_factory=list)  # (column, ref table, ref column)
    checks: List[Tuple[str, str]] = field(default_factory=list)  # (name, expression)


@dataclass
class Index:
    name: str
    table: str
    columns: Tuple[str, ...]
    unique: bool
    ignore_null: bool


def strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))


def split_statements(text: str) -> List[str]:
    """Split a script on ';' outside quotes. Comment lines are removed first."""
    out, buf, quote = [], [], False
    for ch in strip_comments(text):
        if ch == "'":
            quote = not quote
        if ch == ";" and not quote:
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return out


def _split_top(body: str) -> List[str]:
    parts, depth, buf = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        parts.append("".join(buf).strip())
    return parts


_CREATE_TABLE = re.compile(r"^CREATE TABLE (\w+) \((.*)\)$", re.S)
_COLUMN = re.compile(r"^(\w+) (TEXT|MEMO|CURRENCY|DATETIME|LONG|INTEGER|YESNO)(?:\((\d+)\))?(.*)$", re.S)
_INLINE_PK = re.compile(r"CONSTRAINT \w+ PRIMARY KEY")
_INLINE_FK = re.compile(r"CONSTRAINT \w+ REFERENCES (\w+) \((\w+)\)")
_TABLE_PK = re.compile(r"^CONSTRAINT \w+ PRIMARY KEY \(([\w, ]+)\)$")
_TABLE_UQ = re.compile(r"^CONSTRAINT \w+ UNIQUE \(([\w, ]+)\)$")
_TABLE_CK = re.compile(r"^CONSTRAINT (\w+) CHECK \((.*)\)$", re.S)
_CREATE_INDEX = re.compile(r"^CREATE (UNIQUE )?INDEX (\w+) ON (\w+) \(([\w, ]+)\)( WITH IGNORE NULL)?$")
_ALTER_CHECK = re.compile(r"^ALTER TABLE (\w+) ADD CONSTRAINT (\w+) CHECK \((.*)\)$", re.S)
_CREATE_VIEW = re.compile(r"^CREATE VIEW (\w+) AS (SELECT\b.*)$", re.S)


def _cols(text: str) -> Tuple[str, ...]:
    return tuple(c.strip() for c in text.split(","))


def parse_create_table(stmt: str) -> Table:
    m = _CREATE_TABLE.match(stmt.strip())
    if not m:
        raise ValueError("not a CREATE TABLE statement")
    table = Table(m.group(1))
    for part in _split_top(m.group(2)):
        part = " ".join(part.split())
        if part.startswith("CONSTRAINT "):
            if _TABLE_PK.match(part):
                table.primary_key = _cols(_TABLE_PK.match(part).group(1))
            elif _TABLE_UQ.match(part):
                table.uniques.append(_cols(_TABLE_UQ.match(part).group(1)))
            elif _TABLE_CK.match(part):
                ck = _TABLE_CK.match(part)
                table.checks.append((ck.group(1), ck.group(2)))
            else:
                raise ValueError("unsupported table constraint: %s" % part)
            continue
        cm = _COLUMN.match(part)
        if not cm:
            raise ValueError("unsupported column definition: %s" % part)
        name, ctype, length, rest = cm.group(1), cm.group(2), cm.group(3), cm.group(4)
        table.columns[name] = Column(name, ctype, int(length) if length else None, "NOT NULL" in rest)
        if _INLINE_PK.search(rest):
            table.primary_key = (name,)
        fk = _INLINE_FK.search(rest)
        if fk:
            table.foreign_keys.append((name, fk.group(1), fk.group(2)))
    for name in table.columns:
        if not _IDENT.match(name):
            raise ValueError("bad identifier %r" % name)
    return table


def parse_statement(stmt: str):
    """Classify one statement: ('table', Table) | ('index', Index) | ('check', (t, n, e)) | ('view', (n, sql))."""
    flat = " ".join(stmt.split())
    if flat.startswith("CREATE TABLE "):
        return "table", parse_create_table(stmt)
    m = _CREATE_INDEX.match(flat)
    if m:
        return "index", Index(m.group(2), m.group(3), _cols(m.group(4)), bool(m.group(1)), bool(m.group(5)))
    m = _ALTER_CHECK.match(flat)
    if m:
        return "check", (m.group(1), m.group(2), m.group(3))
    m = _CREATE_VIEW.match(stmt.strip())
    if m:
        return "view", (m.group(1), m.group(2))
    raise ValueError("unsupported DDL statement: %s" % flat[:80])


def read_script(name: str, schema_dir: Optional[Path] = None) -> str:
    return (Path(schema_dir or _paths.SCHEMA_DIR) / name).read_text(encoding="utf-8")


def script_statements(name: str, schema_dir: Optional[Path] = None) -> List[str]:
    return split_statements(read_script(name, schema_dir))


@lru_cache(maxsize=None)
def registry() -> Dict[str, Table]:
    """Tables declared by 010_tables.sql, plus CHECKs from 020 (informational)."""
    tables: Dict[str, Table] = {}
    for stmt in script_statements("010_tables.sql"):
        kind, obj = parse_statement(stmt)
        if kind != "table":
            raise ValueError("010_tables.sql must contain only CREATE TABLE")
        tables[obj.name] = obj
    for stmt in script_statements("020_checks.sql"):
        kind, (t, n, e) = parse_statement(stmt)
        tables[t].checks.append((n, e))
    return tables


@lru_cache(maxsize=None)
def indexes() -> Tuple[Index, ...]:
    return tuple(parse_statement(s)[1] for s in script_statements("030_indexes.sql"))


@lru_cache(maxsize=None)
def views() -> Tuple[Tuple[str, str], ...]:
    return tuple(parse_statement(s)[1] for s in script_statements("040_report_views.sql"))


def table(name: str) -> Table:
    try:
        return registry()[name]
    except KeyError:
        raise KeyError("unknown table %r" % name) from None
