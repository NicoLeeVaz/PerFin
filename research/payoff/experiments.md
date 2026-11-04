# Payoff experiments: method, results and test status

Date: 2026-11-04. Everything here uses **synthetic data** and the simplified monthly model M1 from the [math spec](math-spec.md). M1 interest is APR/12 on the opening balance, so **every interest figure below is an approximation** of issuer daily accrual.

## How to reproduce

Run from the repository root with Python 3.10 or later (standard library only; no network, no installs):

```bash
python3 research/payoff/experiments/run_experiments.py
```

```bash
python3 -m unittest discover -s research/payoff/experiments -p "test_*.py" -v
```

The first command rewrites [`experiments/results/results.md`](experiments/results/results.md), which holds every table in full. It prints `OVERALL: PASS` and exits with code 0 only if all invariants and oracle checks pass. The output is deterministic, so a diff against the committed file shows any behavioural change. The upstream reproduction scripts need external clones; see the [source audit](source-audit.md#5-reproducing-this-audit).

| File | Role |
| --- | --- |
| `payoff_ref.py` | Reference engine: integer cents, Decimal rates, declared rounding and event order, strategies, invariants |
| `oracle.py` | Independent brute-force enumerator. It does not import `payoff_ref` and re-implements the month step. |
| `daily.py` | Daily-balance and residual-interest comparators |
| `fixtures/*.json` | 15 synthetic scenarios (listed below) |
| `run_experiments.py` | Runs everything and writes `results/results.md` |
| `test_payoff_ref.py` | 26 unit tests with hand-derived expectations |
| `upstream/*` | Reproduction harnesses for third-party code (they load external clones) |

## Executed results (2026-11-04, Python 3.13.18, Linux)

| Check | Result |
| --- | --- |
| `run_experiments.py` | **OVERALL: PASS**. 210 schedules, **0 invariant violations** (I1–I9). Oracle cases E1–E6 all pass. |
| Payoff unit tests | **26 / 26 passed** |
| Net-worth example tests | **12 / 12 passed** ([module spec](../net-worth/module-spec.md)) |
| Upstream: debt-simulator | Its own test **errors**. 7/7 suspected defects **reproduced**. |
| Upstream: unbury.me | No tests exist. 3/3 defects **reproduced**. |
| Upstream: financial-debt-optimizer | Its suite: **304 passed, 2 failed** (visualization). 3 probes reproduced. |

## Fixtures

| Fixture | Purpose |
| --- | --- |
| f01 | Equal APRs (20%). Costs should agree up to rounding while payoff order differs. |
| f02 | Large balance at low APR vs small balance at high APR |
| f03 | 24.0 / 24.5 / 29.0%: band measured from the top, not chained |
| f03b | Top two APRs 0.40 pp apart with very different balances: the 0.5/1/2 pp bands change the target |
| f04 | All 0% APR: exact principal conservation and same-month spillover |
| f05 | Budget below minimums: infeasible |
| f06 | Fixed minimums below interest: negative amortization and horizon reached |
| f07 | Two cards paid off in month 1: residual capacity spill |
| f08 | f02 plus a $2,000 lump sum in month 3 and a reduced budget in months 7–9 |
| f09 | Deferred-interest deadline (counterexample) |
| f10 | True 0% intro APR expiry (counterexample) |
| f11 | Three APR buckets on one card, plus a transfer fee |
| f12 | f02 truncated at 6 months |
| f13 | Assumed new purchases, identical for every strategy |
| f14 | Near-equal balances: largest-first alternation |

Each fixture is compared under identical starting balances, cash per month and assumed charges. Every minimum is paid first and freed capacity rolls forward. The strategies are:

- largest-first, snowball and avalanche;
- the hybrid at 0, 0.5, 1 and 2 pp × {smallest, largest};
- `+lock` variants;
- minimum-only, reported separately because it uses a different cash schedule.

## 1. Key strategy results

Δ is measured against same-input avalanche. Negative means cheaper than avalanche.

| Fixture | Largest-first | Snowball | Notable hybrid / lock results |
| --- | --- | --- | --- |
| f01 equal APR | +$0.00, 0 mo | −$0.01, 0 mo (rounding) | All within 1¢; first payoff C(15) / C(3) / A(5) |
| f02 big-low vs small-high | **+$654.31, +1 mo** | $0.00 (same order as avalanche here) | Bands ≤ 2 pp change nothing (gaps are 5.99 and 5.1 pp) |
| f03 24.0/24.5/29.0 | +$220.52, +1 mo | +$78.99, +1 mo | smallest @ 0.5–2 pp: $0 (band = {29.0}). largest @ 0.5–2 pp: **+$5.60**, after C is cleared 24.0 joins 24.5 |
| f03b close top rates | +$29.53, 0 mo | +$221.54, 0 mo | smallest: 0.5 pp **+$13.96**, 1 pp +$13.96, 2 pp **+$89.51**. largest: 0.5 / 1 pp +$0.85, 2 pp +$28.07 |
| f07 spillover | +$3.08 | $0.00 | Two cards paid in month 1; 15512¢ ($155.12) spills to C; total paid exactly $500.00 |
| f08 lump / budget change | +$657.28, +2 mo | $0.00 | — |
| f09 deferred interest | +$16.54 | **−$137.30, −1 mo** | Avalanche is charged $153.51 retroactive interest in month 6 |
| f10 0% intro expiry | +$74.07 | +$354.42, +1 mo | **largest+lock −$74.35** vs avalanche |
| f11 multi-bucket | +$10.40 | +$31.16 | largest+lock +$55.15 |
| f13 new purchases | +$1,006.88, +2 mo | $0.00 | — |
| f14 near-equal balances | +$75.78, +1 mo | +$158.47, +1 mo | largest+lock $0.00. Re-ranked largest switched target 23 times. |

Failure states:

- **f05** (budget $100 vs $269.27 of minimums): `INFEASIBLE_BUDGET` in month 1 for every strategy. No schedule, payoff date or ranking is shown.
- **f06**: debt grows from $8,000 to about $11,450, the negative-amortization flag is raised every month, the status is `HORIZON_REACHED` and no payoff date is given.
- **f12**: $11,849.61 is still owed at month 6 under avalanche, with no payoff month.

### Near-APR tradeoff (dollar/month view, limits unset)

For f03b, the user's "pay a smaller/larger card first when the rates are close" preference costs the following, measured on the full schedule:

| Band | Smallest within band | Largest within band |
| --- | --- | --- |
| 0 pp | $0.00, 0 mo (= avalanche) | $0.00, 0 mo |
| 0.5 pp | +$13.96, 0 mo; B paid in month 10 instead of A in month 26 | +$0.85, 0 mo |
| 1 pp | +$13.96, 0 mo | +$0.85, 0 mo |
| 2 pp | +$89.51, 0 mo | +$28.07, 0 mo |

These are research scenarios, not defaults. Whether $13.96 for an early first payoff is acceptable depends on the `max_extra_cost_dollars` and `max_payoff_delay_months` limits, which **remain unset**. The cost is not monotone in a simple way: it depends on which cards fall into the band at each re-ranking. That is why the full schedule must be recomputed rather than estimated from the gap.

## 2. Marginal savings per extra dollar (f02)

- **One month.** $100 extra saves $1.58 on BIG (18.9%), $2.00 on MID (24%) and $2.50 on SMALL (29.99%). BIG has the most interest *dollars* ($141.75/month) but the lowest saving per dollar.
- **Full schedule.** A $100 lump sum in month 1 lowers lifetime cost by $96.01 under avalanche ($0.9601 per $1) and by $96.04 under largest-first. The debt-free month moves 37 → 36 under avalanche and stays at 38 under largest-first. A dollar keeps saving interest on every card it later displaces until the debt-free date.

## 3. Independent enumeration (oracle) vs reference engine

The oracle enumerates every allocation of each month's extra on a grid. Any remainder is left unspent, which is allowed but penalised by the objective. "Replay" feeds payoff_ref's avalanche allocations into the oracle's own month step; it agreed to the cent in every case.

| Case | Plans | Avalanche | Best grid plan | Verdict |
| --- | ---: | ---: | ---: | --- |
| E1: 2 cards, fixed minimums, no payoff, 4 months, $50 grid | 614,656 | $319.13 | $319.13 | Equal (optimum is on the grid) |
| E2: 3 cards, 1% + interest minimums, 3 months | 3,800 | $497.08 | $499.47 | Avalanche ≤ grid |
| E3: payoff + spillover inside horizon | 28,503 | $155.89 | $158.84 | Avalanche ≤ grid |
| E4: equal APRs | 8,000 | $216.20 | $217.44 | Avalanche ≤ grid |
| E5: zero APRs | 2,795 | $0.00 | $0.00 | Equal |
| E6: deferred-interest deadline, 6 months, $100 grid | 46,655 | $419.98 | **$313.29** | Grid beats avalanche by **$106.69** (counterexample) |

E6's best plan sends nearly all extra to the deferred card until it is cleared by month 6.

**Interpretation.** E1–E5 are evidence for the fixed-terms proposition in [math-spec §8](math-spec.md#8-optimality-what-is-and-is-not-claimed). They are not a proof: the grid is coarse and the horizons are short. E6 and f10 show that current-APR avalanche is **not** a global optimum with promotions.

## 4. Hand calculations (used by the unit tests)

**Two cards, 2 months, $300/month, fixed $25 minimums.** Card A is $1,000 at 24% and card B is $500 at 12%.

- **Month 1.** Interest is A = 100000 × 0.24/12 = 2000¢ and B = 50000 × 0.12/12 = 500¢. Extra = 30000 − 5000 = 25000¢.
  - Avalanche sends the extra to A: A ends at 102000 − 2500 − 25000 = **74500¢**, B at 50500 − 2500 = **48000¢**.
- **Month 2.** Interest is A = 1490¢ and B = 480¢. A ends at **48490¢**, B at **45980¢**.
  - Total interest = 2000 + 500 + 1490 + 480 = **4470¢ ($44.70)**. Largest-first is identical here.
- **Snowball.** Month 1: B ends at 50500 − 27500 = 23000¢.
  - Month 2: B interest 230¢, statement 23230¢. B pays its 2500¢ minimum plus 20730¢ of extra and is paid off.
  - The remaining **4270¢** spills to A, which ends at 101490 − 2500 − 4270 = **94720¢**.
  - Interest = 2500 + 1990 + 230 = **4720¢**, so snowball costs $2.50 more over these two months.

**Spillover (f07, month 1).** Statements are A 12200¢, B 13238¢ (13000 × 0.22/12 = 238.33 → 238) and C 405000¢.

- C's minimum is 1% × 405000 + 5000 = 9050¢. Total minimums are 14050¢, leaving 35950¢ of extra.
- Avalanche clears B (10738¢), then A (9700¢). The remaining **15512¢** goes to C, and the total paid is exactly 50000¢.

**Zero APR (f04).** Month 1 extra is 45000¢. It pays A's 27500¢, then B gets 17500¢, so B ends at 80000¢. Month 2 pays 50000¢. Month 3 pays 30000¢, leaving **20000¢ unspent**. Interest is 0 and payments total exactly 130000¢.

**Rounding.** 300¢ × 0.02/12 = exactly 0.5¢, which rounds to 1¢ (half-up). 12345¢ × 0.1999/12 = 205.647, which rounds to 206¢.

**Buckets.** Purchases are $1,000 at 20%, cash advance $500 at 30%, and a $1,000 promo at 0%. The fixed minimum is $100 and the budget $400.

- Interest is 1667 + 1250 = 2917¢.
- The minimum goes to the 0% promo, leaving it at 90000¢.
- The excess goes to the cash advance: 51250 − 30000 = 21250¢. The purchase balance stays at 101667¢.

## 5. Daily accrual

These calculations use rule R2 against M1 for a $3,000 balance at 24% APR.

| Cycle | Daily (R2) | M1 | Hand calculation |
| --- | ---: | ---: | --- |
| Jan 2028 (31 days), $500 paid on day 15 | $55.56 | $60.00 | (3000×14 + 2500×17) × 0.24/365 |
| Feb 2028 (29 days, leap year), /365 | $57.21 | $60.00 | 3000 × 29 × 0.24/365 |
| Feb 2028, /366 day count | $57.05 | $60.00 | 3000 × 29 × 0.24/366 |
| Feb 2027 (28 days) | $55.23 | $60.00 | 3000 × 28 × 0.24/365 |
| $400 purchase posted on day 20 of 31 | $64.31 | $60.00 | (3000×31 + 400×12) × 0.24/365 |

**Residual interest.** A $1,000 statement at 24%, paid in full 25 days after close with no grace period, still incurs **$16.44** next cycle. M1 would declare the card paid one cycle early. M1 errs in both directions by several dollars per cycle at these balances, so a production planner needs statement-date-aware accrual (math spec §9).

## 6. Test status: executed vs proposed

**Executed and passing.** All checks in the "Executed results" table, covering:

- equal APRs, zero APRs, large/low vs small/high;
- near rates, including the band's non-chaining;
- insufficient budget, negative amortization, final-payment spillover;
- lump sum and budget change;
- deferred deadline and 0% expiry;
- multi-bucket allocation and the deferred two-cycle exception (ordering only);
- horizon truncation, new purchases, determinism and the leap-year daily cycle.

**Proposed, not yet executed:**

1. An LP dual-certificate check of avalanche optimality on random fixed-terms instances, using exact rationals.
2. A finer-grid or continuous enumeration.
3. A statement-date-aware daily engine validated against real (redacted) issuer statements, kept outside this repository.
4. Issuer-specific minimum formulas and actual minimum-allocation practice.
5. Payment-posting and weekend due-date handling.
6. A forward-looking promotion-aware strategy, plus a search for its optimality conditions.
7. A port of `payoff_ref` to VBA or Excel, required to reproduce `results.md` exactly.
8. Penalty APR and late-fee scenarios. These are currently unsupported.
