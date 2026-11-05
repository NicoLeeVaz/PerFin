# PerFin

**Private local personal finance with SQLite, Python workflows and Excel files.**

Import statements into an explicit review queue, commit approved transactions to one local database, reconcile statements, generate reports/workbooks, compare payoff plans and view dated net worth. Access remains an explicit optional backend for a later native deployment; a Windows dependency no longer blocks development.

## Start here

- [Complete 18-table model](docs/database/model.md) and [offline clickable relationship explorer](docs/database/model.html)
- [Install and run](docs/GETTING-STARTED.md)
- [Run the synthetic portable demo](docs/runbooks/portable-demo.md): real SQLite, two statement cycles, three Excel workbooks and evidence
- [SQLite backup and full-history portability](docs/database/portability.md)
- [Core workflow](docs/runbooks/core/), [payoff](docs/payoff/), [statements](docs/statements/), [local PDF](docs/runbooks/pdf/)
- [Three new development waves](docs/EXECUTION-PLAN.md), [live tracker](https://github.com/NicoLeeVaz/PerFin/issues/1), [release verification](release/README.md)

```sh
python -m pip install .
perfin --data-root /outside/checkout/perfin-synthetic init --demo
perfin --data-root /outside/checkout/perfin-synthetic status
```

SQLite is the default only for new roots. Existing Access roots retain their backend; conflicting roots are refused. Use `--backend access` with a separate data root for the native path. Tables, exact integer cents, review, audit and exchange contracts are shared; engine-specific types, queries, locking and backup are explicitly mapped.

**Evidence is separate by platform:** real SQLite tests and generated XLSX checks support portable use. Native Access/ACE, desktop Excel recalculation, Power Query and VBA remain release requirements for those features. Cloud demonstrations use synthetic data only. Actual financial data stays local outside this public checkout and sync folders by default.

Initial CSV/PDF profiles are synthetic; real exports require validation. Optional AI export stays disabled. No bank connections, payment execution or telemetry.
