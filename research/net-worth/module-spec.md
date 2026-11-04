# Optional personal statements module: specification

Date: 2026-11-04. Status: **proposed design** with an executed synthetic example, [`example/statements_demo.py`](example/statements_demo.py), and its tests. These are personal management statements. They make **no claim of GAAP, tax, lender or regulatory compliance**, and a balance sheet says nothing about retirement sufficiency.

## Scope

The module is separate from the card payoff planner and optional. It has its own workbook tabs or UI and reads the same ledger. It produces:

| Statement / view | Definition |
| --- | --- |
| Balance sheet (dated) | Included assets − included liabilities at `as_of`. A *gross* total plus labelled sub-views: liquid net worth, and economic-share vs legal-liability liability views. |
| Income and expense | Period income and expense. Card and mortgage **interest and fees are expenses**. Debt principal is not an expense. |
| Cash flow | Change in included cash accounts, classified as operating, debt principal, investing & retirement, and internal transfer. It must equal the actual change in cash. |
| Net-worth bridge | `closing NW = opening NW + income − expenses + valuation changes + other explained changes`, reconciled exactly on the declared basis |
| Schedules | Retirement and brokerage accounts (account total, with holdings as detail), real estate with linked mortgages, vehicles, loans, business interests, other assets |
| Later: retirement scenarios | Contributions, returns, inflation, fees, taxes, retirement age and income assumptions. Kept in a **separate scenario area**, never mixed with observed balances. |

## Data model (proposed)

| Entity | Key fields | Notes |
| --- | --- | --- |
| `Account` | `account_id` (shared with the card module, e.g. `card:A`), kind (asset/liability), class, currency, liquidity (liquid/restricted/illiquid), `ownership_pct`, `legal_liability_pct`, include flag, `parent_id`, tax_status (taxable/tax-deferred/tax-free/unknown) | One row per real account or asset. **The card module and this module use the same IDs.** |
| `JournalEntry` / `Line` | date, kind (opening/income/expense/transfer/principal/valuation/purchase), lines with `account_or_category` and cents | Lines must sum to 0 (double entry, debit-positive convention). Opening balances post against `eq:opening`, never income. |
| `Valuation` | account, `as_of`, value, source, method (statement, market close, appraisal, automated estimate, owner estimate), currency | Marks non-cash assets. Has a staleness threshold per class. |
| `Holding` | parent account, instrument, quantity, value, `as_of`, cost basis | **Detail only.** Must reconcile to the parent total. Never summed into net worth. |
| `CostBasis` | holding or asset, basis, acquisition date, source | Kept separately from current value. Used for later after-tax estimates, not for the gross balance sheet. |
| `FxRate` | currency pair, date, rate, source | No rate means the account is excluded from the converted total and flagged. It is never converted at 1.0. |
| `Link` | asset ↔ liability (property ↔ mortgage), business ↔ underlying asset | Used for equity displays and double-count checks |

## Integration boundary

- **Single ledger.** Cash and card balances come from the reconciled ledger defined in the [credit-card MVP](../credit-card-mvp.md). This module **reads** those balances. It has no editable copy of card transactions or card balances, and no second card ledger.
- **Ownership of edits.** Card purchases, payments, interest and fees are recorded once, by the card or ledger import. This module adds only items the card module does not own:
  - valuations;
  - retirement, brokerage, property and loan accounts;
  - their transactions;
  - mortgage principal/interest splits.
- **Shared payoff inputs.** The payoff planner reads the same card IDs and reconciled statement balances. A planned payment is not a posted transaction, and statements show only posted entries.
- **Excel.** Statement tabs are refreshed outputs. Any edit goes through the one controlled write path chosen in [local architecture](../local-architecture.md).

## Rules

1. **Valuation date and source** are shown for every non-cash line. A value older than its class threshold (proposed: 120 days for property, 7 days for market accounts) is flagged **stale** but still shown with its date. A missing valuation shows "unknown" rather than zero.
2. **Ownership versus liability responsibility.**
   - Assets are included at the household's economic share (`ownership_pct`).
   - Liabilities are included according to the selected view:
     - **legal** (default) shows the obligation the household is legally responsible for, e.g. 100% of a jointly and severally owed mortgage even if the property is 50% owned;
     - **economic** shows the household's share.
   - The two views are labelled and never silently blended. Liabilities are not multiplied by ownership percentage automatically.
   - Actual responsibility comes from the loan documents [Assumption until known].
3. **No double counting.**
   - **Investments.** Count the account total *or* its holdings, never both. Holdings are children (`parent_id`). Posting to a holding is rejected, and the holdings must reconcile to the parent.
   - **Property.** Count the gross property value as an asset and the mortgage as a liability. "Equity" (value − mortgage) is a display, not a separate asset.
   - **Business.** Include *either* the business interest as one equity-method line *or* the underlying business assets and liabilities, never both. A `Link` marks the alternative as excluded.
   - **Cards.** Card debt appears once, as the card liability. A card payment moves value between cash and the card.
4. **Transfers are neutral.**
   - Principal paid from included cash lowers cash and debt equally, so net worth does not change.
   - An employee retirement contribution from included checking to an included retirement account is a **transfer**, not an expense.
   - An **employer contribution is income** when received.
   - Moves between the household's own cash accounts are internal and appear neither as income nor as a net cash flow.
