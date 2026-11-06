# SQLite backup and future Access portability

SQLite is the runnable cross-platform store. The same 18 canonical tables,
repository commands and report contracts remain the foundation for a later
Access deployment. Matching table names is necessary but not sufficient:
types, collations, constraints, query syntax, transactions and driver behavior
must also match.

## Use a backup for recovery; an archive for deliberate migration

| Output | Preserves | Intended use |
| --- | --- | --- |
| SQLite backup set | Complete SQLite database, including pending staging rows, audit and command logs, metadata and versions | Recover the same backend to a new path |
| Full-table JSON archive | All 18 tables and every column, schema/type metadata, row versions, logs, pending staging, and a summary | Inspect a portable representation; restore into a new SQLite database; basis for a future validated Access importer |
| Contract `ledger_bundle` | Financial ledger exchange document | Exchange supported ledger data; **not** a complete history backup |

The archive and backup contain private financial history when used with real
data. Keep them outside Git and sync folders unless deliberately acknowledged.
Cloud demonstrations use synthetic data only. SHA-256 checks detect accidental
changes, not a malicious party who can replace both data and its manifest.
Use operating-system permissions and encrypted storage for private backups.
Original statements/PDFs remain external; back up those private files separately.

## Coherent backup and restore

`perfin_store.sqlite_backup.create_backup(db_path, backup_root)` uses Python's
[`Connection.backup`](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup)
and the [SQLite Online Backup API](https://www.sqlite.org/backup.html).
It captures committed WAL pages through SQLite, not by copying a live database
file. A read-only source connection excludes uncommitted changes. The completed
snapshot is switched to DELETE journal mode so the backup set needs no WAL/SHM
sidecars. Source journal mode is unchanged.

Each unique backup directory contains `snapshot.sqlite3` and `manifest.json`.
The manifest's summary is computed from the snapshot itself. An optional caller
summary is only a consistency assertion; a stale assertion refuses the backup.
Creation verifies file hash/size, SQLite integrity, foreign keys, version support,
ledger validity and summary. Exceptions remove the incomplete backup set.

Restore verifies the set before creating a new target, copies the verified
self-contained snapshot, verifies its exact SHA-256 before opening it, and checks
integrity and summary again. It never overwrites an existing file or associated
SQLite sidecars. A failed restore removes only its newly created target. New
files use owner-only modes where the operating system supports them.

New database creation, backup restore and archive import all refuse an existing
target or any `-wal`, `-shm` or `-journal` sidecar, including dangling symbolic
links. This preserves recovery material when the main database file is missing;
SQLite must not consume it while initializing a replacement. Choose a different
path and recover the old files deliberately. Opening a repository also refuses
newer contract minor versions, consistently with archive import. Same-minor
patch versions remain readable under the existing contract policy.

Python API:

```python
from perfin_store import sqlite_backup

saved = sqlite_backup.create_backup("/private/perfin.sqlite", "/private/backups")
assert sqlite_backup.verify_backup(saved) == []
sqlite_backup.restore_backup(saved, "/private/restored.sqlite")
```

The application CLI selects this implementation for SQLite. The existing
Access backup path remains separate and requires its own native verification.

## Full-table archive commands

From an installed package, or a checkout with `PYTHONPATH=src`:

```sh
python -m perfin_store.portability export --db /private/perfin.sqlite --out /private/full-history.json
python -m perfin_store.portability verify --archive /private/full-history.json
python -m perfin_store.portability import --archive /private/full-history.json --target /private/ported.sqlite
```

Export reads all tables and the summary under one read transaction. Records are
ordered by canonical primary keys and encoded with integer cents, JSON booleans,
ISO calendar dates and UTC timestamps. Archive version 1 records the canonical
schema and SHA-256 of the complete payload. Existing archive destinations are
refused.

Import supports **new SQLite databases only**. It checks the archive hash,
supported versions, exact table/column structure and scalar types before writing.
All table inserts run in one transaction with foreign keys deferred rather than
disabled, allowing forward references and cycles. It validates foreign keys,
ledger semantics, every table row and the summary before committing. Errors roll
back and remove the newly created database. It neither combines histories nor
replays commands nor invents replacement IDs.

`verify` checks hashes, structure and scalar types. Relational and full ledger
validation occurs during import. Do not interpret `verify` alone as proof that an
archive can be imported.

## Mapping to Access

| Canonical value | SQLite | Access target | Port verification |
| --- | --- | --- | --- |
| Integer minor units | INTEGER, contract bounds | CURRENCY containing integer cents via Decimal | Exact positive/negative bounds, no float conversion |
| IDs and bounded text | TEXT with explicit bounded lengths; ASCII NOCASE baseline | TEXT(n), ACE collation | ASCII and non-ASCII comparisons; SQLite NOCASE is not all ACE locale behavior |
| JSON/log text | TEXT | MEMO | Preserve every byte/string and full history |
| Calendar dates | ISO text through adapter | DATETIME at midnight | No timezone or date-part drift |
| UTC timestamps | ISO text through adapter | DATETIME bound as naive UTC | Preserve second precision and chronology via versions |
| Booleans | INTEGER constrained to 0/1 | YESNO | Null refused, correct driver representation |
| Foreign keys/uniqueness | Real constraints, enforcement enabled per connection | Access relationships/indexes | Constraint refusal and rollback evidence |
| Reports | Canonical Python → CSV/workbook outputs | Access saved queries plus Python outputs | Totals, nulls, date filters and rounding match |

There is **no automatic Access archive importer in this release**. Do not rename
a `.sqlite` file to `.accdb`. A future importer must map scalar values through the
Access adapter, preserve every history table and handle dependency order under
ACE's actual constraint rules. It must compare full tables, balances, import
history and report outputs on a synthetic target before any private migration.
SQLite import success does not establish ACE behavior.

## Executed checks and remaining native requirement

The real-file SQLite tests cover live WAL backup, exclusion of uncommitted writes,
full-history restore, hash/manifest tampering, unsafe paths, refusal to overwrite,
failed-restore cleanup, all-table archive roundtrip, forward self-references,
reversals, scalar validation and failed relational import rollback.

Run `python -B -W error -m unittest discover -s tests/portability -v`.
These are real SQLite checks; no fake adapter is used. Native Access/Excel checks
remain release requirements for those optional platforms and do not block
SQLite development.
