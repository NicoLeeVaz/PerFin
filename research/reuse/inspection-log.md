# Inspection log: inspected versus run (task 1b)

Date: 2026-11-04. Environment: a Linux container (kernel 6.18) with Python 3.13.18. No Windows, Office, Excel or Access was available. **No macro, workbook or Access template was opened or executed.**

## Retrieval

Upstream repositories were cloned into an empty scratch directory outside the PerFin checkout and treated as untrusted data. Python that read them ran with `python3 -I`.

| Repository | Command | HEAD verified |
| --- | --- | --- |
| lingxiaoyang/self-employed-ledger-ms-access | `git clone https://github.com/lingxiaoyang/self-employed-ledger-ms-access.git` | `4065602606602a0781873f7ac05dac67e69f9291` = evidence.json |
| WealthFinPilot/Financial-management-tool | `git clone https://github.com/WealthFinPilot/Financial-management-tool.git` | `a5ad1d023152db1aac67579d5c452c6b9c10107e` = evidence.json |
| martin-pthomas/credit-card-spend-tracker | `git clone …credit-card-spend-tracker.git` | `46142914b1be399beb1fc691adc3c0477915d244` = evidence.json |
| ofxparse, ofxtools, pdfminer.six, pypdf, pdfplumber, pyodbc, msaccess-vcs-addin | `git clone --depth 1` | HEADs recorded in catalog.json (`repo_head_observed`) |

PyPI JSON metadata (`https://pypi.org/pypi/<name>/json`) supplied the versions, sdist sha256 values and licence fields. `gh api repos/...` and unauthenticated `api.github.com` calls for the upstream repositories returned 403 (the session policy did not enable them).

The following hosts were blocked: www.vertex42.com, support.microsoft.com, create.microsoft.com, templates.office.com, www.reddit.com (proxy 403 or DNS failure). One web search produced only unverified snippets about the Vertex42 licence.

## Tools

- `oletools` 0.60.2 (olefile 0.47, pcodedmp 1.2.6), installed in a scratch venv: `olevba -a` and `olevba -c`, which only extract and analyse code.
- Python `zipfile`: listed and extracted `.accdt` / `.xlsm` members after rejecting absolute or `..` paths.
- Scratch scripts: compared embedded and exported VBA after normalisation, and decoded the Power Query DataMashup.

## Access template (`Self-Employed Ledger.accdt`, sha256 `a38518f0…d827`)

Inspected:

- All 47 OPC members.
- 8 table XSDs (types, nullability, indexes).
- `relationships.xml`, `vbaReferences.xml` (5 references, all standard VBA/Access/stdole/ACE DAO/Office libraries) and `databaseProperties.xml`. There is no AutoExec and no StartUpForm.
- `template.xml` (RequiredAccessVersion 14, DataLocale 4105).
- `navpane.xml`.
- Both form definitions (UTF-16 → UTF-8).
- The full macro module `DoImportCSV`.

External calls: none. The `http` strings are XML namespaces only. File access goes through `Scripting.FileSystemObject`, local only. Sample data: none.

Run: the Python behavioural port only.

## Financial DashBoard workbook (`WealthFinPilot_v3.0.xlsm`, sha256 `21efc53c…f42e`)

Inspected:

- **VBA modules.** 42 modules in `vbaProject.bin`. Startup/event handlers: `ThisWorkbook` is empty, so there is no `Workbook_Open`. olevba flags ActiveX event handlers such as `AnalyseD_Click` and `Cat_1_Change`.
- **Declares and external calls.** `Declare PtrSafe` calls to user32/gdi32 (`FindWindowA`, `GetDC`, `FrameRect`, …) are used for drawing. Three `FollowHyperlink` calls open government tax pages.
- **Links and connections.** One external hyperlink relationship (statistique.quebec.ca). Power Query M reads only `Excel.CurrentWorkbook()`. The Data Model is present, and there is a legacy worksheet connection named `Finance.xlsx!DataTable`.
- **Exported versus embedded source.** Normalised, 7 modules are identical, 16 differ and 19 exist only in the binary (`Test.bas` plus empty sheet modules). `SplitCSV` and `SafeConvertToNumber` are identical in both. The embedded code names real banks where the export uses `Bank1-3`, and the exported `Triage.bas` has an extra `DTEP` block.
- **olevba flag.** olevba reported "VBA Stomping" (experimental heuristic). It is not resolved.
- **Sample data.** Data Base (775 rows) and Master (113 rows) are populated with data of undocumented provenance. It was not copied.

Run: the Python behavioural port only.

## Credit Card Spending Tracker (`.xlsm`, sha256 `a0cc20e8…07af`)

Inspected: 7 VBA modules. `Workbook_Open` → `ResetStatus` automatically clears and resets the Paid/Not Paid cells after day 15 of each month. There are no Declares, network calls, connections or ActiveX. There is no licence, so the tracker is link-only.

## Executed checks (PerFin repository root)

```text
$ python3 -I -B -m unittest discover -s research/reuse/harness -v
Ran 20 tests ... OK
$ python3 -I -B research/reuse/harness/validate_catalog.py
OK: 27 entries; 2 vendored directories verified
$ python3 -I -m json.tool research/reuse/catalog.json > /dev/null   # exit 0
```
