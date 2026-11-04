# Reusable-asset catalog (task 1b)

Reviewed 2026-11-04 for [#3](https://github.com/NicoLeeVaz/PerFin/issues/3). [catalog.json](catalog.json) is the machine-readable record of every pin, hash and decision. [inspection-log.md](inspection-log.md) lists what was inspected and what was run. Where they overlap, these files supersede the pins in [../evidence.json](../evidence.json).

**Bottom line:** keep the Excel + Access architecture. Build a **small fresh Access backend** from reproducible DDL in task 2b, using the archived MIT Access template as a design reference rather than as the seed. Do not reuse either upstream VBA CSV importer. Use Python's standard-library `csv`/`decimal` for imports and `pyodbc` + the Microsoft ACE driver for writes to Access.

## Decisions at a glance

| Candidate | License (verified?) | Pin | Decision | Copy |
| --- | --- | --- | --- | --- |
| [Self-Employed Ledger (Access)](https://github.com/lingxiaoyang/self-employed-ledger-ms-access) | MIT (yes) | `4065602` | **adapt** (design reference) | Three text members [vendored](../../third_party/self-employed-ledger-ms-access/SOURCE.md) |
| [Financial DashBoard / WealthFinPilot](https://github.com/WealthFinPilot/Financial-management-tool) | MIT (yes) | `a5ad1d0` | **reference-only** (UI patterns) | 49-line defect excerpt [vendored](../../third_party/financial-dashboard-wealthfinpilot/SOURCE.md) |
| [Credit Card Spending Tracker](https://github.com/martin-pthomas/credit-card-spend-tracker) | none found (yes) | `4614291` | **link-only** | none |
| Its [Google Sheets copy](https://docs.google.com/spreadsheets/d/1qGR3FP8tjHgA54_4Js4uvO6ywn76X4oxdh45bSgC0kA/edit?usp=sharing) | none (unverified) | — | link-only | none |
| Microsoft Access *Personal account ledger* | Microsoft template terms (unverified; host blocked) | — | link-only | none |
| Microsoft Create Excel budget/debt templates | Microsoft terms (unverified; host blocked) | — | link-only | none |
| Vertex42 Debt Reduction Calculator / budget templates | private-use EULA per search snippets (unverified; host blocked) | — | link-only (benchmark outputs by hand) | none |
| Reddit / community Google Sheets | no licence by default | — | link-only | none |
| Actual Budget, MMEX, GnuCash | MIT / GPL-2.0+ / GPL-2/3 | from evidence.json | reference-only | none |
| Firefly III | AGPL-3.0 | — | defer | none |

Libraries and tools are covered under [Smallest dependency set](#smallest-dependency-set).

## Access seed decision

**Choice: a fresh, small Access backend that keeps the seed's good patterns.** The seed's schema and import code were read in full: the `.accdt` package holds XML/XSD/text, not a compiled database. Repairing it would take more work than writing roughly ten tables of DDL:

1. **Complex field types.** `Ledger.Taxes` is a multi-valued field, and `Ledger.Receipt` and `BankCSV.CSVFile` are Attachment fields. These work poorly over ODBC/pyodbc. `CSVFile` also embeds every raw bank statement inside the database, which conflicts with the privacy boundary and the 2 GB limit. Removing them changes three of eight tables.
2. **Missing credit-card structure.** There are no statement, due-date, payment-allocation or per-row duplicate-key tables. `Tax`, `Purpose` and `ExpenseType` are Canadian self-employment constructs.
3. **Importer quality.** The importer is per-bank hard-coded VBA. It reads with `OpenTextFile(..., 0)` (ASCII), builds `m/d/yyyy` text for `CDate` (locale-dependent), and calls `End` on any malformed line. Its overlap check misses a new file that fully encloses an earlier period, and it stores the batch ID in an `Integer`. All of these were reproduced or found by static analysis; see below.
4. **Template condition.** The *Import CSV* form's two buttons point to `[Event Procedure]`, but the package contains no form module, so that code is missing. It targets Access 2010 (`RequiredAccessVersion 14`), and the repository was last committed in 2019 and archived in 2021.

**What carries forward to 2b**, as ideas only, with the MIT notice if any code is ported:

- a ledger plus an import-batch table recording the account and statement period;
- lookup tables with unique name indexes and enforced relationships;
- a Currency (fixed-point) amount;
- one DAO/ODBC transaction around a whole import.

The architecture is unchanged: Excel frontend, one authoritative `.accdb`.

## Reproduced CSV/VBA concerns

Method: a **behavioural port** in Python ([harness/vba_ports.py](harness/vba_ports.py), MIT-attributed) of each upstream routine, driven by synthetic cases ([harness/test_vba_ports.py](harness/test_vba_ports.py)). VBA runtime semantics (`IsNumeric`, `CDbl`, `CDate`) are **modelled** from documented behaviour and labelled `MODEL`. They were not executed in VBA.

| Concern | Source | How established | Result |
| --- | --- | --- | --- |
| `SafeConvertToNumber` returns 0 for non-numeric input | WFP `Automate.bas` L161 | port + test | Reproduced: `"N/A"`, `""` and `"0"` all give 0 |
| `SplitCSV` drops a trailing empty field | WFP L135 | port + test | Reproduced. Combined with `If UBound(data) < 8 Then GoTo NextRow`, **a withdrawal row whose final deposit column is empty is skipped silently** |
| `SplitCSV` loses escaped quotes and trims quoted whitespace | WFP L135 | port + test | Reproduced (`Shop ""X"" Ltd` → `Shop X Ltd`) |
| `CDbl` locale handling and Double money | WFP | port + MODEL | `"4.50"` becomes 0 in a comma-decimal locale; `"1,234"` is 1234 or 1.234 depending on locale; 0.10 + 0.20 ≠ 0.30 |
| `CDate` on built `m/d/yyyy` text | Access `ImportFidoCSV` etc. | port + MODEL | On a DMY system, days 1-12 are silently transposed and days after 12 are not |
| Backslash treated as escape character (not RFC 4180) | Access `ParseCSVLine` | port + test | `"C:\temp"` → `C:temp` |
| Malformed line halts all VBA via `End` | Access `ParseCSVLine` | port + test | A space after a closing quote, or a quoted newline, aborts the import |
| Enclosing-period duplicate import not detected | Access `DoImportCSV` DCount | port + test | Reproduced |
| ASCII read, `Integer` batch ID | Access | static analysis | Not executed |

The Access `ParseCSVLine` does **preserve** trailing empty fields and doubled quotes. It is better than WFP's parser, but still not RFC 4180. The reference tests show that Python's `csv` module handles every case above correctly.

## Smallest dependency set

| Role | Choice | Licence | Pin | Offline behaviour |
| --- | --- | --- | --- | --- |
| CSV, money, dates | Python stdlib `csv`, `decimal`, `datetime` | PSF | interpreter | local |
| Python → Access | `pyodbc` | MIT | 5.3.0 (sdist sha256 `2fe0e063…`) | local DSN/file only |
| Access engine | Microsoft ACE ODBC driver; DAO inside Access | Microsoft proprietary (not redistributed) | machine-specific | local; **bitness must match Office** |
| Access source control (dev) | MSAccess VCS Add-in | ISC-style permission notice | use a tagged release; HEAD observed `55eb682` | local |
| Workbook tooling | Excel itself + Power Query for read-only refresh. `openpyxl` only if 2c needs generated or inspected templates | MIT (PyPI metadata) | 3.1.5 | local |
| Macro audit (dev) | `oletools`/olevba | BSD | 0.60.2 | local |
| PDF (wave 4c) | `pdfplumber` → `pdfminer.six` (+ Pillow, `pypdfium2` native PDFium) | MIT / MIT / BSD-3+Apache-2.0 | 0.11.10 / 20260107 | no network imports in package source |
| PDF fallback | `pypdf` | BSD-3-Clause | 6.21.4 | no network imports in package |
| OFX (optional) | `ofxparse` (deps bs4, lxml, six; uses `Decimal`) | MIT | 0.21 (last release 2021) | no network imports |
| OFX rejected | `ofxtools` | GPL-3.0-only (PyPI) | 1.1.1 | **contains a bank-connection client** (`Client.py`, `ofxget`) |

Not selected: XlsxWriter (choose one workbook library), xlwings (only if thin VBA is insufficient), access-parser (possible read-only Linux test aid; source not reviewed).

**Install policy:** use pinned versions with hashes (`pip install --require-hashes -r …`), installed by the user or a reviewed 3a setup step. No automatic download-and-run scripts. Free download is not redistribution permission: never bundle third-party templates.

## Audit gaps and pending Windows/Office checks

- Instantiate the Access template in Microsoft 365 Access. Confirm the missing form modules and the VBA references compile under the user's bitness. Information only, since it is not the seed.
- Resolve the olevba **"VBA stomping"** flag on the WFP workbook. Exported `vba/*.bas` and the embedded source differ in 16 of 23 modules, and the exported versions look newer in places. Do not treat the exported files as equivalent to the binary.
- Confirm the `MODEL` assumptions (`IsNumeric`, `CDbl`, `CDate`) in real VBA under en-US, en-CA, en-GB and fr-CA settings.
- On the user's PC, record Office/ACE bitness, the ODBC driver list and the Access version (needed by 2b).
- Network-blocked hosts were not verified: vertex42.com, support.microsoft.com, create.microsoft.com, templates.office.com, reddit.com and docs.google.com. Re-check their terms before relying on any of them, even as link-only.
- The GitHub REST API was unavailable for the upstream repositories in this session, so the archived flag and repository metadata were not rechecked. Identity was checked by clone URL and commit SHA.
