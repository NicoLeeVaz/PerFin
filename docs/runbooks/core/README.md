# Local finance workflow

Install the project into Python 3.10+ on Linux, macOS or Windows. New data roots use the real local SQLite backend (SQLite 3.37+); `perfin envcheck` reports its version and readiness. Access remains an explicit optional backend: `perfin --backend access envcheck` checks Windows ACE/Office. No ordinary runtime operation needs internet. Initial installation may use a separately prepared local wheelhouse; release instructions explain offline installation.

`perfin --data-root /private/path/PerFin init` creates the guarded layout, `db/perfin.sqlite` and default income/expense categories. On Windows use `%LOCALAPPDATA%\PerFin` as the data root. `perfin --backend access --data-root <separate-root> init` explicitly creates an Access database on a supported Windows installation. `init --demo` also creates synthetic accounts `chk:main`, `card:a`, `card:b`; never mix a demo root and real records. Existing databases are never overwritten. New roots record their backend and database path in `perfin-data-dir.json`. Existing Access roots retain Access automatically; a conflicting `--backend` choice or a root containing both default database files is refused. Use separate roots when evaluating different backends, and explicit portability tooling for migration. `perfin gui` launches an offline Tkinter window for file selection, preview, row decisions, commit, transfer linking, refresh and backup.

Money arguments use integer cents and canonical signs: positive increases an asset or reduces a liability; negative reduces an asset or increases debt.

```
perfin account-add chk:bank --name "Checking" --kind asset --class checking --opening-cents 100000 --opening-date 2026-01-01
perfin profile-create my-bank --account-class checking --date-column Date --description-column Description --amount-column Amount --date-format MM/DD/YYYY --sign as_is
perfin import statement.csv --account chk:bank --profile <data-root>/config/my-bank.json
perfin preview <batch-id>
perfin review <batch-id> --approve 1,2 --reject 3 --reason "Incorrect row"
perfin commit <batch-id>
perfin refresh
perfin backup
```

Profiles are explicit mappings, never guessed. Built-in profiles are synthetic, not verified against any bank. Mapping unknown/malformed values produces review errors, never zero amounts. `review --resolve 4=confirmed_distinct` resolves an ambiguous duplicate before approval. Exact same-file replay displays the existing batch and leaves balances untouched. Rolled-back same-file reimport is deliberately refused in schema 1.0: retain history and use explicit correction transactions; changing a hash to bypass replay is unsupported.

Use `link-transfer <checking-payment-txn> <card-payment-txn>` after inspecting both legs. The confirmed link replaces expense/income splits, so a payment is not double-counted as spending. Use `statement-add july --account card:a --start 2026-07-01 --end 2026-07-31 --opening-cents -20000 --closing-cents -15000 --due-date 2026-08-25 --minimum-cents 2500`, then `reconcile july --transactions txn1,txn2`. Reconciliation validates the selected transaction set and difference. Rerunning reconciliation uses the existing row version. Complex corrections and valuations can use `command file.json` with the frozen command contract; old versions fail rather than being silently refreshed.

`process-outbox` promotes validated workbook drafts, then executes explicit commands. Repeating the same processed payload/actor/version request (even with a new retry timestamp) dequeues it idempotently; reusing its UUID for different content is refused. Commands without required optimistic versions are rejected. The CLI review path obtains the current batch version at the user's explicit action; it never modifies a stale workbook command to force acceptance. Stored staging preserves raw rows, fingerprint, original duplicate evidence, running balance and transfer proposal via its immutable audited staging payload.

`refresh` writes local report CSVs and reproduces the read-only `workbooks/PerFin-Core.xlsx` snapshot. Close Excel first. The snapshot is an explicit local refresh, not a claim that Power Query/VBA has run. Saved scenario parameters are stored in the same selected database: audited `save_payoff_scenario` command payloads plus a metadata pointer to the latest accepted command. They never change ledger balances.

`import-pdf file.pdf --account card:a` runs the registered local extractor, persists review staging and private extraction provenance under `staging/`. Only tested synthetic layouts are supported initially; unreadable, ambiguous or unreconciled extraction cannot auto-approve. No cloud fallback is available.

SQLite backups use a coherent database snapshot and can run with another connection open; `perfin backup` verifies its manifest. `perfin restore <backup-set> --target db/restored.sqlite` verifies checksums and opens a new file; it does not overwrite or activate the restored database. Access backup still requires every database connection and Excel/Access session closed, and its restore target must end in `.accdb`. A backup from one backend is not a migration to the other. Inspect the restored summary before choosing it for recovery. Original statement PDFs, sources and workbook data belong outside Git and sync folders.

## Verification boundary

`python -m unittest discover -s tests/integration_core -q` includes real on-disk SQLite CLI and two-cycle tests, plus the earlier explicitly test-only fake checks. SQLite tests exercise initialization, selection safety, six account statements, exact report totals, repeated imports, transfer links, scenario persistence, generated workbook files and backup/restore. `python tests/integration_core/windows_acceptance.py --workdir <new-local-directory>` executes the same scenario on real Access and writes evidence. That native harness exits 2 (BLOCKED) on Linux. Desktop Excel/Power Query/VBA, Office privacy settings and real ACE behavior are release requirements for those native integrations, not blockers for SQLite development or headless workbook generation. Python generation and file validation do not prove desktop recalculation or macro execution. Cloud development uses synthetic data only; user financial records remain in their private local root.

## Optional modules

`perfin payoff scenario.json` computes the approved scenario contract, saves parameters in the selected database, and builds `workbooks/excel_payoff/PerFin-Payoff.xlsx`. Use `--replace` only to intentionally replace an existing scenario workbook. To edit visible inputs, close Excel then run `python -m perfin_excel_payoff recompute <workbook> --data-root <root>`; `save-command` queues the revised parameters and `perfin process-outbox` records them. No historical ledger balances change.

`perfin statements --as-of 2026-12-31 --period-start 2026-01-01` reads the authoritative ledger snapshot and builds `workbooks/excel_statements/PerFin-Statements.xlsx`. Optional `--options options.json` holds explicit inclusion groups/liability choices. Queue valuation entries before rebuilding: `python -m perfin_excel_statements queue-valuations --workbook <workbook> --data-root <root>`, then `perfin process-outbox`. Run `perfin refresh` to show registered modules in the core launcher. Unrun desktop calculations remain pending, even when Python-generated workbook contents validate.

`perfin payoff-current --as-of 2026-12-31 --monthly-cents 60000` constructs a scenario from posted card balances, reconciled statements and supported current card terms. Missing/unsupported terms are refused, not guessed. `--replace` explicitly regenerates an existing payoff workbook.

### Excel review concurrency

Application refresh also writes **perfin_batch_versions.csv**, a local auxiliary table separate from frozen `rpt_*` contracts. Core templates contain its hidden, protected Settings table; the generated Power Query manifest installs the corresponding local file query into `.xlsm` workbooks. `PerFin_Refresh` refreshes this table before review. Approve/reject macros emit the batch version actually displayed in that snapshot, or refuse if it is missing/invalid. The repository rejects stale versions after another change. Run `perfin refresh` to regenerate source reports, then `PerFin_Refresh` in the macro workbook after processing commands; no command silently adopts a newer version. Existing old macro workbooks require reinstalling the updated source queries/VBA and table from the current template once. Python validates CSV/template contents; VBA compilation and Power Query runtime remain Windows checks.
