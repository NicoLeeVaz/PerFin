"""PerFin Access store (task 2b): the single authoritative ledger.

Access (.accdb through the Microsoft ACE ODBC driver and pyodbc) is the only production
backend. Everything that can run on Linux here is standard library only; pyodbc is imported
lazily, and only by perfin_store.adapter.AccessOdbcAdapter.

Entry points:
    python -m perfin_store.setup --create <path outside the repository>
    python -m perfin_store envcheck | review | stage | import-bundle | export-reports |
                           export-bundle | backup | restore
"""

STORE_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0.0"  # contract_meta.schema_version written by setup

__all__ = ["STORE_VERSION", "SCHEMA_VERSION"]
