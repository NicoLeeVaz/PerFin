# Candidate comparison

Reviewed 2026-11-04. Rankings reflect PerFin's local, Excel-oriented scope, not overall product quality. A public download is not by itself evidence of an open-source license. Features below are documented unless explicitly marked as source-inspected; runtime behavior remains unverified.

## Excel and Access starting points

| Candidate | License evidence | Reuse opportunity | Main gap / decision |
| --- | --- | --- | --- |
| [Self-Employed Ledger for Access](https://github.com/lingxiaoyang/self-employed-ledger-ms-access) | [MIT](https://github.com/lingxiaoyang/self-employed-ledger-ms-access/blob/HEAD/LICENSE), read directly | `.accdt` template; bank accounts, categories, purpose/type distinctions, CSV import and VBA customization guide | **Evaluate first for Access.** Business/tax orientation; no verified statement/due-date/payment-allocation subsystem. Archived; requires a Windows compatibility trial. |
| [Financial DashBoard / WealthFinPilot](https://github.com/WealthFinPilot/Financial-management-tool) | [MIT](https://github.com/WealthFinPilot/Financial-management-tool/blob/HEAD/LICENSE), read directly | `.xlsm`, UserForms, budgeting and exported VBA modules | **Component donor.** Source inspection found invalid numeric input returning zero, CSV edge cases and extensive workbook coupling. Reuse after targeted repairs, not as a verified card ledger. |
| [Credit Card Spending Tracker](https://github.com/martin-pthomas/credit-card-spend-tracker) | No license file found in root or `Files`; README gives no reuse license | Multi-card overview, billing-month assignment, utilization and payment-status presentation | **Reference only pending permission/license.** README describes a manual Paid/Not Paid flag and a reset after the 15th; that is insufficient evidence of payment reconciliation. INR/date conventions require adaptation. |
| [Microsoft Personal account ledger](https://support.microsoft.com/en-us/access/featured-access-templates) | Microsoft template; no open-source grant established | Microsoft documents a personal ledger with categorized income/payments, memos and reports | **Design reference / separate template option.** Do not label it open source or redistribute it as an OSS dependency. Binary availability and current compatibility were not tested. |

The Access template's [setup guide](https://github.com/lingxiaoyang/self-employed-ledger-ms-access/blob/HEAD/docs/Base-Data-Example.md) explicitly includes debit and credit accounts. Its [VBA guide](https://github.com/lingxiaoyang/self-employed-ledger-ms-access/blob/HEAD/docs/VBA-Programming-Guide.md) requires per-bank import functions and date/amount mappings. Those are useful starting assets, not plug-and-play support for the user's banks. Its examples use Canadian tax categories; replace those with personal categories for this MVP.

The credit-card tracker is particularly relevant conceptually, but current-period spending is not necessarily the balance owed. PerFin should use explicit statement records and confirmed payment events, not a monthly flag reset.

## Complete applications worth comparing

| Candidate | License | Local operation / reuse | Fit for this project |
| --- | --- | --- | --- |
| [Actual Budget](https://github.com/actualbudget/actual) | [MIT](https://github.com/actualbudget/actual/blob/HEAD/LICENSE.txt), read directly | Desktop client can import files and budget offline. Node/TypeScript ecosystem. | **Best complete alternative.** Use the app/export boundary before extracting its internal engine. Excel is an adjunct unless we build an integration. |
| [Money Manager Ex](https://github.com/moneymanagerex/moneymanagerex) | [GPL-2.0-or-later](https://github.com/moneymanagerex/moneymanagerex/blob/HEAD/license.txt), read directly | Desktop finance application; SQLite storage, credit-card accounts, scheduled bills, CSV/QIF imports | **Strong desktop benchmark.** Favor exports or read-only snapshots for Excel; direct writes to its internal tables are not an integration contract. |
| [GnuCash](https://github.com/Gnucash/gnucash) | [GPL v2 or v3, with file-specific terms](https://github.com/Gnucash/gnucash/blob/HEAD/LICENSE), read directly | Local double-entry personal/business accounting | **Accounting reference or later expansion.** More accounting workflow than the initial Excel dashboard needs. |
| [Firefly III](https://github.com/firefly-iii/firefly-iii) | [AGPL-3.0](https://github.com/firefly-iii/firefly-iii), project license declaration | Self-hosted finance manager with budgets, categorization, reports and Docker installation | **Defer.** Can run on a local computer, but operating a web application adds deployment work and does not directly deliver an Excel UI. |

Actual's [installation matrix](https://actualbudget.org/docs/install/) says the documented API workflow needs a server; a server on the same computer can still satisfy local hosting. Do not promise a serverless API integration from the desktop download alone. Its [credit-card guide](https://actualbudget.org/docs/budgeting/credit-cards/) and [transfer guide](https://actualbudget.org/docs/transactions/transfers/) are useful behavior references. Statement tracking beyond those documented features still needs verification.

MMEX's `license.txt` includes a privacy policy describing optional usage statistics and how to disable them. Local financial storage does not automatically establish zero outbound traffic. An offline trial should check network settings and avoid optional feeds.

GnuCash's [credit-card concepts](https://www.gnucash.org/docs/v5/C/gnucash-guide/cc-concepts1.html) explain purchase expenses, liability balances, statement reconciliation and payments as transfers. These are the relevant concepts to reproduce independently.

## Observed maintenance signals

| Repository | Observed HEAD commit date (UTC) | Interpretation |
| --- | --- | --- |
| Access ledger | 2019-09-29 | Legacy project; repository displays archive date 2021-01-27. |
| Financial DashBoard | 2026-06-06 | Recent-era workbook; latest commit is a rename, not proof of current testing. |
| Credit Card Spending Tracker | 2026-08-28 | Recent workbook upload; license gap remains. |
| Actual Budget | 2026-11-04 | Active development; use a tested stable release for a trial. |
| Money Manager Ex | 2026-11-04 | Active development; current HEAD is not a certified release. |

Exact observed SHAs are in [evidence.json](evidence.json). No unsupported star-count or maintenance score is used to decide reliability. GnuCash/Firefly were screened from project documentation, not audited at a pinned release.

## Reuse approach

Prefer dependencies with clear licenses and narrow responsibilities. Preserve upstream notices for copied components; review individual files and dependencies before distribution. GPL/AGPL projects are useful applications and references, but do not assume their code can be relicensed as MIT. No license for PerFin itself was selected in this research.

The recommended next step is a small compatibility/import trial, not a wholesale fork. No candidate was demonstrated to satisfy the entire [MVP contract](credit-card-mvp.md).
