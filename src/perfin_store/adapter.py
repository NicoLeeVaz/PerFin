"""Low-level adapter: the only code that talks to the database engine.

Optional native adapter: pyodbc + the Microsoft Access Database Engine (ACE)
ODBC driver "Microsoft Access Driver (*.mdb, *.accdb)". The interface is deliberately small
and DB-API-like so the repository can be unit-tested on Linux against the test-only fake in
tests/store/fake_access.py. Passing those tests proves repository logic, not ACE behaviour.
The real portable SQLite adapter is in sqlite_backend.py and implements this interface.

    begin()                 start a database transaction
    execute(sql, params)    run one parameterized statement
    query(sql, params)      run one parameterized SELECT; return a list of tuples
    commit() / rollback()   end the transaction
    execute_ddl(sql)        run one DDL statement in its own implicit transaction (setup only)
    close()

pyodbc is imported lazily, inside AccessOdbcAdapter.__init__, so nothing on Linux needs it.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Sequence, Tuple

ACE_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"


class AdapterError(RuntimeError):
    pass


class Adapter:  # pragma: no cover - interface documentation
    path: str

    def begin(self) -> None: ...
    def execute(self, sql: str, params: Sequence[Any] = ()) -> None: ...
    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def execute_ddl(self, sql: str) -> None: ...
    def close(self) -> None: ...


def connection_string(path: str, *, exclusive: bool = False, read_only: bool = False,
                      ansi92: bool = True, driver: str = ACE_DRIVER) -> str:
    """ODBC connection string for a local .accdb.

    ExtendedAnsiSQL=1 asks the ACE ODBC driver for ANSI-92 mode, which CHECK constraints and
    CREATE VIEW need [Unverified]. Exclusive=1 opens the file exclusively [Unverified].
    """
    text = str(path)
    if re.search(r"[;{}\x00]", text):
        raise AdapterError("database path may not contain ';', '{', '}' or NUL")
    if not text.lower().endswith(".accdb"):
        raise AdapterError("PerFin databases are .accdb files")
    parts = ["DRIVER={%s}" % driver, "DBQ=%s" % text]
    if ansi92:
        parts.append("ExtendedAnsiSQL=1")
    if exclusive:
        parts.append("Exclusive=1")
    if read_only:
        parts.append("ReadOnly=1")
    return ";".join(parts) + ";"


class AccessOdbcAdapter:
    """pyodbc connection to one .accdb, autocommit off: one ODBC transaction per command."""

    def __init__(self, path: str, *, exclusive: bool = False, read_only: bool = False,
                 autocommit: bool = False, driver: str = ACE_DRIVER):
        try:
            import pyodbc  # lazy: only the real Windows path needs it
        except ImportError as exc:
            raise AdapterError("pyodbc is not installed; see docs/access/README.md") from exc
        if not Path(path).exists():
            raise AdapterError("database file does not exist; create it with perfin_store.setup")
        self.path = str(path)
        self._pyodbc = pyodbc
        try:
            self._conn = pyodbc.connect(connection_string(path, exclusive=exclusive, read_only=read_only,
                                                          driver=driver), autocommit=autocommit)
        except pyodbc.Error as exc:
            state = exc.args[0] if exc.args else ""
            raise AdapterError("could not open the Access database through the ACE ODBC driver "
                               "(%s %s); run `python -m perfin_store envcheck`" % (type(exc).__name__, state)) from exc
        self._in_txn = False

    def begin(self) -> None:
        # With autocommit off, ODBC starts a transaction implicitly at the first statement.
        if self._in_txn:
            raise AdapterError("transaction already open")
        self._in_txn = True

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        cur = self._conn.cursor()
        try:
            cur.execute(sql, *params) if params else cur.execute(sql)
        finally:
            cur.close()

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]:
        cur = self._conn.cursor()
        try:
            cur.execute(sql, *params) if params else cur.execute(sql)
            return [tuple(r) for r in cur.fetchall()]
        finally:
            cur.close()

    def commit(self) -> None:
        self._conn.commit()
        self._in_txn = False

    def rollback(self) -> None:
        try:
            self._conn.rollback()
        finally:
            self._in_txn = False

    def execute_ddl(self, sql: str) -> None:
        cur = self._conn.cursor()
        try:
            cur.execute(sql)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    def close(self) -> None:
        try:
            self._conn.close()
        finally:
            self._in_txn = False


def ace_driver_installed() -> bool:
    try:
        import pyodbc
    except ImportError:
        return False
    return ACE_DRIVER in pyodbc.drivers()
