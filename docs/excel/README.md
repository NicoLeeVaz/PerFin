# PerFin core Excel shell (task 2c)

Task 2c ([#7](https://github.com/NicoLeeVaz/PerFin/issues/7)), part of tracker [#1](https://github.com/NicoLeeVaz/PerFin/issues/1). Built against contract **1.0.0** ([docs/contracts.md](../contracts.md)) and the 1c [privacy boundary](../privacy/privacy-boundary.md).

**Status:** source, generator, Power Query text, VBA text and Linux tests are complete. **Desktop Excel open/recalculate has not been run** (no Windows or Excel in the build container), so that acceptance gate is **blocked/pending**. Use the [Windows checklist](windows-checklist.md) to run it. Statements about Excel, Power Query or VBA behaviour that could not be checked here are marked **[Unverified]**.

## What the workbook is

The core workbook is a **read-only view** of the `rpt_*` report tables. Access (task 2b) is the only ledger. The workbook:

- refreshes six report tables from local CSV files with Power Query. Refresh never writes back.
- shows these views:
  - account and card summaries;
  - transaction filters;
  - the import-review queue;
  - statement reconciliation;
  - the data-as-of date;
  - a refresh status banner on every sheet.
- changes nothing directly. Review actions become contract `command` documents that are validated and placed in `<data root>\commands\outbox`.
- lists separate module workbooks (payoff, statements) and opens each module's **own** file.

```
<data root>\reports\rpt_*.csv  --Power Query (read-only)-->  PerFin-Core.xlsm  (protected views)
                                                                  |
         Review sheet macro --> commands\drafts\<uuid>.json --validator--> commands\outbox\  --> repository (2b/3a)
         Modules sheet macro --> opens <modules dir>\<module>\<own workbook>.xlsm
```

## Files

| Path | Purpose |
| --- | --- |
| `excel/core/perfin_excel_core/workbook.py` | Generates the workbook with openpyxl: sheets, tables, formulas, defined names, protection. |
| `excel/core/perfin_excel_core/reports.py` | Strict reader for the contract CSV dialect plus derived views. It mirrors the M code so Linux tests can check the same rules. |
| `excel/core/perfin_excel_core/powerquery.py` → `excel/core/powerquery/*.pq` | M source, **generated from `report_tables.json`**, plus `queries.txt` (install and refresh order). A test fails if the committed files drift. |
| `excel/core/vba/*.bas` | Exported VBA text: `PerFinCore`, `PerFinCommands`, `PerFinLauncher`, `PerFinSetup`, `PerFinSelfTest`. |
| `excel/core/perfin_excel_core/commands.py` | Builds and validates `approve_rows`/`reject_rows` with `perfin_contracts`, writes to the outbox, and promotes VBA drafts. |
| `excel/core/perfin_excel_core/registry.py` | Module registry and launcher. Validates `module_manifest.json` with the contract (`writes_ledger: false`). |
| `excel/core/perfin_excel_core/offline_check.py` | Static offline-compatibility checker for workbooks, M text and VBA text. |
| `excel/core/requirements.txt` | `openpyxl==3.1.5` and `et-xmlfile==2.0.0`, hash-pinned (1b policy). |
| `fixtures/excel_core/` | Synthetic report CSVs, contract documents, mock module manifests and a VBA-shaped command draft. See its README. |
| `tests/excel_core/` | Linux tests, including a small formula evaluator for the subset of Excel formulas the workbook uses. |

The contract validator (`contracts/python/perfin_contracts`) and the 1c helpers (`needs_formula_escape`, `evaluate_data_dir` from `config/privacy/perfin_privacy_checks.py`) are imported from the checkout, not copied. Packaging for a release belongs to 3a.

## Build and check (Linux or Windows)

```bash
python3 -m pip install --require-hashes -r excel/core/requirements.txt   # once, after review
export PYTHONPATH=excel/core                                             # Windows: set PYTHONPATH=excel\core
python3 -m perfin_excel_core build --out PerFin-Core.xlsx                # empty template
python3 -m perfin_excel_core check PerFin-Core.xlsx --vba excel/core/vba --powerquery excel/core/powerquery
python3 -m perfin_excel_core powerquery --out excel/core/powerquery     # regenerate M after a contract change
python3 -B -W error -m unittest discover -s tests/excel_core -v
```

A synthetic **snapshot** build fills the tables with exactly what a refresh of a report folder produces. The tests use it, and it is useful for a quick look:

```bash
python3 -m perfin_excel_core build --out /tmp/snap.xlsx --reports fixtures/excel_core/reports --checked-at 2026-07-02T09:30:00
```

**No workbook binary is committed.** The template is fully reproducible from source. The tests build it twice and compare cell values, types, formats, formulas, tables, defined names, protection, conditional formats, validations and hyperlinks. Byte equality is not required. A populated workbook belongs in `<data root>\workbooks\`, never in the repository.

openpyxl 3.1.5 (the version importable in the build container) writes `.xlsx` only. It cannot create Power Query queries or embed VBA. Both are added on Windows in a documented one-time step (next section).

## Turning the template into PerFin-Core.xlsm (Windows, one time)

Full steps and expected results are in the [Windows checklist](windows-checklist.md). In short:

1. Open the generated `PerFin-Core.xlsx` in desktop Excel. In the VBA editor (Alt+F11), use **File › Import File…** for each `excel/core/vba/*.bas`. Run **Debug › Compile VBAProject**.
2. Save as **Excel Macro-Enabled Workbook** `PerFin-Core.xlsm` in `<data root>\workbooks\`.
3. Put the data root in **Settings!B4** and run macro **PerFin_InstallQueries**. Point it at `excel\core\powerquery`. The macro:
   - adds every query listed in `queries.txt`;
   - saves all formulas;
   - replaces each generated placeholder table with a Power Query table of the same name in the same place;
   - restores the formulas. Deleting a table breaks structured references, hence the save and restore. [Unverified]
4. Run **PerFin_Refresh**. Run **PerFin_SelfTest** against the synthetic data root.

A manual fallback for step 3 is in the checklist: Data › Get Data › Blank Query, paste the M, then Close & Load To an existing table.

## Workbook layout

| Sheet | Shows | Tables (Power Query load targets) |
| --- | --- | --- |
| Home | Status banner, data-as-of, key figures, navigation links, read-only notice | — |
| Status | Overall status, oldest data-as-of, last refresh, problem count, as-of consistency, days since refresh | `perfin_refresh_status` |
| Accounts | Total assets, total owed (positive), net ledger balance, card share, sign check | `rpt_accounts` |
| Cards | Current owed, statement owed, minimum due, payments, unpaid, unknown limits, utilization (known limits only), next due date | `rpt_card_status` |
| Transactions | Filter inputs (account, from, to, description contains) and matching count, money in, money out, net change, unreconciled count. Table filter buttons also work. | `rpt_transactions` |
| Review | Queue counts (awaiting, approved, rejected, errors, possible duplicates), the drafts folder and the command entry point. Rows with errors or possible duplicates are highlighted. | `rpt_review_queue` |
| Reconciliation | Statements, balanced vs open, non-zero differences, unreconciled items and their net amount, opening balances | `perfin_statement_recon`, `perfin_unreconciled_items` |
| Modules | Registered, launchable and invalid module counts | `perfin_modules` |
| Settings | Data root, stale-after days, modules folder (unlocked inputs), contract and shell versions | — |

`rpt_statements` and `rpt_reconciliation` are connection-only queries that feed the two reconciliation tables. Summary cells have stable defined names (`PerFin_TotalAssets`, `PerFin_Status`, `PerFin_DataAsOf` and others), which the self-test macro and the tests use.

### Money, sign and text rules

- **Money.** Table cells hold **integer minor units** exactly as exported. Only the summary display formulas divide by 100 (`…/100`, format `#,##0.00`).
- **Liabilities.** These are shown as positive owed amounts via `display_balance_minor`. The `*_display_minor` columns of `perfin_statement_recon` apply the same rule. A refresh fails if `display_balance_minor` is not `ledger_balance_minor` for an asset or `−ledger_balance_minor` for a liability.
- **Text.**
  - Text columns (`id`, `text`, `enum`, `currency`, `decimal_string`) stay text. Rates are never converted to binary floats.
  - The generator writes text cells as string cells with the `@` format. A value for which 1c's `needs_formula_escape` is true also gets Excel's quote prefix (`quotePrefix`, the stored form of the leading apostrophe). Such values start with `= + - @`, TAB, CR, LF or a full-width trigger, including after leading spaces.
  - The cell value itself is unchanged. In Power Query these columns are typed `text`, and loaded query values are not evaluated as formulas [Unverified; checklist W8].
  - The checker fails any trigger-text cell without the prefix.
- **Dates.** Dates are built from ISO parts with `#date(...)`. Integers are parsed with the `en-US` culture, so Windows regional settings do not change values [Unverified; checklist W18].

### Refresh status: failures are never shown as old success

- **Per-source status.** Each source gets a row in `perfin_refresh_status`. Its status is `OK`, `MISSING`, `BAD_HEADER` (header not exactly the contract), `INVALID` (BOM, extra field, bad type, money out of bound, sign rule) or `STALE`.
  - A source is `STALE` when its file, or its as-of date, is more than *stale days* (Settings, default 7) older than the refresh.
- **Invalid sources load nothing.** A source that fails loads **no rows**. The M code raises an error for the whole query instead of loading partial rows or error cells. `PerFin_Refresh` also clears any table whose refresh failed, so Excel cannot keep showing the previous rows.
- **Banner.** The banner on every sheet (`PerFin_Status`) shows the first of these that applies:
  - `NOT REFRESHED`;
  - `ERROR: n of 6 report sources are missing, invalid or stale …`;
  - `STALE: last refresh is more than N days old …`, computed with `TODAY()`, so a workbook left unrefreshed turns stale by itself;
  - `ERROR: report sources have different as-of dates`;
  - otherwise `OK`.
  - Red or green conditional formatting marks the result.
- **Data as of.** This is the oldest `balance_as_of`/`as_of` among the sources.

### Protection is not security

All sheets are protected and the workbook structure is locked, with **no password**. This is a UX guard against typing into report tables and building a second, editable ledger. It is **not a security control and not encryption**: the data stays readable, and anyone can unprotect it. Filtering stays enabled. Only the transaction filter inputs and the Settings inputs are unlocked. `PerFin_Refresh` unprotects the sheets, refreshes and protects them again, because query tables cannot refresh on a protected sheet [Unverified].

## Writes only through validated commands

The workbook never writes the ledger. The repository (2b/3a) is not implemented here.

1. **VBA draft.** Select rows of `rpt_review_queue` and run `PerFin_ApproveSelectedRows` or `PerFin_RejectSelectedRows`. The macro:
   - checks the batch id, the row numbers and that all rows come from one batch;
   - refuses to approve rows with errors or unresolved possible duplicates, matching the repository's `E_ROW_UNRESOLVED`/`E_DUPLICATE_UNRESOLVED`;
   - asks for a 1–120 character reason when rejecting;
   - writes a one-line, ASCII-only JSON draft (`\u` escapes) to `<data root>\commands\drafts\<uuid>.json`. The UUID comes from `CoCreateGuid` and `issued_at` comes from `GetSystemTime` (UTC).
2. **Validation.** `python -m perfin_excel_core command promote --data-root <root>` runs the 1c location check on the data root, which refuses a Git checkout and blocks unacknowledged sync or network folders. It then validates each draft with `perfin_contracts.validate_document`. Valid drafts move to `commands\outbox\`. Invalid ones move to `commands\rejected\` with an `.errors.json` file. Files are never overwritten.
3. **Python path.** `python -m perfin_excel_core command approve|reject --data-root … --batch-id … --rows 1,4 [--reason …] [--batch-version N]` builds, validates and writes straight to the outbox. With `--batch-version 1`, the built document is identical to `contracts/examples/valid/command_approve_rows.json`.

The outbox and drafts are inside the user's data root and never in the repository; the tests check that a root inside the checkout is refused.

## Module interface (for 4a/4b and later modules)

- **Layout.** `<modules dir>\<module_dir>\module_manifest.json` plus that module's own workbook. The default modules dir is `<data root>\workbooks`, or Settings!B6.
- **Registry.** `python -m perfin_excel_core registry --modules <dir> --out <data root>\reports\perfin_modules.csv` scans one level deep, sorts by `module_id` and validates each manifest with the contract. An entry is **OK and launchable** only if all of these hold:
  - the manifest validates (`writes_ledger: false`, supported contract range);
  - `module_kind` is `excel_workbook`;
  - `workbook_file` exists in the module folder;
  - `workbook_file` is not `PerFin-Core.xlsx`/`.xlsm`;
  - no other folder declares the same `module_id`.
  - Otherwise the entry is listed as `INVALID` or `MISSING_FILE` with a reason.
- **Launch.** `PerFin_LaunchModule` (VBA) or `registry.launch()` (Python, with an injectable opener; Windows default `os.startfile`) opens **only** that module's own workbook. The VBA opens it with `UpdateLinks:=0` and checks plain names and a local path first.
- **Separation.** Module agents never edit the core workbook or its generator, and the core never writes module workbooks (tested). To add a module: ship a folder with a valid manifest and workbook, then re-run the registry export and refresh.

## Offline-compatibility checker

`python -m perfin_excel_core check <workbook> [--vba DIR] [--powerquery DIR]` exits 1 on any ERROR. It inspects:

| Area | What it flags |
| --- | --- |
| Workbook package | External workbook links (`xl/externalLinks`, `[n]Sheet!` or `[file.xlsx]` references); web add-in, ActiveX and OLE parts; a VBA project inside an `.xlsx` |
| Data connections (`xl/connections.xml`) | Any connection except the Power Query workbook provider (`Microsoft.Mashup.OleDb.1`, `$Workbook$`) or a local `.accdb`/`.mdb` via ACE. Web queries, ODBC/SQL servers and UNC paths are flagged. |
| Embedded Power Query | Decodes the DataMashup part (customXml, per the [MS-QDEFF] layout) and checks its M |
| M text (`.pq` files and embedded) | Anything outside the allow-list: `File.Contents`, `Folder.Files`/`Contents`, `Access.Database`, `Excel.CurrentWorkbook`, and the `Csv`/`Json`/`Xml.Document` parsers. Web, OData, SharePoint, SQL, ODBC, OLE DB, Python/R and `Expression.Evaluate` are named explicitly, as are URL and UNC literals. |
| Hyperlinks | Hyperlink relationships to remote URLs; other external relationships |
| Formulas | WEBSERVICE, FILTERXML, ENCODEURL, RTD, IMAGE, STOCKHISTORY, PY, CALL, REGISTER, EXEC, DDE `app\|topic`, user-defined functions, HYPERLINK to a URL, and volatile INDIRECT/OFFSET/NOW/RAND/INFO/CELL. `TODAY()` is the one allowed volatile function, used for staleness. |
| Text cells | Formula-trigger text without the quote prefix |
| Exported VBA (comments ignored) | XMLHTTP, WinHttp, URLDownloadToFile, wininet/urlmon, Shell, ShellExecute, WScript, FollowHyperlink, mail objects, CreateObject/GetObject, Application.Run, URL or UNC literals, and any `Declare` other than `kernel32 GetSystemTime` and `ole32 CoCreateGuid` |

Run it on the generated template on Linux. On Windows, run it again on the saved `.xlsm`, which contains the real DataMashup, together with `olevba` (1b pin `oletools` 0.60.2) for the embedded VBA. The checker is a static guard. Office telemetry, connected experiences and add-ins stay residual risks under 1c O4–O7, and their checks are manual.

## Design decisions

- **Generator plus text sources instead of a committed binary.** This avoids binary merge collisions and makes the content reviewable. Modules have separate workbooks (execution plan rule).
- **Power Query parameters instead of reading a cell from M.** `PerFin_Refresh` writes the Settings data root into the `PerFinDataRoot` parameter query. This avoids combining `Excel.CurrentWorkbook` with file access, which can trigger the Formula.Firewall [Unverified]. It also keeps user paths out of the template.
- **Failing whole queries.** Error cells and partial loads are never accepted. This replaces the WealthFinPilot patterns that 1b reproduced:
  - `SafeConvertToNumber` returned 0;
  - `SplitCSV` dropped a trailing empty field and rows were then skipped silently;
  - `CDbl` and `CDate` depended on the locale;
  - `End` was called on a malformed line.
  - PerFin instead uses RFC 4180 parsing, an exact header, a field-count check, integer minor units, ISO dates and a visible status row.
- **The same rules in M and Python.** `reports.py` implements the reader and the derived views so Linux tests cover the logic. The M equivalents are exercised only on Windows (pending). On Windows the M reader is a little more lenient than the Python one: it accepts LF line ends, and its handling of missing trailing fields and invalid UTF-8 is [Unverified]. The upstream exporter (2b) should be held to the Python reader.
- **Formula subset.** The workbook uses SUM, SUMIFS, COUNTIFS, COUNT, COUNTA, MIN, MAX, IF, ROUND, INT, LEFT and TODAY with structured references. It avoids TEXT, whose format codes depend on the locale, and dynamic arrays. The tests' evaluator supports exactly this subset and raises on anything else.

## Limitations and tracker items

See the PR description for the list raised to the tracker. In brief:

1. `rpt_review_queue` has no batch `row_version`, so review commands carry empty `expected_versions`.
2. There is no report-export metadata table (export time, ledger version). Data-as-of is derived from `balance_as_of`/`as_of`, and freshness from file times.
3. Three report semantics are not defined by the contract:
   - `rpt_transactions.reconciled` (assumed: included in a *balanced* reconciliation);
   - the separator for `rpt_review_queue.error_codes` (assumed `;`);
   - how `rpt_card_status.confirmed_payments_minor`/`unpaid_statement_minor` are derived.
4. The `<data root>\reports` and `<data root>\commands\{drafts,outbox,rejected}` folders are not in the 1c layout table.
5. Every Excel, Power Query and VBA runtime behaviour is pending the [Windows checklist](windows-checklist.md).
