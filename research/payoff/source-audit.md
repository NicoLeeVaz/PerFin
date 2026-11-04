# Payoff tools: source audit

Date: 2026-11-04. I read the source files, licenses and tests directly from full clones kept **outside** this repository. I ran tests and wrote reproduction harnesses, which live in [`experiments/upstream/`](experiments/upstream/). Those harnesses load the external clone at run time. **No upstream code was copied into PerFin.**

## Summary decision

| Candidate | Commit inspected | License (file read) | Executed? | Decision |
| --- | --- | --- | --- | --- |
| [tomithy83/debt-simulator](https://github.com/tomithy83/debt-simulator) | `3c03137cde51d82bd15628cadcb59a29ba79888b` (2025-05-16) | MIT, © 2025 tomithy83; blob `8dbc5be5…` | Yes: upstream test suite plus 7 reproductions | **Do not fork.** Use only as a behavioural reference. |
| [duaneking/unburyme](https://github.com/duaneking/unburyme): copy of Jordan Santell's unbury.me source; GitHub reports it as not a fork | `c4e6119f2ea7575de5144275e4795dea28231b24` (2011-06-26) | MIT, © 2011 Jordan Santell; blob `d88a76fd…` | Yes: Node harness, 3 reproductions | **Do not reuse.** Licensed source is available, but the calculation loop is defective and DOM-coupled. |
| [bryankemp/financial-debt-optimizer](https://github.com/bryankemp/financial-debt-optimizer): source behind the Read the Docs lead | `16b6691bce77f036a81625c9f9b02995cb4129a9` (2026-10-04) | BSD-3-Clause, © 2025 Bryan Kemp; blob `32af4fe2…` | Yes: pytest suite (304 passed, 2 failed) plus 3 probes | **Do not adopt as the engine.** It is a whole cash-flow application. Possible reference for Excel I/O patterns only. |
| `jsantell/unburyme` | — | — | No | A direct request in this session got HTTP 403 from the session proxy (inconclusive); the previous review recorded a 404. Not relied on. |

**Recommendation.** Reuse no candidate's engine. The component validated in this phase is PerFin's own small reference engine, [`payoff_ref.py`](experiments/payoff_ref.py) (standard library only, about 440 lines), with its independent oracle and fixtures. Upstream projects are kept only as behavioural comparators.

## 1. tomithy83/debt-simulator

**Files read.**

| File | Blob |
| --- | --- |
| `strategies.py` | `5ec7dd1fc79b31a33ee732553915098ea20ee17d` |
| `simulator.py` | `f385f7c87048016ebcd2d158da3e4761280b9a78` |
| `main.py` | `4cd9b78d2c79d7ea1ed52d41dad188cffd545776` |
| `tests/test_strategies.py` | `637150e198bf57f6a464b27c27bfe453a5084390` |
| `requirements.txt` (UTF-16 encoded; pins pandas 2.2.3, numpy 2.2.5) | — |
| `LICENSE` | — |

These blob SHAs match the ones recorded in the plan.

**Upstream test result (executed).** `python -m unittest tests.test_strategies` **errors** with `TypeError: 'int' object is not subscriptable`. The test passes a plan of ints, but `allocate_extra_funds_fully` expects dicts. The project has no passing test of its calculations.

**Inspected functions.**

- `simulate_repayment` uses one month loop and an `extra_pool` that grows by each paid-off card's `MinPayment`.
- `calculate_monthly_interest_and_base` computes float interest as `Remaining × Rate/100/12`.
- `apply_payments`, `allocate_extra_funds_fully`, `split_50_50_strategy`, `proportional_interest_strategy` and `generate_strategy_summary` were read in full.
- Ranking is re-evaluated every month. Python's stable sort breaks ties by input order.
- The "reverse snowball" strategy is literal largest-balance-first.

**Reproduced defects** ([`debt_simulator_repro.py`](experiments/upstream/debt_simulator_repro.py), run against the pinned commit):

| ID | Defect | Observed |
| --- | --- | --- |
| R1 | `split_50_50` merges dicts with overwrite. If one card is both highest-rate and lowest-balance, half the extra is lost. | min $100 + extra $200 should pay $300; **paid $200** |
| R2 | In a payoff month, the unused part of that card's minimum is not spilled to other cards. It only rolls into the pool next month. | $200 budget; **$150.50** paid in month 1 |
| R3 | Summary "Payoff Month" is the last *simulated* month, even with a balance remaining. | Balance $9,684.59 after 6 months, yet a payoff month is reported |
| R4 | Balances ≤ $0.01 are set to zero, and money is float. | $100.009 marked paid after $100.00 |
| R5 | `proportional` strategy drops capped shares instead of reallocating them. | $355 available; **$135.25** paid |
| R6 | Negative amortization runs silently to the horizon. | $5,000 → $6,134.16, no flag |
| R7 | Rounded report rows do not reconcile. | Up to $0.01 per row |

Concerns noted in the plan:

- **50/50 overwrite**: reproduced (R1).
- **Unspent final-payment capacity**: reproduced (R2).
- **False payoff at the horizon**: reproduced (R3).
- **Fixed minimum inputs**: confirmed statically. `MinPayment` is a constant per loan, so there is no declining-minimum rule.

**Reuse decision.** The license is usable (MIT), but the engine needs a rewrite of money handling, allocation, reporting and tests. That leaves nothing worth forking.

## 2. unbury.me (duaneking/unburyme)

**Files read.**

| File | Blob |
| --- | --- |
| `src/LoanApp.js` | `d03f0ebdef9daf9b8bb83601400c1b0bda957212` |
| `src/Date.js` | `06aa33a1a62991e5ade0840653be79863166838a` |
| `src/Config.js` | `f54ec74cc0594a36bc367cda682918895c4d126a` |
| `src/Loan.js` | `9602f1d914ee0d9606a07160d273052a8d4f87e1` |
| `src/Unburyme.js` (namespace header that states the MIT license) | — |
| `LICENSE` | — |

The repository has 30 commits, all from 2011. The repository has no tests. Provenance: the file headers name `github.com/jsantell/unburyme` and Jordan Santell. This copy is the verifiable licensed source; the site's own claim was not relied on.

**Executed** with [`unburyme_harness.js`](experiments/upstream/unburyme_harness.js) under Node v22 with DOM stubs:

| ID | Defect | Observed |
| --- | --- | --- |
| U1 | `sortLoans` selection sort uses strict `> maxValue` starting from 0. A 0% loan (avalanche) is never selected, and uid 0 is duplicated. | Order `[0,0]` for loans at 20% and 0% |
| U2 | When a payoff frees money mid-month, the redistribution loop re-applies the *entire* monthly payment of every unpaid loan, so principal is double-counted. | Month-1 balance **$4,585.00** vs conservation value **$4,643.33** |
| U3 | Ordering is computed once (static) and never re-ranked. | Static check |

Interest is float `balance × APR/12`, minimums are fixed, and there is no horizon or failure reporting besides "year > 2200".

## 3. bryankemp/financial-debt-optimizer

**Files read.**

| File | Blob |
| --- | --- |
| `debt_optimizer/core/debt_optimizer.py` | `32fb812451c3f6f6cd65b3f0b161ed1c62d61445` |
| `debt_optimizer/core/financial_calc.py` | `061f6efb1d7bc71d9d27b4972d71d910a54bf680` |
| `debt_optimizer/core/balance_updater.py` | `eea1033ce1bbb618e88d2fc84c5dfa017ab5362a` |
| `requirements.txt`, test inventory, `LICENSE` | — |

`_run_payment_simulation`, `rank_debts_by_avalanche` / `rank_debts_by_snowball` and `Debt.calculate_interest_charge` were inspected. The project has 71 commits.

**Upstream tests (executed).** I ran pytest in a local venv with pandas 2.3.3, numpy 2.5.4 and matplotlib 3.11.2: **304 passed, 2 failed**. Both failures are in `tests/test_visualization.py`, with `TypeError: object of type 'PieContainer' has no len()`. This looks like an incompatibility with the newer matplotlib, not a calculation failure.

**Static findings.**

- Money is float throughout, with a `Decimal` used only in the minimum-reserve helper.
- Strategies are ordered **once** (`sorted(... interest_rate)`), with no explicit tie key.
- The engine is a chronological bank-balance/income/expense event simulation.
- It has a hard-coded 10-year horizon.
- There is no promotion, deferred-interest or APR-bucket support (no matches in the source).

**Probes** ([`fdo_probe.py`](experiments/upstream/fdo_probe.py)):

| ID | Defect | Observed |
| --- | --- | --- |
| F1 | Unpaid interest is not capitalised. When the payment is below the interest, only the paid portion is booked and the balance stays flat. | 12 payments ≤ $20 against about $104.17/month interest; reported balance **$5,000.00** |
| F2 | The schedule starts at `date.today()`. | Same inputs on different days produce different schedules |
| F3 | The minimum payment is reduced to the available bank balance (`min(required, bank_balance)`). The observed schedule contains $0 payments with no infeasibility status. | Shortfalls are silent |

**Reuse decision.** The license (BSD-3) and test discipline are good, but the scope is a whole application and the core calculation has F1/F3. Its `excel_io` module could be studied later as an XlsxWriter/openpyxl pattern. It does not fit as the payoff engine.

## 4. Existing PerFin candidates (GnuCash, Actual Budget, MMEX)

These were researched earlier as ledger applications ([candidates.md](../candidates.md)). No payoff-optimizer source was inspected in them in this phase, and no complete optimizer is assumed to exist in them. Their role remains ledger/export references for the shared account IDs and reconciled balances (see [net-worth spec](../net-worth/module-spec.md#integration-boundary)).

## 5. Reproducing this audit

Clone each repository outside PerFin and check out the SHA above.

Install dependencies in a throwaway venv:

- debt-simulator: pandas 2.2.3, python-dateutil.
- financial-debt-optimizer: its `requirements.txt` packages plus pytest.

Then run, giving each command the path of its matching clone:

```bash
python debt_simulator_repro.py /path/to/debt-simulator
```

```bash
node unburyme_harness.js /path/to/unburyme
```

```bash
python fdo_probe.py /path/to/financial-debt-optimizer
```

Each line prints `REPRODUCED` or `NOT REPRODUCED`. The results above are from 2026-11-04 in a Linux container with Python 3.13 and Node 22.

## Limits

- This was not a security audit.
- The financial-debt-optimizer probes exercised two behaviours, not the whole application.
- unbury.me's UI files (`Graph.js`, `ResultBar.js`, `interface.js`) were only skimmed for input parsing.
- Regulatory pages could not be fetched in this session because the network policy blocked consumerfinance.gov, ecfr.gov, govinfo.gov, federalregister.gov and law.cornell.edu. Code inspection used GitHub only.