5. **Interest and fees are expenses.** Card interest and mortgage interest reduce net worth through the income statement.
6. **Unrealized value changes are valuation changes.** They change net worth but are not cash receipts and not income. They appear in a separate bridge line.
7. **Currency.** Each account keeps its currency. Totals are in the base currency (USD) only where a dated rate exists. The rate and date are disclosed.
8. **Liquidity and access.**
   - Liquid net worth = liquid assets − short-term debt (cards, other revolving loans), on the declared definition.
   - Retirement accounts are **restricted**: they are tracked, but excluded from liquid net worth. Their tax status is recorded.
   - Pension and Social Security expectations are future cash-flow scenario inputs. They are **not** capitalised into current net worth.
9. **Separate views.** Gross net worth (the default), an optional *estimated* after-tax or liquidation view (which needs cost basis, assumed tax rates and selling costs, all labelled as assumptions) and future retirement scenarios are three distinct outputs with distinct labels.

## Worked synthetic statements (from the executed example)

All accounts are fictional. Opening date 2026-06-30, closing 2026-07-31. Amounts are in USD.

**Opening balance sheet, legal-liability view:**

| Line | Amount |
| --- | ---: |
| Checking | 8,000 |
| Savings | 15,000 |
| 401(k) (restricted) | 65,000 |
| Taxable brokerage | 20,000 |
| Home | 450,000 |
| Rental at 50% owned share of a $300,000 value | 150,000 |
| Card A | −3,500 |
| Card B | −1,200 |
| Home mortgage | −300,000 |
| Rental mortgage, 100% legally owed | −200,000 |
| **Net worth** | **203,300.00** |

The EUR savings account has no FX rate, so it is excluded and flagged.

**July activity:**

| Item | Treatment | Effect on net worth |
| --- | --- | ---: |
| Salary $6,000 to checking | Income | +6,000 |
| 401(k) contribution $500 from checking | Transfer | 0 |
| Employer match $250 | Income | +250 |
| Groceries $400 on card A | Expense; liability up | −400 |
| Card A interest $65 | Expense | −65 |
| Card A principal payment $2,000 from checking | Principal | **0** |
| Mortgage payment: principal $600 | Principal | 0 |
| Mortgage payment: interest $1,100 | Expense | −1,100 |
| Savings → checking $1,000 | Internal transfer | 0 |
| Brokerage unrealized gain $450 | Valuation change | +450 |

**Net-worth bridge:**

| Line | Amount |
| --- | ---: |
| Opening net worth | 203,300.00 |
| + Income (6,000 + 250) | 6,250.00 |
| − Expenses (400 + 65 + 1,100) | −1,565.00 |
| + Valuation change | 450.00 |
| **= Closing net worth** | **208,435.00** |

The bridge equals the closing balance sheet exactly (test `test_bridge_reconciles`).

**Cash flow** (it equals the actual cash change of +$1,800):

| Category | Amount |
| --- | ---: |
| Operating (salary 6,000 − mortgage interest 1,100) | 4,900 |
| Debt principal (card 2,000 + mortgage 600) | −2,600 |
| Investing & retirement (401(k) contribution) | −500 |
| Internal transfers | 0 |

The card *purchase* and card *interest* do not appear in cash flow because no cash moved. They appear as liabilities and expenses.

**Sub-views and flags at close:**

- **Liquid net worth: 42,085.** This is checking 10,800 + savings 14,000 + brokerage 20,450 − cards 3,165. It excludes the restricted 401(k) and property.
- **Economic liability view: 308,435.** The economic view counts 50% of the rental mortgage, so it is $100,000 higher than the legal view. This difference is the reason the views must be labelled.
- **Flags:** the home valuation (2026-01-15) is stale, and the EUR account has no rate.

## Tests

**Executed** with `python3 -m unittest discover -s research/net-worth/example -v`: **12/12 passed**. They cover:

- the bridge identity;
- principal neutrality;
- interest as expense;
- retirement contribution as transfer;
- employer match as income;
- cash-flow reconciliation;
- unrealized gain as non-cash;
- holdings not double counted, and posting to a holding rejected;
- unbalanced entries rejected;
- stale and missing-FX flags;
- the legal vs economic liability difference;
- the liquid view.

**Proposed, not executed:**

- business-interest vs underlying-assets exclusion test;
- partial-ownership activity (posting the household share vs full amounts);
- an FX bridge line for currency translation;
- cost-basis-based after-tax estimate with labelled assumptions;
- a property sale and a refinance;
- import of reconciled card balances from the card ledger, checked by ID.

## Open questions / unknowns

- How a partially owned asset's transactions should be recorded: household share only (proposed), or full amounts with a share applied at reporting.
- Actual liability responsibility for joint loans.
- The valuation sources the user will accept (statement, automated estimate, appraisal).
- Staleness thresholds.
- Whether pensions or annuities should appear only as scenario inputs (proposed) or also as a disclosed present-value estimate.
- Tax-status detail for after-tax estimates.

The design makes no asset-sale or retirement-withdrawal recommendation.
