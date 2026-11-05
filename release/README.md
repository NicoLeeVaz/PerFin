# Release verification

The implementation is source-complete only when all components and integration tests pass. A supported Windows release additionally requires actual ACE and desktop Excel evidence. **Windows/Office acceptance is currently PENDING; no production-ready release is certified.**

## One local check command

From the checkout, with development dependencies installed:

```sh
python scripts/release/check_all.py --offline --report /outside/checkout/local-checks.json
```

On Windows choose a report under `%LOCALAPPDATA%\PerFin-acceptance`. This command runs every required suite in a separate interpreter, records counts and environment, then runs the privacy source scan. A missing suite returns 2. Any failure returns 1 even if a later suite passes. It prevents the earlier multi-command-shell problem where a final successful command masked a previous failure. Tests explicitly cover this behavior.

`--offline` blocks Python socket connections/resolution/sends through an audit hook, including child Python suite processes. This verifies the tested Python paths; it is **not** an OS firewall and does not prove Excel/Power Query's network behavior. Use airplane mode or an outbound firewall rule during the desktop checklist.

## Real Windows run

Use a clean checkout and a fresh synthetic data directory, with Python/ACE/Office of matching bitness:

```bat
python scripts\release\windows_acceptance.py --workdir "%LOCALAPPDATA%\PerFin-acceptance\release-test"
```

The runner executes the real Access acceptance harness, the integrated app harness when available, and a desktop Excel COM open/recalculate smoke test against independently specified fixture totals. The smoke test disables macros and does **not** replace Power Query/VBA checks. It records the Excel version and expected/actual figures. Non-Windows returns **BLOCKED (2)** without writing evidence.

Complete [the core Windows checklist](../docs/excel/windows-checklist.md), [payoff](../docs/runbooks/payoff/), [statements](../docs/runbooks/statements/) and [PDF](../docs/runbooks/pdf/) walkthroughs. Copy `manual-evidence.example.json` outside the checkout, fill the tested SHA/environment/operator and only mark observed checks PASS. Re-run with `--manual-evidence <path>` in a new work directory. The final report labels this portion **operator-reported**; it is not claimed as automated independent verification. Missing checks, a different revision or incomplete environment keep the result BLOCKED. Any FAIL wins over PASS.

Fresh installation/restore includes: install from the built wheel outside the checkout; initialize synthetic accounts; import two statement cycles; review and commit explicitly; repeat an import; reconcile; generate Excel; compare payoff and statement outputs; backup, restore to a new database, reopen and compare balances/history/schema. Keep existing private databases out of acceptance testing.

## Reproducible source package and wheel

Use the tested build tools pinned in `pyproject.toml`: setuptools 84.2.1 and wheel 0.48.0. For the complete synthetic test suite, install `.[test]`; ReportLab is a fixture-generation dependency, not part of ordinary finance use. The release manifest records the actual build-tool versions.

Commit/review all source first. Install the build tools declared by the project. The package command refuses dirty or untracked source, output inside the checkout, symlinks and runtime/private file types. It does not download dependencies.

```sh
python scripts/release/package.py --out /outside/checkout/perfin-build
```

The output contains a deterministic, sorted source ZIP, a locally built wheel, `SHA256SUMS` and a release manifest with the exact revision. ZIP timestamps and modes are normalized. Wheel builds set `SOURCE_DATE_EPOCH` to the commit time and `PYTHONHASHSEED=0`; compare hashes from two clean builds on the same declared toolchain before making a byte-reproducibility claim. Use `--source-only` when wheel prerequisites are unavailable; that is not an installable-wheel verification.

Install and smoke-test the wheel **outside the checkout**, with `PYTHONPATH` cleared and dependency downloads disabled (`--no-index --find-links <reviewed-wheelhouse>`). Run the included smoke script using that environment's Python:

```sh
/path/to/installed/venv/python -I /path/to/source/scripts/release/installed_smoke.py
```

It rejects modules/resources loaded from the source checkout; it checks installed schemas, builtin profiles, module manifests, engine outputs, generated workbooks and CLI help (including the optional PDF parser). Runtime data stays outside the package and outside synced folders.

## Evidence and limitations

- Source licenses and reuse provenance: [third_party](../third_party/README.md) and [reuse catalog](../research/reuse/catalog.md). Runtime dependencies belong to the project manifests; pin and review downloaded wheels before installation.
- No financial data, populated workbooks/databases, logs, statement PDFs, backups, credentials or private NoPii source belongs in the public release.
- Initial bank/PDF profiles are synthetic declared layouts. A passing fixture is not a claim of real-institution support.
- Optional AI export remains disabled. There are no bank connections or payment execution.
- A ZIP, wheel, local-test pass or closed issue does not prove Windows/ACE/Excel runtime acceptance. Attach the actual evidence before certifying the release.
