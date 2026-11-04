# CSV import staging (task 2a)

Task 2a ([#5](https://github.com/NicoLeeVaz/PerFin/issues/5)) builds against contract **1.0.0** ([docs/contracts.md](../contracts.md)). Code: [`src/perfin_import/`](../../src/perfin_import/). Tests: [`tests/import/`](../../tests/import/). Synthetic fixtures: [`fixtures/import/`](../../fixtures/import/).

The importer reads one CSV file, its bytes and an `import_profile`, and returns a `staging_batch` document for human review. It **never writes the ledger**. It does not write files and does no logging. Its only side effect is calling the read-only repository methods listed below. Commit, review commands and storage belong to 2b (Access) and 3a (app).

```
bytes + profile + account_id ──► stage_file ──► staging_batch (contract-validated) + summary counts
                                     │
                                     └── reads only: ImportRepository (get_account, prior_batches,
                                         find_candidates, find_by_source_txn_id, find_transfer_candidates)
```

## Using it

```python
from perfin_import import builtin_profiles, load_profiles_dir, match_profiles, stage_file

profiles = builtin_profiles()                       # or load_profiles_dir("<data root>/config/import_profiles")
hits = match_profiles(data, profiles)               # exact header match; 0 = unknown format, >1 = user chooses
result = stage_file(data, "card_2026-07.csv", hits[0], "card:alpha", repository,
                    category_rules=rules)           # rules are optional
result.document   # staging_batch, already checked by perfin_contracts.semantic.validate_document
result.summary    # counts per review state, duplicate status and error code; no values (log-safe)
```

- `data` must be the file's **bytes**. The importer decodes them with the profile's encoding.
- `source_file_name` may be a full path. Only the base name is stored. Windows and POSIX separators are both handled, and a name that ends in a separator is refused.
- `staged_at` defaults to the current UTC time. Pass it explicitly for reproducible output. Transaction dates never default to anything.
- The contract validator is injected (`validator=`) or imported from `perfin_contracts`. If it is unavailable, profiles are refused (fail closed).
- Exceptions are raised only when the whole file cannot be staged. Their messages contain no field values.

| Exception | Code | When |
| --- | --- | --- |
| `ProfileError` | `E_SCHEMA` (details in `.errors`) | The profile or category rules fail validation |
| `ImportRefused` | `E_ACCOUNT_UNKNOWN`, `E_ACCOUNT_KIND`, `E_CURRENCY_MISMATCH`, `E_PATTERN`, `E_TYPE`, `E_DATE_INVALID` | Unknown account, a profile for another account class, a currency mismatch, a bad file name, `staged_at` or input type |
| `UnknownFormat` (an `ImportRefused`) | `E_SCHEMA`, or `E_PARSE_ENCODING` for an undecodable header | The header does not match the profile. `.found_headers` lists the header cells so a UI can ask the user for a mapping. |

## Parsing rules

These avoid every defect reproduced in [research/reuse/catalog.md](../../research/reuse/catalog.md#reproduced-csvvba-concerns).

| Area | Rule |
| --- | --- |
| CSV | Python `csv` with `strict=True` and RFC 4180 doubled quotes. Quoted delimiters, quoted newlines (kept as `\r\n` exactly), leading/trailing spaces inside quotes and **trailing empty fields are preserved**. Backslash is not an escape character. |
| Oversized fields | A field of any size is read; the process-wide `csv.field_size_limit` is raised only while one file is read and is always restored. A raw field over 4000 characters becomes `E_LENGTH` on that row and the following rows still stage. |
| Malformed quoting | Reading stops at the broken record. Rows read so far are staged, plus one error row (`E_PARSE_FIELD_COUNT`, path `$`, physical line number) in `needs_review`. `summary.file_complete` is `false`, and footer skipping is not applied. |
| Header | The last of `header_rows` holds the column names. Matching is **exact**: no case folding, trimming or fuzzy matching. A missing or repeated mapped column raises `UnknownFormat`. When `expected_field_count` is set, the header width must equal it. |
| Field count | Each data row must have `expected_field_count` fields, or the header width when that is unset. Otherwise the row gets `E_PARSE_FIELD_COUNT` and its raw fields are kept. |
| Blank lines | Completely empty records are skipped and counted (`summary.blank_records_skipped`). A row of delimiters only (`,,,,`) is not blank. It is staged with errors. |
| Encoding | `utf-8`, `utf-8-sig`, `cp1252` and `latin-1`, decoded strictly. Undecodable bytes are **never replaced**. The row gets `E_PARSE_ENCODING` per affected field, and `raw_fields` is `[]` because the exact text cannot be represented. Other rows still stage. An undecodable header raises `UnknownFormat(E_PARSE_ENCODING)`. A UTF-8 BOM under a plain `utf-8` profile is reported with a hint to use `utf-8-sig`. |
| Amounts | `Decimal`-based, to integer minor units. Only the declared decimal and thousands separators are accepted, with **exactly 0 or 2 decimal places**. Grouping must be well formed, and ungrouped digits are allowed. Accepted: one leading `+`/`-`, or parentheses if `parentheses_negative`. Rejected with `E_PARSE_AMOUNT` (**never 0**): currency symbols, trailing minus, the Unicode minus, non-ASCII digits, exponents, an empty required amount, and anything outside ±922337203685477. |
| Sign | `as_is` keeps the file sign. `invert` negates it (cards that show charges as positive). `debit_credit_columns`: the value is `credit − debit`. Debit/credit values must be unsigned. Both non-zero, or both empty, is `E_PARSE_AMOUNT`. One zero and one value is allowed. The result is canonical: **+ = money in / less owed; − = money out / more owed.** The running balance follows the same rule (negated under `invert`). |
| Dates | Exactly the declared `date_format`. `MM/DD/YYYY`, `DD/MM/YYYY` and `DD.MM.YYYY` require two-digit day and month. `M/D/YYYY` and `D/M/YYYY` accept one or two digits. The value must be a real calendar date (leap years). Otherwise `E_PARSE_DATE`. `03/04/2026` is 4 March under `MM/DD/YYYY` and 3 April under `DD/MM/YYYY`. `13/04/2026` under `MM/DD/YYYY` is rejected, never swapped. An empty optional `transaction_date` is `null`. A `transaction_date` after `posted_date` is `E_DATE_ORDER`. |
| Text | Descriptions and source IDs are kept exactly, with no trimming. Descriptions over 1000 characters and source IDs over 128 characters get `E_LENGTH`. A raw field over 4000 characters cannot be stored, so `raw_fields` is `[]` with `E_LENGTH`. |

All errors on a row are reported, not only the first. Error messages never repeat the offending value.

## Fingerprints, duplicates and review states

- **Fingerprint** is `sha256` of a canonical JSON array containing:
  - the scheme tag `perfin-import-fingerprint/1`;
  - the `account_id`;
  - the profile's `dedupe_key` values (default `source_txn_id, posted_date, amount_minor, description`);
  - `row_occurrence`, which is always appended.

  `row_occurrence` counts earlier rows in the same file with the same key values. Two genuine identical purchases therefore get different fingerprints. Fingerprints are deterministic and scoped to the account. Unparsed rows are fingerprinted from their raw fields.
- **Exact file replay.** The same `account_id` and the same file SHA-256 as a prior batch in `staged`, `approved` or `committed` makes every row `exact_reimport` (`review_state: rejected`; commit would change nothing). A `rejected` or `rolled_back` prior batch does not count.
- **Row-level exact reimport.** The same account, the same `source_txn_id` and the same fingerprint as an existing transaction give `exact_reimport`. The same source ID with different details gives `possible`.
- **Source IDs are scoped per account.** The same ID on another account is never a duplicate. Different, non-empty source IDs on the same account are treated as reliable evidence that the rows are distinct.
- **Within the file.** A row with the same posted date, amount and description as an earlier row is `possible`, with `matched_row_number`. This comparison ignores `source_txn_id`, so a row with an ID and an identical row without one are still flagged. Only two non-empty, different source IDs exempt the pair. A repeated source ID is also `possible`. Both rows are kept, and a human resolves them with `resolve_duplicate`.
- **Against the ledger.** A transaction is a candidate when it is on the same account with the same amount within ±3 days, and it has the same fingerprint, the same normalized description, or the same posted date. As within the file, only two non-empty, different source IDs exclude a candidate. Candidates are `possible`, with `matched_transaction_id`. Amount plus a nearby date alone is not enough.
- **Transfers.** Unlinked transactions on *other* accounts in the **same currency** (checked with `get_account`) with the opposite amount within ±5 days are transfer candidates. Contract 1.0 rejects cross-currency links (`E_CURRENCY_MISMATCH`), so a leg in another or unknown currency is neither selected nor counted toward ambiguity. Exactly one candidate sets `transfer_candidate_transaction_id`, and no category split is proposed. More than one leaves the field unset, puts the row in `needs_review` and lists it in `summary.transfer_ambiguous_rows`.
- **Categories (optional).** `category_rules` is an ordered list of `{"category_id", "contains": [...], "direction": "outflow" | "inflow" | "any"}`. The first case-insensitive substring match proposes one `category` split for the full amount. No rule means no proposal. A refund (positive amount) matched to an expense category is a positive split, which reduces spending.
- **Review state.**
  - `rejected`: `exact_reimport`.
  - `needs_review`: any error, a `possible` duplicate or an ambiguous transfer.
  - `pending`: everything else.
  - The importer never sets `approved`. Approval is a human `approve_rows` command.
  - The batch is always `staged`. Partial invalid files stay staged, and `summary` gives counts per state.

## Formula-like text

Descriptions beginning with `=`, `+`, `-`, `@`, tab or CR are stored in staging **exactly as in the file** (see `t002` in the contract and the fixture rows `=SUM(A1:A9)`, `+SYNTHETIC PLUS`, `@SYNTHETIC AT` and `-SYNTHETIC DASH`). The importer does no escaping. Escaping is an output transformation done only when writing Excel cells or CSV/TSV exports: 2c for workbooks and 1c's `escape_spreadsheet_text()` for exports, per [privacy-boundary.md](../privacy/privacy-boundary.md#spreadsheet-formula-injection).

## Privacy

- No logging. `summary` holds counts, row numbers, the batch ID and booleans only, so it fits the 1c log allow-list. Exception and error messages never include descriptions, amounts or raw lines.
- The staging document itself contains financial data. Callers must keep it in `<data root>\staging\`, never in the checkout ([privacy-boundary.md](../privacy/privacy-boundary.md#user-data-directory)). The data-root and sync-folder checks belong to the caller (3a). The importer receives bytes and does not open paths.
- `source_file_name` is stored as a base name. It remains sensitive local provenance.

## Adding a profile without changing code

A new export format is **data only**: one JSON `import_profile` document. Do not edit `src/perfin_import/*.py`.

1. Write the profile. It must validate against [`import_profile.schema.json`](../../contracts/schemas/import_profile.schema.json):
   - give it a unique `profile_id` and a `profile_version`, and bump the version when the mapping changes;
   - copy the header texts **exactly** into `columns`, or use 1-based column numbers as strings when `header_rows` is 0;
   - choose the `date_format`, separators and `sign_rule` that make the result canonical;
   - set `expected_field_count` if the width is fixed.
2. Validate it: `PYTHONPATH=contracts/python python3 -m perfin_contracts my_profile.json`. The importer adds a few checks: columns are unique, numeric columns are used when `header_rows` is 0, and `dedupe_key` names only mapped columns.
3. Put it in a profile directory and load that directory with `load_profiles_dir(path)`. For a real user this is `<data root>\config\` (local, never committed). For a synthetic example in this repository it is `fixtures/import/profiles/`.
4. Add a synthetic fixture and a test that stages it and checks its parsed values.

**Worked example.** [`fixtures/import/profiles/synthetic_eu_semicolon.json`](../../fixtures/import/profiles/synthetic_eu_semicolon.json) is a semicolon-delimited Windows-1252 savings export with:

- a preamble line, so `header_rows` is 2;
- a closing-balance footer, so `skip_footer_rows` is 1;
- `DD.MM.YYYY` dates;
- a decimal comma with `.` as the thousands separator.

It reads [`synthetic_eu_semicolon.cp1252.csv`](../../fixtures/import/synthetic_eu_semicolon.cp1252.csv). `tests/import/test_profiles.py::ExtensionTests` proves three things:

- it is found by `match_profiles`;
- it stages `1.234,56` as `123456` and `29.02.2024` as `2024-02-29`;
- the core code contains no reference to it.

```json
{
  "contract": "perfin", "contract_version": "1.0.0", "document_type": "import_profile",
  "profile_id": "synthetic_eu_semicolon", "profile_version": "1.0.0", "account_class": "savings",
  "file": {"encoding": "cp1252", "delimiter": ";", "quote_char": "\"", "header_rows": 2,
           "skip_footer_rows": 1, "expected_field_count": 3},
  "columns": {"posted_date": "Booking Date", "description": "Narrative", "amount": "Amount"},
  "date_format": "DD.MM.YYYY",
  "amount": {"sign_rule": "as_is", "decimal_separator": ",", "thousands_separator": ".",
             "parentheses_negative": false},
  "dedupe_key": ["posted_date", "amount_minor", "description", "row_occurrence"]
}
```

If no shipped profile matches a file, the user can map the header instead: `profile_from_mapping({"When": "posted_date", "What": "description", "How Much": "amount"}, profile_id=..., date_format=..., sign_rule=..., decimal_separator=...)`. Nothing is inferred. The result is validated exactly like a shipped profile, and it can be saved as a profile file for next time.

## Shipped synthetic profiles

All are marked `SYNTHETIC` and **not verified against any real institution's export**.

| Profile | Class | Encoding | Sign rule | Notes |
| --- | --- | --- | --- | --- |
| `synthetic_checking_signed` | checking | utf-8 | `as_is` | `MM/DD/YYYY`, parentheses negative, running balance, transaction ID |
| `synthetic_checking_debit_credit` | checking | cp1252 | `debit_credit_columns` | `M/D/YYYY`, transaction date, empty unused column |
| `synthetic_card_inverted` | credit_card | utf-8-sig | `invert` | Charges positive in the file, payments and refunds negative |

## Repository interface

The interface is [`repository.py`](../../src/perfin_import/repository.py), a `typing.Protocol` with read-only methods. 2b implements it over Access. The tests use an in-memory fake that records every call and fails if any write method is used.

## Limitations

- A file in the wrong 8-bit encoding (for example UTF-8 declared as `cp1252`) decodes without error into mojibake. Strict decoding cannot detect it. Pick the profile from the header and check the review preview.
- Only USD-style 0 or 2 decimal places are accepted. Currencies with other minor units need a contract change.
- The transfer and duplicate windows (±5 and ±3 days) are importer parameters, not contract fields.
- Windows-specific behaviour has not been run here: reading files from `%LOCALAPPDATA%`, cp1252 exports produced by Excel, and the Access round trip of the staging rows.
