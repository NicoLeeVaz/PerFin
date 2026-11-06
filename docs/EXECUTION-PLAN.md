# PerFin execution plan

Revised 2026-11-05 under the user's explicit SQLite and parallel-agent instruction.
[Live tracker #1](https://github.com/NicoLeeVaz/PerFin/issues/1) records completion evidence.

**Current status:** portable waves 6, 7 and 8a are merged in PR #33 (`af6a794`). The next executable task is [#34: Windows SQLite and desktop Excel acceptance](https://github.com/NicoLeeVaz/PerFin/issues/34). Intended executor: local Codex on Windows; desktop operator: the user; results review: Spot/cloud coordinator. The Windows task is not yet claimed or running. Optional Access/ACE and remaining native release requirements stay open in #30. See [the agent log](AGENT-LOG.md) for actual activity, recorded ownership and later handoffs.

## Outcome and structure first

Run private personal finance locally using a real SQLite database, existing deterministic Python workflows, and generated Excel files. Access remains an explicit optional backend/port target. Native Access and desktop Excel acceptance are release requirements for those features, not blockers for development.

The [complete data model](database/model.md), [offline relationship explorer](database/model.html) and [machine-readable inventory](database/schema-inventory.json) describe all 18 tables:

| Group | Tables | Responsibility |
| --- | --- | --- |
| Accounts/categories | account, category | Dated opening balances and category hierarchy |
| Intake/review | import_batch, staging_row | File identity, provenance, errors and explicit decisions |
| Ledger/transfers | ledger_txn, split, transfer_link | Atomic records, category splits, paired transfers and reversals |
| Statements/reconciliation | statement, statement_bucket_balance, statement_payment, reconciliation, reconciliation_item | Statement buckets, allocations and reconciled transaction membership |
| Card terms | card_terms, card_apr_bucket | Dated limits, minimum payments and APR buckets |
| Wealth | asset_valuation | Dated values with source/method |
| Evidence/metadata | command_log, audit_log, contract_meta | Replay identity, before/after audit, versions and configuration |

Foreign keys and logical references differ; inspect both in the model. SQLite stores exact bounded integer cents, explicit ISO dates and booleans. SQLite/Access SQL and collations are not identical. Canonical Python reports feed CSV/XLSX; Access saved queries remain platform-specific. Full-history archives retain more than ledger_bundle.

## Wave ownership and completion

The five original waves have merged source; do not repeat them. Their native evidence gaps belong to **8b**, without blocking portable work.

| Wave/task | Issue | Recorded owner | Deliverable | Current status |
| --- | --- | --- | --- | --- |
| 6a | [#24](https://github.com/NicoLeeVaz/PerFin/issues/24) | `schema_map` | Structure, relationship explorer, inventory drift checks | Merged #33; closed |
| 6b | [#25](https://github.com/NicoLeeVaz/PerFin/issues/25) | `sqlite_backend` | Real SQLite schema/adapter and repository regressions | Merged #33; closed |
| 6c | [#26](https://github.com/NicoLeeVaz/PerFin/issues/26) | `portability` | Backup/verified restore and full-history archives | Merged #33; closed |
| 7a | [#27](https://github.com/NicoLeeVaz/PerFin/issues/27) | `app_backend` | SQLite default, explicit Access option, full CLI workflow | Merged #33; closed |
| 7b | [#28](https://github.com/NicoLeeVaz/PerFin/issues/28) | `cloud_workbooks` | Synthetic database workflow and three Excel workbooks | Merged #33; closed |
| 8a | [#29](https://github.com/NicoLeeVaz/PerFin/issues/29) | `root` coordinator | Offline suites, installed wheel, portable package/evidence | Merged #33; closed; 547 tests and installed smoke PASS |
| 8b | [#30](https://github.com/NicoLeeVaz/PerFin/issues/30) | Compatible Windows operator needed | Native ACE/Excel/Power Query/VBA and future Access import validation | Open; native requirements UNRUN |
| Next Windows slice | [#34](https://github.com/NicoLeeVaz/PerFin/issues/34) | Local Codex + user; Spot reviews results | Actual Windows SQLite and desktop Excel evidence | Open; intended executor not yet claimed |

Implementation owners above come from the original wave issues; they are historical attribution, not newly launched agents. The next actor should claim #34 and update the agent log before starting. Follow actual code dependencies and record component results separately. Missing optional Access/ACE does not prevent independent SQLite/Excel checks or continued development.

## Previous task reconciliation

| Original task | Retained source outcome | Continuing responsibility |
| --- | --- | --- |
| 1a #2 | Contract/schema validation | 6a structure; coordinate contract changes |
| 1b #3 | Reuse/license review | Retain provenance; SQLite explicitly authorized |
| 1c #4 | Privacy/location guards | Add SQLite database/journal exclusions |
| 2a #5 | Reviewed CSV importer | 7a/7b integrate with SQLite |
| 2b #6 | Access repository/recovery | 6b reuses semantics; 8b real ACE tests |
| 2c #7 | Excel shell/CSV reports | 7b portable files; 8b native refresh/recalculation |
| 3a #8 | Finance workflow | 7a removes Access-only runtime dependency |
| 3b #9 | Payoff engine | Reuse verified math and declared limitations |
| 3c #10 | Statements/net worth | Reuse engine with SQLite snapshots |
| 4a #11 | Payoff workbook | 7b file demo; 8b native acceptance |
| 4b #12 | Statements workbook | 7b file demo; 8b native acceptance |
| 4c #13 | Local PDF staging | Reuse explicit review; synthetic layout only |
| 5a #14 | Source/wheel package | 8a portable verification; 8b native release |

## Ownership

- 6a: model/inventory, scripts/database, tests/database.
- 6b: src/perfin_store/sqlite_backend.py, tests/sqlite.
- 6c: sqlite_backup.py, portability.py, tests/portability, portability guide.
- 7a: src/perfin_app, tests/integration_core, core runbook.
- 7b: scripts/core/portable_demo.py, tests/portable_demo, demo guide.
- 8a: root instructions/README, getting-started/release docs, package/release scripts, privacy/static guards, integration.
- 8b: native harnesses and operator evidence; no invented PASS.

## Evidence gates

| Evidence | Enables | Does not establish |
| --- | --- | --- |
| Contract/Python unit tests | Continued development | Real database behavior |
| Real on-disk SQLite integration | Portable SQLite workflow | ACE or native Excel behavior |
| Workbook/formula inspection | Inspectable XLSX demonstrations | Desktop recalculation, Power Query or VBA |
| Installed-wheel/portable acceptance | Tested portable release candidate | Universal platform/bank support |
| Actual Windows/ACE/Office evidence | Applicable native release claims | Unsupported profiles or financial assumptions |

Use `python scripts/release/check_all.py --offline` for isolated sequential suites. See [portable demo](runbooks/portable-demo.md) and [release verification](../release/README.md). Record exact results and unrun requirements in the tracker and verification record.

## Shared boundaries

One selected authoritative backend per data root. Existing roots retain their backend; ambiguous/mismatched roots are refused. Private data stays outside Git/sync by default. Synthetic cloud work is authorized; actual financial data is not automatically uploaded. No cloud production database, bank connection, payment execution or external AI fallback.

No native release check is marked passed by this plan. Development continues independently while #30 remains pending.
