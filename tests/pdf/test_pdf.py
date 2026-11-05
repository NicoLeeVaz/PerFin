"""PDF parser and review-boundary regressions, using generated synthetic bytes."""
import copy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "src", ROOT / "contracts/python", ROOT / "tests/store", ROOT / "fixtures/pdf"):
    sys.path.insert(0, str(path))
# Import fixture by explicit path: the store tests also use a module named synthetic.
import importlib.util
spec = importlib.util.spec_from_file_location("pdf_synthetic", ROOT / "fixtures/pdf/synthetic.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
from perfin_pdf import extract_pdf, stage_pdf, PdfRefused, LAYOUT_ID
from perfin_contracts.semantic import validate_document
from perfin_import import profile_from_mapping, stage_file
from fake_access import new_fake_store


class ReadRepo:
    def __init__(self):
        self.batches = []
    def get_account(self, account_id):
        return {"account_id": account_id, "account_class": "checking", "currency": "USD"}
    def prior_batches(self, account_id): return self.batches
    def find_candidates(self, *args): return []
    def find_by_source_txn_id(self, *args): return []
    def find_transfer_candidates(self, *args): return []


class ExtractionTests(unittest.TestCase):
    def test_multipage_headers_and_wrapped_description(self):
        data = fixture.pdf_bytes()
        result = extract_pdf(data)
        self.assertTrue(result.reconciled, result.errors)
        self.assertEqual(result.pages, 2)
        self.assertEqual([r["amount_minor"] for r in result.rows], [-5000, 2000, 20000])
        self.assertEqual(result.rows[0]["description"], "SYNTHETIC SHOP WRAPPED DESCRIPTION")
        self.assertEqual(result.rows[0]["source_lines"][1]["page"], 1)
        self.assertEqual(result.rows[2]["source_lines"][0]["page"], 2)
        self.assertEqual(result.source_sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(result.metadata["activity_minor"], 17000)

    def test_missing_row_and_wrong_totals_are_not_reconciled(self):
        lines = fixture.pages()
        lines[1].remove("2026-07-02 | SYNTHETIC REFUND | | 20.00")
        result = extract_pdf(fixture.pdf_bytes(lines))
        self.assertEqual({e["code"] for e in result.errors}, {"TRANSACTION_COUNT", "STATEMENT_TOTAL"})

    def test_repeated_boundary_row_is_not_silently_deduplicated(self):
        lines = fixture.pages()
        lines[1].insert(3, "2026-07-01 | SYNTHETIC SHOP | 50.00 |")
        result = extract_pdf(fixture.pdf_bytes(lines))
        self.assertEqual(len(result.rows), 4)
        self.assertFalse(result.reconciled)

    def test_both_debit_and_credit_are_ambiguous(self):
        lines = fixture.pages()
        lines[0][6] = "2026-07-01 | SYNTHETIC SHOP | 60.00 | 10.00"
        result = extract_pdf(fixture.pdf_bytes(lines))
        self.assertIn("AMBIGUOUS_AMOUNT", [e["code"] for e in result.errors])
        self.assertFalse(result.reconciled)

    def test_negative_debit_is_not_guessed(self):
        lines = fixture.pages()
        lines[0][6] = "2026-07-01 | SYNTHETIC SHOP | -50.00 |"
        self.assertFalse(extract_pdf(fixture.pdf_bytes(lines)).reconciled)

    def test_wrong_page_sequence(self):
        lines = fixture.pages()
        lines[1][-1] = "Page 3 of 3"
        self.assertIn("PAGE_SEQUENCE", [e["code"] for e in extract_pdf(fixture.pdf_bytes(lines)).errors])

    def test_orphan_continuation_is_error(self):
        lines = fixture.pages()
        lines[1].insert(2, "> ORPHAN")
        self.assertIn("AMBIGUOUS_CONTINUATION", [e["code"] for e in extract_pdf(fixture.pdf_bytes(lines)).errors])

    def test_unknown_line_cannot_be_ignored(self):
        lines = fixture.pages()
        lines[1].insert(2, "unexpected total or transaction")
        self.assertFalse(extract_pdf(fixture.pdf_bytes(lines)).reconciled)

    def test_duplicate_metadata_is_error(self):
        lines = fixture.pages()
        lines[0].insert(2, "Opening: 1000.00")
        self.assertFalse(extract_pdf(fixture.pdf_bytes(lines)).reconciled)

    def test_missing_header_or_invalid_date_is_not_reconciled(self):
        lines = fixture.pages()
        lines[0].remove(fixture.HEADER)
        self.assertFalse(extract_pdf(fixture.pdf_bytes(lines)).reconciled)
        lines = fixture.pages()
        lines[0][6] = "2026-02-30 | SYNTHETIC SHOP | 50.00 |"
        self.assertFalse(extract_pdf(fixture.pdf_bytes(lines)).reconciled)

    def test_scanned_blank_unreadable_encrypted_refused(self):
        from pypdf import PdfWriter
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.lib.utils import ImageReader
        from PIL import Image
        out = BytesIO()
        canvas = Canvas(out)
        canvas.drawImage(ImageReader(Image.new("RGB", (4, 4), "white")), 20, 20, 100, 100)
        canvas.save()
        for data, expected in [(out.getvalue(), "PDF_NO_TEXT"), (fixture.pdf_bytes([[]]), "PDF_NO_TEXT"),
                               (b"not a pdf", "PDF_UNREADABLE"), (b"%PDF-1.4 broken", "PDF_UNREADABLE")]:
            with self.subTest(expected=expected), self.assertRaises(PdfRefused) as cm:
                extract_pdf(data)
            self.assertEqual(cm.exception.code, expected)
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("synthetic-test-password")
        encrypted = BytesIO(); writer.write(encrypted)
        with self.assertRaises(PdfRefused) as cm: extract_pdf(encrypted.getvalue())
        self.assertEqual(cm.exception.code, "PDF_ENCRYPTED")

    def test_wrong_layout_and_limit_refused(self):
        with self.assertRaises(PdfRefused) as cm: extract_pdf(fixture.pdf_bytes(), layout_id="some_bank")
        self.assertEqual(cm.exception.code, "PDF_LAYOUT_UNSUPPORTED")
        with mock.patch("perfin_pdf.parser.MAX_BYTES", 3), self.assertRaises(PdfRefused):
            extract_pdf(fixture.pdf_bytes())
        lines = fixture.pages(); lines[1][0] = "A REAL BANK"
        with self.assertRaises(PdfRefused): extract_pdf(fixture.pdf_bytes(lines))

    def test_no_network_and_input_unchanged(self):
        data = fixture.pdf_bytes()
        digest = hashlib.sha256(data).hexdigest()
        with mock.patch("socket.socket", side_effect=AssertionError("network forbidden")):
            extract_pdf(data)
        self.assertEqual(hashlib.sha256(data).hexdigest(), digest)


class StagingTests(unittest.TestCase):
    def stage(self, lines=None, repo=None):
        return stage_pdf(fixture.pdf_bytes(lines), "synthetic.pdf", "chk:main", repo or ReadRepo(),
                         staged_at="2026-07-10T12:00:00Z")

    def test_contract_and_explicit_review(self):
        result = self.stage()
        self.assertEqual(validate_document(result.document), [])
        self.assertEqual([r["review_state"] for r in result.rows], ["needs_review"] * 3)
        self.assertTrue(all(not r["errors"] for r in result.rows))
        self.assertEqual(result.provenance["source_sha256"], result.document["batch"]["source_file_sha256"])
        self.assertEqual(result.provenance["rows"][0]["source_lines"][1]["page"], 1)

    def test_matches_canonical_csv_values(self):
        profile = profile_from_mapping({"Date": "posted_date", "Description": "description", "Amount": "amount"},
            profile_id="synthetic_csv", profile_version="1.0.0", account_class="checking", date_format="YYYY-MM-DD",
            sign_rule="as_is", decimal_separator=".")
        csv = ("Date,Description,Amount\r\n2026-07-01,SYNTHETIC SHOP WRAPPED DESCRIPTION,-50.00\r\n"
               "2026-07-02,SYNTHETIC REFUND,20.00\r\n2026-07-03,SYNTHETIC DEPOSIT,200.00\r\n").encode()
        canonical = stage_file(csv, "canonical.csv", profile, "chk:main", ReadRepo())
        self.assertEqual([r["parsed"] for r in self.stage().rows], [r["parsed"] for r in canonical.rows])

    def test_exact_pdf_replay_and_distinct_pdf_hashes(self):
        repo = ReadRepo()
        result = self.stage(repo=repo)
        repo.batches = [dict(result.document["batch"], batch_status="committed")]
        again = self.stage(repo=repo)
        self.assertTrue(all(r["duplicate"]["status"] == "exact_reimport" for r in again.rows))
        self.assertTrue(all(r["review_state"] == "rejected" for r in again.rows))
        self.assertEqual(again.document["batch"]["source_file_sha256"], hashlib.sha256(fixture.pdf_bytes()).hexdigest())

    def test_unreconciled_errors_block_real_repository_approval(self):
        # Fake adapter exercises production repository command/approval logic, not ACE runtime.
        repo, ad, _ = new_fake_store()
        bundle = {"contract": "perfin", "contract_version": "1.0.1", "document_type": "ledger_bundle",
                  "base_currency": "USD", "accounts": [{"account_id": "chk:main", "account_class": "checking",
                  "kind": "asset", "display_name": "SYNTHETIC", "currency": "USD", "opening_balance_minor": 100000,
                  "opening_balance_date": "2026-06-30", "row_version": 1}], "categories": [], "transactions": []}
        self.assertEqual(repo.import_bundle(bundle)["result_status"], "accepted")
        lines = fixture.pages(); lines[0][3] = "Closing: 999.00"
        result = self.stage(lines)
        self.assertTrue(all(any(e["code"] == "E_RECON_MISMATCH" for e in r["errors"]) for r in result.rows))
        staged = repo.stage_batch(result.document)
        self.assertEqual(staged["result_status"], "accepted")
        bid = result.document["batch"]["batch_id"]
        b = repo._one("import_batch", {"batch_id": bid})
        command = {"contract": "perfin", "contract_version": "1.0.1", "document_type": "command",
                   "command_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "command_type": "approve_rows",
                   "issued_at": "2026-07-10T12:00:00Z", "issued_by": "cli:pdf-test",
                   "payload": {"batch_id": bid, "row_numbers": [1]},
                   "expected_versions": [{"entity": "batch", "entity_id": bid, "row_version": b["row_version"]}]}
        response = repo.execute(command)
        self.assertEqual(response["result_status"], "rejected")
        self.assertIn("E_ROW_UNRESOLVED", [e["code"] for e in response["errors"]])
        self.assertEqual(ad.db.rows["ledger_txn"], [])

    def test_manifest_validates(self):
        doc = json.loads((ROOT / "src/perfin_pdf/module_manifest.json").read_text())
        self.assertEqual(validate_document(doc), [])

    def test_formula_like_text_stays_text_and_foreign_currency_refused(self):
        lines = fixture.pages()
        lines[1][3] = "2026-07-02 | =SUM(A1:A9) | | 20.00"
        result = self.stage(lines)
        self.assertEqual(result.rows[1]["parsed"]["description"], "=SUM(A1:A9)")
        repo = ReadRepo()
        repo.get_account = lambda aid: {"account_id": aid, "account_class": "checking", "currency": "EUR"}
        from perfin_import.errors import ImportRefused
        with self.assertRaises(ImportRefused) as cm: self.stage(repo=repo)
        self.assertEqual(cm.exception.code, "E_CURRENCY_MISMATCH")

    def test_reviewed_fixture_commits_to_expected_balance(self):
        # This validates the supported command flow, not the actual Access engine.
        repo, ad, _ = new_fake_store()
        bundle = {"contract": "perfin", "contract_version": "1.0.1", "document_type": "ledger_bundle",
                  "base_currency": "USD", "accounts": [{"account_id": "chk:main", "account_class": "checking",
                  "kind": "asset", "display_name": "SYNTHETIC", "currency": "USD", "opening_balance_minor": 100000,
                  "opening_balance_date": "2026-06-30", "row_version": 1}], "categories": [
                      {"category_id": "out", "name": "SYNTHETIC spending", "category_kind": "expense"},
                      {"category_id": "in", "name": "SYNTHETIC income", "category_kind": "income"}], "transactions": []}
        self.assertEqual(repo.import_bundle(bundle)["result_status"], "accepted")
        self.assertEqual(repo.set_default_categories("out", "in")["result_status"], "accepted")
        result = self.stage()
        self.assertEqual(repo.stage_batch(result.document)["result_status"], "accepted")
        bid = result.document["batch"]["batch_id"]
        for cmd_type, payload, cid in [
            ("approve_rows", {"batch_id": bid, "row_numbers": [1, 2, 3]}, "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            ("commit_batch", {"batch_id": bid, "source_file_sha256": result.document["batch"]["source_file_sha256"]},
             "cccccccc-cccc-4ccc-8ccc-cccccccccccc")]:
            b = repo._one("import_batch", {"batch_id": bid})
            command = {"contract": "perfin", "contract_version": "1.0.1", "document_type": "command",
                       "command_id": cid, "command_type": cmd_type, "issued_at": "2026-07-10T12:00:00Z",
                       "issued_by": "cli:pdf-test", "payload": payload,
                       "expected_versions": [{"entity": "batch", "entity_id": bid, "row_version": b["row_version"]}]}
            response = repo.execute(command)
            self.assertEqual(response["result_status"], "accepted", response["errors"])
        self.assertEqual(repo.summary()["account_balances_minor"]["chk:main"], 117000)
        self.assertEqual(len(ad.db.rows["ledger_txn"]), 3)

    def test_cli_exit_codes_and_source_unchanged(self):
        from perfin_pdf.__main__ import main
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "synthetic.pdf"
            data = fixture.pdf_bytes(); path.write_bytes(data)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout): rc = main(["extract", str(path)])
            self.assertEqual(rc, 0)
            self.assertTrue(json.loads(stdout.getvalue())["human_review_required"])
            self.assertEqual(path.read_bytes(), data)
            with contextlib.redirect_stderr(io.StringIO()): rc = main(["extract", str(path), "--layout", "bad"])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
