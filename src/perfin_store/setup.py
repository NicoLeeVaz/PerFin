"""Create a new, empty PerFin Access database from the access/schema/*.sql scripts.

    python -m perfin_store.setup --create C:\\Users\\me\\AppData\\Local\\PerFin\\db\\perfin.accdb
        [--base-currency USD] [--engine odbc|adox] [--acknowledge-location]

Order of work:
1. Location checks (config/privacy/perfin_privacy_checks.evaluate_data_dir, imported): a path
   inside a git checkout is refused with no override; sync, network and redirected folders are
   blocked until --acknowledge-location. An existing file is never overwritten.
2. Create the empty .accdb (Windows only):
   * engine "odbc" (default): ODBC installer API SQLConfigDataSourceW with the ACE driver's
     CREATE_DBV12 attribute, through ctypes [Unverified attribute name]. Same bitness as pyodbc.
   * engine "adox": ADOX.Catalog.Create through PowerShell COM with the ACE OLE DB provider
     [Unverified]. The path is passed in an environment variable, never spliced into a command.
3. Run 010_tables, 020_checks (each CHECK on its own; failures recorded, see fallback),
   030_indexes, 040_report_views (failures recorded), then write contract_meta.
4. Re-open through the Repository, which checks schema_version and validates the empty ledger.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import SCHEMA_VERSION, STORE_VERSION, _paths, ddl, sqlbuild
from .adapter import ACE_DRIVER

EXIT_OK, EXIT_REFUSED, EXIT_UNSUPPORTED, EXIT_FAILED = 0, 2, 3, 4


class SetupError(RuntimeError):
    pass


def check_target(path, acknowledge_location: bool = False) -> Dict[str, Any]:
    """Raise SetupError unless `path` may hold a new real PerFin database."""
    p = Path(path)
    if p.suffix.lower() != ".accdb":
        raise SetupError("the database file must end in .accdb")
    verdict = _paths.privacy().evaluate_data_dir(str(p))
    if verdict["decision"] == "refuse":
        raise SetupError("refused: " + "; ".join(verdict["reasons"]))
    if verdict["decision"] == "warn" and not acknowledge_location:
        raise SetupError("blocked until acknowledged (--acknowledge-location): " + "; ".join(verdict["reasons"]))
    if p.exists():
        raise SetupError("refusing to overwrite an existing file")
    for lock in (p.with_suffix(".laccdb"), p.with_suffix(".ldb")):
        if lock.exists():
            raise SetupError("a lock file for this path exists; another process may be creating it")
    return verdict


def create_file_odbc(path: str) -> None:
    odbccp32 = ctypes.WinDLL("odbccp32")
    fn = odbccp32.SQLConfigDataSourceW
    fn.argtypes = [ctypes.c_void_p, ctypes.c_ushort, ctypes.c_wchar_p, ctypes.c_wchar_p]
    fn.restype = ctypes.c_int
    if '"' in path:
        raise SetupError("path may not contain double quotes")
    attrs = 'CREATE_DBV12="%s" General\0\0' % path  # ODBC_ADD_DSN = 1; double-NUL terminated list
    if not fn(None, 1, ACE_DRIVER, attrs):
        raise SetupError("SQLConfigDataSourceW(CREATE_DBV12) failed; is the %s driver installed for %d-bit Python?"
                         % (ACE_DRIVER, ctypes.sizeof(ctypes.c_void_p) * 8))


ADOX_PS = ("$ErrorActionPreference='Stop'; $c = New-Object -ComObject ADOX.Catalog; "
           "[void]$c.Create('Provider=Microsoft.ACE.OLEDB.12.0;Data Source=' + $env:PERFIN_NEW_DB); "
           "$c.ActiveConnection.Close()")


def create_file_adox(path: str) -> None:
    env = dict(os.environ, PERFIN_NEW_DB=path)
    if ";" in path:
        raise SetupError("path may not contain ';'")
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ADOX_PS],
                          env=env, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise SetupError("ADOX create failed (PowerShell exit %d); check ACE OLE DB bitness" % proc.returncode)


def create_schema(adapter, *, base_currency: str = "USD", now: str, contract_version: Optional[str] = None,
                  schema_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Run the creation scripts against an empty database and write contract_meta."""
    if not (len(base_currency) == 3 and base_currency.isalpha() and base_currency.isupper()):
        raise SetupError("base currency must be an ISO 4217 code such as USD")
    contract_version = contract_version or _paths.contracts()[2]
    report: Dict[str, Any] = {"tables": 0, "indexes": 0, "checks_ok": [], "checks_failed": [], "views_ok": [],
                              "views_failed": []}
    for stmt in ddl.script_statements("010_tables.sql", schema_dir):
        adapter.execute_ddl(stmt)
        report["tables"] += 1
    for stmt in ddl.script_statements("020_checks.sql", schema_dir):
        name = ddl.parse_statement(stmt)[1][1]
        try:
            adapter.execute_ddl(stmt)
            report["checks_ok"].append(name)
        except Exception as exc:  # ANSI-89 engines reject CHECK: fall back to repository validation
            report["checks_failed"].append("%s (%s)" % (name, type(exc).__name__))
    for stmt in ddl.script_statements("030_indexes.sql", schema_dir):
        adapter.execute_ddl(stmt)
        report["indexes"] += 1
    for stmt in ddl.script_statements("040_report_views.sql", schema_dir):
        name = ddl.parse_statement(stmt)[1][0]
        try:
            adapter.execute_ddl(stmt)
            report["views_ok"].append(name)
        except Exception as exc:
            report["views_failed"].append("%s (%s)" % (name, type(exc).__name__))
    meta = {"schema_version": SCHEMA_VERSION, "contract_version": contract_version, "base_currency": base_currency,
            "created_at": now, "created_by": "perfin_store %s" % STORE_VERSION,
            "check_constraints": "present" if not report["checks_failed"] else
            ("absent" if not report["checks_ok"] else "partial"),
            "check_fallback": "repository validation (perfin_store.repository + perfin_contracts)",
            "report_views": "present" if not report["views_failed"] else ("absent" if not report["views_ok"] else "partial")}
    adapter.begin()
    try:
        for k, v in meta.items():
            adapter.execute(*sqlbuild.insert("contract_meta", {"meta_key": k, "meta_value": v}))
        adapter.commit()
    except Exception:
        adapter.rollback()
        raise
    report["contract_meta"] = meta
    return report


