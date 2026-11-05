# PerFin Access backend (task 2b)

Issue [#6](https://github.com/NicoLeeVaz/PerFin/issues/6), part of tracker [#1](https://github.com/NicoLeeVaz/PerFin/issues/1). Built against contract **1.0.0** (frozen, `contracts/VERSION`); no contract file is changed.

**Status:** the code and its Linux unit tests are complete. **Every Windows/Access check is pending.** Nothing here has run against Microsoft Access or the ACE driver. Statements about Microsoft behaviour that this session could not check against Microsoft documentation are marked **[Unverified]**. The Windows acceptance script ([below](#windows-acceptance-pending)) is the evidence the wave gate needs.

Command semantics, ids and the rules the repository adds are in [commands.md](commands.md).

## What is where

| Path | Contents |
| --- | --- |
| `access/schema/010_tables.sql` | Tables, keys and relationships. These match the reference DDL exactly, apart from the CHECK constraints (a test proves it). |
| `access/schema/020_checks.sql` | CHECK constraints (ANSI-92 only): the reference's five, plus an integer check on every CURRENCY column. |
| `access/schema/030_indexes.sql` | Secondary indexes. `ux_txn_reverses` makes "reversed at most once" an engine rule as well as a repository rule. |
| `access/schema/040_report_views.sql` | Read-only `rpt_*` views. Their columns match `contracts/schemas/report_tables.json` exactly. |
| `access/setup/Get-PerfinEnvironment.ps1` | Optional PowerShell environment report (local only). |
| `access/setup/PerfinSetup.bas` | Optional exported VBA/DAO module. It saves the report SELECTs as queries if `CREATE VIEW` is rejected. |
| `src/perfin_store/` | Setup, adapter, repository, reports, backup, environment check and CLI. All standard library; `pyodbc` is imported lazily. |
| `tests/store/` | Linux unit tests, the **test-only** fake adapter, synthetic fixtures and `windows_acceptance.py`. |

## Deployment prerequisites (Windows)

1. **Windows 10/11** with Microsoft 365 / Office desktop, *or* the free **Access Runtime** / **Microsoft Access Database Engine (ACE)**. The ACE ODBC driver must be registered as `Microsoft Access Driver (*.mdb, *.accdb)` [Unverified name on the user's version].
2. **Bitness must match.** ACE has the same bitness as Office (32- or 64-bit). Python and pyodbc must have that bitness too: 64-bit Office needs 64-bit Python. Mixing them is the most common failure; `envcheck` reports it [Unverified].
3. **Python 3.9+** of that bitness, plus **pyodbc 5.3.0** (MIT). Install it with hashes, as the 1b catalog recommends: `py -3 -m pip install --require-hashes -r <reviewed requirements file>`. 3a owns the shared requirements file; until then `py -3 -m pip install pyodbc==5.3.0`. Installing it is the only step that uses the network, and it involves no financial data.
4. **Full Access (not the Runtime)** is needed only for *design work*: opening the database to inspect tables, relationships or queries, importing `PerfinSetup.bas`, or editing forms and VBA. The Runtime cannot open design view [Unverified]. Day-to-day use (setup, commands, reports, backup) needs only ACE + Python.
5. **Data location.** The database lives in the data root, `%LOCALAPPDATA%\PerFin\db\` by default (see [privacy boundary](../privacy/privacy-boundary.md)). It is never inside this repository or a sync folder. Setup, report export, backup and restore all call `evaluate_data_dir()` from `config/privacy/perfin_privacy_checks.py`, which is imported, not copied:
   - inside a git checkout: refused, with no override;
   - sync, network or redirected folders: blocked until `--acknowledge-location`.

Check the machine first:

```bat
py -3 -m perfin_store envcheck
powershell -NoProfile -ExecutionPolicy Bypass -File access\setup\Get-PerfinEnvironment.ps1
```

Run these from the repository root with `set PYTHONPATH=src` until 3a packages PerFin.

`envcheck` reports:

- the Windows version;
- Python version and bitness;
- Office version, bitness and products (Click-to-Run registry, or the MSI `Outlook\Bitness` value);
- full Access versus Runtime (a heuristic, labelled as one);
- the ODBC drivers for both registry views;
- the ACE OLE DB providers and pyodbc.

It makes no network calls. On Linux/macOS it prints `unsupported platform` and exits 2.

## Primary adapter

**pyodbc + the ACE ODBC driver** is the one production adapter (`perfin_store.adapter.AccessOdbcAdapter`); 1b selected it. DAO/VBA appears only in the optional `.bas` helper.

- **Connection string:** `DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=<path>;ExtendedAnsiSQL=1;`. `ExtendedAnsiSQL=1` requests ANSI-92 mode, which CHECK and `CREATE VIEW` need [Unverified]. Paths containing `;`, `{` or `}` are refused.
- **Parameters:** every value is a `?` parameter. Identifiers come only from `010_tables.sql` and are bracket-quoted (`perfin_store.sqlbuild`). No SQL is built from values.
- **Types:**

  | Column type | Python type |
  | --- | --- |
  | CURRENCY | `Decimal` holding the integer count of cents |
  | DATETIME | `datetime` at midnight; timestamps in UTC |
  | Yes/No | `bool` |
  | TEXT(n) | length-checked text, never truncated |

  How the driver binds and returns these is [Unverified]. The acceptance script records the Python types it gets back.
- **Money:** amounts are exact. `money.minor_to_db` and `money.db_to_minor` use `Decimal`; the contract bound ±922337203685477 is the integer range of CURRENCY. The repository never creates a float. A value read back from the driver is accepted only if it is a whole number, and every in-range whole number is exact as a double.
- **No other database.** SQLite and other databases are not used anywhere in `src/`; a static test enforces this.

## Setup

```bat
py -3 -m perfin_store.setup --create "%LOCALAPPDATA%\PerFin\db\perfin.accdb" --base-currency USD
```

1. **Location check.** The path is checked first. Setup also refuses an existing file and any extension other than `.accdb`.
2. **Create an empty file.** The default engine `odbc` calls the ODBC installer API `SQLConfigDataSourceW` with `CREATE_DBV12="<path>" General` through `ctypes`; it has the same bitness as pyodbc [Unverified attribute]. The alternative `--engine adox` uses `ADOX.Catalog.Create` through PowerShell COM with `Microsoft.ACE.OLEDB.12.0` [Unverified]; the path is passed in an environment variable.
3. **Build the schema.** Setup runs `010` → `020` → `030` → `040`, then writes `contract_meta`. That table holds `schema_version=1.0.0`, `contract_version`, `base_currency`, `created_at`, `created_by`, `check_constraints`, `check_fallback` and `report_views`.
4. **Re-open.** Setup re-opens the file through the repository, which checks the schema version and validates the empty ledger.

**CHECK constraints and their fallback.** Access accepts CHECK only in ANSI-92 mode [Unverified]. Setup runs each CHECK separately. If Access rejects them, `contract_meta.check_constraints` becomes `absent` (or `partial`) and the documented fallback applies:

- the repository validates every rule itself before writing (money integrality and range in `money`/`codec`, enums and all cross-record rules through `perfin_contracts`);
- PerFin has no other write path.

The same applies to views: `report_views=absent|partial` means the views can be saved by hand or with `PerfinSetup.bas`, or the CSV export can be used.

**Migrations.** `perfin_store.migrations` reads `schema_version` whenever a database is opened:

| Database version | Result |
| --- | --- |
| Newer major | Refused |
| Newer minor | Refused (fail closed) |
| Older | Upgraded only through an explicit `MIGRATIONS` chain. There are no migrations yet, so an older database is refused. |

## Controlled writes

`perfin_store.repository.Repository` is the only write path. Each call:

1. validates the input `command` (or `staging_batch` / `ledger_bundle`) with `perfin_contracts.semantic.validate_document`;
2. opens **one database transaction**;
3. checks `expected_versions` (`E_STALE_VERSION`) and the business rules;
4. writes;
5. re-reads the whole ledger as a `ledger_bundle` and validates it with the contract's semantic rules;
6. writes `command_log` and `audit_log` (before/after JSON) in the same transaction, then commits.

What happens when a call does not succeed:

| Case | Database | `command_log` | Result |
| --- | --- | --- | --- |
| Rule failure | Rolled back; nothing changes | Not written | `rejected` |
| Replay (same `command_id`, or `commit_batch` for an already-committed file) | Rolled back | Not written | `replayed` with `E_IDEMPOTENT_REPLAY` |
| Engine failure | Rolled back | Not written | `StorageError` is raised; the contract has no storage error code (tracker item T6) |

Results are `command_result` documents. They are validated before they are returned.

The audit trail holds values. It is part of the protected ledger, never a diagnostic log (privacy boundary, "Logs and audit-log redaction"). PerFin writes no diagnostic log in 2b.

Minimal review CLI for 3a (prints the queue; each action is a contract command with `issued_by: cli:review`):

```bat
py -3 -m perfin_store review --db DB --batch b2026_07_alpha
py -3 -m perfin_store review --db DB --batch b2026_07_alpha --resolve 5=confirmed_distinct --approve 1,2,5 --reject 3 --reason "not mine" --commit
```

Other subcommands:

- `stage`
- `import-bundle` (the setup path for accounts and categories; see commands.md)
- `set-defaults`
- `command --file cmd.json`
- `export-reports`
- `export-bundle`
- `backup`
- `restore`

## Read-only reports

There are two ways to read the report tables.

**Views.** The `rpt_*` views in `040_report_views.sql` are for Excel/Power Query refresh. Refresh never writes back.

**CSV export.** `python -m perfin_store export-reports --db DB --out DIR --as-of YYYY-MM-DD` writes the same tables as CSV in the contract dialect:

- UTF-8 without BOM, comma separator, RFC 4180 minimal quoting, CRLF line ends;
- the exact header from `report_tables.json`;
- empty field = null, `TRUE`/`FALSE`, integer minor units.

Text columns get the privacy boundary's formula prefix (`'`). The tables exported are:

- `rpt_accounts`, `rpt_transactions`, `rpt_splits`, `rpt_card_status`, `rpt_statements`, `rpt_reconciliation`, `rpt_review_queue`;
- `rpt_card_terms`, `rpt_valuations`, `rpt_statement_buckets`.

The `rpt_payoff_*` and `rpt_net_worth_*` tables are produced by 3b/3c, not by the store.

The output directory gets the data-root location checks. Two differences between the views and the CSV:

- The views compute "as of" from `Date()`; the CSV export takes `--as-of`.
- `rpt_review_queue.error_codes` holds the raw `errors_json` in the view, because Access SQL cannot parse JSON. The CSV holds codes joined with `;`.

## Backup and restore

`python -m perfin_store backup --db DB --dest "%LOCALAPPDATA%\PerFin\backups"`:

1. **Quiescent only.** The backup is refused while `<name>.laccdb`/`.ldb` exists, or while Windows cannot open the file with no sharing (`CreateFileW`, share mode 0).
2. **Summary first.** The ledger summary is taken through the repository: balances, import history, statements, reconciliations, row counts and versions. The connection is then closed.
3. **Copy and verify.** The source is hashed, copied, and both are re-hashed. Any difference, or a lock appearing during the copy, aborts the backup and deletes the partial set.
4. **Manifest.** `manifest.json` lists each file's relative path, size and SHA-256, the PerFin, schema and contract versions, and the summary. The set is verified again after writing.
5. **Destination checks.** A destination inside a checkout is refused. Sync, network or redirected destinations need `--acknowledge-location`; use an encrypted container for anything that leaves the device.

`python -m perfin_store restore --set <set dir> --target <new path>.accdb`:

1. Every hash is verified **before anything is written**.
2. The manifest's `schema_version` and contract major are checked.
3. The database is copied to a **new** path and its hash is checked again.
4. The copy is opened through the repository, which repeats the version checks and the ledger validation.
5. The restored summary must equal the manifest's: balances, import history, statements, reconciliations, row counts and schema version. On any mismatch the restored copy is deleted.

Statement PDFs are never stored in Access: `statement.evidence_ref` is an opaque reference, and paths are refused. Originals stay in `statements\originals\`. 3a can pass them to `create_backup(extra_files=..., data_root=...)` so they are copied and hashed with the set.

## Windows acceptance (pending)

Run this on the Windows PC, from the repository root, with Office/ACE and pyodbc of the same bitness:

```bat
set PYTHONPATH=src
py -3 -m perfin_store envcheck
py -3 tests\store\windows_acceptance.py --workdir "%LOCALAPPDATA%\PerFin-acceptance"
```

The script uses synthetic data only. It creates a temporary `.accdb` outside the repository and records PASS/FAIL for each check:

- the environment;
- create/open and `schema_version`;
- whether CHECK constraints are present or the fallback applies;
- exact cents at ±922337203685477;
- atomic commit;
- rollback after an injected failure (on the third split insert);
- replay protection;
- a stale-version rejection;
- `rpt_*` views equal to the CSV export;
- backup refused while the database is open;
- backup with manifest;
- restore matching balances, import history and schema version.

Evidence is written to `<workdir>\run-<time>\acceptance-evidence.json`; attach it to the PR or tracker. The databases are deleted afterwards unless `--keep` is given. On Linux it prints `BLOCKED` and exits 2.

## Linux tests (what they prove)

```bash
python3 -B -W error -m unittest discover -s tests/store -v
```

These tests run the real creation scripts, the repository, reports, backup/restore and the CLI against **`tests/store/fake_access.py`, a TEST-ONLY in-memory fake** of the adapter. They prove **repository logic only, not Access/ACE behaviour.**

The fake models:

- the schema, executed from the real scripts;
- NOT NULL, keys, unique indexes and relationships;
- the strict parameter types (Decimal for CURRENCY, no Null in Yes/No);
- case-insensitive keys;
- snapshot transactions;
- injected failures;
- an optional JSON file with a `.laccdb` lock file.

The following are covered only by `windows_acceptance.py`: SQL dialect, driver type mapping, CHECK/view support, locking, file creation and real copy behaviour.
