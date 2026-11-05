"""Strict, locale-independent parsing of amounts and dates.

Nothing here consults the operating-system locale, guesses a format, coerces an
invalid value to zero or substitutes today's date. Every rejection raises
``ValueParseError`` with a reason that never repeats the input value.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from .errors import ValueParseError

MONEY_BOUND = 922337203685477  # common.schema.json $defs/money_minor (contract 1.0.0)
MAX_AMOUNT_TEXT = 40  # longer strings are rejected before any numeric work

_DATE_PATTERNS = {
    # format: (regex, (year group, month group, day group))
    "YYYY-MM-DD": (r"([0-9]{4})-([0-9]{2})-([0-9]{2})", (1, 2, 3)),
    "MM/DD/YYYY": (r"([0-9]{2})/([0-9]{2})/([0-9]{4})", (3, 1, 2)),
    "DD/MM/YYYY": (r"([0-9]{2})/([0-9]{2})/([0-9]{4})", (3, 2, 1)),
    "M/D/YYYY": (r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", (3, 1, 2)),
    "D/M/YYYY": (r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", (3, 2, 1)),
    "DD.MM.YYYY": (r"([0-9]{2})\.([0-9]{2})\.([0-9]{4})", (3, 2, 1)),
}
DATE_FORMATS = tuple(_DATE_PATTERNS)
_COMPILED_DATES = {k: (re.compile(p), g) for k, (p, g) in _DATE_PATTERNS.items()}
_SPACE = " \t"


def parse_date(text, date_format):
    """Return an ISO ``YYYY-MM-DD`` string or raise ValueParseError(E_PARSE_DATE).

    The text must match the declared format exactly (no surrounding text, no time
    part, no two-digit year) and name a real calendar date, leap years included.
    """
    if date_format not in _COMPILED_DATES:
        raise ValueParseError("E_PARSE_DATE", "date format is not declared by the contract")
    value = text.strip(_SPACE)
    if value == "":
        raise ValueParseError("E_PARSE_DATE", "date is empty; no default date is ever used")
    regex, (gy, gm, gd) = _COMPILED_DATES[date_format]
    m = regex.fullmatch(value)
    if not m:
        raise ValueParseError("E_PARSE_DATE", "does not match the declared date format %s" % date_format)
    year, month, day = int(m.group(gy)), int(m.group(gm)), int(m.group(gd))
    if year < 1:
        raise ValueParseError("E_PARSE_DATE", "year is out of range")
    if not 1 <= month <= 12:
        raise ValueParseError("E_PARSE_DATE", "month is out of range for format %s" % date_format)
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        raise ValueParseError("E_PARSE_DATE", "day is not valid for that month and year") from None


def _number_regex(decimal_separator, thousands_separator):
    dec = re.escape(decimal_separator)
    if thousands_separator:
        ts = re.escape(thousands_separator)
        integer = r"(?:[0-9]{1,3}(?:%s[0-9]{3})+|[0-9]+)" % ts
    else:
        integer = r"[0-9]+"
    # Exactly 0 or 2 decimal places (USD minor units). A bare separator is rejected.
    return re.compile(r"(%s)(?:%s([0-9]{2}))?" % (integer, dec))


_REGEX_CACHE = {}


def parse_amount(text, decimal_separator, thousands_separator="", parentheses_negative=False,
                 allow_sign=True):
    """Return signed integer minor units for ``text`` exactly as written in the file.

    Returns None only for an empty (or all-space) field; callers decide whether an
    empty field is allowed. Raises ValueParseError(E_PARSE_AMOUNT) for anything that
    is not unambiguous under the declared separators.
    """
    if decimal_separator not in (".", ","):
        raise ValueParseError("E_PARSE_AMOUNT", "decimal separator is not declared")
    if thousands_separator == decimal_separator:
        raise ValueParseError("E_PARSE_AMOUNT", "decimal and thousands separators must differ")
    value = text.strip(_SPACE)  # outer padding only; inner spaces stay significant
    if value == "":
        return None
    if len(value) > MAX_AMOUNT_TEXT:
        raise ValueParseError("E_PARSE_AMOUNT", "amount text is too long")
    negative = False
    signed = False
    if value.startswith("(") or value.endswith(")"):
        if not parentheses_negative:
            raise ValueParseError("E_PARSE_AMOUNT", "parentheses are not declared as negative by the profile")
        if not (value.startswith("(") and value.endswith(")")) or len(value) < 3:
            raise ValueParseError("E_PARSE_AMOUNT", "unbalanced parentheses")
        value = value[1:-1]
        negative = signed = True
        if value[:1] in ("+", "-"):
            raise ValueParseError("E_PARSE_AMOUNT", "sign inside parentheses is ambiguous")
    elif value[:1] in ("+", "-"):
        negative = value[0] == "-"
        signed = True
        value = value[1:]
    if signed and not allow_sign:
        raise ValueParseError("E_PARSE_AMOUNT", "a signed value in a debit/credit column is ambiguous")
    key = (decimal_separator, thousands_separator)
    regex = _REGEX_CACHE.get(key)
    if regex is None:
        regex = _REGEX_CACHE[key] = _number_regex(decimal_separator, thousands_separator)
    m = regex.fullmatch(value)
    if not m:
        raise ValueParseError(
            "E_PARSE_AMOUNT",
            "not a number with exactly 0 or 2 decimal places under the declared separators "
            "(decimal %r, thousands %r); never coerced to 0" % (decimal_separator, thousands_separator))
    integer = m.group(1).replace(thousands_separator, "") if thousands_separator else m.group(1)
    fraction = m.group(2) or "00"
    try:
        minor = Decimal(integer + "." + fraction).scaleb(2)
    except InvalidOperation:  # pragma: no cover - regex already restricts the text
        raise ValueParseError("E_PARSE_AMOUNT", "not a decimal number") from None
    if minor != minor.to_integral_value():  # pragma: no cover - two decimals at most
        raise ValueParseError("E_PARSE_AMOUNT", "more precision than minor units")
    result = int(minor)
    if negative:
        result = -result
    if abs(result) > MONEY_BOUND:
        raise ValueParseError("E_PARSE_AMOUNT", "outside the contract money bound of +/-%d minor units" % MONEY_BOUND)
    return result
