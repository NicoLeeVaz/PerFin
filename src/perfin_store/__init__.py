"""PerFin local store: one selected authoritative backend per data root.

SQLite is the portable default; Access (.accdb via ACE/pyodbc) remains explicit.
Both use Repository commands and the same canonical table definitions. SQLite
uses exact integer cents and real transactions; it is not the test-only fake.
pyodbc is loaded lazily only for native Access operations.

Entry points:
    perfin --data-root PATH [--backend sqlite|access] init
    python -m perfin_store.portability export | verify | import
    Access-specific legacy CLI:
    python -m perfin_store.setup --create <path outside the repository>
    python -m perfin_store envcheck | review | stage | import-bundle | export-reports |
                           export-bundle | backup | restore
"""

STORE_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0.0"  # contract_meta.schema_version written by setup

__all__ = ["STORE_VERSION", "SCHEMA_VERSION"]
