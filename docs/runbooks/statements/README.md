# Statements workbook

Install PerFin and keep the data root outside the checkout and sync folders. `perfin_excel_statements` creates a separate `PerFin-Statements.xlsx`, registered with the existing core launcher. It never edits the core or payoff workbook. Generated financial workbooks stay in the private data root.

1. Export a current `ledger_bundle` from Access using the core workflow.
2. Create or refresh the statements workbook:

   ```powershell
   python -m perfin_excel_statements build --bundle "$env:LOCALAPPDATA\PerFin\exports\ledger.json" --data-root "$env:LOCALAPPDATA\PerFin" --as-of 2026-02-28 --period-start 2026-02-01
   ```

   The output is `workbooks\excel_statements\PerFin-Statements.xlsx`. A manifest beside it lets the core registry launch it. Optional `--options` accepts a JSON object with `liability_view`, `stale_days` and `inclusion_groups`; all referenced IDs must be in the bundle.

3. Open Summary, Accounts, Income, Cash flow and Bridge. Summary shows the period and coverage. Missing inputs and stale values remain visible. The balance sheet shows ledger amounts alongside included values, valuation dates/source and separate ownership/legal liability shares. Tables are protected read-only views, not a second ledger. Protection prevents accidental edits and is not encryption.
4. To record a new dated asset estimate, fill a row on **Valuations**: stable account ID, date, value in currency units (at most two decimals), currency, source, method, an optional valuation ID (blank creates a stable account/date ID), blank existing version, and **Queue=Yes**. Methods: `statement`, `market_close`, `appraisal`, `automated_estimate`, `owner_estimate`.
5. Close Excel and explicitly queue selected rows:

   ```powershell
   python -m perfin_excel_statements queue-valuations --workbook "$env:LOCALAPPDATA\PerFin\workbooks\excel_statements\PerFin-Statements.xlsx" --data-root "$env:LOCALAPPDATA\PerFin"
   ```

   Every selected row is validated before any is queued. Formulas, fractional cents and malformed commands are rejected. The command queue contains private data. Unchanged submissions use stable command IDs; retries do not duplicate a valuation. This step does not execute commands or change Access. Use the core command executor to review/apply them, then export the updated bundle and rerun build.
6. Different dates with new IDs preserve valuation history. Blank IDs are stable for one account/date. Correcting an existing valuation ID requires its current `row_version` in Existing version; stale writes are rejected by Access. Never use both account totals and holdings as included accounts; configure explicit overlap groups and one valuation basis.

Rebuild is explicit and replaces the snapshot workbook, including unsent input rows. Queue or save unsent requests before rebuilding. The workbook has no embedded network calls, Excel add-ins, bank connection, macro execution or payment execution. The local Python engine recomputes statements; workbook totals and chart use current included values when Excel recalculates. Opening an old file does not refresh Access automatically.

## Verification status

Executed: exact engine examples, workbook ZIP/XML inspection, source text protection, local-path refusal, strict valuation parsing/queue retries, registry discovery and changed-valuation rebuild tests. Reproduction source lives in `excel/statements/perfin_excel_statements` and uses the project's installed openpyxl dependency.

Pending on declared Windows/Office: desktop open/recalculate and chart rendering; worksheet protection/filter behavior; registered launch; queue a valid valuation, apply through Access, export and rebuild; verify new totals against the engine; exercise backup/restore with preserved valuation history and network blocked. A generated workbook and Linux tests do not establish these runtime checks.
