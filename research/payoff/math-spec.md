# Payoff planner: mathematical specification

Date: 2026-11-04. Status: **proposed specification plus an executed reference experiment**. It is not production software and not financial advice. The reference code is [`experiments/payoff_ref.py`](experiments/payoff_ref.py). Results are in [experiments.md](experiments.md).

Labels used below:

- **[Spec]**: a proposed engineering rule.
- **[Approx]**: a known simplification of real card accounting.
- **[Assumption]**: a declared input that is unknown for real cards.
- **[Unverified]**: a regulatory statement that could not be re-read from a primary source in this session.
- **[Unsupported]**: the engine must refuse or flag the case rather than compute it.

## 1. Units, precision and rounding

| Item | Rule |
| --- | --- |
| Money | Integer US cents everywhere. No floats. Excel and Access hold integer cents exactly in doubles or Currency, provided every stored result is already rounded to a whole cent. |
| Rates | `Decimal` APR stored as a decimal fraction (24.99% = `0.2499`). One percentage point (pp) = `0.01`. |
| R1 monthly interest [Approx] | `interest = round_half_up(balance_cents × APR / 12)`, computed per APR bucket per month on the opening balance. |
| R2 daily interest [Approx] | Σ over days of end-of-day balance × APR / `days_in_year`, summed unrounded, rounded half-up once per cycle. Issuers disclose their own method, day count and rounding. R2 is a comparator, not a claim about any issuer. |
| Rounding mode | Half-up to the cent. In Excel, `ROUND()` rounds halves away from zero, which matches half-up for positive amounts. **VBA's `Round()` uses banker's rounding.** A VBA port must use `WorksheetFunction.Round` or an explicit integer routine. This should be re-checked on the target Office build. |
| Determinism | No wall-clock dates, randomness or iteration-order dependence. Every tie has an explicit key (section 4). |

**Every M1 (APR/12) result is an approximation of issuer accrual.** Section 8 measures the gap.

## 2. Inputs

| Input | Meaning |
| --- | --- |
| Cards `i` | Stable ID (sort key for ties), one or more APR buckets `k`, a minimum rule, assumed new charges `c[i,t]` and fees `f[i,t]` |
| Bucket | Balance, current APR, optional promotion end month, post-promotion APR, `deferred` flag |
| Cash `P[t]` | Total cash for **all** card payments in month `t`: base budget, per-month overrides and lump sums. `P[t]` is identical across the strategies being compared. |
| Horizon `T` | Maximum number of months simulated |

The forecast minimum is a **declared rule** [Assumption], because issuers' formulas differ and only the latest statement's minimum is known:

- `fixed(a)`: `min(a, S)`.
- `pct(p, floor)`: `min(max(floor, round(p·S)), S)`.
- `pct_plus_interest(p, floor)`: `min(max(floor, round(p·S) + interest + fees), S)`.

Here `S` is the statement balance after interest, fees and charges. When an actual statement minimum is known, it overrides the forecast for that month.

## 3. Month event order (model M1)

For each month `t = 1..T`, with cards processed in ID order:

| Step | Event |
| --- | --- |
| E0 | Stop with `PAID_OFF` if every balance is 0 and no future charges or fees are scheduled. |
| E1 | Interest per bucket at that month's rate using R1. A deferred bucket inside its promotion charges 0, but accrues shadow interest at its post-promotion APR. |
| E2 | Fees are added to bucket 0. |
| E3 | Assumed new charges are added to bucket 0. They accrue interest from the next month [Approx: no grace-period modelling]. |
| E4 | Statement balance `S[i,t]` and forecast minimum `m[i,t]`. |
| E5 | Feasibility: if `Σ m[i,t] > P[t]`, then status is `INFEASIBLE_BUDGET`. The run stops, no plan exists for month `t` or later, and no payoff date is reported. |
| E6 | Pay every minimum. Within a card, the minimum goes to the lowest current rate first (A6, adverse case). |
| E7 | Extra `E[t] = P[t] − Σ m[i,t]` is allocated by strategy (section 4). Within a card, the excess goes to the highest current rate first, with the deferred exception (section 7). |
| E8 | Deferred deadline: if a deferred bucket's promotion ends this month with a positive balance, the accrued shadow interest is added as interest. Otherwise it is waived. |
| E9 | Unspent cash `U[t] = P[t] − Σ payments ≥ 0`. It can be positive only when no card has remaining capacity. |
| E10 | Flags: negative amortization when a card's ending balance exceeds its opening balance plus fees in a month with no new charges. |

