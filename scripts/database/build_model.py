"""Generate the table inventory and offline explorer from PerFin's canonical DDL.

Run from any directory: python scripts/database/build_model.py [--check]
This reads schema/source metadata only; it never opens a populated database.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from perfin_store import SCHEMA_VERSION, codec, ddl, money  # noqa: E402

GROUPS = {
    "Foundation": ["account", "category", "contract_meta"],
    "Import review": ["import_batch", "staging_row"],
    "Ledger": ["ledger_txn", "split", "transfer_link"],
    "Statements": ["statement", "statement_bucket_balance", "statement_payment", "reconciliation", "reconciliation_item"],
    "Planning": ["card_terms", "card_apr_bucket", "asset_valuation"],
    "History": ["command_log", "audit_log"],
}
PURPOSES = {
    "account": "One financial account: opening balance, currency, ownership and account class.",
    "category": "Income/expense classifications, with an optional parent category.",
    "contract_meta": "Schema/contract/backend versions, configuration and saved-scenario command pointers.",
    "import_batch": "One source file for one account; its hash prevents silent repeated imports.",
    "staging_row": "One raw/parsed source row, proposed splits, duplicate decision and human review state.",
    "ledger_txn": "One signed posted transaction. Retains source provenance or a reversal reference.",
    "split": "Allocates a transaction amount among categories, transfers or adjustments.",
    "transfer_link": "Pairs an outgoing and incoming ledger transaction for a transfer between accounts.",
    "statement": "Dated statement totals for one account, with an opaque external evidence reference.",
    "statement_bucket_balance": "One balance per statement and APR bucket identifier.",
    "statement_payment": "Allocates some of a payment transaction to a particular statement.",
    "reconciliation": "A statement comparison, its remaining difference and review status.",
    "reconciliation_item": "Associates each included transaction with a reconciliation.",
    "card_terms": "Effective-dated credit limit and minimum-payment rule for a card account.",
    "card_apr_bucket": "APR and promotional/deferred-interest terms for each bucket in a terms record.",
    "asset_valuation": "A dated asset estimate, its source/method and optional cost basis.",
    "command_log": "Accepted command/result documents supporting idempotent replay and saved scenario payloads.",
    "audit_log": "Before/after images of changed entities, linked to their accepted command.",
}
SQLITE_TYPES = {"TEXT": "TEXT", "MEMO": "TEXT", "DATETIME": "TEXT", "CURRENCY": "INTEGER",
                "LONG": "INTEGER", "INTEGER": "INTEGER", "YESNO": "INTEGER"}
LOGICAL = [
    {"source_table": "ledger_txn", "source_columns": ["source_batch_id", "source_row_number"],
     "target_table": "staging_row", "target_columns": ["batch_id", "row_number"],
     "note": "Import provenance. source_batch_id has a physical FK; this composite source-row link is repository-managed."},
    {"source_table": "staging_row", "source_columns": ["matched_transaction_id"],
     "target_table": "ledger_txn", "target_columns": ["transaction_id"],
     "note": "Duplicate-match evidence; no SQL foreign key is declared."},
    {"source_table": "audit_log", "source_columns": ["entity", "entity_id"],
     "target_table": None, "target_columns": [],
     "note": "Polymorphic reference to the changed entity; retained after an entity is removed, so it is not a SQL FK."},
    {"source_table": "contract_meta", "source_columns": ["meta_value"],
     "target_table": "command_log", "target_columns": ["command_id"],
     "note": "Only meta_key values beginning scenario: point to saved payoff commands; ordinary metadata values do not."},
]


def inventory():
    tables = ddl.registry()
    if set(tables) != set(PURPOSES):
        raise ValueError("Update the model descriptions when canonical tables change")
    indexes = ddl.indexes()
    out = {"inventory_format": 1, "schema_version": SCHEMA_VERSION,
           "contract_version": (ROOT / "contracts/VERSION").read_text().strip(),
           "source_files": [], "groups": GROUPS,
           "mapping": {"sqlite_types": SQLITE_TYPES, "money_min": money.MONEY_MIN, "money_max": money.MONEY_MAX,
                       "integer_min": codec.INT32[0], "integer_max": codec.INT32[1],
                       "sqlite_tables": "STRICT; SQLite 3.37 or newer",
                       "text_collation": "NOCASE on canonical TEXT columns; ASCII folding, not full ACE locale equivalence",
                       "report_path": "Python report exports are canonical for SQLite; Access rpt_* SQL is backend-specific"},
           "tables": [], "logical_relationships": LOGICAL, "reports": []}
    for relative in ["access/schema/" + f for f in ddl.SCHEMA_FILES] + ["contracts/schemas/report_tables.json"]:
        out["source_files"].append({"path": relative, "sha256": hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()})
    for name, table in tables.items():
        columns = []
        for column in table.columns.values():
            item = asdict(column)
            item["sqlite_type"] = SQLITE_TYPES[column.type]
            item["primary_key"] = column.name in table.primary_key
            if column.type == "DATETIME":
                item["format"] = "UTC timestamp, seconds" if (name, column.name) in codec.TIMESTAMP_COLUMNS else "calendar date"
            columns.append(item)
        out["tables"].append({"name": name, "group": next(g for g, names in GROUPS.items() if name in names),
                              "purpose": PURPOSES[name], "columns": columns, "primary_key": list(table.primary_key),
                              "unique_keys": [list(u) for u in table.uniques],
                              "foreign_keys": [{"column": c, "table": t, "target_column": tc}
                                               for c, t, tc in table.foreign_keys],
                              "checks": [{"name": n, "expression": e} for n, e in table.checks],
                              "indexes": [dict(asdict(index), columns=list(index.columns)) for index in indexes if index.table == name]})
    spec = json.loads((ROOT / "contracts/schemas/report_tables.json").read_text())
    for name, _sql in ddl.views():
        out["reports"].append({"name": name, "columns": spec["tables"][name]})
    return out


def markdown(data):
    lines = ["# PerFin database structure", "",
             "SQLite is the current local backend; Access is an optional Windows backend and future portability target. "
             "Both use the same logical entities and repository commands. Native Access/desktop Excel acceptance is a release requirement, "
             "not a prerequisite for continuing development.", "",
             "Open [the offline table explorer](model.html) for clickable tables, incoming/outgoing links and all column definitions. "
             "The [machine-readable inventory](schema-inventory.json) is generated from the canonical DDL, not a populated database.", "",
             "## Read the structure in this order", "",
             "1. **Accounts and categories** define where money belongs and how flows are classified.",
             "2. **Batches and staging rows** retain the original file/row and human decisions. Staging does not change balances.",
             "3. **Ledger transactions and splits** record approved activity atomically. Split amounts must total the transaction.",
             "4. **Transfers** connect two equal-and-opposite transactions on different same-currency accounts; they are not spending twice.",
             "5. **Statements and reconciliations** compare the ledger against external evidence without overwriting history.",
             "6. **Terms and valuations** support payoff planning and dated net worth. Reports and workbooks are read models.",
             "7. **Commands and audits** preserve replay protection, revisions and before/after values in the same transaction.", "",
             "## Core relationships", "", "```mermaid", "flowchart TD",
             '  A["account"] -->|account_id| T["ledger_txn"]',
             '  T -->|transaction_id| S["split"]',
             '  C["category"] -->|category_id| S',
             '  T -->|from / to transaction| L["transfer_link"]',
             '  L -->|transfer_link_id| S', "```", "",
             "Arrows run from referenced parent to referencing child. Most are one-to-many. "
             "A transfer names two ledger legs; the repository validates their direction, equal magnitude, currency and pairing. "
             "Each category may reference another category, and a reversal references its original transaction.", "",
             "## The complete table map", "", "| Group | Table | Primary key | Role |", "| --- | --- | --- | --- |"]
    for table in data["tables"]:
        lines.append("| %s | [%s](#%s) | `%s` | %s |" % (table["group"], table["name"], table["name"],
                     ", ".join(table["primary_key"]), table["purpose"]))
    lines += ["", "## Physical and logical relationships", "",
              "A physical foreign key is enforced by the database when FK enforcement is enabled. "
              "SQLite connections enable it explicitly. The following links are intentionally repository-managed:", "",
              "| From | To | Meaning |", "| --- | --- | --- |"]
    for r in data["logical_relationships"]:
        lines.append("| `%s.%s` | %s | %s |" % (r["source_table"], ", ".join(r["source_columns"]),
                     "`" + r["target_table"] + "." + ", ".join(r["target_columns"]) + "`" if r["target_table"] else "Changed entity", r["note"]))
    lines += ["", "`statement_bucket_balance.bucket_id` labels a statement bucket; it is not a foreign key to "
              "`card_apr_bucket`, whose key also includes `terms_id`. A category split, a transfer split and an adjustment "
              "have different semantic rules. These and balancing, date validity, duplicate review and row versions are "
              "validated by repository/contracts in addition to physical keys.", "",
              "Saved payoff scenarios do not have a nineteenth table: their payload is in `command_log`, "
              "with a `scenario:` key in `contract_meta` pointing to the latest command and history in `audit_log`.", "",
              "## Storage mapping", "", "| Canonical Access type | SQLite storage | Rule |", "| --- | --- | --- |",
              "| CURRENCY | INTEGER | Integer minor units, not dollars; bounded to ±922337203685477. Never binary-float money. |",
              "| LONG / INTEGER | INTEGER | Retain the repository's signed 32-bit bounds. |",
              "| YESNO | INTEGER | 0/1 booleans; repository refuses null Yes/No values even where reference DDL is nullable. |",
              "| DATETIME | TEXT | ISO calendar dates or second-resolution timestamps; adapter preserves existing codec semantics. |",
              "| TEXT(n) | TEXT | Length bound retained, NOCASE comparison for canonical TEXT columns. ASCII folding is not full ACE locale equivalence. |",
              "| MEMO | TEXT | Long descriptions and JSON documents; no blanket case folding. |", "",
              "SQLite uses STRICT tables (3.37+) and checks types/bounds. PK, unique, foreign-key and index definitions "
              "come from the canonical registry. A connection must enable foreign keys. Backend metadata distinguishes "
              "SQLite storage from Access; sharing logical tables is not enough to establish native compatibility.", "",
              "## Reports, Excel and later porting", "",
              "The canonical Python report builder produces contract-shaped `rpt_*` CSV data for either repository adapter. "
              "SQLite does not execute the Access-specific `Date()`, `IIf`, `Round` and view syntax. Workbook file generation "
              "and formula inspection can run without desktop Excel; native recalculation, VBA and Power Query need their own release evidence.", "",
              "A `ledger_bundle` carries ledger-domain data but does not preserve every staging row, command or audit event. "
              "A complete port needs a full-table snapshot, ordered FK-safe insertion, exact types and versions, history/replay preservation, "
              "schema metadata handling and independent balance/history checks. Renaming `.sqlite` to `.accdb` is not a conversion. "
              "See [portability](portability.md) for the supported exchange path and remaining native acceptance.", "",
              "## Column dictionary", ""]
    for table in data["tables"]:
        lines += ["### " + table["name"], "", table["purpose"], "",
                  "| Column | Access type | SQLite | Required by DDL | Key/reference |", "| --- | --- | --- | --- | --- |"]
        for column in table["columns"]:
            refs = (["PK"] if column["primary_key"] else []) + [f"FK → {f['table']}.{f['target_column']}" for f in table["foreign_keys"] if f["column"] == column["name"]]
            ctype = column["type"] + ("(%s)" % column["length"] if column["length"] else "")
            lines.append("| `%s` | %s | %s | %s | %s |" % (column["name"], ctype, column["sqlite_type"], "Yes" if column["not_null"] else "No", "; ".join(refs)))
        if table["unique_keys"]:
            lines += ["", "Unique keys: " + "; ".join("`" + ", ".join(u) + "`" for u in table["unique_keys"]) + "."]
        if table["indexes"]:
            lines += ["", "Indexes: " + "; ".join("`" + i["name"] + "` (" + ", ".join(i["columns"]) + ")" + (" UNIQUE" if i["unique"] else "") + (" ignoring nulls" if i["ignore_null"] else "") for i in table["indexes"]) + "."]
        if table["checks"]:
            lines += ["", "Declared checks: " + "; ".join("`" + c["name"] + "`: `" + c["expression"] + "`" for c in table["checks"]) + "."]
        lines.append("")
    lines += ["## Reproduce the inventory", "", "```sh", "python3 scripts/database/build_model.py", "python3 scripts/database/build_model.py --check", "python3 -B -m unittest discover -s tests/database -v", "```", "",
              "Generated inventory format %s; schema %s; contract %s. Source hashes in the JSON inventory make drift visible. "
              "`--check` exits nonzero when any generated artifact differs. No financial data is included." % (data["inventory_format"], data["schema_version"], data["contract_version"]), ""]
    return "\n".join(lines)


def outputs():
    data = inventory()
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    template = (Path(__file__).with_name("model-template.html")).read_text(encoding="utf-8")
    page = template.replace("__INVENTORY_JSON__", payload.replace("<", "\\u003c"))
    return {"schema-inventory.json": payload, "model.md": markdown(data), "model.html": page}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    folder = ROOT / "docs/database"
    problems = []
    for name, content in outputs().items():
        path = folder / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                problems.append(str(path.relative_to(ROOT)))
        else:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if problems:
        print("OUTDATED: " + ", ".join(problems))
        return 1
    print("Database model current" if args.check else "Generated database model (18 tables; no financial data)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
