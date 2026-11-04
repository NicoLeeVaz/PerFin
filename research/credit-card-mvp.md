# First usable version: finances and credit cards

Proposed acceptance contract, 2026-11-04. This is independent of Excel/Access/SQLite implementation.

**Outcome:** see what was spent, what is owed, what is due next, and whether the ledger matches the bank and card statements.

## Minimum screens / Excel tabs

| View | Must answer |
| --- | --- |
| Overview | Cash balances, card debt, monthly income/spending, next due payments and data-as-of date |
| Transactions | Account, posted date, original description, category, amount and review/reconciliation state |
| Cards | Statement balance, current posted balance, credit limit, due date, issuer minimum due, confirmed payments and planned payment |
| Statements | Opening/closing balances, included posted transactions and unexplained reconciliation difference |
| Review | Possible duplicates, ambiguous transfers, rejected imports and uncategorized entries |

## Minimal data model

| Entity | Essential information |
| --- | --- |
| Account | Stable ID, alias, asset/liability type, currency, opening balance/date; no full card number required |
| CardTerms | Account ID, effective dates, limit, APR/promotion details if known; actual statement dates override predicted dates |
| ImportBatch / ImportRow | File hash, account, importer version, row identity, raw values, source transaction ID, disposition and error |
| Transaction / Split | Stable IDs, account, transaction and posted dates, exact amount, currency, category allocation and source links |
| TransferLink | Both account legs, match evidence, review status; unmatched legs remain visible |
| Statement | Card ID, cycle start/end, due date, opening balance, closing balance, minimum due, fees and interest as disclosed |
| PaymentAllocation | Confirmed payment/transfer, statement, allocated amount; distinguish a plan from a posted payment |
| Category / Rule | Explicit precedence, condition, result and rule version; manual overrides retained |

Use integer minor units for posted amounts (USD cents for the initial scope); use Decimal or fixed precision for rates/calculations and explicit rounding. An Access implementation may use Currency fields with an enforced minor-unit policy. Opening balances are balance setup, not income or spending. Separate currencies; do not silently sum them.

## Rules that prevent misleading totals

- A card purchase is spending and increases debt. Paying the card transfers value from checking to the liability; it is not a second expense. Interest and fees are separate expenses. This treatment is consistent with [GnuCash's explanation](https://www.gnucash.org/docs/v5/C/gnucash-guide/cc-concepts1.html).
- Preserve both source records of a checking-to-card payment, linked to one transfer event. Do not delete one account's movement or book the card-side receipt as income.
- Reimporting an identical file changes nothing. Prefer issuer transaction IDs scoped to account; where absent, identify possible duplicates using multiple fields and preserve legitimate repeated purchases. Amount/date alone is not sufficient.
- Pending items do not enter a closed statement's reconciliation. Retain a pending-to-posted link if pending data is imported.
- Store actual statement closing and due dates. Calendar-month spending and predicted cycle dates are useful views, not substitutes for statements.
- Store issuer minimum due and statement balance. Derive payment progress from confirmed allocations, showing partial payments. Refunds and credits are not automatically proof that the issuer's minimum-payment obligation is satisfied.
- Show posted-balance utilization with its date and denominator. Do not label it credit-bureau-reported utilization. Missing/zero limits yield “unknown,” not a division error or fabricated percentage.
- Preserve the raw import and an edit trail. Malformed dates/amounts go to review; they do not silently become today's date or zero dollars.

For reconciliation, using a positive-debt display convention: closing debt = opening debt + purchases + fees + interest - payments - credits. The implementation must document its internal sign convention separately. Fees/interest already present as transactions must not be added a second time.

## Acceptance scenarios

| Scenario | Expected result |
| --- | --- |
| $100 card purchase, followed by $100 checking-to-card payment | Spending $100; checking down $100; card debt returns to its prior level; payment adds no expense |
| Import the same statement twice, then an overlapping export | Identical records do not inflate balances; uncertain overlaps enter review |
| Two real $20 purchases at the same merchant on the same date | Both retained unless reliable identity evidence establishes duplication |
| $500 statement; $200 confirmed payment | Statement and payment history preserved; $300 unallocated statement balance shown, subject to subsequent issuer adjustments |
| $25 refund and $5 interest | Credit reduces the relevant purchase/category balance; interest is its own expense |
| Purchase before close, posted after close | Assigned using actual statement evidence; no silent reassignment based solely on purchase date |
| Pending authorization becomes posted at a different amount | One final posted purchase, with linkage/review; no double count |
| Transfer legs arrive days apart | Match can span dates; unresolved/ambiguous legs remain visible |
| Month end, leap day, changed due date | Valid explicit dates; no fixed “15th” reset of historical payment status |
| Comma/quote in description, empty final CSV field, invalid amount, US/EU date formats | Correct profile-specific parsing or explicit rejection; no silent value loss |
| Missing limit, credit balance, changed limit | Explicit handling; no invented limit or misleading utilization |
| Restore backup and reopen Excel | Same reconciled balances, import identities, statement history and refresh result |

These are proposed tests, not tests reported as passing. First trial: one checking account, two cards, two cycles, synthetic data. Later modules can add debt payoff scenarios, investments, tax views and optional bank connectivity after this contract passes. No payment initiation is part of v1.