def create_database(path, *, base_currency: str = "USD", engine: str = "odbc", acknowledge_location: bool = False,
                    adapter_factory: Optional[Callable[..., Any]] = None, now: Optional[str] = None) -> Dict[str, Any]:
    verdict = check_target(path, acknowledge_location)
    if sys.platform != "win32" and adapter_factory is None:
        raise NotImplementedError("unsupported platform: creating an Access database needs Windows with the "
                                  "Microsoft ACE driver")
    from .repository import Repository, utc_now

    now = now or utc_now()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if adapter_factory is None:
        from .adapter import AccessOdbcAdapter

        (create_file_adox if engine == "adox" else create_file_odbc)(str(path))
        adapter_factory = AccessOdbcAdapter
    adapter = adapter_factory(str(path), autocommit=False)
    try:
        report = create_schema(adapter, base_currency=base_currency, now=now)
        repo = Repository(adapter)  # schema_version check + empty-ledger validation
        report["opened"] = {"schema_version": repo.meta["schema_version"], "blocked": bool(repo.blocked_errors)}
    finally:
        adapter.close()
    report["path_check"] = verdict
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m perfin_store.setup", description=__doc__.split("\n")[0])
    ap.add_argument("--create", metavar="PATH", required=True, help="new .accdb path outside any git checkout")
    ap.add_argument("--base-currency", default="USD")
    ap.add_argument("--engine", choices=("odbc", "adox"), default="odbc")
    ap.add_argument("--acknowledge-location", action="store_true",
                    help="accept a sync/network/redirected folder after reading the privacy warning")
    args = ap.parse_args(argv)
    try:
        report = create_database(args.create, base_currency=args.base_currency, engine=args.engine,
                                 acknowledge_location=args.acknowledge_location)
    except SetupError as exc:
        print("setup refused: %s" % exc, file=sys.stderr)
        return EXIT_REFUSED
    except NotImplementedError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_UNSUPPORTED
    except Exception as exc:  # report without values or paths
        print("setup failed: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return EXIT_FAILED
    print(json.dumps(report, indent=2, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
