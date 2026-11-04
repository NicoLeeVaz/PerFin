# Source inspection and evidence limits

Reviewed 2026-11-04. This records static observations, not a full audit. Upstream project instructions were treated as reference material; no macros were enabled or executed.

## Financial DashBoard / WealthFinPilot

Observed repository HEAD: `a5ad1d023152db1aac67579d5c452c6b9c10107e`.

Read the published `LICENSE`, `vba/Automate.bas` and `vba/Triage.bas`; inspected the root and VBA file inventory. The repository contains a workbook and exported `.bas`, `.frm`, `.frx` and `.cls` assets. Binary/source equivalence has not been established.

| Source observation | Consequence for reuse |
| --- | --- |
| [`Automate.bas`, `SafeConvertToNumber`](https://github.com/WealthFinPilot/Financial-management-tool/blob/a5ad1d023152db1aac67579d5c452c6b9c10107e/vba/Automate.bas#L161) returns zero if `IsNumeric` fails | Invalid financial input can be hidden as a valid zero; reject or quarantine it instead. |
| [`SplitCSV`](https://github.com/WealthFinPilot/Financial-management-tool/blob/a5ad1d023152db1aac67579d5c452c6b9c10107e/vba/Automate.bas#L135) appends the final field only if the buffer is nonempty | A trailing empty field is dropped. Preserve field count. |
| Same parser toggles quote state without retaining quote characters | Escaped literal quotes can be lost. Use a standards-aware parser with fixtures. |
| Numeric conversion uses `Double`/`CDbl`; date conversion uses `CDate` | Add explicit locale rules and exact money policy; test the user's export formats. |
| [`Triage.bas`](https://github.com/WealthFinPilot/Financial-management-tool/blob/a5ad1d023152db1aac67579d5c452c6b9c10107e/vba/Triage.bas) uses named sheets/tables and repeated `On Error Resume Next` | Extraction is coupled to the workbook; silent error handling needs review before ledger use. |

These findings justify reusing selected UI patterns and repairing the importer. They do not establish that every workbook feature is broken, or that the workbook contains malicious code. Statement reconciliation, import idempotency and payment allocation were not demonstrated.

## Archived Access ledger

Observed HEAD: `4065602606602a0781873f7ac05dac67e69f9291` (2019-09-29 UTC). Repository displays archive date 2021-01-27.

Read MIT license, changelog and both setup/VBA guides; confirmed `Self-Employed Ledger.accdt` in the repository. [Setup documentation](https://github.com/lingxiaoyang/self-employed-ledger-ms-access/blob/4065602606602a0781873f7ac05dac67e69f9291/docs/Base-Data-Example.md) names `ExpenseType`, `Category`, `Tax` and `BankAccount`; [import documentation](https://github.com/lingxiaoyang/self-employed-ledger-ms-access/blob/4065602606602a0781873f7ac05dac67e69f9291/docs/VBA-Programming-Guide.md) explains bank-specific branching and signed amounts.

The binary template's internal VBA, relationships, forms and macros were not extracted. Current Office compatibility, precise schema constraints, rollback behavior, duplicate handling and statement support are unknown. A `.accdt` template and its documentation are promising assets; they are not proof that it is ready for financial records.

## Dedicated card tracker

Observed HEAD: `46142914b1be399beb1fc691adc3c0477915d244`. Root and `Files` inventories contain a README, workbook, PDF guide and Google Sheets link; no license file was found. The README documents a date-driven payment-status reset and manual Paid/Not Paid selection. The workbook's formulas and embedded VBA were not inspected. Do not copy its implementation into PerFin until reuse rights are established.

## Other evidence and reproducibility

Actual Budget and MMEX README/license files and current commit metadata were inspected. Official Actual documentation establishes which desktop features work without a server. GnuCash's license/README and official credit-card concepts, Firefly's README, Microsoft support pages and library documentation were also consulted.

The [manifest](evidence.json) records selected observed commits and content blob SHAs. Files fetched using `HEAD` are identified by the returned blob SHA; the commit timestamps are separate maintenance observations, not release certifications. Moving web documentation was reviewed on the date above. The research does not claim exhaustive discovery of all Access databases, Windows runtime verification, performance benchmarks or a full dependency/security audit.
