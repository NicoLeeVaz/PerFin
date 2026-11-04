"""PerFin core Excel shell tooling (task 2c).

The core workbook is a read-only, refreshed view of the PerFin report tables
(contracts/schemas/report_tables.json). It never writes the ledger: changes leave
Excel only as validated `command` documents in the local data root.

Run with PYTHONPATH=excel/core (3a owns packaging):

    python3 -m perfin_excel_core build --out PerFin-Core.xlsx
    python3 -m perfin_excel_core check PerFin-Core.xlsx
"""
CORE_WORKBOOK_TEMPLATE = "PerFin-Core.xlsx"
CORE_WORKBOOK_MACRO = "PerFin-Core.xlsm"
SHELL_VERSION = "0.1.0"
