# PerFin

Private local personal finance: **Excel frontend, Microsoft Access database, local Python automation.**

PerFin imports statements into a review queue, records approved transactions through an audited write path, exports Excel views and compares credit-card payoff plans. Optional modules provide personal statements/net worth and reviewed text-PDF extraction. Financial data stays in a local data folder outside this public source repository; external AI export is disabled by default.

**Status:** source implementation is available, with automated local checks and reproducible packaging tools. Windows/ACE and desktop Excel acceptance remain **pending**, so a production-ready Windows release is not yet certified. See the [tracker](https://github.com/NicoLeeVaz/PerFin/issues/1) for exact merged revisions and test evidence.

- [Install and run](docs/GETTING-STARTED.md)
- [Core import/review workflow](docs/runbooks/core/)
- [Payoff engine](docs/payoff/) and [Excel planner](docs/runbooks/payoff/)
- [Statements/net worth](docs/statements/) and [Excel statements](docs/runbooks/statements/)
- [Local PDF extraction](docs/runbooks/pdf/)
- [Release checks and packaging](release/README.md)
- [Contracts](docs/contracts.md), [privacy](docs/privacy/privacy-boundary.md), [research](research/README.md)
- [Agent execution plan](docs/EXECUTION-PLAN.md)

The production database is Access; Linux tests use a test-only fake adapter and do not certify ACE behavior. Payoff results clearly identify their supported calculation assumptions. Initial CSV/PDF profiles are synthetic, not verified against every bank. There are no payment execution or bank-connection features.