**Rolling freed capacity.** `P[t]` stays constant when a minimum disappears, so a paid-off card's minimum automatically becomes extra for the other cards. Unused capacity in a payoff month spills to the next target in the same month (E7 waterfall). A minimum is never counted twice: freed capacity exists only as part of `E[t]`.

**Minimum-only comparison.** This sets `P[t] = Σ m[i,t]`. It is a *different cash schedule*, reported separately and never mixed into the strategy comparison.

## 4. Strategies, ranking and ties

`R[i,t] = S[i,t] − m[i,t]` is the card's remaining capacity after its minimum. Balance keys use a **snapshot** of `R[i,t]` taken before any extra in month `t`. A card's **marginal APR** is the current rate of the bucket that its next excess dollar would hit (section 7). Cards with `R = 0` are ineligible.

| Strategy | Choose next target among eligible cards by | Tie keys, in order |
| --- | --- | --- |
| Largest balance first (user's literal request) | largest `R` snapshot | card ID ascending |
| Snowball | smallest `R` snapshot | card ID ascending |
| Avalanche | highest marginal APR | card ID ascending |
| Near-APR hybrid `(g, pref)` | band `B = {i : apr_i ≥ apr_top − g × 0.01}`, where `apr_top` is the highest marginal APR among eligible cards, then smallest (or largest) `R` snapshot within `B` | higher marginal APR, then card ID |

Mechanics [Spec]:

- **Re-ranking.** Targets are recomputed every month (default). The variant `+lock` keeps the current target until its capacity is zero.
- **Fill.** Balance rules fill the chosen card completely before spilling to the next. APR rules (avalanche, hybrid) fill one bucket segment at a time, then re-choose, so a card whose next dollar would reach a lower-rate bucket can lose priority within the same month.
- **The band is not chained.** It is always measured from the current top marginal APR. With 29.0 / 24.5 / 24.0 and `g = 0.5`, the band is {29.0} until that card is full. Then it becomes {24.5, 24.0}. The 24.0 card never joins through 24.5 while 29.0 is eligible (test `test_band_is_measured_from_top_not_chained`).
- With `g = 0` the hybrid equals avalanche except that it breaks equal-APR ties by balance preference instead of ID.

**Four quantities that are often confused:**

| Quantity | Definition | f02 example: BIG $9,000 at 18.9%, SMALL $1,500 at 29.99% |
| --- | --- | --- |
| Highest balance | largest `B` | BIG |
| Highest APR | largest rate | SMALL |
| Highest monthly interest dollars | largest `B × APR/12` | BIG: $141.75/month vs SMALL $37.49 |
| Highest utilization | `B / limit` | Not part of any strategy here. It is undefined without a limit and is not a cost driver in this model. |

Interest dollars are dominated by size. The **saving per extra dollar** depends only on rate and time, which is why largest-first and avalanche diverge.

**Re-ranking caveat for largest-first.** With monthly re-ranking, literal largest-first keeps switching targets whenever the leading balance drops below the next one, which pushes balances toward equality. In f14 it switched targets 23 times, cost $75.78 more and paid off one month later than `largest+lock`, which matched avalanche there. The user should choose between re-ranking and lock. Both are reported.

## 5. Objective and comparison

- `total_cost(s) = Σ interest + Σ fees`. This includes deferred interest charged and transfer fees.
- With identical `P[t]` and a fixed horizon, `total_cost = Σ_i B[i,T] − Σ_t U[t] + constant`. Lower cost is therefore equivalent to a better terminal net position. Comparing schedules that are truncated at the same horizon is valid only on this basis, and the unpaid balance must be shown.
- `delta_cost(s) = total_cost(s) − total_cost(avalanche)`.
- `delta_time(s) = debt_free_month(s) − debt_free_month(avalanche)`. This is undefined (shown as —) if either schedule has not paid everything off.
- **Payoff month** of a card: the month its balance became 0 and stayed 0 through the end of the run. It is **never** reported for a card with a remaining balance at the horizon or on an infeasible run. `debt_free_month` exists only when status = `PAID_OFF`.
- **User tolerance.** The settings `max_extra_cost_dollars` and `max_payoff_delay_months` are **unset**. Unset means "report only", never "approved". A preference strategy qualifies only when both limits are set and the complete feasible schedule satisfies them.
- **Wording.** For promotional or complex terms, avalanche is a *comparator*, not a proven optimum, so a negative `delta_cost` is possible and must be shown as such.

## 6. Marginal savings per extra dollar

- **One-month view [Approx].** An extra dollar on card `i` this month avoids `APR_i / 12` of next month's interest. Moving $1,000 from a 20% card to a 30% card saves about $8.33 in one month. Across a 0.5 pp gap it saves about $0.42 per month (about $2.50 over six months). This is an illustration, not a schedule.
- **Full-schedule view (shadow price).** Add a lump sum `L` in month 1 and re-run with everything else unchanged. The saving per dollar is `(cost − cost_with_L) / L`. In a continuous M1 model the dollar compounds through every rate it displaces until the debt-free date, approximately `Π (1 + ρ_k)^{months on card k} − 1`. Measured on f02 with L = $100, avalanche saves **$0.96 per extra $1** over the remaining schedule. This value depends on strategy, horizon and rounding, so it is reported per run.

## 7. Within-card allocation (multiple APR buckets)

- **Minimum (A6) [Assumption].** The minimum is applied to the lowest current rate first. This is adverse to the cardholder. Issuer practice should be checked in the card agreement, and an issuer-specific rule can replace A6.
- **Excess over the minimum.** Applied to the highest current rate first. If a deferred-interest bucket expires in month `d`, the excess goes to that bucket first in months `d−1` and `d`. **[Unverified]** This is modelled on 12 CFR 1026.53(a) and 1026.53(b)(1), which also allow a cardholder-requested allocation to a deferred balance. Re-read the [CFPB text of § 1026.53](https://www.consumerfinance.gov/rules-policy/regulations/1026/53/) before relying on it; it could not be reached in this session.
- **Consequence.** A cardholder cannot direct every dollar to an arbitrary bucket. The avalanche "marginal APR" is therefore the rate the issuer's rule will actually hit, not a blended APR. In f11, card X's 29.99% cash-advance bucket attracts extra before card Y at 25.99%. Its 0% transfer bucket receives the minimum, and the transfer fee counts in cost.

## 8. Optimality: what is and is not claimed

**Setting C** (continuous, idealised M1):

- fixed monthly rates `ρ_i`;
- no rounding;
- exogenous charges and fees;
- minimum amounts that do not depend on balances (fixed, capped at the balance);
- single-bucket cards with no promotions;
- cash `P[t]` identical across plans;
- the objective is total interest, equivalently the terminal net position.

**Proposition (proof sketch, not a complete proof).** In setting C, a plan that sends each month's extra to the highest-rate card with remaining capacity minimises total interest.

Sketch:

1. Unroll a card's balance: `B[i,T] = (1+ρ_i)^T B[i,0] + Σ_t (1+ρ_i)^{T−t} (c[i,t] − p[i,t])`.
2. Take any plan that, in month `t`, pays ε of extra to card `j` while card `i` with `ρ_i > ρ_j` still has a positive balance after month `t`. Move that ε to `i`.
3. If `i` is never paid off within the horizon, terminal debt changes by `−ε(1+ρ_i)^{T−t} + ε(1+ρ_j)^{T−t} < 0`.
4. Otherwise, at the first later month `s` in which `i` receives extra, reduce `i`'s payment by `δ = ε(1+ρ_i)^{s−t}`. This leaves `i`'s path from `s` onward unchanged. Then give `j` its extra `ε(1+ρ_j)^{s−t} ≤ δ` back.
5. That frees `λ = ε[(1+ρ_i)^{s−t} − (1+ρ_j)^{s−t}] > 0`, which is exactly the interest saved.
6. Hence every non-avalanche allocation can be weakly improved.

**Gap.** The case where `j` itself is paid off between `t` and `s` needs an additional compensation step that is not written out here. A full proof, or an LP dual certificate checked per instance, is a proposed next step.

**Evidence actually executed** (see [experiments.md](experiments.md)):

- Exhaustive enumeration on a $50 grid (E1–E5: fixed and balance-dependent minimums, payoff with spillover, equal APRs, zero APRs) never found a cheaper plan than avalanche. In E1 the optimum is on the grid and equals avalanche to the cent: $319.13 over 614,656 plans.

**Not covered:**

- **Rounding.** Cent rounding can move totals by cents. f01 equal APRs: snowball $1,123.31 vs avalanche $1,123.32.
- **Balance-dependent minimums.** Not covered by the sketch. Small-case enumeration (E2) is consistent with avalanche, but that is evidence, not proof.
- **Promotions, deferred interest, fees triggered by behaviour, grace-period effects, payment-allocation restrictions, penalty APRs and limits on allocation.** Static current-APR avalanche is **not** optimal there. Two counterexamples were executed:
  - **Deferred interest (f09 / E6).** Avalanche ranks the deferred card at 0%, misses the deadline and is charged $153.51 of retroactive interest. Snowball is $137.30 cheaper over the full schedule. Enumeration over 6 months finds a plan $106.69 cheaper.
  - **True 0% intro APR expiring (f10).** `largest+lock` pays the large intro balance during the 0% window and costs $74.35 less than current-APR avalanche.

## 9. Realistic accrual: research findings and model contract

| Topic | Finding / contract | Status |
| --- | --- | --- |
| Daily accrual | Measured M1 error on a $3,000, 24% balance: $55.56 daily vs $60.00 M1 with a mid-cycle $500 payment. February is $57.21 (leap year, /365) vs $55.23 (non-leap); a /366 day count gives $57.05. A $400 mid-cycle purchase gives $64.31 vs M1's $60.00, because M1 delays new charges a month. | Executed ([experiments.md §5](experiments.md#5-daily-accrual)) |
| Cycle and due dates | Real cycles are 28–31 days, with closing dates set by statements. A payment's effect depends on its posting date relative to close. The production model must take actual statement close/due dates and planned posting dates, and must never shift a historical status to a fixed day. | [Spec] |
| Payment crediting / cut-off / weekend due dates | Reg Z § 1026.10 governs crediting and due dates. Model inputs use the *posted* date from evidence. | [Unverified] in this session |
| Grace period and residual interest | Paying the statement balance in full after carrying a balance can still produce interest for the days between close and payment. Example: $1,000 at 24% paid 25 days after close gives **$16.44**, billed next cycle. M1 cannot represent this and would show the card paid off one cycle early. Reg Z § 1026.54 limits finance charges tied to loss of a grace period. | Example executed; rule [Unverified] |
| Changing minimums | Minimums decline with the balance under `pct` rules. Forecast with the declared rule, override with the actual statement minimum, and re-plan after each statement. | [Spec] |
| Multiple APR buckets and issuer allocation | Section 7. | Modelled; rule [Unverified] |
| 0% promotion expiry | Rate switch at the end month. Avalanche must use the *current* rate if it is the comparator; forward-looking strategies are a research extension (f10). Reg Z § 1026.55(b)(1) is believed to require promotional rates to last at least 6 months. | Modelled; rule [Unverified] |
| Deferred interest | Shadow accrual at the post-promotion APR on the outstanding balance, charged in full if any balance remains at the deadline [Approx]. Real plans may compute interest from the purchase date on the original amount. Use the agreement's terms. | Modelled [Approx] |
| Balance-transfer fees | Fee events posted to bucket 0 in the transfer month and included in cost (f11: $60). Fee rate and whether it is capitalised come from the agreement. | Modelled |
| Penalty APR / late fees | Not modelled. A feasible plan always pays minimums by the due date, and late fees on infeasible plans are not forecast. | [Unsupported] |

## 10. Failure states and unsupported cases (must be explicit)

| Case | Required output |
| --- | --- |
| `Σ minimums > cash` | `INFEASIBLE_BUDGET` at month `t`. No schedule beyond, no payoff dates, and no "best strategy" ranking for that scenario. |
| Payment ≤ interest (negative amortization) | Per-card per-month flag. If the horizon is reached: `HORIZON_REACHED` with the remaining balance. |
| Horizon reached | `HORIZON_REACHED`. Remaining debt shown, no debt-free date, no payoff month for unpaid cards (invariant I8/I9). |
| Missing APR or minimum rule | Reject the input. Never default to 0%. |
| Non-USD card, variable-rate index changes, penalty APR, cash-advance fees by behaviour, credit-balance refunds, disputes, issuer-specific minimum formulas not expressible as the declared rules, daily-accrual production model, payment posting by business day | [Unsupported] in M1. Must be refused or flagged, not silently approximated. |

## 11. Invariants (checked on every schedule)

| ID | Invariant |
| --- | --- |
| I1 | `initial debt + charges + interest + fees − payments = final debt` in aggregate, exact cents |
| I2 | Same identity per card per month |
| I3 | No negative balance |
| I4 | Every minimum is paid on a feasible month |
| I5 | No payment exceeds the statement balance |
| I6 | `Σ payments + unspent = cash`, and unspent ≥ 0 |
| I7 | No idle cash while any balance remains |
| I8 | No debt-free date unless `PAID_OFF` |
| I9 | No payoff month for a card with a balance at the horizon |

**Executed:** 210 schedules (15 fixtures × 13 strategy variants + minimum-only) with 0 violations.

## 12. Excel / Access mapping (proposed)

The workbook is the interface. The calculation lives in one engine: Python, or VBA ported from the reference with identical fixtures.

- Inputs go on typed sheets.
- Each month is a row per card, holding the E1–E10 columns.
- Totals are sums of integer cents.
- Any VBA or Excel port must reproduce `results.md` for all fixtures before use.
