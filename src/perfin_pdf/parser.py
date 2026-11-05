"""Strict parser for one declared synthetic layout; never guesses bank layouts."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import re

from perfin_import.values import parse_amount, parse_date
from perfin_import.errors import ValueParseError

LAYOUT_ID = "perfin.synthetic.statement.v1"
TITLE = "PERFIN SYNTHETIC STATEMENT v1"
HEADER = "Date | Description | Debit | Credit"
MAX_BYTES = 16 * 1024 * 1024
MAX_PAGES = 100
MAX_STREAM_BYTES = 4 * 1024 * 1024
MAX_TEXT_CHARS = 2 * 1024 * 1024


class PdfRefused(ValueError):
    """Safe diagnostic without source data. Codes belong to the PDF adapter."""
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass
class Extraction:
    source_sha256: str
    layout_id: str
    rows: list
    metadata: dict
    errors: list
    pages: int

    @property
    def reconciled(self):
        return not self.errors

    def as_dict(self):
        return {"source_sha256": self.source_sha256, "layout_id": self.layout_id,
                "rows": self.rows, "metadata": self.metadata, "errors": self.errors,
                "pages": self.pages, "reconciled": self.reconciled,
                "confidence": "declared_layout_reconciled" if self.reconciled else "unreconciled",
                "human_review_required": True}


def extract_pdf(data: bytes, *, layout_id=LAYOUT_ID) -> Extraction:
    """Extract bytes without writing or changing the original PDF.

    Reconciliation is evidence of consistency, not a guarantee of extraction
    accuracy. Limits are best-effort resource bounds, not a sandbox for hostile
    PDFs. There is no OCR, password retry, attachment or network fallback.
    """
    if layout_id != LAYOUT_ID:
        raise PdfRefused("PDF_LAYOUT_UNSUPPORTED", "choose an installed, verified layout")
    if not isinstance(data, bytes) or not data or not data.startswith(b"%PDF-"):
        raise PdfRefused("PDF_UNREADABLE", "input is not readable PDF bytes")
    if len(data) > MAX_BYTES:
        raise PdfRefused("PDF_LIMIT", "PDF exceeds the local input size limit")
    try:
        from pypdf import PdfReader
    except ImportError:
        raise PdfRefused("PDF_DEPENDENCY", "install the optional local PDF dependency") from None
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise PdfRefused("PDF_ENCRYPTED", "encrypted PDFs are unsupported; no password is requested")
        n = len(reader.pages)
        if not 1 <= n <= MAX_PAGES:
            raise PdfRefused("PDF_LIMIT", "unsupported page count")
        pages = []
        total = 0
        for page in reader.pages:
            content = page.get_contents()
            if content is not None and len(content.get_data()) > MAX_STREAM_BYTES:
                raise PdfRefused("PDF_LIMIT", "PDF page content exceeds the local size limit")
            text = page.extract_text() or ""
            if not text.strip():
                raise PdfRefused("PDF_NO_TEXT", "blank or image-only page; OCR is not installed")
            total += len(text)
            if total > MAX_TEXT_CHARS:
                raise PdfRefused("PDF_LIMIT", "extracted text exceeds the local size limit")
            pages.append(text)
    except PdfRefused:
        raise
    except Exception:
        # Parser exceptions may contain PDF fragments or paths; don't echo them.
        raise PdfRefused("PDF_UNREADABLE", "PDF parser could not read this document") from None
    return _parse_pages(pages, hashlib.sha256(data).hexdigest())


def _parse_pages(pages, source_hash):
    rows, errors, metadata = [], [], {}
    titles, headers, numbers = set(), set(), {}

    def problem(code, page=None, line=None):
        item = {"code": code}
        if page is not None:
            item["page"] = page
        if line is not None:
            item["line"] = line
        errors.append(item)

    for page_no, page_text in enumerate(pages, 1):
        current = None  # continuation never crosses a page boundary
        for line_no, raw in enumerate(page_text.splitlines(), 1):
            text = raw.strip()
            if not text:
                continue
            if text == TITLE:
                titles.add(page_no)
                current = None
                continue
            if text == HEADER:
                headers.add(page_no)
                current = None
                continue
            match = re.fullmatch(r"Page ([0-9]{1,9}) of ([0-9]{1,9})", text)
            if match:
                if page_no in numbers:
                    problem("DUPLICATE_PAGE_NUMBER", page_no, line_no)
                numbers[page_no] = tuple(map(int, match.groups()))
                current = None
                continue
            match = re.fullmatch(r"(Currency|Opening|Closing|Transactions): (.+)", text)
            if match:
                key, value = match.groups()
                if key in metadata or page_no != 1:
                    problem("DUPLICATE_OR_MISPLACED_METADATA", page_no, line_no)
                else:
                    metadata[key] = value
                current = None
                continue
            if text.startswith("> "):
                if current is None or "|" in text:
                    problem("AMBIGUOUS_CONTINUATION", page_no, line_no)
                else:
                    current["description"] += " " + text[2:]
                    current["source_lines"].append({"page": page_no, "line": line_no, "text": raw})
                continue
            if "|" in text:
                cells = [s.strip() for s in text.split("|")]
                if len(cells) != 4:
                    problem("FIELD_COUNT", page_no, line_no)
                    current = None
                    continue
                current = {"posted_date": cells[0], "description": cells[1], "debit": cells[2],
                           "credit": cells[3], "source_lines": [{"page": page_no, "line": line_no, "text": raw}]}
                rows.append(current)
                continue
            problem("UNKNOWN_LINE", page_no, line_no)
            current = None

    if titles != set(range(1, len(pages) + 1)):
        raise PdfRefused("PDF_LAYOUT_UNSUPPORTED", "every page must match the explicitly selected layout")
    if headers != set(range(1, len(pages) + 1)):
        problem("MISSING_COLUMN_HEADER")
    if not rows:
        raise PdfRefused("PDF_NO_TRANSACTIONS", "no transaction rows found; no batch can be staged")
    if numbers != {i: (i, len(pages)) for i in range(1, len(pages) + 1)}:
        problem("PAGE_SEQUENCE")
    if set(metadata) != {"Currency", "Opening", "Closing", "Transactions"}:
        problem("MISSING_METADATA")
    if metadata.get("Currency") != "USD":
        problem("UNSUPPORTED_CURRENCY")
    count = metadata.get("Transactions", "")
    if not re.fullmatch(r"[0-9]{1,9}", count) or int(count) != len(rows):
        problem("TRANSACTION_COUNT")
    amounts = []
    for i, row in enumerate(rows, 1):
        try:
            parse_date(row["posted_date"], "YYYY-MM-DD")
        except ValueParseError:
            problem("INVALID_DATE", row["source_lines"][0]["page"], row["source_lines"][0]["line"])
        if not row["description"] or len(row["description"]) > 1000:
            problem("INVALID_DESCRIPTION", row["source_lines"][0]["page"], row["source_lines"][0]["line"])
        try:
            debit = parse_amount(row["debit"], ".", "", allow_sign=False)
            credit = parse_amount(row["credit"], ".", "", allow_sign=False)
            if (debit is None and credit is None) or (debit and credit):
                raise ValueError
            amount = (credit or 0) - (debit or 0)
            row["amount_minor"] = amount
            amounts.append(amount)
        except (ValueError, ValueParseError):
            problem("AMBIGUOUS_AMOUNT", row["source_lines"][0]["page"], row["source_lines"][0]["line"])
        row["row_number"] = i
    try:
        opening = parse_amount(metadata.get("Opening", ""), ".", "")
        closing = parse_amount(metadata.get("Closing", ""), ".", "")
        if opening is None or closing is None:
            raise ValueError
        metadata["opening_minor"], metadata["closing_minor"] = opening, closing
        metadata["activity_minor"] = sum(amounts)
        if len(amounts) != len(rows) or opening + sum(amounts) != closing:
            problem("STATEMENT_TOTAL")
    except (ValueError, ValueParseError):
        problem("INVALID_BALANCES")
    return Extraction(source_hash, LAYOUT_ID, rows, metadata, errors, len(pages))
