"""CSV structure and encodings: the reproduced VBA defects must not recur.

See research/reuse/catalog.md "Reproduced CSV/VBA concerns": dropped trailing
empty fields, lost escaped quotes, backslash escapes, locale conversion, and
aborting on quoted newlines.
"""
import json
import unittest

from import_support import FakeRepository, csv_bytes, fixture_bytes, profile, stage
from perfin_import import UnknownFormat, profile_from_mapping

HEADER = "Date,Description,Amount,Balance,Transaction ID\n"


class QuotingTests(unittest.TestCase):
    def test_escaped_quotes_and_quoted_newline_kept_exactly(self):
        res = stage(self, fixture_bytes("synthetic_checking_signed.csv"), "synthetic_checking_signed.csv",
                    profile("synthetic_checking_signed"), "chk:main")
        r1, r2 = res.rows[0], res.rows[1]
        self.assertEqual(r1["raw_fields"][1], 'SYNTHETIC GROCER, "MAIN ST"')
        self.assertEqual(r1["parsed"]["description"], 'SYNTHETIC GROCER, "MAIN ST"')
        self.assertEqual(r2["raw_fields"][1], "SYNTHETIC\r\nMULTILINE MEMO")
        self.assertEqual(r2["parsed"]["description"], "SYNTHETIC\r\nMULTILINE MEMO")
        self.assertEqual(len(res.rows), 8, "a quoted newline does not split or abort the record")

    def test_backslash_is_not_an_escape(self):
        data = csv_bytes(HEADER + '07/01/2026,"C:\\temp \\"x",-1.00,1.00,B-1\n')
        # RFC 4180: \" is not an escape, so the quoted field ends after the backslash
        # and the stray text makes the record malformed; nothing is silently rewritten.
        res = stage(self, data, "b.csv", profile("synthetic_checking_signed"), "chk:main")
        self.assertFalse(res.summary["file_complete"])
        data = csv_bytes(HEADER + '07/01/2026,C:\\temp\\new,-1.00,1.00,B-2\n')
        res = stage(self, data, "b.csv", profile("synthetic_checking_signed"), "chk:main")
        self.assertEqual(res.rows[0]["parsed"]["description"], "C:\\temp\\new")

    def test_quoted_whitespace_preserved(self):
        data = csv_bytes(HEADER + '07/01/2026,"  SYNTHETIC PADDED  ",-1.00,1.00,W-1\n')
        res = stage(self, data, "w.csv", profile("synthetic_checking_signed"), "chk:main")
        self.assertEqual(res.rows[0]["parsed"]["description"], "  SYNTHETIC PADDED  ")

    def test_trailing_empty_column_preserved(self):
        res = stage(self, fixture_bytes("synthetic_checking_debit_credit.cp1252.csv"), "dc.csv",
                    profile("synthetic_checking_debit_credit"), "chk:main")
        row = res.rows[0]
        self.assertEqual(row["raw_fields"], ["7/1/2026", "6/30/2026", "SYNTHETIC CAF\u00c9", "4.50", ""])
        self.assertEqual(row["parsed"]["amount_minor"], -450, "row with an empty final column is not skipped")
        self.assertEqual(len(res.rows), 3)

    def test_trailing_empty_source_id_column(self):
        res = stage(self, fixture_bytes("synthetic_card_inverted.csv"), "card.csv",
                    profile("synthetic_card_inverted"), "card:alpha")
        self.assertEqual(res.rows[0]["raw_fields"][-1], "")
        self.assertEqual(len(res.rows[0]["raw_fields"]), 5)
        self.assertIsNone(res.rows[0]["parsed"]["source_txn_id"])

    def test_unterminated_quote_stops_with_error_row(self):
        data = csv_bytes(HEADER + "07/01/2026,SYNTHETIC OK,-1.00,1.00,Q-1\n"
                         '07/02/2026,"SYNTHETIC UNTERMINATED,-1.00,1.00,Q-2\n')
        res = stage(self, data, "q.csv", profile("synthetic_checking_signed"), "chk:main")
        self.assertEqual(res.rows[0]["review_state"], "pending")
        last = res.rows[-1]
        self.assertIsNone(last["parsed"])
        self.assertEqual(last["errors"][0]["code"], "E_PARSE_FIELD_COUNT")
        self.assertEqual(last["review_state"], "needs_review")
        self.assertFalse(res.summary["file_complete"])

    def test_blank_lines_skipped_and_counted(self):
        data = csv_bytes(HEADER + "\n07/01/2026,SYNTHETIC A,-1.00,1.00,L-1\n\n\n07/02/2026,SYNTHETIC B,-2.00,1.00,L-2\n")
        res = stage(self, data, "l.csv", profile("synthetic_checking_signed"), "chk:main")
        self.assertEqual([r["row_number"] for r in res.rows], [1, 2])
        self.assertEqual(res.summary["blank_records_skipped"], 3)

    def test_delimiter_only_row_is_not_blank(self):
        data = csv_bytes(HEADER + ",,,,\n")
        res = stage(self, data, "e.csv", profile("synthetic_checking_signed"), "chk:main")
        self.assertEqual(res.rows[0]["raw_fields"], ["", "", "", "", ""])
        self.assertEqual({e["code"] for e in res.rows[0]["errors"]}, {"E_PARSE_DATE", "E_PARSE_AMOUNT"})

    def test_lf_and_cr_line_endings(self):
        for sep in ("\n", "\r"):
            text = HEADER.rstrip("\n") + sep + "07/01/2026,SYNTHETIC A,-1.00,1.00,E-1" + sep
            res = stage(self, text.encode("utf-8"), "e.csv", profile("synthetic_checking_signed"), "chk:main")
            self.assertEqual(res.rows[0]["parsed"]["amount_minor"], -100)


