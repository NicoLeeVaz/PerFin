# NoPii export adapter contract

Task 1c ([#4](https://github.com/NicoLeeVaz/PerFin/issues/4)). Contract version **perfin-nopii-export/0.1.0** (draft until the Wave 1 gate freezes it). See also the [privacy boundary](privacy-boundary.md) and the [test checklist](test-checklist.md).

Machine-readable parts: [`config/privacy/nopii-export-envelope.schema.json`](../../config/privacy/nopii-export-envelope.schema.json), synthetic examples in [`config/privacy/examples/`](../../config/privacy/examples/) and the gate/fidelity reference logic in [`config/privacy/perfin_privacy_checks.py`](../../config/privacy/perfin_privacy_checks.py).

## Scope and assumptions

NoPii is a private project of the repository owner. **This document does not describe NoPii's internals, and no NoPii source is copied here.** It defines only the narrow interface PerFin needs. A small adapter, maintained alongside NoPii or locally by the user, translates between this contract and NoPii.

Assumptions, to be confirmed by the NoPii owner before integration:

| ID | Assumption | If false |
| --- | --- | --- |
| A1 | NoPii (or the adapter) can run as a local process with no network access. | The adapter must report `offline: false`; PerFin then disables export. |
| A2 | It can scrub free text and named string fields in structured records. | Only the supported `payload_kind` is offered. |
| A3 | It can leave specified fields untouched (amounts, dates, currency). | Exact-fidelity exports cannot be offered. |
| A4 | It can report counts of replacements by category without echoing original values. | `findings` is empty and the preview shows less detail; export still requires confirmation. |
| A5 | Its replacements are consistent placeholders (for example `[MERCHANT_1]`). | Allowed but not required. |

**No assumption is a guarantee.** PerFin claims nothing about NoPii's effectiveness. Until the integration tests in the checklist pass against a real adapter, the export feature stays behind a disabled flag and is described as experimental.

## Where NoPii is and is not needed

| Workflow | NoPii needed? |
| --- | --- |
| Local CSV/OFX import, review, commit, reconcile, Excel refresh, backups | **No.** Core local use never calls NoPii, never loads the adapter, and works when NoPii is absent. |
| Local PDF extraction (4c) | No. Extraction is local; its output goes to the normal staging review. |
| Export of data for use with an external AI service | **Yes.** Export is unavailable without a supported adapter. |

## Export flow

1. **Explicit action.** The user chooses "Prepare scrubbed export" for a specific selection (date range, accounts, fields). There is no automatic, scheduled or background export. The feature flag `outbound.O1.enabled` must also be on; it is off by default.
2. **Minimise.** PerFin builds the request from an allow-list of fields (below). Account identifiers are replaced by the account alias before the adapter sees anything. Original PDFs and raw import rows are never included.
3. **Adapter discovery.** PerFin reads the adapter path from `settings.json` and runs the adapter's `describe` operation (a local subprocess, JSON over standard input/output). PerFin checks the `contract_version` major number, the `payload_kind` and `offline: true`.
4. **Scrub.** PerFin sends the request envelope. The adapter returns a response envelope.
5. **PerFin's own checks** (independent of the adapter):
   - envelope validation and matching `export_id`;
   - record count and record ids unchanged;
   - **monetary fidelity:** every `amount_minor` and `currency` identical to the request; for text payloads, the multiset of monetary amounts found in the text is unchanged. Money tokens are two-decimal amounts (with or without a currency symbol) and whole amounts with a `$`, `€` or `£` symbol, compared by value (`$100` = `$100.00`). Bare integers without a symbol are not treated as money, because they may be identifiers that must be scrubbed;
   - **unscrubbed fields:** every record field not listed in `scrub_fields` or `preserve_fields` comes back unchanged, and deleting it counts as a change. A scrubbed field must still be present;
   - **date fidelity:** every `date` identical and valid `YYYY-MM-DD`; for text payloads, the multiset of ISO dates is unchanged;
   - payload shape: the response carries only the payload field the request selected (`records` for `ledger_rows`, `text` for text); any other payload field cancels the export;
   - residual scan, over every payload field present in the response: no Luhn-valid card number, no run of 6 or more digits, no email address and no field from the request's `sensitive_values` list (strings PerFin knows, such as the user's name and account numbers from settings) appears in the output;
   - spreadsheet formula escaping applied to every text field of the outbox file.
6. **Preview.** The user sees the scrubbed output, the record count, replacement counts by category, the fidelity results and a warning that scrubbed text can still be sensitive. Any failed check blocks the export and the preview says which check failed.
7. **Confirm.** Only after confirmation does PerFin write the file to `<data root>\exports\outbox\` (JSON or CSV), together with an audit entry without content (export id, time, record count, adapter name/version, SHA-256 of the file).
8. **Transfer is manual.** PerFin contains no AI client and does not upload anything. The user decides whether to move the file to an external service.

## Unsupported or missing adapter: export disabled, never raw fallback

| Condition | Behaviour |
| --- | --- |
| No adapter configured, path missing, process fails to start | Export disabled; message "NoPii adapter not available — export disabled." |
| `describe` fails, times out (default 10 s) or returns invalid JSON | Export disabled. |
| Contract major version differs, payload kind unsupported, `offline` not `true` | Export disabled. |
| The export response's own `adapter.offline` is not `true` (even if `describe` said it was) | This export is cancelled; nothing is written. |
| Response `status` is `refused`, `unsupported` or `error`, or the envelope is invalid | This export is cancelled; nothing is written. |
| Any fidelity or residual check fails | This export is cancelled; nothing is written. |
| Feature flag off | Export menu item hidden or disabled. |

In none of these cases does PerFin write, show for copying, or offer the unscrubbed data as an alternative. There is no "export anyway" option. Reference implementation: `decide_export()`.

## Allow-listed fields

Ledger-row payload (`payload_kind: "ledger_rows"`):

| Field | Type | Sent to adapter as | Scrubbed? |
| --- | --- | --- | --- |
| `record_id` | opaque string generated for the export (not the ledger id) | as is | No, must be returned unchanged |
| `date` | `YYYY-MM-DD` (posted date) | as is | No, fidelity-checked |
| `amount_minor` | signed integer minor units | as is | No, fidelity-checked |
| `currency` | ISO 4217 code | as is | No, fidelity-checked |
| `account_alias` | user alias, for example `Card A` | as is | No (alias only, never the number) |
| `category` | string | as is | Optional |
| `description` | original description text | as is | **Yes** |
| `memo` | string | as is | **Yes** |

Never sent: account or card numbers, ledger primary keys, import file names/paths, raw import rows, balances not requested, statement PDFs, the audit trail.

Text payload (`payload_kind: "text"`): a single `text` field, for example a user-written question plus a pasted extract. The same money/date multiset checks apply.

## Envelope (summary)

Request (`kind: "perfin.nopii.export_request"`): `contract_version`, `export_id`, `created` (`YYYY-MM-DD`), `purpose` (`external_ai`), `payload_kind`, `preserve_fields` (must include `date`, `amount_minor`, `currency`), `scrub_fields`, `sensitive_values` (optional), `records` or `text`.

Response (`kind: "perfin.nopii.export_response"`): `contract_version`, `export_id`, `status` (`ok`, `refused`, `unsupported`, `error`), `adapter` (`name`, `version`, `offline`), `findings` (list of `{category, count}`, no original values), `records` or `text` when `status` is `ok`, `message` otherwise.

`describe` response (`kind: "perfin.nopii.adapter_description"`): `contract_version`, `adapter` (`name`, `version`, `offline`), `payload_kinds`.

The JSON Schema is authoritative for structure; PerFin's fidelity rules above are authoritative for content.

## Limits of scrubbing

- **Text scrubbing does not sanitize the original PDF.** The PDF in `statements\originals` keeps every account number, name and address, including content in images, metadata, annotations and hidden layers. PerFin never exports original PDFs.
- **Sanitized text may remain sensitive.** Merchant names, locations, exact amounts and dates, rare transactions and spending patterns can identify a person or reveal health, religion, politics or location. The preview says so.
- **Placeholders can leak structure** (for example how many different people appear).
- **The outbox file is still sensitive data** and has the retention rules of the [privacy boundary](privacy-boundary.md#retention).
- Exact preservation of amounts and dates is required for useful analysis but increases re-identification risk. Bucketing or shifting dates and amounts is not part of version 0.1; adding it requires a contract change and new fidelity rules.

## Items to reconcile at the Wave 1 gate

- Field names `amount_minor`, `currency`, `date` and the id style must match the 1a contract.
- NoPii owner confirms or rejects assumptions A1–A5 and the subprocess JSON-over-stdio transport.
- 4c decides whether a PDF-text payload is offered; if so it uses `payload_kind: "text"` with the same checks.
