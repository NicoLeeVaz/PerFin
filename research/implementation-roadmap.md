# Implementation roadmap: payoff planner and personal statements

Date: 2026-11-04. Status: **proposed sequence**. Nothing here is a production build, a bank connection or a payment instruction.

## Recommendation

1. **Build PerFin's own small payoff engine.** Start from the validated reference in [`payoff/experiments/payoff_ref.py`](payoff/experiments/payoff_ref.py) and its fixtures. Do not fork an upstream project. Each audited candidate failed basic conservation or reporting checks ([source audit](payoff/source-audit.md)).
2. **Keep Excel as the interface and run the engine locally.** Python + SQLite is the lower-risk engine host, because the reference, oracle and tests already run there with the standard library only. Access/VBA stays viable if Access forms win the [ledger trial](README.md#first-implementation-experiment). It would need a VBA port that reproduces [`results.md`](payoff/experiments/results/results.md) exactly.
3. **Report avalanche as the cost baseline and the user's strategy as a measured preference.** Use largest-first, snowball or the near-APR hybrid, and always show `Δ cost` and `Δ months`. Label avalanche a *comparator* whenever promotions or deferred interest are present. Two executed counterexamples show it is not optimal there.
4. **Build the statements module after the card ledger reconciles.** Use shared account IDs, read-only card balances and its own valuations ([module spec](net-worth/module-spec.md)).

## Verified reuse candidates

| Component | Status | Use |
| --- | --- | --- |
| PerFin `payoff_ref.py`, `oracle.py`, `daily.py` and fixtures | Executed: 26 unit tests, 210 invariant-checked schedules, 6 oracle cases, all passing | Seed for the engine and regression suite |
| PerFin `statements_demo.py` | Executed: 12 tests passing | Seed for statement identities and tests |
| tomithy83/debt-simulator (MIT) @ `3c03137` | Executed; 7 defects reproduced | Behavioural reference only |
| unbury.me source (MIT) @ `c4e6119` (duaneking copy) | Executed; 3 defects reproduced | Not reused |
| bryankemp/financial-debt-optimizer (BSD-3) @ `16b6691` | Executed: 304 pass / 2 fail; 3 probe findings | Possible reference for Excel I/O patterns; not the engine |
| XlsxWriter / openpyxl / xlwings (from [local architecture](local-architecture.md)) | License-screened earlier, not executed in this phase | Excel output / bridge when the UI is built |

## Minimum implementation sequence

1. **Card ledger trial.** Run the existing [MVP acceptance scenarios](credit-card-mvp.md#acceptance-scenarios) on synthetic data and choose Access or SQLite. *Needs the user's Windows/Office/Access check.*
2. **Engine package.** Promote `payoff_ref` into a module with the input schema of math-spec §2.
   - Read card IDs, statement balances, minimums and APR buckets from the reconciled ledger.
   - Keep fixtures and `results.md` as golden regression files.
3. **Excel I/O.** Inputs come from typed tabs or a read-only export. The engine writes a strategy-comparison tab and per-card schedules, with status and flags in visible columns.
   - Calculations stay out of formulas, or any formula port must match the golden files.
   - Imported text stays text.
4. **Statement-date accrual (M2).** Daily balance per cycle using actual close and due dates, posted payment dates, residual interest and issuer-declared rounding.
   - Keep M1 as a labelled quick estimate.
   - Validate against real statements privately, outside this repository.
5. **Promotion-aware comparator.** Implement and test a forward-looking rule (for example, deadline-first for deferred balances) and an LP or exact-search optimiser for small cases. Then show the user's choice against both avalanche and the best found plan.
6. **Statements module.** Add `Account` extensions, valuations, holdings detail, mortgage splits and the bridge. Port the 12 identity tests, then add the proposed tests in the module spec.
7. **Later.** Retirement scenarios in a separate scenario area (assumptions, never observed balances); optional after-tax estimate views.

## Windows / Excel / Access trial still needed

- Office build and bitness, and whether Access is installed. Then the ODBC/ACE driver needed if Python reads Access.
- VBA rounding: `Round()` uses banker's rounding, so confirm `WorksheetFunction.Round` or integer-cent routines on the actual build.
- Whether the local Python install is permitted, and whether xlwings is needed for buttons or whether file export/import is enough.
- OneDrive or other sync on the data folder. Keep real workbooks and databases outside this public repository.

## Open user choices (unset; nothing is assumed approved)

| Choice | Options researched |
| --- | --- |
| Preferred ordering | Largest-first (literal), snowball, near-APR hybrid with smallest or largest preference |
| Re-ranking | Monthly re-rank (default) vs lock-until-paid. Matters for largest-first: f14 shows 23 target switches and +$75.78. |
| Near-APR band | 0 / 0.5 / 1 / 2 pp researched; no default |
| `max_extra_cost_dollars`, `max_payoff_delay_months` | Unset. Strategies are reported, never auto-approved. |
| Minimum forecast rule per card | `fixed`, `pct`, or `pct + interest` with floor; or the issuer formula from the agreement |
| Liability view for joint debts | Legal (default) vs economic share |
| Valuation sources and staleness thresholds | See module spec |

## Not authorized by this phase

Production deployment, payment execution, bank or account connections, real data in this repository, asset-sale or retirement-withdrawal recommendations, and sending data to third parties.
