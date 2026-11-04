# Local architecture and automation

Proposed design, 2026-11-04. These choices are recommendations, not an implemented system.

## Storage decision

| Option | Strength | Cost / limitation | Choose when |
| --- | --- | --- | --- |
| Excel workbook only | Fast manual prototype, familiar formulas | Import history, controlled edits and cross-account reconciliation require custom discipline | Testing the workflow with a small dataset |
| Excel + Access | Local relational tables plus form/report designer; Excel Power Query can import Access data | Windows/Office dependencies, driver bitness, binary artifacts; 2 GB database limit | Access forms materially reduce implementation effort |
| Excel + SQLite | Local, serverless database; easy Python testing and portable data | No built-in Access-style forms; Excel needs a file export or configured connector | Automation and future flexibility are the priorities |

Evidence: [Access connector](https://learn.microsoft.com/en-us/power-query/connectors/access-database), [Access limits](https://support.microsoft.com/en-us/access/access-specifications), [SQLite application file format](https://www.sqlite.org/appfileformat.html).

**Recommendation:** evaluate the Access seed first because it directly matches the proposed approach. If it saves little form/import work, use SQLite with Excel. In either case, keep one authoritative ledger. Excel reports are refreshed views; approved edits go through one controlled write path. Power Query import is not database write-back.

For SQLite, a first version can export typed report tables to `.xlsx` or CSV for Excel refresh, avoiding an extra SQLite ODBC installation. Imported text must remain text, including descriptions beginning with formula characters. A later Access frontend could use ODBC, but that introduces a driver and is not necessary for v1.

## Which automation runs locally?

| Technology | Recommended responsibility | Local constraint |
| --- | --- | --- |
| VBA + DAO/ADO | Buttons, forms, controlled Access writes, Excel refresh | Desktop Office; review macros and external calls before use |
| Power Query Desktop | Repeatable local-file transformations and reporting imports | Use local sources; Power Query Online is a different deployment |
| Installed Python | CSV/OFX parsing, validation, deduplication, reconciliation, exports | Run a normal local process; use exact decimal/minor-unit arithmetic |
| Node.js / JavaScript | Alternative importer or Excel file generator | Runs locally; adds little value if Python already handles the same task |
| Microsoft Python in Excel | Not selected for this local-processing design | [Calculations run in Microsoft's cloud and require internet](https://support.microsoft.com/en-us/excel/python/introduction-to-python-in-excel) |
| Office Scripts | Not selected for offline operation | [Requires internet and connected experiences](https://learn.microsoft.com/en-us/office/dev/scripts/testing/platform-limits); [scripts are accessed through cloud storage](https://learn.microsoft.com/en-us/office/dev/scripts/overview/script-storage) |

Default to one automation language plus thin VBA controls. No AI is needed for arithmetic or reconciliation; rule-based categorization with a review queue is sufficient initially.

## Reusable libraries and development tools

| Component | License evidence | What to reuse / limit |
| --- | --- | --- |
| [xlwings](https://github.com/xlwings/xlwings) | [BSD-3-Clause for open-source portion](https://github.com/xlwings/xlwings/blob/HEAD/LICENSE.txt); excludes `xlwings.pro` | Bridge installed Python and desktop Excel if interactive buttons/refresh are needed. Do not assume PRO features are included. |
| [XlsxWriter](https://github.com/jmcnamara/XlsxWriter) | [BSD-2-Clause](https://github.com/jmcnamara/XlsxWriter/blob/main/LICENSE.txt) | Generate new reports with tables/charts. [Cannot edit existing workbooks or calculate formulas](https://xlsxwriter.readthedocs.io/faq.html); use calculated values or Excel recalculation. |
| [pyodbc](https://github.com/mkleehammer/pyodbc) | [Permissive license text](https://github.com/mkleehammer/pyodbc/blob/HEAD/LICENSE.txt), read directly | Python-to-Access connection through a compatible installed ODBC driver; pyodbc itself does not supply that driver. |
| [ofxparse](https://github.com/jseutter/ofxparse) | [MIT](https://github.com/jseutter/ofxparse/blob/HEAD/LICENSE), read directly | Candidate parser for downloaded OFX statements. Validate real issuer formats before depending on it. |
| [ofxtools](https://github.com/csingley/ofxtools) | [GPL-3.0-or-later](https://github.com/csingley/ofxtools/blob/HEAD/LICENSE), read directly | Alternative with documented OFX v1/v2 and QFX support. Broader format work; choose deliberately given license and scope. |
| [ExcelJS](https://github.com/exceljs/exceljs) | [MIT](https://github.com/exceljs/exceljs/blob/master/LICENSE) | JavaScript alternative for XLSX/CSV work. Does not by itself supply the finance ledger or reconciliation rules. |
| [Access VCS add-in](https://github.com/joyfullservice/msaccess-vcs-addin) | [BSD-style permissive notice](https://github.com/joyfullservice/msaccess-vcs-addin/blob/HEAD/LICENSE.txt), read directly | Export forms, queries and VBA as reviewable source. Export definitions and synthetic lookup data only, not household transactions. |

These libraries were screened from primary project docs/licenses, not installed or benchmarked. CSV can initially use Python's standard library; avoid adding every listed dependency.

## Modernizing the Access option

1. Make a working copy of the original template; retain its MIT notice and record its revision.
2. In Windows Access, inspect tables, relationships, startup macros, VBA references and import behavior before running it with data. Export source for review.
3. Compile against the user's actual Office bitness. Inspect API declarations and old controls; do not assume adding `PtrSafe` alone fixes pointer types. See [Microsoft's compatibility guidance](https://support.microsoft.com/en-gb/office/lifecycle/officeinstall/choose-between-the-64-bit-or-32-bit-version-of-office).
4. Use an Access data backend and separate frontend if adopting Access forms. Keep statements/receipts as local files with references rather than embedding large attachments.
5. Replace bank-specific parsing with explicit import profiles, exact money handling and duplicate controls. Add statement and payment-allocation tables.
6. Prove Excel refresh, backup and restore on the actual computer.

Microsoft's [Access Runtime](https://support.microsoft.com/en-us/access/download-and-install-microsoft-365-access-runtime) includes database connectivity interfaces and is available in 32/64-bit versions. It has Office installation compatibility constraints; verify the existing setup before adding drivers. A runtime installation is not a substitute for the full Access design environment needed to edit forms and VBA.

## Local data boundary

The inspected PerFin repository is public. Store code, documentation, empty templates and synthetic fixtures there. Keep statements, populated workbooks, database files, backups and credentials outside the checkout. Local processing also requires checking OneDrive/other folder sync and optional integrations. Worksheet protection is not file encryption.

Use consistent database backups rather than blindly copying an actively written file. Test restoration with the statements and import history needed to reproduce balances. For the first version, manually download statements and run imports locally; automatic bank access and unattended payments are outside scope.
