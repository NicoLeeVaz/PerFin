# Local PDF statement staging

The optional `perfin_pdf` module converts **one explicitly declared synthetic digital-text layout** into the same staged rows used by CSV imports. It has no ledger write, bank connection, OCR or cloud fallback. **No real institution's PDF format is supported or verified yet.** Use bank CSV exports for normal initial use.

## Run

Install the project's optional PDF dependency (`pypdf==6.10.0`). From a source checkout, put `src` and `contracts/python` on `PYTHONPATH`, or use the installed package.

```console
python -m perfin_pdf extract private-statement.pdf --layout perfin.synthetic.statement.v1
```

This command prints **private financial text** as JSON to the terminal; do not redirect it into the public checkout or a synced folder. It writes no files. Exit codes: `0` means the declared layout, count and totals reconcile; `1` means an extraction was produced with blocking reconciliation errors; `2` means unsupported/unreadable input. Reconciliation is not an accuracy guarantee. Review every row against the original before approval.

The core application's PDF import route calls:

```python
from perfin_pdf import stage_pdf
result = stage_pdf(pdf_bytes, source_file_name, account_id, import_repository)
# result.document: existing staging_batch contract
# result.provenance: private page/line sidecar
# result.summary: counts and non-value status
# result.extraction: private extracted text, amounts and reconciliation evidence
```

`import_repository` is the CSV importer's **read-only** protocol, not a second database. The caller persists the document using the Access repository's normal `stage_batch`, then uses explicit human review and approval/commit commands. Save the provenance sidecar beside the staging document under the privacy-checked local data root. Do not put raw extracted text in diagnostic logs.

## Declared layout

Every page must contain these exact title and column-header lines. Headers may repeat; they are never transactions. Every page needs `Page n of N` matching its physical order. The first page contains exactly one copy of each metadata field. The signed opening/closing balances use the canonical cash/net-liability convention, so a card balance owed is negative. Debit and credit columns themselves are unsigned, with one unused side empty or zero. Amounts have zero or two decimal places, a period decimal separator, and no thousands/currency symbols.

```text
PERFIN SYNTHETIC STATEMENT v1
Currency: USD
Opening: 1000.00
Closing: 950.00
Transactions: 1
Date | Description | Debit | Credit
2026-07-01 | SYNTHETIC SHOP | 50.00 |
> OPTIONAL WRAPPED DESCRIPTION
Page 1 of 1
```

Dates are explicit `YYYY-MM-DD`. A continuation must immediately follow a transaction on the same page and begin `> `. Other nonempty text, missing headers/metadata, two nonzero debit/credit values, signs in debit/credit columns, invalid dates, page gaps, transaction-count mismatch and opening + activity != closing are unresolved extraction errors. Descriptions containing `|` require a different verified layout; this parser refuses ambiguous column counts rather than guessing.

Repeated transaction rows are **retained**, including page-boundary repeats. Normal duplicate detection makes them reviewable. The declared count and statement total must still reconcile; dropping a repeat automatically could erase a real identical purchase.

## Review and replay guarantees

- Every new row starts in `needs_review`; no PDF row is automatically approved. Exact replays remain rejected.
- Any extraction reconciliation defect adds `E_RECON_MISMATCH` to **every** staged row. The production repository refuses approval of those rows, including approval of only a convenient subset. Fix the input/layout and restage rather than deleting errors.
- PDF source hashes and replay matching use the **original PDF bytes**, not the generated intermediate CSV. No original file is changed.
- The contract stores the original base filename/hash and row fingerprints. The separate `perfin.pdf.provenance/1` sidecar records layout ID, PDF hash, batch ID, page/line coordinates, original extracted lines and reconciliation error codes. It contains sensitive local data.
- Confidence labels describe only declared-layout/reconciliation status. They are not statistical probabilities or promises that OCR/extraction is correct.
- Formula-like descriptions are kept as data. Existing Excel/report export escaping remains mandatory.

## Unsupported and bounded

Encrypted files are refused without asking for a password. Blank or image-only pages are refused, including a scan mixed with text pages. No OCR is silently applied. Unknown layouts, unreadable PDFs and empty transaction documents are refused. Only USD checking, savings and credit-card accounts are supported by this initial layout.

The default bounds are 16 MiB input, 100 pages, 4 MiB decoded page content and 2 MiB extracted text. These are best-effort resource limits, **not a security sandbox**: decompression itself can consume resources before its size is known. Process only trusted local statement files. The library never executes embedded PDF actions or fetches external resources.

Adding an institution requires a separate explicit layout parser, synthetic representative fixtures, count/sign/reconciliation evidence and review of a matching sanitized sample. Do not merely rename the synthetic profile or add fuzzy recognition. Register the existing module via `src/perfin_pdf/module_manifest.json`; Excel core needs no change.

## Verification

```console
python3 -B -W error -m unittest discover -s tests/pdf -q
```

Tests generate PDFs in memory from `fixtures/pdf/synthetic.py` using ReportLab. They exercise actual pypdf extraction, multi-page headers, wrapped lines, repeated rows, date/amount ambiguity, count/totals mismatch, scan/blank/encrypted/unreadable refusal, exact source replay, network-blocked execution, unchanged source bytes, canonical CSV equivalence and approval refusal in the production repository using its test-only fake adapter. Generated PDFs are synthetic and not stored in Git. The representative fixture was rendered with Poppler and visually inspected.

Linux parser and repository-logic tests do not prove Windows/ACE, Excel refresh or installed application behavior. Those remain part of the integration/release acceptance run.

## Dependency and license record

- Runtime: **pypdf 6.10.0**, installed distribution metadata declares **BSD-3-Clause**. Its exact installed license is retained in [PYPDF-LICENSE.txt](PYPDF-LICENSE.txt), SHA-256 `a97ac230e5f33ef10a5367a850eb01f91f1a0b064e34742c7794d2294557f524`. This module calls the library API; it copies no parser source. Preserve the license in any bundled dependency redistribution. Upstream: <https://github.com/py-pdf/pypdf>. Text extraction limitations: <https://pypdf.readthedocs.io/en/stable/user/extract-text.html>.
- Test fixture generation: **ReportLab 4.4.9**, installed metadata declares BSD license; not required for ordinary extraction. Pillow is used only to synthesize the image-only test page. Keep dependency license notices when building an offline wheelhouse.
- The pinned version is the tested installed version, not a claim to be latest. Upgrade dependencies through regression and license review.
