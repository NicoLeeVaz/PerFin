# Research plan: credit-card payoff and personal financial statements

Date: 2026-11-04. Status: research brief and proposed acceptance criteria, not a completed payoff model. **Update:** the section F deliverables now exist; see [research results](README.md#research-results-2026-11-04). Extends the [original research](README.md) and [credit-card MVP](credit-card-mvp.md).

## Outcomes and priorities

1. **Payoff planner:** compare payment strategies mathematically and explain the cost of the user's preferred ordering.
2. **Optional personal statements module:** track assets, liabilities and net worth, including retirement accounts and real estate.
3. **Later retirement projections:** model future scenarios separately from current balances. Tracking retirement assets does not by itself establish retirement readiness.

Keep Excel as the preferred interface. Evaluate Access and local Python/SQLite without committing to both backends. Research and small synthetic experiments are in scope; production development, bank connections and payment execution are not.

## A. Define the payoff alternatives precisely

The user's “highest card balances first” is interpreted literally. Do not silently substitute highest APR. Because the preferred tie-break for similar rates is not fully specified, research both balance-order alternatives within an APR band.

| Strategy | Destination of extra payment after all required minimums | Purpose |
| --- | --- | --- |
| Largest balance first | Card with largest remaining balance | Reduce the largest obligation first |
| Snowball | Card with smallest remaining positive balance | Eliminate small debts earlier |
| Avalanche | Card whose next extra payment has the highest applicable APR in the simplified model | Interest-cost baseline |
| Near-APR hybrid | Among eligible cards within a configurable APR gap of the highest rate, choose smallest OR largest balance | Respect balance preference while measuring the cost |

Use the same initial debts, start date, payment dates, total cash budget and assumed future charges for every comparison. Hold the total payment budget constant as minimums decline or cards are paid off; roll freed funds into other debts. Display a minimum-only comparison separately because it uses a different payment schedule.

Specify whether an ordering is fixed, re-ranked each month, or locked to a target until payoff. Use monthly re-ranking as the initial comparison convention with stable account-ID tie-breaks; show a target-until-paid variant if switching materially affects results. Zero-balance cards are ineligible. Extra payments may spill into multiple cards in one period.

### Why rates and balances are different

In a simple interest-bearing case, the near-term interest saved by an extra dollar depends on its rate and time outstanding. For example, an extra $1,000 at 30% instead of 20% saves approximately $8.33 more over one month: $1,000 × (0.30 − 0.20) / 12. This is a marginal illustration, not a complete repayment schedule.

Under fixed rates, identical payment timing/budget, no new charges, no special fees/promotions and otherwise compatible repayment constraints, avalanche is the interest-minimizing baseline. Require an explicit derivation and small independent optimization checks before claiming optimality. With promotions, different accrual rules, payment restrictions or grace-period effects, static APR ordering is not a universal optimizer. A large balance may create more total interest dollars while a smaller, higher-rate balance offers greater savings per extra dollar.

## B. Make “close in interest rate” measurable

Use both a local selection rule and a full-schedule cost test:

- `apr_gap_pp`: percentage-point tolerance below the highest applicable APR. Test **0, 0.5, 1 and 2 percentage points** as research scenarios, not approved defaults. One percentage point is 0.01 when APR is stored as a decimal.
- `balance_preference`: largest-first or smallest-first within that band.
- `max_extra_cost_dollars`: acceptable additional lifetime interest plus fees compared with the same-input avalanche schedule.
- `max_payoff_delay_months`: acceptable delay relative to that baseline.

For a candidate strategy s, compute `delta_cost = total_cost(s) − total_cost(avalanche)` and `delta_time = payoff_month(s) − payoff_month(avalanche)`. A near-APR strategy qualifies only if its complete feasible schedule respects both user-set limits. Do not interpret an unset limit as approval for any cost. Present a cost/time tradeoff table when limits are unset.

An APR gap alone is insufficient: redirecting $1,000 across a 0.5-percentage-point gap for six months costs roughly $2.50 in simple interest, but larger balances and longer delays change the result. Recompute the entire schedule, including promotion expirations. For complex terms, label avalanche a comparator; do not imply every positive or negative delta is measured against a proven global optimum.

## C. Research the calculation engine

| Area | Required research / model contract |
| --- | --- |
| Inputs | Per-card balance/as-of date, APR buckets, issuer minimum rule, due/closing dates, promotions, fees, available payment cash by date, extra lump sums and assumed new charges |
| Baseline model | Monthly forecast with declared interest-first/payment-last event order; `interest = opening_balance × APR / 12`, then fees/charges, payments and ending balance; visibly approximate |
| Precision | Decimal or integer cents, explicit rounding points, deterministic calculations; no LLM-produced arithmetic |
| Realistic model | Research daily balances, day-count convention, payment posting dates, residual interest and grace periods against actual issuer terms; distinguish measured terms from assumptions |
| Within-card allocation | Multiple APR buckets; issuer allocation of minimums and above-minimum payments; a user cannot freely direct every dollar to an arbitrary bucket |
| Promotions | Distinguish true introductory 0% APR from deferred interest; track expiration, post-promo APR, retroactive-interest conditions and transfer fees |
| Constraints | Minimums by due date, no overpayment, cash reserve/budget, no negative balances from rounding; insufficient budget is infeasible, not a valid plan |
| Failure states | Missing APR/minimum rule, non-amortizing debt, negative amortization, max-horizon reached, remaining balance and unverified terms |
| Output | Per-card schedule, payoff date, total interest/fees/payments, first card paid off, debt-free date, minimum commitment freed and difference from baseline |

Forecast minimums must follow a documented rule; the last statement's minimum is only known for that statement. Separate planned payments from posted transactions. No payoff date may be reported for a card with a residual balance at the simulation horizon. Compare bucket-aware marginal allocation with a simple one-APR-per-card model rather than using an unexplained blended APR.

### Acceptance experiments

| Experiment | What it must establish |
| --- | --- |
| Equal APRs and identical accrual/timing assumptions | Aggregate costs should agree across ordering except documented rounding effects; card payoff order can differ |
| High balance / lower APR versus low balance / higher APR | Largest-first and avalanche remain distinct; report the calculated tradeoff |
| APRs 24.0%, 24.5%, 29.0% | A 0.5-point band is measured from the current highest eligible APR, not through a chain of pairwise “close” rates |
| 0% debts and sufficient cash | Exact principal conservation and spillover; no interest or phantom payment |
| Payment budget below minimums / below accrued interest | Explicit infeasibility or negative-amortization output |
| Small final balances and multiple payoffs in one month | Reuse residual payment capacity without exceeding the total budget |
| Promotion expiration / deferred-interest deadline / multiple APR buckets | Correct contract-specific allocation or explicitly unsupported result |
| Large lump sum, changed budget, new purchases, leap year | Consistent event timing and reproducibility |
| Horizon stops before payoff | Remaining debt shown; no false “paid off” summary |
| Small synthetic optimization cases | Independent enumeration/solver agrees with the simplified baseline under its stated assumptions |

Use invariant checks: total debt movement reconciles to charges + interest + fees − payments; payments never exceed cash available; payments cover required minimums on feasible schedules; no double use of freed minimums. Tiny cases with hand-derived answers are more valuable than merely testing one implementation against itself.

## D. Reusable payoff tools to investigate

| Lead | Current evidence | Next action |
| --- | --- | --- |
| [tomithy83/debt-simulator](https://github.com/tomithy83/debt-simulator) | MIT license read; `strategies.py` implements snowball, avalanche and reverse snowball. `simulator.py` inspected. | Audit and benchmark before reuse. Monthly float arithmetic, fixed minimum inputs and a summary based on last simulated month need attention. |
| [unburyme.org](https://unburyme.org/) | Site describes avalanche/snowball and claims MIT; linked `jsantell/unburyme` source returned 404 in this review. | Locate a verifiable maintained fork and actual license/source, or exclude it. Do not treat the hosted site's claim as verified reusable code. |
| [Financial Debt Optimizer](https://financial-debt-optimizer.readthedocs.io/en/latest/faq.html) | Documentation search lead only; not source-reviewed. | Locate upstream, verify license, inspect math/tests and maintenance. |
| Existing PerFin candidates | GnuCash, Actual Budget and MMEX already researched as ledger/application references. | Inspect whether their data models/exports help a separate payoff engine and net-worth module; do not assume a complete optimizer exists. |

Static follow-up for `debt-simulator`: the 50/50 strategy combines dictionaries using overwrite semantics; if the same card wins both rankings, allocations can be lost. Also investigate unspent capacity in final payments and false payoff reporting at the horizon. These are inspection findings to reproduce, not a claim of executed tests. Observed content blob SHAs: `strategies.py` = `5ec7dd1fc79b31a33ee732553915098ea20ee17d`; `simulator.py` = `f385f7c87048016ebcd2d158da3e4761280b9a78`; `LICENSE` = `8dbc5be52c1b651db07ea294863e74ddf7858743`. Pin a commit during the next review. No upstream code was copied.

## E. Separate personal statements module

Research a modular design with shared stable account/asset/liability IDs and dated snapshots. It can have its own workbook or UI while importing the same reconciled cash/card balances. Do not maintain a second editable card ledger.

| Statement / view | Initial scope |
| --- | --- |
| Personal balance sheet | Assets minus liabilities at an explicit date; total and clearly defined liquid-net-worth views |
| Income and expense statement | Period income and spending, with interest/fees separate from debt principal |
| Cash-flow statement | Cash receipts/payments, including principal and asset purchases, reconciled to cash movement |
| Net-worth change bridge | Opening net worth + income − expenses + valuation changes + other explained changes = closing net worth; reconciled on a declared accounting basis |
| Asset schedules | Retirement/brokerage accounts, cash, home/rental real estate, vehicles, business interests and other material assets |
| Retirement scenario, later | Contributions, withdrawals, inflation, returns, taxes/fees, retirement age and income assumptions; scenarios clearly separate from observed statements |

Record valuation date/source/method, ownership interest, currency and uncertainty/staleness. Use market/estimated current values for a management net-worth view while retaining cost basis separately. Specify mortgage and joint-liability treatment according to the actual obligation; do not automatically multiply every liability by an ownership percentage.

Avoid double counting retirement account totals plus their underlying holdings; property value plus property equity; or business equity plus the business's underlying assets. A mortgage remains a liability against the property's gross included value. Retirement contributions are generally transfers between included household assets, not consumption expense. Recognize income such as an employer contribution separately when applicable. Debt principal paid from included cash reduces cash and debt equally, so by itself it does not increase net worth; interest expense reduces it. Unrealized value changes are not cash receipts.

Track retirement balances separately from accessibility and tax status. Pension/Social Security income assumptions belong in future cash-flow scenarios; do not silently capitalize them into current net worth. Gross net worth and an optional estimated after-tax/liquidation view must remain distinct. Define these as personal management statements; do not claim GAAP, tax or lender compliance without researching the applicable reporting basis.

Test statement identities, transfer neutrality, principal/interest splits, retirement contribution transfers, property/mortgage accounting, ownership, stale values and missing FX. Build a small synthetic household example; no actual user balances are needed for this research.

## F. Deliverables and completion order

1. `research/payoff/source-audit.md`: verified upstream URLs, commit/license evidence, inspected functions, reuse decisions and reproduced defects.
2. `research/payoff/math-spec.md`: objectives, equations, event order, constraints, near-APR policy, assumptions and limits of optimality.
3. `research/payoff/experiments.md` plus a small reproducible local script and synthetic fixtures: strategy tables, schedules, invariants and actual test results.
4. `research/net-worth/module-spec.md`: statement definitions, data model, integration boundary and worked synthetic statements.
5. `research/implementation-roadmap.md`: minimum implementation sequence, recommended reuse, Windows/Excel/Access trial still needed, and open user choices.

Start with the payoff math. Specify the net-worth module without delaying the debt planner. Keep the final executive readout short and detailed evidence in files. Research experiments do not authorize production deployment or banking actions.

## Primary references checked

- [CFPB: debt reduction strategies](https://www.consumerfinance.gov/archive/blog/how-reduce-your-debt/) — minimums, highest-rate ordering and snowball.
- [CFPB: different APR balances](https://www.consumerfinance.gov/ask-cfpb/my-bill-shows-different-aprs-and-shows-how-much-of-the-balance-is-subject-to-each-interest-rate-i-cannot-figure-out-how-this-is-calculated-how-does-that-work-en-39/) — separate rate buckets and allocation.
- [CFPB: payment allocation rule](https://www.consumerfinance.gov/rules-policy/regulations/1026/53/) — U.S. above-minimum allocation and exceptions; verify current scope when implementing.
- [CFPB: deferred interest](https://www.consumerfinance.gov/ask-cfpb/i-got-a-credit-card-promising-no-interest-for-a-purchase-if-i-pay-in-full-within-12-months-how-does-this-work-en-40/) — deadlines and distinction from unconditional 0% offers.
- [Investor.gov: figure out your finances](https://www.investor.gov/introduction-investing/investing-basics/save-and-invest/figure-out-your-finances) — assets, liabilities and net worth.

Detailed model/module requirements above are proposed engineering decisions and research questions, not claims that those sources prescribe a particular software implementation.
