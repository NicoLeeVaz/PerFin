"""Read PerFin report CSVs in the contract dialect and derive the core views.

This mirrors the Power Query code in excel/core/powerquery so the Linux tests can
check the same rules: exact header, UTF-8 without BOM, CRLF, RFC 4180 minimal quoting,
empty field = null, TRUE/FALSE, integer minor units, and a visible status for every
source. A source that is missing or invalid yields no rows, never old data.
"""
import csv
import datetime as dt
import io
import os
import re

from . import spec

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_INT = re.compile(r"^-?[0-9]+$")
_DECIMAL = re.compile(r"^[0-9]+(\.[0-9]+)?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
MONEY_BOUND = 922337203685477


class ReportError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def parse_value(raw, col_type, nullable):
    """Convert one CSV field to its typed value. Raises ValueError with a reason."""
    if raw == "":
        if not nullable:
            raise ValueError("empty field in non-nullable column")
        return None
    if col_type in ("text", "enum"):
        return raw
    if col_type == "id":
        if not _ID.match(raw):
            raise ValueError("not a contract id")
        return raw
    if col_type == "currency":
        if not _CURRENCY.match(raw):
            raise ValueError("not an ISO 4217 code")
        return raw
    if col_type == "decimal_string":
        if not _DECIMAL.match(raw):
            raise ValueError("not a decimal string")
        return raw  # rates stay text, never binary floats
    if col_type in ("money_minor", "integer"):
        if not _INT.match(raw):
            raise ValueError("not an integer")
        value = int(raw)
        if col_type == "money_minor" and abs(value) > MONEY_BOUND:
            raise ValueError("outside the contract money bound")
        return value
    if col_type == "boolean":
        if raw == "TRUE":
            return True
        if raw == "FALSE":
            return False
        raise ValueError("boolean must be TRUE or FALSE")
    if col_type == "date":
        if not _DATE.match(raw):
            raise ValueError("date must be YYYY-MM-DD")
        return dt.date.fromisoformat(raw)  # rejects 2026-02-30
    raise ValueError("unknown column type %s" % col_type)


def _canonical(rows):
    out = io.StringIO(newline="")
    w = csv.writer(out, delimiter=",", quotechar='"', lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerows(rows)
    return out.getvalue()


def write_report_csv(path, table, rows):
    """Write rows (dicts of raw strings or typed values) in the contract dialect."""
    names = spec.column_names(table)
    data = [names] + [[format_value(r.get(n)) for n in names] for r in rows]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(_canonical(data))


def format_value(v):
    if v is None:
        return ""
    if v is True:
        return "TRUE"
    if v is False:
        return "FALSE"
    if isinstance(v, (dt.date,)):
        return v.isoformat()
    return str(v)


def read_report_csv(path, table):
    """Return typed rows for `table`, or raise ReportError(status, message).

    Messages name the row and column only; they never echo field values.
    """
    cols = spec.columns(table)
    names = [c[0] for c in cols]
    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        raise ReportError(spec.STATUS_MISSING, "file not found") from None
    if data.startswith(b"\xef\xbb\xbf"):
        raise ReportError(spec.STATUS_INVALID, "UTF-8 byte order mark is not allowed")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ReportError(spec.STATUS_INVALID, "not valid UTF-8") from None
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=",", quotechar='"', strict=True))
    except csv.Error as e:
        raise ReportError(spec.STATUS_INVALID, "CSV syntax error: %s" % e) from None
    if not rows:
        raise ReportError(spec.STATUS_BAD_HEADER, "empty file (header row required)")
    if rows[0] != names:
        raise ReportError(spec.STATUS_BAD_HEADER, "header does not match the contract columns for %s" % table)
    if _canonical(rows) != text:
        raise ReportError(spec.STATUS_INVALID,
                          "not in the contract CSV dialect (CRLF line ends, minimal RFC 4180 quoting)")
    out = []
    for i, raw in enumerate(rows[1:], start=2):
        if len(raw) != len(names):
            raise ReportError(spec.STATUS_INVALID, "line %d: expected %d fields, found %d" % (i, len(names), len(raw)))
        rec = {}
        for (name, col_type, nullable), value in zip(cols, raw):
            try:
                rec[name] = parse_value(value, col_type, nullable)
            except ValueError as e:
                raise ReportError(spec.STATUS_INVALID, "line %d column %s: %s" % (i, name, e)) from None
        out.append(rec)
    _semantic_checks(table, out)
    return out


def _semantic_checks(table, rows):
    if table == "rpt_accounts":
        for i, r in enumerate(rows, start=2):
            want = r["ledger_balance_minor"] if r["kind"] == "asset" else -r["ledger_balance_minor"]
            if r["kind"] not in ("asset", "liability"):
                raise ReportError(spec.STATUS_INVALID, "line %d: kind must be asset or liability" % i)
            if r["display_balance_minor"] != want:
                raise ReportError(spec.STATUS_INVALID,
                                  "line %d: display_balance_minor must equal the ledger balance for assets "
                                  "and minus it for liabilities" % i)


