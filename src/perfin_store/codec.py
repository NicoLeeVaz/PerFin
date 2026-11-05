"""Convert between contract values and the Python values bound to Access parameters.

Repository code works with contract values: int minor units, ISO date strings, UTC timestamp
strings, bool, str and None. The adapter only ever sees the types below, chosen per the column's
declared type in access/schema/010_tables.sql:

    CURRENCY  -> decimal.Decimal (exact integer; money.minor_to_db)
    DATETIME  -> datetime.datetime (dates at midnight; timestamps in UTC, naive)
    LONG/INTEGER -> int (32-bit range)
    YESNO     -> bool (Access Yes/No cannot hold Null [Unverified], so None is refused here)
    TEXT(n)   -> str of at most n characters (longer values are refused, never truncated)
    MEMO      -> str
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict

from . import ddl, money

TIMESTAMP_COLUMNS = {
    ("import_batch", "staged_at"),
    ("import_batch", "committed_at"),
    ("command_log", "issued_at"),
    ("audit_log", "recorded_at"),
}
INT32 = (-(2 ** 31), 2 ** 31 - 1)


class CodecError(ValueError):
    pass


def parse_date(text: str) -> datetime:
    try:
        d = date.fromisoformat(text)
    except (TypeError, ValueError):
        raise CodecError("not an ISO calendar date") from None
    if len(text) != 10:
        raise CodecError("not an ISO calendar date")
    return datetime(d.year, d.month, d.day)


def parse_timestamp(text: str) -> datetime:
    if not isinstance(text, str) or len(text) != 20 or not text.endswith("Z"):
        raise CodecError("timestamps are UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise CodecError("timestamps are UTC YYYY-MM-DDTHH:MM:SSZ") from None


def format_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_db(table: str, column: str, value: Any) -> Any:
    col = ddl.table(table).columns.get(column)
    if col is None:
        raise CodecError("unknown column %s.%s" % (table, column))
    if value is None:
        if col.not_null:
            raise CodecError("%s.%s is NOT NULL" % (table, column))
        if col.type == "YESNO":
            raise CodecError("%s.%s is Yes/No and cannot store Null" % (table, column))
        return None
    t = col.type
    if t == "CURRENCY":
        return money.minor_to_db(value)
    if t == "DATETIME":
        if (table, column) in TIMESTAMP_COLUMNS:
            return parse_timestamp(value)
        return parse_date(value)
    if t in ("LONG", "INTEGER"):
        if isinstance(value, bool) or not isinstance(value, int) or not INT32[0] <= value <= INT32[1]:
            raise CodecError("%s.%s needs a 32-bit integer" % (table, column))
        return value
    if t == "YESNO":
        if not isinstance(value, bool):
            raise CodecError("%s.%s needs a boolean" % (table, column))
        return value
    if not isinstance(value, str):
        raise CodecError("%s.%s needs text" % (table, column))
    if t == "TEXT" and col.length is not None and len(value) > col.length:
        raise CodecError("%s.%s is longer than %d characters" % (table, column, col.length))
    return value


def from_db(table: str, column: str, value: Any) -> Any:
    col = ddl.table(table).columns[column]
    if value is None:
        return None
    t = col.type
    if t == "CURRENCY":
        return money.db_to_minor(value)
    if t == "DATETIME":
        if not isinstance(value, datetime):
            if isinstance(value, date):
                value = datetime(value.year, value.month, value.day)
            else:
                raise CodecError("%s.%s: expected a datetime from the driver" % (table, column))
        if (table, column) in TIMESTAMP_COLUMNS:
            return format_timestamp(value)
        if (value.hour, value.minute, value.second, value.microsecond) != (0, 0, 0, 0):
            raise CodecError("%s.%s holds a time part; dates are stored at midnight" % (table, column))
        return value.date().isoformat()
    if t in ("LONG", "INTEGER"):
        if isinstance(value, bool):
            raise CodecError("unexpected boolean")
        return int(value)
    if t == "YESNO":
        return bool(value)
    return str(value)


def row_to_db(table: str, row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: to_db(table, k, v) for k, v in row.items()}
