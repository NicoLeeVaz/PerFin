"""Build parameterized Access SQL from the schema registry.

Every value is a '?' parameter; identifiers come only from access/schema/010_tables.sql and
are bracket-quoted. The repository issues no other SQL, so this module is the whole DML
surface. Statement shapes (also what the test-only fake adapter accepts):

    INSERT INTO [t] ([c1], [c2]) VALUES (?, ?)
    UPDATE [t] SET [c1] = ?, [c2] = ? WHERE [k1] = ? AND [k2] = ?
    DELETE FROM [t] WHERE [k1] = ? AND [k2] IS NULL
    SELECT [c1], [c2] FROM [t] WHERE [k1] = ? ORDER BY [c1], [c2]
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import ddl

Statement = Tuple[str, Tuple[Any, ...]]


def _check(table: str, columns: Iterable[str]) -> ddl.Table:
    t = ddl.table(table)
    for c in columns:
        if c not in t.columns:
            raise KeyError("unknown column %s.%s" % (table, c))
    return t


def _q(name: str) -> str:
    return "[%s]" % name


def _where(where: Dict[str, Any]) -> Tuple[str, List[Any]]:
    if not where:
        return "", []
    parts, params = [], []
    for col, value in where.items():
        if value is None:
            parts.append("%s IS NULL" % _q(col))
        else:
            parts.append("%s = ?" % _q(col))
            params.append(value)
    return " WHERE " + " AND ".join(parts), params


def insert(table: str, row: Dict[str, Any]) -> Statement:
    _check(table, row)
    cols = list(row)
    sql = "INSERT INTO %s (%s) VALUES (%s)" % (_q(table), ", ".join(map(_q, cols)), ", ".join("?" for _ in cols))
    return sql, tuple(row[c] for c in cols)


def update(table: str, changes: Dict[str, Any], where: Dict[str, Any]) -> Statement:
    if not changes or not where:
        raise ValueError("UPDATE needs changes and a WHERE clause")
    _check(table, list(changes) + list(where))
    w, wp = _where(where)
    sql = "UPDATE %s SET %s%s" % (_q(table), ", ".join("%s = ?" % _q(c) for c in changes), w)
    return sql, tuple(changes.values()) + tuple(wp)


def delete(table: str, where: Dict[str, Any]) -> Statement:
    if not where:
        raise ValueError("DELETE needs a WHERE clause")
    _check(table, where)
    w, wp = _where(where)
    return "DELETE FROM %s%s" % (_q(table), w), tuple(wp)


def select(table: str, columns: Optional[Sequence[str]] = None, where: Optional[Dict[str, Any]] = None,
           order_by: Optional[Sequence[str]] = None) -> Statement:
    t = ddl.table(table)
    cols = list(columns or t.columns)
    _check(table, cols + list(where or {}) + list(order_by or []))
    w, wp = _where(where or {})
    sql = "SELECT %s FROM %s%s" % (", ".join(map(_q, cols)), _q(table), w)
    if order_by:
        sql += " ORDER BY " + ", ".join(map(_q, order_by))
    return sql, tuple(wp)
