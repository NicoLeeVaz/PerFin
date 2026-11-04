# PerFin contracts 1.0.0

Task 1a ([#2](https://github.com/NicoLeeVaz/PerFin/issues/2)). Status: **proposed freeze for Wave 2**. The freeze takes effect when the coordinator records the Wave 1 gate in [tracker #1](https://github.com/NicoLeeVaz/PerFin/issues/1).

The contracts let the importer (2a), the Access backend (2b) and the Excel shell (2c) build independently against the same definitions. They are a small contract, not an accounting platform.

| Artifact | Path |
| --- | --- |
| Version | [`contracts/VERSION`](../contracts/VERSION): `1.0.0` |
| JSON schemas (exchange documents) | [`contracts/schemas/*.schema.json`](../contracts/schemas/) |
| Excel read-only report tables (CSV/table columns) | [`contracts/schemas/report_tables.json`](../contracts/schemas/report_tables.json) |
| Reference Access DDL (**not executed**) | [`contracts/access/perfin_v1_reference.sql`](../contracts/access/perfin_v1_reference.sql) |
| Synthetic examples | [`contracts/examples/valid/`](../contracts/examples/valid/), and [`invalid/`](../contracts/examples/invalid/) with [`expected.json`](../contracts/examples/invalid/expected.json) |
| Conformance validator (standard library) | [`contracts/python/perfin_contracts/`](../contracts/python/perfin_contracts/) |
| Tests | [`contracts/tests/test_contracts.py`](../contracts/tests/test_contracts.py) |

To validate a document:

```bash
PYTHONPATH=contracts/python python3 -m perfin_contracts contracts/examples/valid/ledger_household.json
```

To run the conformance tests:

```bash
python3 -m unittest discover -s contracts/tests -v
```

## 1. Architecture rules the contract encodes

- **One authoritative ledger.** It is the Access database (task 2b). JSON/CSV documents are exchange and test formats, not a second store. The validator checks documents; it holds no data.
- **Flow:** importer → `staging_batch` → human review → `command` → Access repository → `rpt_*` report tables → Excel refresh.
  - Staging rows are **not** ledger records.
  - Excel and modules change data only by emitting a validated `command`. Refresh never writes back.
- **Modules.** Payoff (3b/4a) and statements (3c/4b) read report tables and emit `payoff_result` / `net_worth_report` documents or commands. Their manifest must declare `writes_ledger: false`. Each Excel module ships its own workbook file.
- **Privacy-related fields** (to be reconciled with 1c at the gate):
  - account IDs are aliases (`card:alpha`), never numbers;
  - `number_hint` holds at most the last 4 digits;
  - a full `card_number` field is rejected as an unknown field;
  - `source_file_name` is a base name only, never a local path;
  - `evidence_ref` is an opaque reference.

## 2. Conventions

| Topic | Rule |
| --- | --- |
| Money | JSON integers in minor units (USD cents), bounded to ±(2⁵³−1) so Excel/VBA doubles hold them exactly. **Floats, numeric strings and booleans are rejected** (`E_AMOUNT_NOT_INTEGER` / `E_TYPE`). Rates are decimal strings (`"0.2499"` = 24.99%). Percentage-point bands are strings (`"0.5"`). |
| Sign | `amount_minor` is from the account's point of view. **`+` = money into the account or less owed; `−` = money out of the account or more owed.** Asset balances are positive. Liability balances are negative when money is owed. Excel displays liabilities as positive owed amounts (`display_balance_minor = −ledger_balance` for liabilities). Payoff documents use non-negative *owed* amounts (`owed = −ledger balance`). |
| Dates | ISO `YYYY-MM-DD` calendar dates, validated as real dates (leap years included). No time zone. Timestamps are UTC `YYYY-MM-DDTHH:MM:SSZ`. |
| Currency | ISO 4217 code per account. Transactions, valuations and transfer legs must match their account's currency. Cross-currency transfers and FX are **unsupported in 1.0**. |
| IDs | Stable text keys (`[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}`). Account IDs are `<class prefix>:<alias>`. Commands use UUIDs. |
| Text | Stored and shown as text. A writer must never turn a value beginning with `= + - @`, TAB or CR into a formula (example: `t002`). |
| Opening balances | `opening_balance_minor` + `opening_balance_date` on the account. They are balance setup: **not income, not spending**. Ledger transactions must be posted strictly after the opening date. |

## 3. Entities (ledger_bundle)

| Entity | Key constraints (validator rule → error code) |
| --- | --- |
| `account` | Kind must agree with class (credit_card/loan/mortgage/other_liability are liabilities) → `E_ACCOUNT_KIND`. Holds ownership %, legal liability %, liquidity, tax status and the net-worth include flag. |
| `category` | Kind is one of `income`, `expense`, `interest` or `fee`; interest and fee are expenses reported separately. A parent must exist. |
| `transaction` | Account must exist (`E_ACCOUNT_UNKNOWN`) and currencies match. `transaction_date ≤ posted_date`. **Splits must sum to the amount** (`E_SPLITS_UNBALANCED`). Imported transactions carry `source` (batch, row, source transaction ID). Edits bump `row_version`. Reversals are new transactions that negate the original (`entry_method: reversal`): the total **and every split** (same kinds, categories and links, opposite amounts), so a reversal cannot re-categorize. A linked transfer leg is corrected with `unlink_transfer` + `set_splits` rather than reversed while linked (1.0 limit). |
| `split` | `category` splits need a category. `transfer` splits need a `transfer_link_id` and **no category** (`E_SPLIT_KIND`), so they never count as income or expense. `adjustment` splits are uncategorized and unlinked (explicit reconciliation adjustments), and appear only on a manual transaction or on the reversal of a manual adjustment. |
| `transfer_link` | Joins two transactions on different accounts (`E_TRANSFER_SAME_ACCOUNT`). Each leg has transfer splits for the link (`E_TRANSFER_UNPAIRED`). The from-leg is negative and equals minus the to-leg (`E_TRANSFER_AMOUNT`). The legs may be days apart. Only `confirmed` links are ledger records; candidates live in staging. |
| `statement` | `period_start ≤ period_end ≤ due_date`. Balances use the ledger sign. Optional APR-bucket balances must sum to the closing balance (`E_BUCKET_SUM`). Minimum, interest and fees are as disclosed. |
| `statement_payment` | Allocates a confirmed payment (an inflow on the same card) to a statement. Allocations never exceed the payment (`E_ALLOCATION_EXCEEDS`). A plan is not a payment. |
| `reconciliation` | `difference = closing − (opening + Σ included posted transactions in the period)`. It is recomputed and must match. `balanced` requires 0 (`E_RECON_MISMATCH`). |
| `card_terms` | Credit-card accounts only. Holds the minimum rule (`fixed`, `pct`, or `pct_plus_interest` with a floor) and APR buckets. A promotion needs `promo_end_date` and `post_promo_apr`; deferred interest needs a deadline. `credit_limit_minor: null` means unknown, and utilization is then unknown, never computed. |
| `asset_valuation` | Asset accounts only. Dated value with source, method and optional cost basis. Non-cash assets (property, vehicles) take their value from valuations; their account opening balance is 0. |

Staging and audit tables appear in the DDL: `import_batch`, `staging_row`, `command_log`, `audit_log` and `contract_meta`.

### Accounting semantics

These are proven by the tests in `Semantics`:

- **Card purchase.** `−10000` on the card with an expense split. Spending is $100 and debt is up $100.
- **Card payment from checking.** Checking `−10000` and card `+10000`, both transfer splits joined by a link. The payment adds **no** expense, checking falls $100, and the card returns to its prior debt.
- **Refund.** A positive split on the expense category reduces spending.
- **Interest and fees.** Separate `interest` / `fee` categories; they are expenses, not principal.
- **Mortgage payment.** The principal part is a transfer split to the mortgage account, so it does not reduce net worth. The interest part is an `interest` expense.

## 4. Import, review and commit interfaces

| Step | Contract |
| --- | --- |
| Profile | `import_profile` declares: encoding, delimiter, header and footer rows, expected field count, column mapping, date format, decimal and thousands separators, and the sign rule (`as_is`, `invert` or `debit_credit_columns`). The sign rule must produce the canonical sign. Dedupe keys are declared per profile. |
| Stage | Writes `import_batch` plus `staging_row`, never the ledger. Each row keeps `raw_fields` as exact strings. Parse failures stay as rows with codes (`E_PARSE_DATE`, `E_PARSE_AMOUNT`, `E_PARSE_FIELD_COUNT`, `E_PARSE_ENCODING`). They are **never coerced to zero or today's date**. |
| Duplicates | `exact_reimport` (same file hash, or same source ID and fingerprint) changes nothing on commit. `possible` must be resolved by a human to `confirmed_duplicate` or `confirmed_distinct` (`resolve_duplicate`). Legitimate repeated purchases are kept via `row_occurrence` in the fingerprint. |
| Review | `approve_rows` / `reject_rows`. An approved row cannot have errors (`E_ROW_UNRESOLVED`) or an unresolved duplicate (`E_DUPLICATE_UNRESOLVED`). A batch becomes `approved`/`committed` only when every row is approved or rejected (`E_BATCH_STATE`). |
| Commit | `commit_batch(batch_id, source_file_sha256)` is **atomic**: all approved rows become transactions in one Access transaction, or none do. Repeating it for an already-committed file returns `replayed` (`E_IDEMPOTENT_REPLAY`) and changes nothing. |
| Rollback | `rollback_batch` reverses a committed batch by creating reversal transactions (non-destructive), while nothing in it is reconciled. A failed commit rolls back the database transaction. |
| Edits / audit | `edit_transaction`, `set_splits`, `reverse_transaction`, `link_transfer`, `unlink_transfer`, `record_statement`, `reconcile_statement`, `record_valuation`, `set_card_terms`, `save_payoff_scenario`. `save_payoff_scenario`, `set_card_terms` and `set_splits` payloads get the same record-local rules as the standalone documents. Rules needing ledger context (references, balances) run in the repository at execution. Each command carries `expected_versions` for optimistic concurrency (`E_STALE_VERSION`) and produces a `command_result` plus `audit_log` rows holding before/after JSON. **Rejected commands change nothing.** |
| Excel | Refreshes the `rpt_*` tables in `report_tables.json` as read-only tables. CSV dialect: UTF-8, comma, RFC 4180 quoting, CRLF, exact headers, empty field = null, `TRUE`/`FALSE`, integer minor units. |

## 5. Module interfaces (frozen)

- **Read interface.** Modules read only the `rpt_*` tables.
  - `rpt_card_terms`: one row per APR bucket, carrying the minimum rule, the post-promotion APR, the credit limit and the terms source.
  - `rpt_statement_buckets`: per-statement bucket balances.
  - `rpt_accounts`: ownership, legal liability, liquidity and tax status.
  - `rpt_valuations`: cost basis.
  - Together these are enough to build `payoff_scenario` and `net_worth_report` without reading Access directly. `promo_end_month` is derived from `promo_end_date` relative to the scenario's `as_of`.
- **Payoff.**
  - **Input: `payoff_scenario`.** Cards come from reconciled statements (`source_statement_id`), with APR buckets and owed balances, a minimum rule, assumed charges and fees, a cash plan, strategies (`largest_balance`, `snowball`, `avalanche`, `near_apr_hybrid` with `gap_pp`/`prefer`, optional `lock_target`) and tolerance limits.
  - **Tolerance.** `null` means unset, and unset never means approved.
  - **Accrual model.** 1.0 freezes only `m1_monthly_apr_div_12`, a documented approximation.
  - **Output: `payoff_result`.** Per-strategy status (`paid_off`, `horizon_reached`, `infeasible_budget` or `unsupported_terms`), totals, the Δ against avalanche, flags and the monthly schedule.
  - **Payoff dates.** `debt_free_month` and per-card payoff months are null unless paid off.
- **Statements: `net_worth_report`.**
  - Contents: dated lines with ledger and included amounts, the valuation date, a stale flag and the exclusion reason (`missing_fx_rate`, `missing_valuation`, …).
  - Totals: net worth and liquid net worth, under a declared `liability_view` (`legal` or `economic`).
  - Bridge: opening + income − expenses + valuation change + other = closing.
  - Scope: a management statement. It makes no GAAP, tax or lender compliance claim.
- **`module_manifest`.**
  - Fields: module ID and version, kind (`import_profile`, `calculation_module` or `excel_workbook`), the supported contract range, the report tables it reads, the documents it emits, the commands it may issue, its own `workbook_file`, and `writes_ledger: false` (otherwise `E_MODULE_WRITES_LEDGER`).
  - CSV import profiles are plugins of kind `import_profile`.

## 6. Version and compatibility policy

- The contract is semantic-versioned and every document carries `contract_version`.
  - **Patch** (1.0.x): wording, examples or validator fixes with no change to accepted documents. Readers accept any patch.
  - **Minor** (1.x.0): additive optional fields, enum values or document types. A reader **fails closed** on a newer minor than it supports (`E_VERSION_UNSUPPORTED`). Writers emit the lowest version that represents the data.
  - **Major** (x.0.0): breaking changes. Readers reject them.
- Schemas use `additionalProperties: false`, so unknown fields are rejected instead of silently dropped.
- Access stores the version in `contract_meta` (`schema_version`). 2b's setup and migration scripts must refuse to open a newer-major database.
- **Changes after the freeze** go through the tracker. The coordinator bumps the version, and dependent tasks are paused and revalidated (see the execution plan). Wave 2 builds against 1.0.x only.

## 7. Windows / Office assumptions (pending verification by 2b/2c)

None of these were run here; this task was executed on Linux only.

- Access stores `*_minor` columns as **Currency holding the integer count of minor units**. Currency is exact fixed-point, so integer cents in it are exact, with far more range than the ±$21.47M a 32-bit Long allows. Repository code must reject non-integers, and the reference DDL's `CHECK (x = Int(x))` needs ANSI-92/ADO mode.
- `ledger_txn` is used because `transaction` is reserved.
- Dates are `DATETIME` with no time part.
- Rates are text.
- JSON columns (`*_json`) are Long Text (MEMO).
- Excel/VBA hold integer cents exactly as doubles up to 2⁵³. Display divides by 100 in formatting only.
- VBA `Round()` is banker's rounding; calculations stay in the engine. The payoff research recommends `WorksheetFunction.Round` or integer routines for any VBA port.
- Power Query/ODBC reads the `rpt_*` tables or queries. The Access database engine (ACE) bitness must match Office/Python; 2b records it.
- The DDL is a **reference**. 2b must execute it, adjust syntax if Access rejects any part, and report the evidence. A DDL change that alters a JSON field is a contract change.

## 8. Known limits and items for the Wave 1 gate

- Out of 1.0 scope (unsupported, must be refused): multi-currency/FX, investment holdings and lots, pending-authorization ledger records (staging only), split-level tax tags, budgets, daily-accrual payoff models.
- **Reconcile with 1c:** sync-folder and data-directory rules, `number_hint`, `source_file_name`, audit-log redaction of `before_json`/`after_json`, and the NoPii export envelope (not defined here).
- **Reconcile with 1b:** if an Access seed is adopted, its table names map onto these entities. They do not replace them.
- The validator implements a declared JSON Schema subset and rejects unknown keywords. Other languages may use any draft 2020-12 validator for the structural part, but the cross-record rules live in `semantic.py` and must be ported or called.
