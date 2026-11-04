# PerFin: local personal finance research

Research date: **2026-11-04**. Scope: personal finances and credit cards first; additional modules later.

**Recommendation: keep Excel as the interface, use one local database as the ledger, and reuse selected components rather than assume a downloaded workbook already handles credit cards correctly.** There is a real open-source Access starting point worth evaluating.

| Route | Best reason to choose it | Assessment |
| --- | --- | --- |
| Excel + Access + VBA, with optional local Python | Familiar Windows forms, queries and reports | Closest to the proposed approach. Evaluate the archived MIT Access template before deciding how much to reuse. |
| Excel + local Python + SQLite | Easier automated imports, testing and future extensions | My preferred engineering default if Access forms are not important. Excel remains the everyday interface. |
| Actual Budget desktop, with Excel exports | Start using a complete system sooner | Strong alternative if using an existing application matters more than making Excel the main interface. |

These are alternatives, not three ledgers to maintain. A database backend is recommended for repeatable imports and reconciliation; a workbook-only prototype is still reasonable for a small manual trial.

## Most useful discoveries

| Candidate | Role in PerFin |
| --- | --- |
| [Self-Employed Ledger for Access](https://github.com/lingxiaoyang/self-employed-ledger-ms-access) | MIT-licensed `.accdt` template; strongest Access seed found. Last observed commit: 2019; archived in 2021. |
| [Financial DashBoard / WealthFinPilot](https://github.com/WealthFinPilot/Financial-management-tool) | MIT Excel/VBA workbook with exported modules. Useful UI/import examples, but the sampled importer needs corrections. |
| [Actual Budget](https://github.com/actualbudget/actual) | MIT local finance application; useful complete alternative and behavioral reference. |
| [Money Manager Ex](https://github.com/moneymanagerex/moneymanagerex) | Desktop alternative with a SQLite database and credit-card accounts. |

Detailed evidence, licenses, limitations and further candidates: [candidate comparison](candidates.md).

## Read next

1. [Candidate comparison](candidates.md): what can be reused and what cannot yet be recommended.
2. [Local architecture and automation](local-architecture.md): Excel/Access/SQLite tradeoffs and reusable libraries.
3. [Credit-card MVP](credit-card-mvp.md): minimum data, behavior and acceptance scenarios.
4. [Source inspection](source-review.md): concrete findings and what remains untested.
5. [Evidence manifest](evidence.json): observed commit and file identities for follow-up work.

## Payoff planning and personal statements

The next research phase compares largest-balance-first, snowball, avalanche and near-APR hybrid payoff strategies, then specifies an optional personal statements/net-worth module.

- [Research plan and mathematical acceptance criteria](payoff-and-net-worth-plan.md)
- [Ready-to-paste Claude Code prompt](claude-code-research-prompt.md)

These documents define the next work; the payoff engine and financial statements module have not been implemented.

## First implementation experiment

Use synthetic data for one checking account and two cards over two statement cycles. Compare the Access seed against a minimal Python/SQLite ledger using the same [acceptance scenarios](credit-card-mvp.md#acceptance-scenarios). Keep whichever requires less custom repair while preserving Excel usability. Do not build both production paths.

The machine's Windows/Office versions, Office bitness, Access availability and bank export formats still need checking during implementation. Research does not depend on those answers.

## Verification boundary

This is a source/documentation review, not an installation or full security audit. Selected VBA source and licenses were read; the Excel workbook and Access template were **not executed**. No upstream code or binaries were copied into PerFin. No personal financial records were used. The repository was empty and public when inspected; keep real statements, populated workbooks, databases and backups outside it.
