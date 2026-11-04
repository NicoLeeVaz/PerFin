"""Synthetic reproductions of known CSV/VBA concerns (task 1b, issue #3).

Run:  python3 -I -m unittest discover -s research/reuse/harness -v

Every input is synthetic. A test named ``test_defect_*`` *passes when the
upstream defect is reproduced*. A test named ``test_reference_*`` shows the
behaviour PerFin should require, using the Python standard library.
"""

import csv
import datetime as dt
import io
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vba_ports as vp  # noqa: E402


def stdlib_row(line: str) -> list[str]:
    return next(csv.reader(io.StringIO(line)))


# Synthetic bank-export layout implied by WFP Automate.bas:
# 0 acct | 1 type | 2 "EOP" | 3 date | 4 line no | 5 description | 6 x | 7 withdrawal | 8 deposit
WITHDRAWAL_ROW = 'SYN-001,CHQ,EOP,2026-01-15,7,"Coffee, synthetic",x,4.50,'
DEPOSIT_ROW = 'SYN-001,CHQ,EOP,2026-01-16,8,Payroll synthetic,x,,1200.00'


class WfpSplitCsv(unittest.TestCase):
    def test_defect_trailing_empty_field_dropped(self):
        self.assertEqual(len(stdlib_row("a,b,")), 3)
        self.assertEqual(vp.wfp_split_csv("a,b,"), ["a", "b"])

    def test_defect_withdrawal_row_silently_skipped(self):
        # The 9-column withdrawal row has an empty final deposit field.
        # SplitCSV returns 8 parts, so the UBound guard skips the row
        # without any message. The deposit row is processed.
        self.assertEqual(len(stdlib_row(WITHDRAWAL_ROW)), 9)
        self.assertFalse(vp.wfp_row_is_processed(vp.wfp_split_csv(WITHDRAWAL_ROW)))
        self.assertTrue(vp.wfp_row_is_processed(vp.wfp_split_csv(DEPOSIT_ROW)))

    def test_defect_escaped_quotes_lost(self):
        line = '1,"Shop ""Synthetic"" Ltd",2'
        self.assertEqual(stdlib_row(line)[1], 'Shop "Synthetic" Ltd')
        self.assertEqual(vp.wfp_split_csv(line)[1], "Shop Synthetic Ltd")

    def test_defect_quoted_whitespace_trimmed(self):
        self.assertEqual(stdlib_row('" padded ",x')[0], " padded ")
        self.assertEqual(vp.wfp_split_csv('" padded ",x')[0], "padded")

    def test_reference_quoted_delimiter_kept(self):
        # Both parsers keep a comma that appears inside quotes.
        self.assertEqual(vp.wfp_split_csv(WITHDRAWAL_ROW)[5], "Coffee, synthetic")
        self.assertEqual(stdlib_row(WITHDRAWAL_ROW)[5], "Coffee, synthetic")


class WfpSafeConvertToNumber(unittest.TestCase):
    def test_defect_non_numeric_returns_zero(self):
        for bad in ("N/A", "12.5O", "--", "abc"):
            with self.subTest(bad=bad):
                self.assertEqual(vp.wfp_safe_convert_to_number(bad, False, vp.EN_US), 0.0)

    def test_defect_invalid_indistinguishable_from_blank_and_zero(self):
        f = vp.wfp_safe_convert_to_number
        self.assertEqual(f("N/A", True, vp.EN_US), f("", True, vp.EN_US))
        self.assertEqual(f("N/A", True, vp.EN_US), f("0", True, vp.EN_US))

    def test_valid_values_convert(self):
        self.assertEqual(vp.wfp_safe_convert_to_number("4.50", True, vp.EN_US), -4.5)
        self.assertEqual(vp.wfp_safe_convert_to_number('"1,200.00"', False, vp.EN_US), 1200.0)

    def test_defect_locale_dot_decimal_zeroed_in_comma_locale(self):
        # MODEL: in a comma-decimal locale, where Excel uses system separators,
        # the replacement branch never runs, so "4.50" fails IsNumeric and becomes 0.
        self.assertEqual(vp.wfp_safe_convert_to_number("4.50", True, vp.FR_CA), 0.0)
        self.assertEqual(vp.wfp_safe_convert_to_number("4,50", True, vp.FR_CA), -4.5)

    def test_defect_same_text_different_value_by_locale(self):
        # MODEL: in en-US, "1,234" means one thousand two hundred thirty-four;
        # in fr-CA it means 1.234.
        self.assertEqual(vp.wfp_safe_convert_to_number("1,234", False, vp.EN_US), 1234.0)
        self.assertEqual(vp.wfp_safe_convert_to_number("1,234", False, vp.FR_CA), 1.234)

    def test_defect_double_accumulation_not_exact(self):
        vals = [vp.wfp_safe_convert_to_number(v, False, vp.EN_US) for v in ("0.10", "0.20")]
        self.assertNotEqual(sum(vals), 0.30)
        self.assertEqual(Decimal("0.10") + Decimal("0.20"), Decimal("0.30"))


