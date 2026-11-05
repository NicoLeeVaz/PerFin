# Portable verification — 2026-11-05

Status: portable implementation verified; merge approval pending. Native release acceptance remains unexecuted in issue #30.

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