def load_reports(report_dir, checked_at, stale_days=spec.DEFAULT_STALE_DAYS):
    """Load every core source. Returns (tables, status_rows).

    `checked_at` is the local refresh time (datetime). A source is STALE when its file
    or its data-as-of date is older than `stale_days` before `checked_at`.
    """
    tables, status = {}, []
    horizon = checked_at - dt.timedelta(days=stale_days)
    for source in spec.CORE_SOURCES:
        file_name = source + ".csv"
        path = os.path.join(report_dir, file_name)
        row = {"source": source, "file_name": file_name, "status": spec.STATUS_OK, "row_count": None,
               "file_modified": None, "data_as_of": None, "checked_at": checked_at, "message": None}
        try:
            rows = read_report_csv(path, source)
        except ReportError as e:
            row["status"], row["message"] = e.status, e.message
            tables[source] = []
            if e.status != spec.STATUS_MISSING:
                row["file_modified"] = _mtime(path)
            status.append(row)
            continue
        tables[source] = rows
        row["row_count"] = len(rows)
        row["file_modified"] = _mtime(path)
        col = spec.AS_OF_COLUMN.get(source)
        if col and rows:
            row["data_as_of"] = max(r[col] for r in rows)
        reasons = []
        if row["file_modified"] is not None and row["file_modified"] < horizon:
            reasons.append("file older than %d days" % stale_days)
        if row["data_as_of"] is not None and row["data_as_of"] < horizon.date():
            reasons.append("data as of more than %d days before refresh" % stale_days)
        if reasons:
            row["status"], row["message"] = spec.STATUS_STALE, "; ".join(reasons)
        status.append(row)
    tables.update(derive_views(tables, status))
    return tables, status


def not_refreshed_status():
    """Status rows for a template that has never been refreshed."""
    return [{"source": s, "file_name": s + ".csv", "status": spec.STATUS_NOT_REFRESHED, "row_count": None,
             "file_modified": None, "data_as_of": None, "checked_at": None,
             "message": "not refreshed yet: run PerFin_Refresh"} for s in spec.CORE_SOURCES]


def _mtime(path):
    try:
        return dt.datetime.fromtimestamp(int(os.stat(path).st_mtime))
    except OSError:
        return None


def derive_views(tables, status):
    """Statement reconciliation and unreconciled items (same logic as the M queries)."""
    usable = {s["source"] for s in status if s["status"] in (spec.STATUS_OK, spec.STATUS_STALE)}
    need = {"rpt_statements", "rpt_reconciliation", "rpt_transactions", "rpt_accounts"}
    if not need <= usable:
        return {"perfin_statement_recon": [], "perfin_unreconciled_items": []}
    kinds = {a["account_id"]: a["kind"] for a in tables["rpt_accounts"]}
    recs = {}
    for r in sorted(tables["rpt_reconciliation"], key=lambda r: (r["recon_status"] == "balanced", r["reconciliation_id"])):
        recs[r["statement_id"]] = r  # balanced wins over in_progress; then the highest id
    recon, items = [], []
    for st in sorted(tables["rpt_statements"], key=lambda s: (s["account_id"], s["period_end"], s["statement_id"])):
        kind = kinds.get(st["account_id"])
        sign = {"asset": 1, "liability": -1}.get(kind)
        open_txns = sorted((t for t in tables["rpt_transactions"]
                            if t["account_id"] == st["account_id"] and not t["reconciled"]
                            and st["period_start"] <= t["posted_date"] <= st["period_end"]),
                           key=lambda t: (t["posted_date"], t["transaction_id"]))
        rec = recs.get(st["statement_id"])
        recon.append({
            "statement_id": st["statement_id"], "account_id": st["account_id"], "account_kind": kind,
            "period_start": st["period_start"], "period_end": st["period_end"], "due_date": st["due_date"],
            "opening_balance_minor": st["opening_balance_minor"], "closing_balance_minor": st["closing_balance_minor"],
            "opening_display_minor": None if sign is None else sign * st["opening_balance_minor"],
            "closing_display_minor": None if sign is None else sign * st["closing_balance_minor"],
            "reconciliation_id": rec["reconciliation_id"] if rec else None,
            "recon_status": rec["recon_status"] if rec else spec.NOT_RECONCILED,
            "included_count": rec["included_count"] if rec else None,
            "difference_minor": rec["difference_minor"] if rec else None,
            "unreconciled_count": len(open_txns),
            "unreconciled_minor": sum(t["amount_minor"] for t in open_txns),
        })
        for t in open_txns:
            items.append({"statement_id": st["statement_id"], "account_id": t["account_id"],
                          "transaction_id": t["transaction_id"], "posted_date": t["posted_date"],
                          "amount_minor": t["amount_minor"], "description": t["description"]})
    return {"perfin_statement_recon": recon, "perfin_unreconciled_items": items}
