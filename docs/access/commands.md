# Repository command semantics (task 2b)

`perfin_store.repository.Repository` implements the contract 1.0.0 command flow ([docs/contracts.md §4](../contracts.md#4-import-review-and-commit-interfaces)). This page records the choices the contract leaves to the store, plus the gaps that need a tracker decision. Behaviour shown here is tested on Linux against the test-only fake; Access behaviour is pending ([README](README.md#windows-acceptance-pending)).

## Common rules

- **Input validation.** Every input is validated with `perfin_contracts.semantic.validate_document`: structure, version (`E_VERSION_UNSUPPORTED` on a newer minor) and payload rules.
- **Post-write validation.** After writing, inside the same transaction, the whole ledger is exported as a `ledger_bundle` and validated again. Those errors come back with a `post-command ledger check:` message prefix and roll everything back.
- **Fail closed on open.** If the stored ledger is already invalid when the database is opened, writes are refused (`E_SCHEMA`).
- **expected_versions.**
  - Every entry must match the current `row_version`; otherwise `E_STALE_VERSION` (or `E_REF_UNKNOWN` if the entity does not exist).
  - The command's *target* must be listed. A missing entry is `E_STALE_VERSION`:

    | Commands | Target that must be listed |
    | --- | --- |
    | Batch commands | `batch` |
    | `edit_transaction`, `set_splits`, `reverse_transaction` | `transaction` |
    | `link_transfer` | both `transaction` legs |
    | `unlink_transfer` | `transfer_link` |
    | Upserts of an existing `statement`, `reconciliation`, `card_terms` or `asset_valuation` | that entity |

  - Every change bumps `row_version`. `statement_payment` has no `row_version` column, so its version is always 1 (T5).
- **Replays.**
  - A `command_id` that is already in `command_log` returns `replayed` / `E_IDEMPOTENT_REPLAY`.
  - Rejected commands are not logged, so a corrected command may reuse its id.
- **Audit.** `audit_log` gets one row per changed entity, with `before_json`/`after_json` (contract shapes, plus `reason` where the payload has one). `audit_ids` are `<command_id>.<nnnn>`.
- **Derived ids.** Ids are `a.b.c` when that fits the contract id pattern. Otherwise they are `<prefix>.<40 hex of SHA-256>`.

  | Id | Form |
  | --- | --- |
  | Imported transaction | `<batch_id>.r<row>` |
  | Its splits | `<txn>.s<n>` |
  | Rollback reversal | `<txn>.rev` |
  | Link split | `<txn>.tl.<link>` |

## Administrative operations (no contract command exists)

| Operation | Why | Behaviour |
| --- | --- | --- |
| `stage_batch(staging_batch)` | Staging is not a command in 1.0 | Writes `import_batch` and `staging_row`, never the ledger. Needs `batch_status: staged` and a known account. Re-staging the same file for the same account returns `replayed`. Fields that have no column are dropped (T2). |
| `import_bundle(ledger_bundle)` | No command creates accounts, categories or manual history (T1) | Insert-only and all-or-nothing. It validates the bundle *merged with* the stored ledger, refuses existing ids (`E_DUPLICATE_ID`) and needs a committed batch for imported transactions. Logged and audited. |
| `set_default_categories(out, in)` | There is no command to categorize staging rows (T3) | Stored in `contract_meta`. An approved row with no `proposed_splits` gets one category split: outflow for negative amounts, inflow otherwise. With no default set, commit fails with `E_ROW_UNRESOLVED`. |

All three are logged in `command_log` with their own `command_type` (`stage_batch`, `import_bundle`, `set_default_categories`).

## Commands

| Command | Store behaviour |
| --- | --- |
| `approve_rows` | Needs a batch that is not committed or rolled back. Each row must exist (`E_REF_UNKNOWN`), have no errors (`E_ROW_UNRESOLVED`), and have duplicate status `none` or `confirmed_distinct` (`E_DUPLICATE_UNRESOLVED`). The batch becomes `approved` once every row is decided and at least one is approved. It becomes `rejected` if every row is rejected. |
| `reject_rows` | The reason is kept in the audit `after_json`. |
| `resolve_duplicate` | Only `possible` rows; otherwise `E_BATCH_STATE`. A `confirmed_duplicate` row must still be rejected explicitly. |
| `commit_batch` | See the [commit_batch](#commit_batch) section below. |
| `rollback_batch` | See the [rollback_batch](#rollback_batch) section below. |
| `edit_transaction` | Changes the description and dates, and the amount when the transaction has **one** split (that split follows the amount). With several splits, collapse them with `set_splits` first (`E_SPLITS_UNBALANCED`). Reconciled and linked amounts are protected by the post-write check (`E_RECON_MISMATCH`, `E_TRANSFER_AMOUNT`). |
| `set_splits` | Replaces all splits. They must sum to the amount, reference known categories and links, and not reuse another transaction's split id. Adjustment splits only on manual transactions (contract rule). |
| `reverse_transaction` | Creates the negating reversal (`entry_method: reversal`, same categories and links). It refuses a second reversal and refuses a linked transfer leg (`E_TRANSFER_UNPAIRED`): unlink it first (contract 1.0 limit). |
| `link_transfer` | See the [link_transfer and unlink_transfer](#link_transfer-and-unlink_transfer) section below. |
| `unlink_transfer` | See the [link_transfer and unlink_transfer](#link_transfer-and-unlink_transfer) section below. |
| `record_statement` | Inserts, or updates with the expected version. Buckets are replaced as a whole. Duplicate `bucket_id` values are `E_DUPLICATE_ID`, which matches contract 1.0.1 (PR #18) and the `statement_bucket_balance` key. `evidence_ref` must be opaque: values containing `/` or `\` are refused (`E_PATTERN`). PDFs never go into Access. |
| `allocate_statement_payment` / `remove_statement_payment` | Allocation follows the contract's payment-portion rules (`E_ACCOUNT_KIND`, `E_ALLOCATION_EXCEEDS`). Removal deletes the row; the deleted row is kept in `before_json`. |
| `reconcile_statement` | Inserts, or updates with the expected version. Included transactions must exist and may not belong to another reconciliation (`E_DUPLICATE_ID`). The contract recomputes `difference_minor`. |
| `record_valuation`, `set_card_terms` | Upsert. Card APR buckets are replaced as a whole. The contract's local rules and its asset-only / credit-card-only rules apply. |
| `save_payoff_scenario` | **Not stored**: there is no table in the reference DDL (T7). Returns `E_COMMAND_PAYLOAD`. |

### commit_batch

- **Hash.** The hash must equal the staged file's; otherwise `E_BATCH_STATE`.
- **Replay.** A batch that is already committed returns `replayed` before its version is checked. A re-sent commit with an old expected version is still a harmless replay.
- **State.** The batch must be `approved`.
- **What is written.** Each approved row becomes one `ledger_txn` with `source` (batch, row, source transaction id), plus its splits. Proposed split ids are renumbered. The batch is marked `committed` with `committed_at`. All of this happens in **one database transaction**.
- **Guards.** These rules are applied again at commit time:
  - errors, duplicates, split sums and references;
  - a `source_txn_id` already in the ledger for the account, or repeating an earlier approved row of the same batch, is `E_DUPLICATE_UNRESOLVED` unless the row is `confirmed_distinct`. The whole commit is rejected.
- **Failure.** Any engine failure rolls back the whole batch.

### rollback_batch

- **Non-destructive.** One reversal is created per batch transaction, posted on the original date, so balances return to their pre-import values on every date. The batch becomes `rolled_back`.
- **Skipped.** Transactions that are already reversed are skipped.
- **Refused** (`E_BATCH_STATE`) if any transaction in the batch:
  - is in a reconciliation (in progress or balanced);
  - has a statement-payment allocation;
  - is a linked transfer leg.

### link_transfer and unlink_transfer

**link_transfer** links whole transactions only. The rules:

- the legs are on different accounts (`E_TRANSFER_SAME_ACCOUNT`);
- `from < 0` and `to = −from` (`E_TRANSFER_AMOUNT`);
- neither leg is already linked (`E_TRANSFER_UNPAIRED`).

Each leg's splits are replaced by one transfer split. The previous splits are kept in the audit trail. A partial link, such as the principal portion of a mortgage payment, cannot be expressed by the 1.0 payload (T4). It can be loaded only through `import_bundle`.

**unlink_transfer** restores each leg's splits as they were before the link, taken from the audit trail. For a link with no audit record (one loaded through a bundle), the link's transfer splits become one default-category split. With no default set, the command is rejected. The link row is then deleted. The post-write check refuses an unlink that would leave a statement-payment allocation on a non-payment.

## Tracker items (contract gaps and ambiguities found by 2b)

None of these changed the contract. Each needs a coordinator decision before 1.1:

| # | Finding | 2b behaviour now |
| --- | --- | --- |
| T1 | No command creates accounts, categories or manual transactions. | Logged admin `import_bundle`. |
| T2 | The `staging_row` DDL has no column for `duplicate.matched_row_number`, `duplicate.evidence`, `transfer_candidate_transaction_id` or `parsed.running_balance_minor`. | Dropped at stage time; not returned by `export_staging_batch`. |
| T3 | No command sets or edits `proposed_splits` on a staged row. | Default categories in `contract_meta`; otherwise `E_ROW_UNRESOLVED`. |
| T4 | The `link_transfer` payload cannot say which splits form the transfer. | Whole-transaction links only. |
| T5 | `statement_payment` is an `expected_versions` entity but has no `row_version` column. | Its version is 1. |
| T6 | `command_result` has no code for a storage or engine failure. | `StorageError` is raised after rollback. |
| T7 | `save_payoff_scenario` has no Access table. | Rejected with `E_COMMAND_PAYLOAD`. |
| T8 | `include_in_net_worth` is optional in JSON, but Access Yes/No cannot store Null [Unverified]. | An absent flag is stored as `TRUE`. |
| T9 | Access compares text keys case-insensitively [Unverified], but contract ids are case-sensitive. | `T001` and `t001` collide (the fake models this). Suggest a contract rule that ids are unique case-insensitively. |
| T10 | `uq_batch_file (account_id, source_file_sha256)` blocks re-staging a file after `rollback_batch`. | Re-importing a rolled-back file needs a contract decision. |
| T11 | The format of `rpt_review_queue.error_codes` is unspecified. | The CSV uses `;`-joined codes; the view returns raw JSON. |
| T12 | `rpt_card_status` derivations are unspecified. | Latest statement with `period_end ≤ as_of`; terms effective on `as_of`; payments are allocations whose transaction posted on or before `as_of`; `unpaid = max(0, statement owed − those payments)`; utilization in basis points, rounded half-to-even; null when the limit is null or 0. To be confirmed with 2c/3b. |
| T13 | `command_result` has no warnings field. | Dropped staging fields (T2) cannot be reported back. |
| T14 | Contract 1.0.1 (PR #18) rejects duplicate bucket ids. | Already enforced. Compatible; no change is needed when it merges. |
| T15 | `scan_repo_for_forbidden()` (1c) reports the nil UUID `00000000-…-000000000000` as a Luhn-valid card number. | 2b builds the nil UUID in code instead of writing it out. Suggest a 1c fix: exclude all-zero sequences. |
