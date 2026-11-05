# Payoff engine

`perfin_payoff.simulate(payoff_scenario)` returns a validated `payoff_result` using contract 1.0.x. Integer cents and Decimal rates keep calculations deterministic; the caller's input is not mutated. `sensitivity(document, extra_monthly_minor)` reports the interest/month savings from an explicit budget increase, only when both forecasts finish.

```sh
PYTHONPATH=src:contracts/python python -m perfin_payoff fixtures/payoff/scenario.synthetic.json
PYTHONPATH=src:contracts/python python -m perfin_payoff fixtures/payoff/scenario.synthetic.json --extra-monthly-minor 1000
python -B -W error -m unittest discover -s tests/payoff -q
```

Installed use does not need PYTHONPATH. JSON results on stdout contain private financial data when private inputs are used; save them only in the approved local data root. There are no ledger writes, network calls, payment execution, external AI calls or bank connections.

## Exact model definition

This is **approximate monthly APR / 12**, not issuer-exact daily accrual. The first payment is one calendar month after `as_of`; dates clamp to each month's last day, independently of earlier clamps (January 31 → February 28/29 → March 31). The day label does not change the APR / 12 accrual factor.

For each month and card:

1. Interest = opening debt × APR / 12, rounded half-up to cents once per card.
2. Add scheduled fees and new charges after interest. Charges receive their first interest next month.
3. Compute the minimum, capped at the amount due. `fixed` uses the specified amount; `pct` uses the post-interest/fee/charge amount due × pct, rounded half-up and floored; `pct_plus_interest` uses (opening + charges) × pct, rounded half-up, plus interest + fees, floored.
4. The month's override replaces the regular budget; all lump sums add. Cash not used in that month is reported as unspent and does not carry forward automatically.
5. If cash cannot cover every minimum, accrue that month, stop with `infeasible_budget`, and simulate no payments for that month. Required minimums remain visible; they were not paid.
6. Otherwise pay all minimums, then allocate extra to ranked positive balances. Cap each payment and immediately spill unused capacity into the next eligible card. The total budget remains constant as minimums decline.

Balances used for ranking are the balances **after minimum payments**. Stable account-ID ties make every run repeatable. Largest balance and smallest balance/snowball are separate from highest-APR avalanche. A hybrid selects from the band below the highest remaining APR; `gap_pp = "0.5"` means 0.5 percentage points, not 50% or a chained pairwise comparison. Prefer largest or smallest balance within that band. Ranking refreshes each month and after a target is paid. `lock_target: true` retains the extra-payment target until paid, even if a promotion changes rates. This optional behavior can cost more than dynamic avalanche.

True introductory rates are supported for one bucket: the promotional APR applies through `promo_end_month`; the post-promo APR applies from the following month. Multiple APR buckets and deferred interest return `unsupported_terms` for the whole scenario, preserving starting debt and withholding a payoff date. Daily balance accrual, grace periods, issuer-specific allocation, residual interest and complex minimum rules are not supported; unknown fields/models fail schema validation. Do not flatten a multi-bucket card into a blended rate.

Future dated charges/fees prevent an early debt-free claim. A horizon cutoff retains outstanding debt and null payoff date. Growing balances get negative-amortization flags; interest-only/non-amortizing schedules also remain incomplete at the horizon. Cash/charge/fee events beyond the selected horizon are rejected rather than silently omitted.

## Comparisons and limits

A dynamically reranked avalanche baseline is calculated even when absent from the requested strategies. Lifetime cost and delay comparisons are populated only when both runs finish. Incomplete comparisons are null. Both tolerance limits must be set and both runs complete before `within_tolerance` can be `yes`; blank limits mean unset.

`total_interest_minor + total_fees_minor` is cost; total payments also includes principal and assumed purchases. Unspent funds do not count as payments. The engine makes no global-optimality claim. Under rounding, minimum constraints and changing rates, the avalanche comparator is not proof of a universal optimum.

## Verification

Tests include hand-calculated interest/cent rounding, independent zero-APR algebra on 60 deterministic random portfolios, reversed rate/balance ranking, band widths 0/0.5/1/2, all minimums first, spillover, fixed/percent/percent-plus-interest rules, promotion and locked-target changes, overrides/lumps/fees/purchases, future debt after initial payoff, unsupported terms, tolerance semantics and exact conservation. Workbook/Windows acceptance is separate; Python tests do not execute desktop Excel.

## Current Access balances

`from_ledger(bundle, as_of=..., monthly_minor=..., scenario_id=..., horizon_months=...)` builds a read-only scenario from an Access-exported ledger bundle. It uses opening balances plus posted transactions through `as_of`; future transactions are excluded. Each owed card requires exactly one active set of explicit APR/minimum terms and the latest eligible statement must have a balanced reconciliation. Its source statement ID is a provenance anchor: subsequent posted activity changes the current balance, so the snapshot does **not** claim the statement closing equals current debt. Zero/credit-balance cards are omitted.

This convenience snapshot supports USD, one fixed-rate bucket per card. Missing statements/reconciliation/terms, multiple buckets, calendar promotions/deferred-interest terms and mixed currencies are refused rather than guessed. Promotions can instead be modeled in an explicitly reviewed what-if scenario with month-based terms. The helper never mutates the ledger bundle or accesses the database itself.
