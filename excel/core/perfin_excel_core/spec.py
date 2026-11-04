"""Table definitions for the core workbook.

Report-table columns come from the frozen contract (report_tables.json); nothing here
redefines them. The derived, status and module tables are 2c's own read-only views.
"""
import json
from functools import lru_cache

from ._deps import REPORT_TABLES_JSON

# Report tables the core shell refreshes. Modules read the others in their own workbooks.
CORE_SOURCES = (
    "rpt_accounts",
    "rpt_transactions",
    "rpt_card_status",
    "rpt_statements",
    "rpt_reconciliation",
    "rpt_review_queue",
)

# Which column of a source carries its data-as-of date (None: no as-of column).
AS_OF_COLUMN = {
    "rpt_accounts": "balance_as_of",
    "rpt_card_status": "as_of",
}

# Status values written to perfin_refresh_status. Only OK counts as current.
STATUS_OK = "OK"
STATUS_MISSING = "MISSING"
STATUS_BAD_HEADER = "BAD_HEADER"
STATUS_INVALID = "INVALID"
STATUS_STALE = "STALE"
STATUS_NOT_REFRESHED = "NOT_REFRESHED"

DEFAULT_STALE_DAYS = 7

# 2c-owned views. Column types use the same vocabulary as report_tables.json, plus
# "datetime" (local refresh time) for the status table.
DERIVED_TABLES = {
    "perfin_statement_recon": [
        ("statement_id", "id", 0),
        ("account_id", "id", 0),
        ("account_kind", "enum", 1),
        ("period_start", "date", 0),
        ("period_end", "date", 0),
        ("due_date", "date", 1),
        ("opening_balance_minor", "money_minor", 0),
        ("closing_balance_minor", "money_minor", 0),
        ("opening_display_minor", "money_minor", 1),
        ("closing_display_minor", "money_minor", 1),
        ("reconciliation_id", "id", 1),
        ("recon_status", "enum", 0),
        ("included_count", "integer", 1),
        ("difference_minor", "money_minor", 1),
        ("unreconciled_count", "integer", 0),
        ("unreconciled_minor", "money_minor", 0),
    ],
    "perfin_unreconciled_items": [
        ("statement_id", "id", 0),
        ("account_id", "id", 0),
        ("transaction_id", "id", 0),
        ("posted_date", "date", 0),
        ("amount_minor", "money_minor", 0),
        ("description", "text", 0),
    ],
}

STATUS_TABLE = "perfin_refresh_status"
STATUS_COLUMNS = [
    ("source", "id", 0),
    ("file_name", "text", 0),
    ("status", "enum", 0),
    ("row_count", "integer", 1),
    ("file_modified", "datetime", 1),
    ("data_as_of", "date", 1),
    ("checked_at", "datetime", 1),
    ("message", "text", 1),
]

MODULES_TABLE = "perfin_modules"
MODULES_CSV = "perfin_modules.csv"
MODULES_COLUMNS = [
    ("module_id", "id", 0),
    ("module_version", "text", 0),
    ("module_kind", "enum", 0),
    ("module_dir", "text", 0),
    ("workbook_file", "text", 1),
    ("launchable", "boolean", 0),
    ("status", "enum", 0),
    ("message", "text", 1),
    ("reads", "text", 1),
    ("commands", "text", 1),
]

NOT_RECONCILED = "not_reconciled"


@lru_cache(maxsize=1)
def report_tables():
    """The frozen contract's report tables: {table: [(name, type, nullable), ...]}."""
    with open(REPORT_TABLES_JSON, encoding="utf-8") as f:
        doc = json.load(f)
    return {t: tuple((c["name"], c["type"], bool(c["nullable"])) for c in cols)
            for t, cols in doc["tables"].items()}


@lru_cache(maxsize=1)
def csv_dialect():
    with open(REPORT_TABLES_JSON, encoding="utf-8") as f:
        return json.load(f)["csv_dialect"]


def columns(table):
    """Column definitions for any table the core workbook shows."""
    if table in DERIVED_TABLES:
        return tuple((n, t, bool(nl)) for n, t, nl in DERIVED_TABLES[table])
    if table == STATUS_TABLE:
        return tuple((n, t, bool(nl)) for n, t, nl in STATUS_COLUMNS)
    if table == MODULES_TABLE:
        return tuple((n, t, bool(nl)) for n, t, nl in MODULES_COLUMNS)
    return report_tables()[table]


def column_names(table):
    return [c[0] for c in columns(table)]