class EncodingTests(unittest.TestCase):
    def _mapped(self, encoding):
        return profile_from_mapping(
            {"Date": "posted_date", "Text": "description", "Amount": "amount"},
            profile_id="user_enc_" + encoding.replace("-", "_"), profile_version="1.0.0",
            account_class="checking", date_format="YYYY-MM-DD", sign_rule="as_is",
            decimal_separator=".", encoding=encoding)

    def test_declared_encodings_decode_exactly(self):
        text = "Date,Text,Amount\n2026-07-01,SYNTHETIC CAF\u00c9 \u00fc,-1.00\n"
        for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
            data = csv_bytes(text, enc)
            if enc == "utf-8-sig":
                self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
            res = stage(self, data, "enc.csv", self._mapped(enc), "chk:main")
            self.assertEqual(res.rows[0]["parsed"]["description"], "SYNTHETIC CAF\u00c9 \u00fc", enc)

    def test_cp1252_specials(self):
        res = stage(self, fixture_bytes("synthetic_checking_debit_credit.cp1252.csv"), "dc.csv",
                    profile("synthetic_checking_debit_credit"), "chk:main")
        self.assertEqual(res.rows[1]["parsed"]["description"], "SYNTHETIC \u20ac TRANSFER IN")

    def test_utf8_sig_strips_bom_once(self):
        res = stage(self, fixture_bytes("synthetic_card_inverted.csv"), "card.csv",
                    profile("synthetic_card_inverted"), "card:alpha")
        self.assertEqual(res.rows[0]["raw_fields"][0], "06/30/2026")

    def test_bom_under_plain_utf8_profile_needs_review(self):
        data = b"\xef\xbb\xbf" + csv_bytes(HEADER + "07/01/2026,SYNTHETIC,-1.00,1.00,X\n")
        with self.assertRaises(UnknownFormat) as cm:
            stage(self, data, "bom.csv", profile("synthetic_checking_signed"), "chk:main")
        self.assertIn("utf-8-sig", cm.exception.message)

    def test_undecodable_row_flagged_never_replaced(self):
        good = csv_bytes("Date,Text,Amount\n2026-07-01,SYNTHETIC OK,-1.00\n", "cp1252")
        bad = b"2026-07-02,SYNTHETIC \x81 BAD,-2.00\r\n"  # 0x81 is undefined in cp1252
        tail = b"2026-07-03,SYNTHETIC AFTER,-3.00\r\n"
        res = stage(self, good + bad + tail, "x.csv", self._mapped("cp1252"), "chk:main")
        self.assertEqual(res.rows[0]["review_state"], "pending")
        row = res.rows[1]
        self.assertIsNone(row["parsed"])
        self.assertEqual(row["raw_fields"], [])
        self.assertEqual(row["errors"], [{"code": "E_PARSE_ENCODING", "path": "raw_fields[1]",
                                          "message": row["errors"][0]["message"]}])
        self.assertEqual(row["review_state"], "needs_review")
        self.assertEqual(res.rows[2]["parsed"]["amount_minor"], -300)
        dumped = json.dumps(res.document, ensure_ascii=False)
        self.assertNotIn("\ufffd", dumped)
        self.assertFalse(any(0xDC80 <= ord(c) <= 0xDCFF for c in dumped))

    def test_latin1_bytes_under_utf8_profile(self):
        data = csv_bytes("Date,Text,Amount\n2026-07-01,SYNTHETIC CAF\u00c9,-1.00\n", "latin-1")
        res = stage(self, data, "x.csv", self._mapped("utf-8"), "chk:main")
        self.assertEqual(res.rows[0]["errors"][0]["code"], "E_PARSE_ENCODING")
        self.assertEqual(res.summary["error_codes"], {"E_PARSE_ENCODING": 1})

    def test_undecodable_header_refused_as_encoding(self):
        data = "Date,T\u00e9xt,Amount\n".encode("latin-1")
        prof = profile_from_mapping({"Date": "posted_date", "T\u00e9xt": "description", "Amount": "amount"},
                                    profile_id="user_hdr", profile_version="1.0.0", account_class="checking",
                                    date_format="YYYY-MM-DD", sign_rule="as_is", decimal_separator=".")
        with self.assertRaises(UnknownFormat) as cm:
            stage(self, data, "x.csv", prof, "chk:main", FakeRepository())
        self.assertEqual(cm.exception.code, "E_PARSE_ENCODING")


if __name__ == "__main__":
    unittest.main()