class LedgerParseCsvLine(unittest.TestCase):
    def test_trailing_empty_field_preserved(self):
        self.assertEqual(vp.ledger_parse_csv_line("a,b,"), ["a", "b", ""])

    def test_doubled_quote_preserved(self):
        line = '1,"Shop ""Synthetic"" Ltd",2'
        self.assertEqual(vp.ledger_parse_csv_line(line), stdlib_row(line))

    def test_defect_backslash_escape_non_rfc4180(self):
        line = '1,"C:\\temp\\synthetic",2'
        self.assertEqual(stdlib_row(line)[1], "C:\\temp\\synthetic")
        self.assertEqual(vp.ledger_parse_csv_line(line)[1], "C:tempsynthetic")

    def test_defect_space_after_closing_quote_aborts(self):
        self.assertEqual(stdlib_row('"a" ,b'), ['a ', 'b'])
        with self.assertRaises(vp.LedgerCsvAbort):
            vp.ledger_parse_csv_line('"a" ,b')

    def test_defect_embedded_newline_aborts_line_reader(self):
        # Upstream reads one physical line at a time (ReadLine), so a quoted
        # multi-line field reaches the parser as an unterminated line.
        multi = '1,"line one\nline two",2\n'
        self.assertEqual(len(list(csv.reader(io.StringIO(multi)))), 1)
        with self.assertRaises(vp.LedgerCsvAbort):
            vp.ledger_parse_csv_line(multi.split("\n")[0])


class LedgerOverlapAndDates(unittest.TestCase):
    def test_overlap_detected_for_partial_overlap(self):
        d = dt.date
        self.assertTrue(vp.ledger_period_overlaps(d(2026, 1, 1), d(2026, 1, 31), d(2026, 1, 15), d(2026, 2, 14)))

    def test_defect_enclosing_period_not_detected(self):
        # A new file covering 1 Jan - 28 Feb fully encloses an existing
        # 10-20 Jan import. Neither endpoint falls inside the existing range,
        # so the duplicate transactions are imported.
        d = dt.date
        self.assertFalse(vp.ledger_period_overlaps(d(2026, 1, 10), d(2026, 1, 20), d(2026, 1, 1), d(2026, 2, 28)))

    def test_defect_cdate_month_day_transposition(self):
        # MODEL: the date is built as m/d/yyyy text and then CDate'd. On a DMY
        # system, days 1-12 are silently transposed; days after 12 are not.
        self.assertEqual(vp.ledger_fido_date("2026-03-04", vp.EN_US), dt.date(2026, 3, 4))
        self.assertEqual(vp.ledger_fido_date("2026-03-04", vp.EN_GB), dt.date(2026, 4, 3))
        self.assertEqual(vp.ledger_fido_date("2026-03-13", vp.EN_GB), dt.date(2026, 3, 13))

    def test_reference_iso_parse_is_locale_free(self):
        self.assertEqual(dt.date.fromisoformat("2026-03-04"), dt.date(2026, 3, 4))


if __name__ == "__main__":
    unittest.main()
