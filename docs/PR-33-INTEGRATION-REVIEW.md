# PR #33 independent integration review — 2026-11-05

Result: the portable SQLite source is ready for explicit user merge approval
after two consequential gaps were corrected. Merge has not been authorized or
performed. Native release acceptance remains pending in [#30](https://github.com/NicoLeeVaz/PerFin/issues/30).

## Revisions and evidence provenance

| Item | Revision / result |
| --- | --- |
| Current main used for comparison | `535153f20f5915f1f85a4629d8251f0cf4e6006e` |
| Submitted PR head reviewed independently | `edaab914ce52b5a59c60abbb7f12bebf25ae0d19` |
| Correction commit independently tested | `54c59d4d03af2494459fafef23efa79460a442ca` |
| Exact tested tree, including regression tests | `efcc18432dda8f84cf2fb163cb50e8594608640a` |
| Original verification's intermediate revision | `a2a88604ae946fbcfb96c66774e71ac649dd09fb`, as reported in the original record; this review tested the actual submitted head instead |

The submitted branch was one commit ahead of main and zero behind. It includes
the merged CSV importer and optional finance toolbox. Corrections extend that
branch without rewriting its history or changing the SQLite-first architecture.
The follow-up documentation commit changes no runtime source or tests.

The original record's installed-wheel smoke, 31 demo checks and four earlier
implementation fixes were initially reported evidence. This review independently
ran the submitted head's entire 540-test suite and privacy scan, then ran the
corrected source's complete suite, demo and installed-wheel smoke. Existing
regressions for the four earlier fixes pass; their original intermediate agent
runs were not re-created or counted as new independent executions.

## Findings corrected

| Finding | Consequence and correction | Regression evidence |
| --- | --- | --- |
| P2: new SQLite creation ignored orphaned sidecars | With no main file, creating the target succeeded beside existing `-wal`/`-journal` files and deleted their synthetic sentinel contents. A shared target guard now refuses the database or any recovery sidecar before SQLite opens it. Restore/import also refuse dangling sidecar links instead of following or consuming them. | Real-file creation with each sidecar and dangling link; restore/import with each dangling sidecar. Existing files/links remain untouched and no target is created. |
| P2: repository opening accepted a future contract minor | The inherited shared compatibility check checked the contract major only. The new SQLite open/backup paths could accept `1.1.0` while archive import refused it. Repository construction now passes the supported minor to the compatibility check, so open and backup fail closed. | Future-minor open is refused without changing bytes; backup refuses and removes its partial set. Contract `1.0.0` and `1.0.999` remain readable under same-minor patch policy. |

Seven regression tests were added. The defect cases failed or errored against
the submitted implementation before correction, then passed with the fixes.
The same target guard is reused across creation, restore and archive import so
the recovery-file policy does not drift between entry points.

## Integration assessment

| Area | Independently checked evidence and conclusion |
| --- | --- |
| Model/integration | All 18 canonical tables, columns, keys, checks and indexes are exercised on real SQLite. Generated inventory/explorer drift check passes. CLI tests exercise default SQLite, persisted selection, legacy Access selection and dual-backend refusal. |
| Exact data | Bounded integer cents, scalar constraints, foreign keys, persistence, duplicate review/recovery and same-second transfer chronology pass on real files. Contract remains 1.0.1; table model remains unchanged. |
| Atomicity | An injected third-split failure rolls back the full table state and permits retry. Replay, stale versions, exclusive writer contention and close-with-uncommitted-data checks pass. Existing shared command transactions are retained. |
| Read consistency | Deterministic two-connection WAL interleavings verify coherent bundle, transaction, report, summary, constructor and staging reads. Reader exceptions release only the owned read transaction. |
| Backup safety | Live WAL backup captures committed pages, excludes uncommitted changes and produces a self-contained snapshot. Hash/integrity/FK/summary checks, all-table restore equality, tamper rejection, refusal to overwrite and failed-restore cleanup pass. Recovery-file refusal now covers all entry points. |
| Portability | All-table JSON roundtrip preserves staging, audit/command history and versions. Invalid versions, money, missing tables and relationships are refused; final reopen failure removes the new target. Access conversion remains unimplemented. |
| Compatibility | Shared compatibility now refuses newer contract minors. Same-minor patches remain accepted. Existing fake Access suites pass, providing repository-level evidence only. Native ACE driver behavior is still unexecuted. |
| Privacy/package | Synthetic inputs only. New-root and backup/archive/file permission tests pass on POSIX. Python network denial, static privacy scan, packaging exclusions and installed resource resolution pass. No private runtime data is added to source. |

## Independent results and reproducible commands

Environment: Linux, Python 3.12.14, SQLite 3.53.1, setuptools 84.2.1,
wheel 0.48.0, openpyxl 3.1.5, et-xmlfile 2.0.0, pypdf 6.10.0 and
reportlab 4.4.9. All financial data was synthetic.

| Execution | Result |
| --- | --- |
| Submitted head: `python -B scripts/release/check_all.py --offline --report <outside-checkout>/original-tests.json` | 540 tests PASS across 18 suites; privacy scan PASS |
| Corrected tree: same command with a fresh external report | 547 tests PASS across 18 suites; privacy scan PASS |
| Corrected SQLite suite | 23 tests PASS |
| Corrected portability suite | 20 tests PASS |
| `python -B scripts/database/build_model.py --check` | Model current |
| `python -B scripts/core/portable_demo.py --out /tmp/perfin-pr33-review-demo-20261105` | 31 checks PASS; 16 transactions, 6 imports, 4 transfers and 6 reconciliations; three workbooks inspected |
| `python -B scripts/release/package.py --out /tmp/perfin-pr33-review-build-code` | Clean corrected commit packaged offline; source ZIP and 0.3.0 wheel created |
| Installed wheel smoke below | PASS: packaged resources, real reviewed SQLite import/persistence/backup/restore, engines, generated workbooks and CLI help |
| `git diff --check` | PASS |

The demo independently reproduced checking 234000 cents, card balances -17600
and -6200 cents, and net worth 210200 cents.

Installed smoke was run from `/tmp`, outside the checkout:

```sh
python -m venv --system-site-packages /tmp/perfin-pr33-review-venv
/tmp/perfin-pr33-review-venv/bin/python -m pip install --no-deps --no-index /tmp/perfin-pr33-review-build-code/perfin_local-0.3.0-py3-none-any.whl
/tmp/perfin-pr33-review-venv/bin/python -I -B /path/to/PerFin/scripts/release/installed_smoke.py
```

This separate environment reused the already installed declared dependencies;
PerFin itself was installed from the built wheel. No dependencies were downloaded.
The isolated interpreter smoke rejects source-checkout module/resource resolution.
This was not a from-empty dependency installation or a byte-reproducibility test.

Packages built from corrected commit `54c59d4d03af2494459fafef23efa79460a442ca`:

| Artifact | SHA-256 |
| --- | --- |
| `PerFin-54c59d4d03af-source.zip` | `67b94f82d318c6dee5d9e82a089d1283211b033b2a20d522dd62486ddf9c85bb` |
| `perfin_local-0.3.0-py3-none-any.whl` | `be905dd9b3601d20e28caa341d2c1ff22c08e7a9835d869214f628fc7b372988` |

These hashes identify the tested code package, before the documentation follow-up.
No hosted CI or external security-scan success is claimed. No PR workflow runs
or commit status checks were present for the corrected code commit when inspected.
The GitHub Codex review is separate evidence; the latest review must be checked
against the actual final head before merge.

## Merge and issue reconciliation plan — awaiting approval

1. Obtain explicit user approval for PR #33's final head. Do not enable auto-merge.
2. Re-read PR head, current main, mergeability and latest review threads. Require
   the approved head and reviewed main above; if either moved, assess the change
   and repeat affected integration checks before proceeding. Do not treat a
   review of an older SHA as a review of the approved head.
3. Squash-merge #33 into `main`, with GitHub's expected-head SHA set to the
   approved final head. Confirm the merge result and resulting commit/tree.
4. Verify that the merged source tree matches the approved final tree. If no
   source changed during merge, reuse that exact tree's test evidence; any new
   difference requires investigation and affected verification.
5. Confirm that closing references reconcile #24–#29. Update tracker #1 with
   the actual merge SHA, 547-test evidence and completed portable wave status.
6. Keep #30 open, leave native acceptance unchecked, and preserve any older
   issues whose remaining acceptance requires a native host. Keep tracker #1
   open while its native release requirements remain outstanding.

No issue is closed as part of this pre-merge review.

## Remaining limitations

- Windows/ACE create/open, types/constraints, transactions, recovery, exact cents,
  report parity and backup/restore are UNRUN, tracked separately in #30.
- Desktop Excel recalculation, Power Query and VBA are UNRUN. OOXML/formula
  inspection and Python calculations do not establish native Excel behavior.
- The optional GUI was inspected in source; manual GUI interaction was not run.
- SQLite-to-Access full-history import is unimplemented. Matching entities or
  renaming a database is not a verified conversion.
- Original statement/PDF evidence files are external and need separate backup.
  Archives and backups contain private history when used with real data.
- Python network denial is not an OS firewall guarantee; POSIX mode tests do
  not establish Windows ACL behavior. Synthetic profiles are not real-bank
  compatibility claims.

These native gaps remain release requirements for their respective features,
separate from continued development and the verified portable SQLite candidate.
