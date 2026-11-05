"""Strict amount and date parsing: no locale, no coercion, no default date."""
import unittest

import import_support  # noqa: F401  (sets sys.path)
from perfin_import.errors import ValueParseError
from perfin_import.values import MONEY_BOUND, parse_amount, parse_date


class AmountTests(unittest.TestCase):
    def ok(self, text, expected, dec=".", ts=",", paren=False):
        self.assertEqual(parse_amount(text, dec, ts, paren), expected, text)

    def bad(self, text, dec=".", ts=",", paren=False, allow_sign=True):
        with self.assertRaises(ValueParseError, msg=text) as cm:
            parse_amount(text, dec, ts, paren, allow_sign=allow_sign)
        self.assertEqual(cm.exception.code, "E_PARSE_AMOUNT")
        self.assertNotIn(text.strip(), cm.exception.reason.replace("+/-", ""),
                         "rejection reasons never echo the value")

    def test_basic_and_signs(self):
        self.ok("12.34", 1234)
        self.ok("-12.34", -1234)
        self.ok("+12.34", 1234)
        self.ok("12", 1200)
        self.ok("0.00", 0)
        self.ok("-0.00", 0)
        self.ok("  7.05 ", 705)
        self.ok("0.10", 10)  # exact: no binary floating point anywhere

    def test_declared_separators_disambiguate(self):
        self.ok("1,234.56", 123456, ".", ",")
        self.ok("1.234,56", 123456, ",", ".")
        self.bad("1.234,56", ".", ",")
        self.bad("1,234.56", ",", ".")
        self.ok("1234.56", 123456, ".", ",")  # grouping optional
        self.ok("1 234,56", 123456, ",", " ")
        self.ok("1'234.56", 123456, ".", "'")
        self.ok("1,234,567.00", 123456700, ".", ",")
        self.ok("1.234", 123400, ",", ".")  # grouped integer under decimal comma

    def test_undeclared_or_ambiguous_rejected(self):
        self.bad("1,234", ".", "")      # thousands separator not declared
        self.bad("1,234", ",", "")      # would be 3 decimal places
        self.bad("1.234", ".", ",")     # 3 decimals under decimal point
        self.bad("12.5")                # exactly 0 or 2 decimals
        self.bad("12.345")
        self.bad("12.")
        self.bad(".50")
        self.bad("12,34.56")            # malformed grouping
        self.bad("1234,567.00")
        self.bad("1,234.56", ".", "'")

    def test_invalid_never_zero(self):
        for text in ("abc", "N/A", "--1.00", "+-1.00", "1.00-", "- 1.00", "$12.00", "12.00 USD", "1e3",
                     "١٢.00", "−12.00", "12.00.00", "0x10", "1_000.00", "nan", "Infinity"):
            self.bad(text)

    def test_empty_is_none_not_zero(self):
        self.assertIsNone(parse_amount("", ".", ","))
        self.assertIsNone(parse_amount("   ", ".", ","))

    def test_parentheses(self):
        self.ok("(12.34)", -1234, paren=True)
        self.ok("(1,234.00)", -123400, paren=True)
        self.bad("(12.34)", paren=False)
        self.bad("(12.34", paren=True)
        self.bad("12.34)", paren=True)
        self.bad("(-12.34)", paren=True)
        self.bad("()", paren=True)

    def test_debit_credit_columns_refuse_signs(self):
        self.bad("-12.34", allow_sign=False)
        self.bad("+12.34", allow_sign=False)
        self.assertEqual(parse_amount("12.34", ".", ",", allow_sign=False), 1234)

    def test_money_bound(self):
        # Built from the constant: the literal digits would trip the 1c Luhn repo scan.
        def text(minor, grouped=False):
            units, cents = divmod(minor, 100)
            return ("{:,}" if grouped else "{}").format(units) + ".%02d" % cents
        self.ok(text(MONEY_BOUND), MONEY_BOUND, ".", "")
        self.ok("-" + text(MONEY_BOUND, grouped=True), -MONEY_BOUND)
        self.bad(text(MONEY_BOUND + 1), ".", "")
        self.bad("9" * 39, ".", "")
        self.bad("9" * 5000, ".", "")

    def test_same_separators_refused(self):
        with self.assertRaises(ValueParseError):
            parse_amount("1.00", ".", ".")


class DateTests(unittest.TestCase):
    def bad(self, text, fmt):
        with self.assertRaises(ValueParseError, msg=(text, fmt)) as cm:
            parse_date(text, fmt)
        self.assertEqual(cm.exception.code, "E_PARSE_DATE")

    def test_locale_ambiguity_resolved_only_by_profile(self):
        self.assertEqual(parse_date("03/04/2026", "MM/DD/YYYY"), "2026-03-04")
        self.assertEqual(parse_date("03/04/2026", "DD/MM/YYYY"), "2026-04-03")
        self.assertEqual(parse_date("3/4/2026", "M/D/YYYY"), "2026-03-04")
        self.assertEqual(parse_date("3/4/2026", "D/M/YYYY"), "2026-04-03")
        self.assertEqual(parse_date("03.04.2026", "DD.MM.YYYY"), "2026-04-03")
        self.bad("13/04/2026", "MM/DD/YYYY")   # no silent swap to DD/MM
        self.bad("04/13/2026", "DD/MM/YYYY")
        self.bad("3/4/2026", "MM/DD/YYYY")     # undeclared single-digit form
        self.bad("2026-03-04", "MM/DD/YYYY")   # undeclared ISO form
        self.bad("03/04/2026", "YYYY-MM-DD")

    def test_iso_and_flexible_digits(self):
        self.assertEqual(parse_date("2026-12-31", "YYYY-MM-DD"), "2026-12-31")
        self.assertEqual(parse_date("12/31/2026", "M/D/YYYY"), "2026-12-31")
        self.assertEqual(parse_date(" 2026-01-05 ", "YYYY-MM-DD"), "2026-01-05")

    def test_real_calendar_dates_and_leap_years(self):
        self.assertEqual(parse_date("02/29/2024", "MM/DD/YYYY"), "2024-02-29")
        self.assertEqual(parse_date("29.02.2000", "DD.MM.YYYY"), "2000-02-29")
        self.bad("02/29/2025", "MM/DD/YYYY")
        self.bad("29.02.2100", "DD.MM.YYYY")
        self.bad("04/31/2026", "MM/DD/YYYY")
        self.bad("07/32/2026", "MM/DD/YYYY")
        self.bad("00/10/2026", "MM/DD/YYYY")
        self.bad("2026-00-10", "YYYY-MM-DD")
        self.bad("0000-01-01", "YYYY-MM-DD")

    def test_never_defaults(self):
        for text in ("", "   ", "today", "2026-07-01 00:00:00", "2026-07-01T00:00Z", "26-07-01", "07/01/26",
                     "٢٠٢٦-01-01"):
            self.bad(text, "YYYY-MM-DD")

    def test_unknown_format_refused(self):
        self.bad("2026-01-01", "YYYY/MM/DD")


if __name__ == "__main__":
    unittest.main()
