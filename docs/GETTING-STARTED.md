# Getting started

PerFin uses SQLite as the default portable local store and generates Excel files. Access is an explicit optional native backend. Python performs deterministic imports, calculations and controlled writes. Keep the checkout and private data folder separate.

**SQLite works without Windows or Office.** Native Access/ACE and desktop Excel acceptance are separate release requirements; their pending status does not block portable development. Generated files and inspected formulas are not native Excel recalculation evidence.

## 1. Install the portable app

Use Python 3.10+ with SQLite 3.37+ (check `perfin envcheck` after installation).

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install .
perfin envcheck
```

SQLite uses Python's standard-library sqlite3. Workbook generation uses the
project's declared local Python dependencies; desktop Excel is not required to
generate XLSX files. Install `.[pdf]` for the optional local PDF parser, or
`.[test]` for the full synthetic development suite. A reviewed local wheelhouse
with `--no-index --find-links` supports offline installation.

For the optional Access backend, install `.[windows]` on compatible Windows with
matching Python/ACE/Office bitness, then use `perfin --backend access envcheck`.
Full Access is needed for design inspection. Native evidence remains pending.

Choose `%LOCALAPPDATA%\PerFin` or another local, nonsynced folder. Actual CSV/PDF statements, `.accdb` databases, generated workbooks, reports, commands, backups and logs must not be placed in this public checkout. Synced/network paths require explicit acknowledgment; checkout paths are refused.

## 2. Initialize synthetic accounts first

After installing the `perfin` command:

```bat
set PERFIN_DATA=%LOCALAPPDATA%\PerFin-synthetic
perfin --data-root "%PERFIN_DATA%" init --demo
perfin --data-root "%PERFIN_DATA%" gui
```

`--demo` creates synthetic checking/two-card accounts and categories. It does not connect to a bank or invent an import history. SQLite is selected for new roots and saved in perfin-data-dir.json. Existing Access roots are preserved; backend conflicts are refused. The GUI requires a local display; headless/cloud users use the CLI. Use a separate data root when starting with real data.

To onboard your own accounts, prepare a validated local `ledger_bundle` JSON with account IDs, opening dates/balances, currency and categories. The [contract examples](../contracts/examples/valid/ledger_household.json) show the document format; do not treat the synthetic numbers as your own. Then:

```bat
perfin --data-root "%PERFIN_DATA%" onboard C:\Private\accounts.json
```

## 3. Import, review, commit

Pick a profile whose encoding, column mapping, date format and sign convention actually match the file. Initially shipped profiles are **synthetic**; use a local custom JSON profile for a real export. [Profile extension guide](import/README.md).

```bat
perfin --data-root "%PERFIN_DATA%" import C:\Private\statement.csv --account ACCOUNT_ID --profile C:\Private\profile.json
perfin --data-root "%PERFIN_DATA%" preview BATCH_ID
perfin --data-root "%PERFIN_DATA%" review BATCH_ID --approve 1,2 --reject 3 --reason "duplicate"
perfin --data-root "%PERFIN_DATA%" commit BATCH_ID
perfin --data-root "%PERFIN_DATA%" refresh --as-of 2026-07-31
```

Replace `ACCOUNT_ID`, `BATCH_ID`, row numbers and dates with values shown by your actual preview. Import only stages data. Review signs, dates, category suggestions, ambiguous transfers, duplicate candidates and statement totals before approval. Parse errors cannot become silently valid amounts. A confirmed distinct duplicate is an explicit decision:

```bat
perfin --data-root "%PERFIN_DATA%" review BATCH_ID --resolve 4=confirmed_distinct
```

A card payment is a transfer between checking and the card; it must not be counted as a new expense. Reconciliation uses opening balance + posted activity = closing balance. Use the app command workflow described in the [core runbook](runbooks/core/) to link transfers and record/reconcile statements.

## 4. Excel, payoff and net worth

`refresh` writes local reports and the core workbook. Rebuild/refresh explicitly after changes; Excel views are not a second editable ledger. For interactive Power Query/VBA refresh, install the exported components as described in the [Excel guide](excel/README.md), then complete the [Windows checklist](excel/windows-checklist.md).

Build the statements module directly from the selected local ledger:

```bat
perfin --data-root "%PERFIN_DATA%" statements --as-of 2026-07-31 --period-start 2026-07-01
```

Install and register the payoff module from a supported local scenario (the repository includes `fixtures/payoff/scenario.synthetic.json` for practice):

```bat
python -m perfin_excel_payoff install C:\Private\scenario.json --data-root "%PERFIN_DATA%"
python -m perfin_excel_payoff recompute "%PERFIN_DATA%\workbooks\excel_payoff\PerFin-Payoff.xlsx" --data-root "%PERFIN_DATA%"
```

The install command places the workbook and manifest together under `workbooks/excel_payoff`; refresh the core registry to show it in the launcher. Close the workbook before recomputing. Saved scenario parameters are queued through `save-command`, then applied by `perfin --data-root "%PERFIN_DATA%" process-outbox`; this does not rewrite historical transactions.

For a plan drawn directly from the local ledger:

```bat
perfin --data-root "%PERFIN_DATA%" payoff-current --as-of 2026-07-31 --monthly-cents 60000
perfin --data-root "%PERFIN_DATA%" refresh --as-of 2026-07-31
```

This requires a balanced latest statement and supported single-bucket fixed-APR card terms; subsequent posted activity is included. Missing, promotional, deferred-interest or multi-bucket terms are refused in this current-balance adapter. Review the generated scenario before relying on it. To save/build your own supported scenario through the same application path, use `perfin --data-root "%PERFIN_DATA%" payoff C:\Private\scenario.json`. Existing workbooks require explicit `--replace`; close Excel first.

The payoff and statements workbooks are separate modules. Their runbooks give complete commands:

- [Payoff workbook](runbooks/payoff/): edit scenario inputs, explicitly recompute, compare largest-balance-first, snowball, avalanche and near-APR strategies. Check feasibility, remaining balances and the disclosed monthly approximation before using a plan.
- [Personal statements workbook](runbooks/statements/): dated assets/liabilities, income/expense, cash flow and net-worth bridge. Valuations use explicit dates/sources and write through validated commands; missing/stale values remain visible. The current ledger contract refuses foreign-currency accounts; supplying an FX rate does not enable unsupported currencies.
- [PDF import](runbooks/pdf/): `perfin --data-root "%PERFIN_DATA%" import-pdf C:\Private\statement.pdf --account ACCOUNT_ID --layout perfin.synthetic.statement.v1`. Only the declared synthetic text layout is currently supported; there is no cloud OCR fallback. Extraction errors and unreconciled totals require correction/review before any commit. Keep the original file private and unchanged.

## 5. Backup, restore and update

SQLite backup uses the online snapshot API so committed WAL data is included. Close Access/Excel connections when backing up the optional Access backend. Use a new restore target so an existing database is never silently overwritten:

```bat
perfin --data-root "%PERFIN_DATA%" backup
perfin --data-root "%PERFIN_DATA%" restore BACKUP_SET --target db/perfin-restored.sqlite
```

Restore creates a new file and does not silently switch the active database. Access restore targets use `.accdb`; SQLite targets use `.sqlite`, `.sqlite3` or `.db`. A backup set includes hashes and metadata. Restore validates integrity and checks balances/history/schema through the backend. Keep a backup before a code upgrade. Newer/incompatible database schemas are refused; do not bypass schema checks or edit the database directly. Restore the prior backup/code pair if an upgrade cannot be completed.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| ACE/ODBC unavailable | Run environment check; align Python/Office/ACE bitness. A Linux fake test does not install ACE. |
| Location refused | Choose a local folder outside the checkout and sync roots. Do not disable privacy guards. |
| Unknown CSV layout | Create an explicit profile; do not guess dates, signs or encodings. |
| Duplicate or unresolved row | Inspect preview and resolve/reject deliberately; committing retries is not approval. |
| Stale/missing Excel data | Refresh from current reports and inspect status; stale figures are not current success. |
| PDF scanned/encrypted/unsupported | Use a known CSV export or separately validated local extraction workflow; there is no cloud fallback. |
| Payoff unsupported/infeasible | Correct card terms or budget; a truncated schedule is not debt-free. |
| Net-worth totals incomplete | Supply missing valuations and resolve overlapping assets rather than adding totals twice. Foreign currencies are refused until the ledger contract supports them; FX inputs do not bypass this restriction. |

For a complete synthetic demo on Linux/cloud, run `python scripts/core/portable_demo.py --out /tmp/perfin-demo-new`; see [demo instructions](runbooks/portable-demo.md). For the full schema, use the [relationship explorer](database/model.html). For audit-preserving archives, see [portability](database/portability.md); `snapshot` is only a ledger exchange, not a full-history backup. For developers, run `python scripts/release/check_all.py --offline`. For an actual Windows release, follow [release verification](../release/README.md). No paid hosted CI is required.
