# Windows / desktop Excel checklist for the core shell (2c)

**Status: every check below is PENDING. The "desktop Excel open/recalculate" acceptance gate of [#7](https://github.com/NicoLeeVaz/PerFin/issues/7) is BLOCKED** until someone runs this checklist on the declared Windows/Office setup and records the results. The 2c build container had no Windows and no Excel. Linux tests cannot replace these checks and must not be reported as passing them.

Use **synthetic data only**. Never point these steps at a real data root.

## 0. Record the environment

| Item | How to read it | Value |
| --- | --- | --- |
| Windows edition, version, build | `winver` | |
| Excel version, build, channel | File › Account › About Excel | |
| Office bitness | About Excel (32-bit/64-bit) | |
| Access Database Engine / ACE bitness (only if the optional Access query is tried) | ODBC Data Sources (64-bit or 32-bit) › Drivers | |
| Regional format (decimal and date separators) | Settings › Time & language › Region | |
| Macro setting | File › Options › Trust Center › Macro Settings | |
| External content setting (data connections, links) | Trust Center › External Content | |
| Python version, and `pip list` showing openpyxl 3.1.5 and et-xmlfile 2.0.0 | `py -V` | |
| Repository revision | `git rev-parse HEAD` | |

## 1. Prepare (Command Prompt in the repository checkout)

```bat
py -m pip install --require-hashes -r excel\core\requirements.txt
set PYTHONPATH=excel\core
set ROOT=%LOCALAPPDATA%\PerFin-synthetic
mkdir "%ROOT%\reports" "%ROOT%\workbooks\excel_payoff" "%ROOT%\workbooks\excel_statements"
echo {"kind": "synthetic", "created": "2026-11-04"} > "%ROOT%\perfin-data-dir.json"
py config\privacy\perfin_privacy_checks.py check-data-dir "%ROOT%"
copy fixtures\excel_core\reports\*.csv "%ROOT%\reports\"
copy fixtures\excel_core\modules\excel_payoff\module_manifest.json "%ROOT%\workbooks\excel_payoff\"
copy fixtures\excel_core\modules\excel_statements\module_manifest.json "%ROOT%\workbooks\excel_statements\"
py -m perfin_excel_core build --out "%ROOT%\workbooks\PerFin-Core.xlsx"
py -m perfin_excel_core check "%ROOT%\workbooks\PerFin-Core.xlsx" --vba excel\core\vba --powerquery excel\core\powerquery
```

- `check-data-dir` must print `"decision": "ok"`. A sync-folder warning means you should choose another folder.
- `check` must print `OK`.
- **Create the mock module workbooks with Excel**: a blank workbook saved as *Excel Macro-Enabled Workbook* named `%ROOT%\workbooks\excel_payoff\PerFin-Payoff.xlsm`, and another named `%ROOT%\workbooks\excel_statements\PerFin-Statements.xlsm`. openpyxl cannot write a valid `.xlsm`. Then export the registry:

```bat
py -m perfin_excel_core registry --modules "%ROOT%\workbooks" --out "%ROOT%\reports\perfin_modules.csv"
```

Both modules must be listed with status `OK`.

## 2. Checks

Mark each row PASS or FAIL with notes and a screenshot where useful. "Expected" values come from the Linux tests (`tests/excel_core`), which computed them independently from the synthetic contract documents.

| ID | Step | Expected |
| --- | --- | --- |
| W1 | Open `PerFin-Core.xlsx` in desktop Excel. | Opens with no repair prompt and no "external links" or "data connections" security bar. Nine sheets; the Home banner reads `NOT REFRESHED…`. |
| W2 | Alt+F11. Use File › Import File… for each of the five `excel\core\vba\*.bas` files. Run Debug › Compile VBAProject. | Compiles with no error on this bitness. If possible, repeat on the other bitness (`#If VBA7` Declares). |
| W3 | Save As *Excel Macro-Enabled Workbook* `%ROOT%\workbooks\PerFin-Core.xlsm`. In Settings!B4 enter `%ROOT%` expanded, for example `C:\Users\<you>\AppData\Local\PerFin-synthetic`. Alt+F8 › `PerFin_InstallQueries`, folder `<checkout>\excel\core\powerquery`. | "Installed 15 queries". Data › Queries & Connections lists exactly the 15 queries in `queries.txt`. Table names are unchanged (`rpt_accounts`, …, `perfin_refresh_status`). No summary cell shows `#REF!` or `#NAME?`. |
| W4 | Alt+F8 › `PerFin_Refresh`. | No Formula.Firewall or privacy-level prompt. If one appears, record its exact text; it is the main [Unverified] risk. The "Refreshed" message appears and the sheets are protected again. |
| W5 | Status sheet. | Six source rows, each `STALE` (the synthetic data is dated 2026-06-30, more than 7 days ago) or `OK`. None is `MISSING`, `BAD_HEADER` or `INVALID`. Data as of `2026-06-30`. Last refresh is now. The banner is red `ERROR: … stale …` on every sheet, so stale data is not shown as success. |
| W6 | Formulas › Calculation Options = Automatic. Press Ctrl+Alt+F9 (full recalculation). | No `#VALUE!`, `#REF!` or `#NAME?` anywhere. |
| W7 | Compare the figures (cell B of each row; filters blank). | Accounts: Total assets **13,700.00**; Total owed **300,005.00** (positive); Net **-286,305.00**; credit cards **605.00**; Check `OK`. Cards: Current owed **605.00**; Statement owed **605.00**; Minimum due **60.00**; Payments **100.00**; Unpaid **505.00**; Unknown limit **1**; Utilization **11.0%**; Next due **2026-07-25**. Transactions: **12** matching; In **4,225.00**; Out **2,580.00**; Net **1,645.00**; Not reconciled **8**. Review: Rows **10**; Awaiting **8**; Approved **1**; Rejected **1**; Errors **2**; Possible duplicates **1**. Reconciliation: Statements **2**; Balanced **1**; Open **1**; Non-zero differences **1**; Unreconciled items **2**; their net **-55.00**; Opening balances **450.00**. Modules: Registered **2**, Launchable **2**, Invalid **0**. |
| W8 | Alt+F8 › `PerFin_SelfTest`. | `0 failure(s)`. The summary lists the Excel version and bitness. The file `%ROOT%\logs\perfin-selftest.txt` holds PASS/FAIL names only (no amounts). Attach it. |
| W9 | Text safety. Transactions: click the `t002` description. Review: rows 6–10. | The cell shows `=SYNTHETIC GROCER #12 (leading '=' must stay text)` as text. Its formula bar shows the same text, not a formula result. Rows 6–10 start with `+`, `-`, `@`, TAB and CR and none is evaluated. |
| W10 | Filters: Transactions!B5 = `card:alpha`. Then clear it and set B6 = 2026-06-10, B7 = 2026-06-20. Then clear those and set B8 = `refund`. | `card:alpha`: **4** matching, In **100.00**, Out **200.00**, Net **-100.00**, Not reconciled **0**. 10–20 June: **5** matching (t003, t004, t006, t009, t010), In **625.00**, Out **600.00**, Net **25.00**. `refund`: **1** matching, Net **25.00**. Table filter buttons work on the protected sheet. |
| W11 | Protection: try to type in any `rpt_accounts` cell and in Home!B5. | Excel refuses (protected). The Transactions filter inputs and Settings!B4–B6 accept input. This is a UX guard only; protection is not security. |
| W12 | Missing source: rename `%ROOT%\reports\rpt_accounts.csv` to `.bak`, then `PerFin_Refresh`. | The message lists `rpt_accounts` as failed. The `rpt_accounts` table is **empty** (old rows cleared). The Status row shows `MISSING`. The banner reads `ERROR: …`. Accounts totals are 0. Rename the file back and refresh again. |
| W13 | Bad header and bad value: change the first header field of `rpt_card_status.csv` and refresh. Restore it. Then replace `,300000,` with `,3000.00,` in `rpt_transactions.csv` and refresh. Restore it. | `BAD_HEADER`, then `INVALID`. Each time the affected table is cleared and the banner is red. Nothing partial is loaded. |
| W14 | Stale without refresh: set Settings!B5 = 1, refresh, save and close. Reopen on a later day **without** refreshing. | The banner reads `STALE: last refresh is more than 1 days old…` (or `ERROR` because the data itself is stale). It never reads `OK`. Restore B5 = 7. |
| W15 | Commands: on Review, select table rows with `row_number` 1 and 4 and run `PerFin_ApproveSelectedRows`. Select row 2 and run it again. Select rows 6–7, run `PerFin_RejectSelectedRows` and give a reason containing `é` and `"`. Then run `py -m perfin_excel_core command promote --data-root "%ROOT%"`. | Rows 1 and 4: a draft is written to `%ROOT%\commands\drafts\<uuid>.json`. Row 2: refused ("has errors") and no file. Rows 6–7: a draft is written. `promote` reports both as promoted and none rejected. `py -m perfin_contracts %ROOT%\commands\outbox\*.json` (with `PYTHONPATH=contracts\python`) prints `OK` for each. The ledger and the report CSVs are unchanged. |
| W15b | Location guard: set Settings!B4 to `C:\Users\<you>\OneDrive\PerFin-test` (create it with a `perfin-data-dir.json`), select row 1 and run `PerFin_ApproveSelectedRows`. Repeat with a folder inside the Git checkout (for example `<checkout>\tmp-root`, with a marker), with a UNC path `\\localhost\c$\PerFin-test`, and with a local folder **without** `perfin-data-dir.json`. Restore B4 to `%ROOT%`. | Each attempt shows "No command written. The PerFin data root is refused: …" naming the reason (sync folder segment, inside a Git checkout, network (UNC) path, no marker). No `commands` folder or file is created in any of those locations. Delete the test folders afterwards. |
| W16 | Modules: on the Modules sheet, select the `excel_payoff` row and run `PerFin_LaunchModule`. Also run it with no selection and type `excel_statements`. | Each opens its own module workbook from `%ROOT%\workbooks\<module>\`. `PerFin-Core.xlsm` is not modified (its file time is unchanged if you do not save). |
| W17 | Offline: turn on airplane mode, or disconnect the network, and repeat W4–W7. | Same results with no network prompts. Data › Edit Links is unavailable (no links). Queries & Connections shows only PerFin queries. |
| W18 | Saved workbook inspection: `py -m perfin_excel_core check "%ROOT%\workbooks\PerFin-Core.xlsm" --vba excel\core\vba`. Optionally run `olevba` (oletools 0.60.2, the 1b pin) on the same file. | `OK`. The only non-error finding is `INFO vba_project`, and the embedded DataMashup decodes with no non-local source. If the DataMashup cannot be decoded, record it as a checker defect. olevba reports no network or Shell keywords. Note the VBA-stomping caveat in research/reuse/catalog.md. |
| W19 | Locale: switch Region to a comma-decimal, day-first format (for example de-DE or fr-CA), restart Excel, and repeat W4–W7 and W10. | Identical values and dates. Integers are parsed with `en-US` and dates are built from ISO parts. |
| W20 (optional) | Manual query fallback: in a fresh template, add one query (Data › Get Data › From Other Sources › Blank Query › Advanced Editor), paste `rpt_accounts.pq`, then Close & Load To… the existing table location. | Documents a fallback if `PerFin_InstallQueries` fails on this Excel build. |

## 3. Record the result

Report in the PR or tracker:

- the environment table;
- each W row with PASS/FAIL, notes and the self-test log;
- the exact Excel build;
- any message text, especially Formula.Firewall, protection and refresh errors.

A FAIL in W1–W13 or W15–W18 blocks the 2c gate. Fixes go to `excel/core/**` only. Do not record a check as passed unless it was run on Windows with desktop Excel.
