# Personal management statements

`perfin_statements` reads a validated `ledger_bundle` and performs no writes. Access remains the authoritative ledger. Amounts are integer minor units; multiplication by ownership shares or a permitted FX factor uses decimal arithmetic with half-up rounding at the account/split level. The current frozen contract accepts integer ownership percentages only.

```python
from perfin_statements import build_report, build_statements

report = build_report(bundle, as_of="2026-02-28", period_start="2026-02-01")
details = build_statements(bundle, as_of="2026-02-28", period_start="2026-02-01",
                          liability_view="legal", stale_days=365,
                          inclusion_groups=[["ret:total", "holding:one"]])
```

`report` is a validated contract `net_worth_report`. `details` contains that report under `net_worth`, plus `income_expense`, `cash_flow`, `provenance`, `bridge_accounts`, signed-value `assets_minor`/`liabilities_minor`, and `complete`. Positive balances are assets; negative balances are obligations, including cash overdrafts. Totals cover included, measurable accounts only. Liquid net worth is the signed total of accounts explicitly tagged `liquidity="liquid"`; restricted/illiquid accounts and accounts without a liquidity tag are excluded from that subtotal. It is not a forced-liquidation estimate or liquid assets less every household debt. `complete=False` and warnings identify missing valuations or incomplete opening coverage; stale estimates remain visible and flagged.

## Valuation and ownership rules

- Opening net worth is the day **before** `period_start`. Income/activity includes both period endpoints. An account not yet opened contributes zero to the earlier snapshot, and its setup appears in other change.
- Checking, savings, cash and liability accounts use opening balance plus posted transactions through the cutoff. Nonzero closed-account balances remain visible rather than silently erasing debt.
- Retirement, brokerage, real estate, vehicles, businesses and other assets require an explicit valuation. Missing valuation is excluded, never replaced with cost or assumed zero without a warning.
- A dated valuation is the **whole-account end-of-day value**, including that day's posted activity. Only activity posted **after** its date is added. Two valuations on one account/date are rejected as ambiguous. Future valuations are ignored.
- Cost basis is provenance, never added to market value. Valuation source, method, ownership, liquidity and date accompany each line.
- Asset values use `ownership_pct` (default 100). Legal liability view uses `legal_liability_pct` (default 100), independently of asset ownership. Economic view uses `ownership_pct` and warns that legal responsibility can be larger. A 50%-owned home does not automatically halve its mortgage.
- Each `inclusion_groups` entry identifies mutually exclusive representations: account total versus holdings, property versus equity, business equity versus underlying assets. More than one included account in a group is rejected. Set `include_in_net_worth=False` on representations not used. Groups reference known stable IDs. The contract has no parent/holding identity field, so overlap cannot be inferred from account names; absence of groups carries an explicit user-review warning.
- Contract 1.0.1 rejects foreign-currency accounts. They fail with `E_CURRENCY_MISMATCH` even if an FX rate is supplied. No currency conversion or consolidated multicurrency support is claimed. The optional rate parser is forward-compatible only; any future contract extension requires renewed tests and source/date policy.

## Income, cash flow and the bridge

Category splits report income and expenses; refunds reduce the corresponding expense. Transfers never become a second expense. Cash flow covers checking, savings and cash, with signed receipts/payments separated into categories, internal cash transfers, financing, investment transfers, other transfers and adjustments. Retirement contributions and debt principal are transfers; interest is expense.

The bridge identity is:

`opening + income - expenses + valuation change + other change = closing`.

Valuation change is the change in the included value's adjustment over the ledger balance for accounts measurable at both cutoffs. It therefore excludes contributions already in the ledger. **Other change is an unclassified residual requiring review**, not proof that source transactions are reconciled. Account-level opening/closing differences support investigation. Likewise cash-flow `setup_valuation_and_rounding_minor` is a disclosed residual, and `arithmetic_difference_minor` verifies only the resulting arithmetic identity. Neither replaces bank-statement reconciliation. Missing initial values, unrecorded transfers, account setup and rounding may appear in residuals.

These are gross personal management statements. After-tax liquidation, actuarial pension values, retirement sufficiency and tax/lender/GAAP certification are not implemented. Retirement projections remain separate future work.

## Independent synthetic example

`fixtures/statements/household.synthetic.json` contains invented data only. Opening values: cash 100,000, mortgage -40,000, half of a 300,000 property, retirement 200,000 = **410,000** minor units. Period salary 10,000 less spending/refund net 1,500 and interest 500 yields surplus 8,000. A retirement contribution of 5,000 is neutral; its ending valuation of 208,000 implies gain 3,000. Principal payment 10,000 is neutral. Closing net worth is **421,000**, with other change zero. `expected.synthetic.json` records these hand-derived controls.

Run `python -B -W error -m unittest discover -s tests/statements -q`. Linux tests verify the arithmetic, privacy-free pure function, ownership, cutoffs, duplicate basis and explicit unsupported currency handling. Desktop Excel and Windows/Access integration remain pending.
