"""Convert extracted PDF rows to the existing CSV staging/review contract."""
from dataclasses import dataclass
import csv
import hashlib
import io

from perfin_import import stage_file, summarize_batch
from perfin_import.profiles import default_validator, profile_from_mapping
from perfin_import.errors import ImportRefused
from .parser import LAYOUT_ID, extract_pdf


@dataclass
class PdfStageResult:
    document: dict
    summary: dict
    provenance: dict
    extraction: object

    @property
    def rows(self):
        return self.document["rows"]


class _PdfRepository:
    """Match replays by original PDF bytes, never a synthetic CSV hash."""
    def __init__(self, repo, pdf_sha, csv_sha):
        self.repo, self.pdf_sha, self.csv_sha = repo, pdf_sha, csv_sha

    def prior_batches(self, account_id):
        return [dict(b, source_file_sha256=self.csv_sha) for b in self.repo.prior_batches(account_id)
                if b["source_file_sha256"] == self.pdf_sha]

    def __getattr__(self, name):
        return getattr(self.repo, name)


def stage_pdf(data, source_file_name, account_id, repository, *, layout_id=LAYOUT_ID,
              staged_at=None, batch_id=None, category_rules=None):
    """Read-only stage. Persist document + provenance under the guarded local data root.

    Every unreconciled extraction gives every row a contract error, preventing a
    caller from approving a convenient subset while ignoring missing PDF rows.
    Correct the source/layout and restage; never delete these errors to approve.
    """
    extraction = extract_pdf(data, layout_id=layout_id)
    account = repository.get_account(account_id)
    if account is None:
        raise ImportRefused("E_ACCOUNT_UNKNOWN", "account is not known to the repository")
    if account.get("currency") != "USD":
        raise ImportRefused("E_CURRENCY_MISMATCH", "this PDF layout supports USD accounts only")
    profile = profile_from_mapping(
        {"Date": "posted_date", "Description": "description", "Debit": "debit", "Credit": "credit"},
        profile_id="pdf.synthetic.statement.v1", profile_version="1.0.0", account_class=account["account_class"],
        date_format="YYYY-MM-DD", sign_rule="debit_credit_columns", decimal_separator=".",
        currency="USD", expected_field_count=4)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(["Date", "Description", "Debit", "Credit"])
    for row in extraction.rows:
        writer.writerow([row["posted_date"], row["description"], row["debit"], row["credit"]])
    csv_bytes = stream.getvalue().encode("utf-8")
    csv_sha = hashlib.sha256(csv_bytes).hexdigest()
    adapter = _PdfRepository(repository, extraction.source_sha256, csv_sha)
    result = stage_file(csv_bytes, source_file_name, profile, account_id, adapter,
                        staged_at=staged_at, batch_id=batch_id or "pdf-" + hashlib.sha256(
                            (account_id + ":" + extraction.source_sha256).encode()).hexdigest()[:24],
                        category_rules=category_rules)
    result.document["batch"]["source_file_sha256"] = extraction.source_sha256
    result.document["batch"]["importer_version"] = "0.1.0"
    for row in result.rows:
        if extraction.errors:
            row["errors"].append({"code": "E_RECON_MISMATCH", "path": "$",
                                  "message": "PDF extraction does not reconcile; review original and restage"})
        # Exact replay remains rejected; no rows are ever approved automatically.
        if row["duplicate"]["status"] != "exact_reimport":
            row["review_state"] = "needs_review"
    errors = default_validator()(result.document)
    if errors:
        raise RuntimeError("PDF adapter generated invalid staging document")
    summary = summarize_batch(result.document)
    summary.update(pdf_pages=extraction.pages, pdf_reconciled=extraction.reconciled,
                   human_review_required=True, pdf_layout_id=layout_id)
    provenance = {"format": "perfin.pdf.provenance/1", "batch_id": result.document["batch"]["batch_id"],
                  "source_sha256": extraction.source_sha256, "layout_id": layout_id,
                  "confidence": "declared_layout_reconciled" if extraction.reconciled else "unreconciled",
                  "reconciliation_errors": extraction.errors,
                  "rows": [{"row_number": r["row_number"], "source_lines": r["source_lines"]}
                           for r in extraction.rows]}
    return PdfStageResult(result.document, summary, provenance, extraction)
