# Access recovery verification — 2026-11-05

The three reported defects were already fixed on the verified main revision.
This follow-up adds two importer/backend integration tests, fixes the separate
zero-limit utilization query defect, and extends the Windows acceptance harness.
Contracts and native acceptance gates remain unchanged.

## Revisions and existing corrections

- Verified main: `b2ff8bdfdf931c907d9564f4b58c132c042dfda0` (including merged 2a importer #19 and integration #22).
- [Fix commit](https://github.com/NicoLeeVaz/PerFin/commit/19313626f2faacb5f4485768f08b10bd5eabfa5d):
  `19313626f2faacb5f4485768f08b10bd5eabfa5d`.
- [PR #21](https://github.com/NicoLeeVaz/PerFin/pull/21) already merged as
  `bf527c3425cae4db9ebd63102c00d40af56e7d40` at 2026-11-05 01:38:21 UTC.
  Its later review superseded the quoted HOLD for these source defects.
- [Tracker #1](https://github.com/NicoLeeVaz/PerFin/issues/1) still leaves Wave 2
  unchecked. Source completion does not pass the native gate.

| Finding | Current implementation | Deterministic existing regression |
| --- | --- | --- |
| Commit discovers a duplicate initially marked `none`, but explicit resolution fails | Allow resolution only when an actual same-account ledger collision or earlier approved same-batch source-ID collision exists; audit the real previous status | `SourceIdsWithinBatch.test_commit_collision_can_be_resolved_and_retried` and `test_ledger_collision_can_be_resolved_and_retried` |
| Same-second transfer relinking restores an obsolete category | Select the pre-link audit snapshot with the highest transaction `row_version`; UUID and timestamp ordering are irrelevant | `Transfers.test_reused_link_id_restores_latest_splits_at_same_timestamp`: descending UUIDs, fixed clock, intervening recategorization and description edit |
| Setup assertion expects contract 1.0.0 | Compare stored metadata with `contracts/VERSION` (currently 1.0.1); retain schema/check/view assertions | `SetupOnFake.test_ansi92_creates_everything` |

## Changes

`tests/store/test_import_recovery.py` uses the merged `stage_file`, builtin
synthetic CSV profile and production `ImportView` with the test-only fake store.
No importer results are edited to force the desired state.

1. Two CSV rows share a source ID. The importer flags the second as `possible`;
   approval fails atomically until explicit `confirmed_distinct` review. Both
   then commit, producing the independently expected balance of 244100 cents.
2. A CSV row is staged and approved while its source ID is absent from the ledger.
   A different CSV with that ID commits first. The pending commit is rejected
   atomically, explicit review succeeds, and retry preserves both legitimate
   transactions. A further commit is a replay with no changes.

Both tests assert validated contract documents, no parser writes, exact balances,
and transaction counts. The race test compares all fake tables on refusal and
replay, including command logs, audit logs, and versions.

The separate [zero-limit P2](https://github.com/NicoLeeVaz/PerFin/pull/21#discussion_r4475580803)
is corrected by dividing by `IIf(q.credit_limit_minor = 0, Null, q.credit_limit_minor)`.
This prevents a zero divisor even when both branches evaluate. Microsoft documents
[IIf's eager evaluation](https://support.microsoft.com/en-gb/access/functions/iif-function).
Missing and zero limits yield null utilization; positive limits preserve the
existing half-to-even rounding. Two additional tests cover Python/CSV output and
the SQL divisor guard. The fake does not execute the report query. Three new
Windows harness checks execute it on real ACE for missing, zero and positive
limits, expecting null, null and 2500 basis points for 12500 cents owed against a
50000-cent positive limit. The general view-versus-export check also covers them.

The corrected SQL is installed when creating a new database. Existing databases
retain their saved query until it is refreshed; the existing
`access/setup/PerfinSetup.bas` / `CreatePerfinReportQueries` helper can recreate
the saved report queries from the updated SQL in full Access. Follow the setup
guide and verify on a synthetic copy first. This change does not implement an
automatic migration or modify any existing user database.

## Executed checks

Environment: Linux, Python 3.12.14, synthetic data only. No Windows/Office/ACE.
The unmodified main baseline passed 107 store, 41 contract, 81 importer and 11
integration tests. The final offline release runner executes each suite sequentially:

```sh
python3 -B scripts/release/check_all.py --offline --report <outside-checkout>/perfin-final-checks.json
```

It passed all **473 tests across 13 suites**, plus the privacy scan. The offline
guard denies Python socket access; this is not an OS firewall or native-runtime test.
Relevant final suite counts:

| Command | Result |
| --- | --- |
| `python3 -B -W error -m unittest discover -s tests/store -q` | 111 passed |
| `python3 -B -W error -m unittest discover -s contracts/tests -q` | 41 passed |
| `python3 -B -W error -m unittest discover -s tests/import -q` | 81 passed |
| `python3 -B -W error -m unittest discover -s tests/integration_core -q` | 11 passed |
| `python3 -B -W error -m unittest discover -s config/privacy -q` | 52 passed |
| `python3 -B config/privacy/perfin_privacy_checks.py scan-repo .` | OK |
| `python3 -B tests/store/windows_acceptance.py` | BLOCKED, exit 2 |

The other suites passed: reuse 20, Excel core 66, payoff 26, statements 15,
Excel payoff 12, Excel statements 11, PDF 21, release acceptance 6.

Negative control: temporarily substituted only `repository.py` from pre-fix
`fbad71d61c87293892fb544d625b9d51985f158d`, retaining current main contracts/tests.
The two existing recovery regressions and new CSV race regression all failed
with `E_BATCH_STATE`; the existing transfer regression restored
`exp.uncategorized` instead of `exp.groceries`. All four failed as expected.
Restored the current source byte-for-byte before the final passing run.
The new SQL source regression also fails against the old report query, then
passes against the guarded query. That is source-level evidence, not ACE execution.

An initial parallel run caused one store safety-test failure because the
integration packaging test temporarily creates `access/synthetic-private-decoy.accdb`.
The packaging test cleans it up. Running these suites sequentially avoids this
shared-fixture collision; the complete sequential run above passed. Do not run
these two suites concurrently in the same checkout.

## Remaining acceptance — Wave 2 stays blocked

Use compatible Windows/Python/Office/ACE bitness and the dependency versions in
`pyproject.toml`; follow `docs/GETTING-STARTED.md`. Use synthetic data outside the
checkout and outside sync folders. From an installed/source checkout:

```bat
set PYTHONPATH=src
py -3 -m perfin_store envcheck
powershell -NoProfile -ExecutionPolicy Bypass -File access\setup\Get-PerfinEnvironment.ps1
py -3 tests\store\windows_acceptance.py --workdir "%LOCALAPPDATA%\PerFin-acceptance"
py -3 tests\integration_core\windows_acceptance.py --workdir "%LOCALAPPDATA%\PerFin-acceptance\integration-new"
```

Required evidence: real create/open and metadata, CHECK/fallback behavior, exact
CURRENCY cents and driver types, atomic success and injected-failure rollback,
replay/stale-version refusal, report-query versus CSV parity, exclusive backup
behavior, and restore matching balances/history/schema. Preserve the generated
`acceptance-evidence.json` and `integration-evidence.json`, identifying the tested
commit and environment. Also replay the two duplicate-recovery paths and
same-second transfer relinking on ACE; the Python regressions alone cannot
establish their native behavior.

Full Access design-view inspection and the desktop Excel/Power Query/VBA checks
in `docs/excel/windows-checklist.md` remain separate Wave 2 requirements.
Successful source merging, fake-adapter tests, or a closed issue do not pass them.

The new zero/null/positive-limit query checks must also pass on ACE. A Linux
unit-test pass cannot establish Access SQL syntax, null propagation or driver behavior.

## Publication scope

The user's follow-up instruction to finish the work authorizes publication and
merge of this focused correction. PR #21 is already merged, so this work uses a
new follow-up PR. Native gate checkboxes remain unchanged; the Windows evidence
above is still required.
