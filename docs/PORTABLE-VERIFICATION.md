# Portable verification — 2026-11-05

Status: portable implementation verified and merged in PR #33 as `af6a794502698ac2fad776fd5fa2e9327ad898ee` after user approval. The merged tree exactly matches the approved tree. Native release acceptance remains unexecuted in issue #30; the next Windows task is [#34](https://github.com/NicoLeeVaz/PerFin/issues/34). See [the agent log](AGENT-LOG.md) for ownership and handoff status.

## Independent integration review follow-up — 2026-11-05

The submitted head `edaab914ce52b5a59c60abbb7f12bebf25ae0d19` independently reproduced the **540 passing offline tests** and privacy scan. Further review found two gaps: new SQLite creation could consume orphaned recovery files, and the shared open-time compatibility check accepted a newer contract minor. Corrections are committed as `54c59d4d03af2494459fafef23efa79460a442ca` (tested tree `efcc18432dda8f84cf2fb163cb50e8594608640a`). Creation, backup restore and archive import now share a guard covering existing database files, recovery sidecars and dangling sidecar links. The repository refuses newer contract minors while retaining same-minor patch compatibility.

The corrected source independently passes **547 offline tests**, privacy scan, **31 synthetic demo checks**, inventory drift verification and an installed 0.3.0 wheel smoke outside the checkout. Seven new regression tests were added; defect cases were run against the submitted implementation before correction. The follow-up documentation changes no runtime code or tests. See [the integration review and pre-merge plan](PR-33-INTEGRATION-REVIEW.md) for commands, evidence distinctions, package hashes and limitations. The approved candidate was subsequently merged as `af6a794`; issues #24–#29 are closed. Native Windows/Office acceptance is still **UNRUN** in #30.

## Original implementation verification record

Tested source revision: `a2a88604ae946fbcfb96c66774e71ac649dd09fb`, including current main `535153f20f5915f1f85a4629d8251f0cf4e6006e` (optional finance toolbox) and the previously merged 2a CSV importer. Subsequent changes to this record are documentation only.

Environment: Linux, Python 3.12.14, SQLite 3.53.1. Synthetic financial data only.

## Results

`python3 -B scripts/release/check_all.py --offline --report <outside-repo.json>`: **540 tests PASS**, plus repository privacy scan. Python socket connections/resolution denied during suites; this is not an OS firewall guarantee.

| Suite | Tests | Result |
| --- | ---: | --- |
| contracts/tests | 41 | PASS |
| config/privacy | 53 | PASS |
| research/reuse/harness | 20 | PASS |
| tests/import | 81 | PASS |
| tests/store | 111 | PASS |
| tests/excel_core | 66 | PASS |
| tests/integration_core | 24 | PASS |
| tests/payoff | 26 | PASS |
| tests/statements | 15 | PASS |
| tests/excel_payoff | 12 | PASS |
| tests/excel_statements | 11 | PASS |
| tests/pdf | 21 | PASS |
| tests/acceptance | 6 | PASS |
| tests/database | 4 | PASS |
| tests/sqlite | 19 | PASS |
| tests/portability | 17 | PASS |
| tests/portable_demo | 3 | PASS |
| tests/extras | 10 | PASS |
| privacy-scan | 0 | PASS |

Installed wheel built offline with no dependency download, installed in a separate virtual environment, and checked outside source with `python -I -B scripts/release/installed_smoke.py`: PASS. It verifies packaged resources, a real SQLite reviewed CSV import, persistence, backup/restore equality, calculation engines, generated workbooks and CLI help.

Synthetic portable demo: **31 checks PASS**, six imports, sixteen transactions, four transfers, six reconciliations; checking balance 234000 cents, cards -17600/-6200 cents, net worth 210200 cents. Three XLSX files generated and inspected for expected structures, formulas and external links. This does not execute desktop Excel formulas, Power Query or VBA.

## Independent review and regression evidence

Five implementation agents worked on schema, storage, portability, app integration and cloud workbooks. An independent sixth agent reviewed integration. Four findings were fixed and independently rechecked: unsupported archive version acceptance; permissive backup/archive/restore files; inconsistent concurrent multi-table reads; permissive newly created app roots.

Deterministic two-connection WAL interleaving proves coherent read snapshots and reader cleanup. The old repository failed three regression tests with five assertions; fixed code passes. Existing command transactions are reused. Duplicate recovery after explicit review and repeated same-second transfer linking with descending UUIDs pass against real SQLite. The current contract version assertion and legacy fake-adapter suites also pass; fake results remain distinct from SQLite evidence.

## Remaining release requirements

- Windows/ACE: actual create/open, constraints, types, exact cents, atomic success/rollback, replay, duplicate recovery, transfer chronology, report parity and backup/restore.
- Desktop Excel: recalculation, offline behavior, Power Query, VBA and relevant Access design inspection.
- Future SQLite-to-Access import: implement and verify native destination mapping and full-history equality. The current archive exports/imports SQLite with audit/staging/history; it is not an implemented Access importer.
- Optional third-party workbook activation still requires its own license, hash, synthetic math and desktop review. Link catalog presence is not acceptance.

These are release requirements for the applicable native features, not development blockers. No native acceptance claim or Wave 2 native PASS is made.
