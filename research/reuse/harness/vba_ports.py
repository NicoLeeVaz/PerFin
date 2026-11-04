"""Behavioural ports of upstream VBA, used ONLY to reproduce known defects.

THIS IS NOT PERFIN PRODUCTION CODE. Each function reproduces the control flow
of one upstream VBA routine, so its behaviour can be tested with synthetic
inputs on a machine without Office. Every port is a derivative of MIT-licensed
code:

* ``wfp_split_csv``, ``wfp_safe_convert_to_number`` and ``wfp_row_is_processed``
  come from WealthFinPilot/Financial-management-tool @ a5ad1d02, vba/Automate.bas.
  Copyright (c) 2026 Sebastien Oger, MIT. See
  third_party/financial-dashboard-wealthfinpilot/{LICENSE,SOURCE.md}.
* ``ledger_parse_csv_line`` and ``ledger_period_overlaps`` come from
  lingxiaoyang/self-employed-ledger-ms-access @ 40656026, macro module
  DoImportCSV inside "Self-Employed Ledger.accdt".
  Copyright (c) 2019 Ling X. Yang, MIT. See
  third_party/self-employed-ledger-ms-access/{LICENSE,SOURCE.md}.

Where a port depends on VBA runtime behaviour (IsNumeric, CDbl, CDate, Trim),
that behaviour is *modelled* from Microsoft's documented semantics, through the
``VbaLocale`` model below. The model has not been checked against real VBA. Each
modelled assumption is labelled MODEL and listed as a pending Windows check in
research/reuse/catalog.md.

Standard library only. No I/O, no network.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# MODEL: a minimal VBA locale used for IsNumeric / CDbl / CDate.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class VbaLocale:
    name: str
    decimal: str          # Application.International(xlDecimalSeparator)
    thousands: str        # system digit-grouping symbol
    date_order: str       # "MDY" or "DMY" (system short-date order)


EN_US = VbaLocale("en-US", ".", ",", "MDY")
EN_CA = VbaLocale("en-CA", ".", ",", "DMY")  # MODEL: en-CA short date is often dd/mm/yyyy
FR_CA = VbaLocale("fr-CA", ",", " ", "DMY")  # MODEL: NBSP grouping, comma decimal
EN_GB = VbaLocale("en-GB", ".", ",", "DMY")


def vba_trim(s: str) -> str:
    """VBA Trim removes leading and trailing spaces only (not tabs or NBSP)."""
    return s.strip(" ")


def vba_is_numeric(s: str, loc: VbaLocale) -> bool:
    """MODEL of VBA IsNumeric, for plain decimal strings.

    Accepts surrounding spaces, an optional sign, grouping separators in the
    integer part, one locale decimal separator and an optional exponent.
    Real VBA also accepts currency symbols, parentheses, &H hex and other
    forms; this model deliberately does not, so it under-accepts rather than
    over-accepts. The defects tested here do not depend on those forms.
    """
    t = vba_trim(s)
    if not t:
        return False
    d, g = re.escape(loc.decimal), re.escape(loc.thousands)
    pat = rf"[+-]?(\d[\d{g}]*)?({d}\d*)?([eE][+-]?\d+)?"
    if not re.fullmatch(pat, t):
        return False
    return any(ch.isdigit() for ch in t)


def vba_cdbl(s: str, loc: VbaLocale) -> float:
    """MODEL of VBA CDbl: locale-aware parse into an IEEE-754 double."""
    if not vba_is_numeric(s, loc):
        raise ValueError(f"Type mismatch (CDbl): {s!r}")
    t = vba_trim(s).replace(loc.thousands, "").replace(loc.decimal, ".")
    return float(t)


def vba_cdate_numeric(s: str, loc: VbaLocale) -> _dt.date:
    """MODEL of VBA CDate for an 'a/b/yyyy' string.

    VBA reads the parts in the system short-date order. If that reading is not
    a valid date, it silently tries the other order, which is documented
    'best guess' behaviour. So '03/13/2026' is read as 13 March even on a DMY
    system, while '03/04/2026' becomes 3 April on DMY and 4 March on MDY.
    """
    a, b, y = (int(p) for p in s.split("/"))
    first, second = ((a, b), (b, a)) if loc.date_order == "MDY" else ((b, a), (a, b))
    for month, day in (first, second):
        try:
            return _dt.date(y, month, day)
        except ValueError:
            continue
    raise ValueError(f"Type mismatch (CDate): {s!r}")


# ---------------------------------------------------------------------------
# WealthFinPilot / Financial DashBoard, vba/Automate.bas (lines 135-182)
# ---------------------------------------------------------------------------
def wfp_split_csv(csv_line: str) -> list[str]:
    """Port of ``Function SplitCSV(ByVal csv As String) As Variant``."""
    parts: list[str] = []
    buffer = ""
    in_quotes = False
    for char in csv_line:                       # For i = 1 To Len(csv)
        if char == '"':
            in_quotes = not in_quotes           # quote chars are never kept
        elif char == "," and not in_quotes:
            parts.append(vba_trim(buffer))
            buffer = ""
        else:
            buffer += char
    if len(buffer) > 0:                         # "Capture final part"
        parts.append(vba_trim(buffer))          # empty final field is dropped
    return parts


def wfp_safe_convert_to_number(value: str, is_negative: bool, loc: VbaLocale,
                               application_decimal: str | None = None) -> float:
    """Port of ``Function SafeConvertToNumber(value, isNegative) As Double``.

    ``application_decimal`` models ``Application.DecimalSeparator``. It is
    normally equal to the locale separator, unless the user overrides
    "Use system separators" in Excel.
    """
    local_dec = loc.decimal
    alt_dec = "," if local_dec == "." else "."
    app_dec = local_dec if application_decimal is None else application_decimal
    if value[:1] == '"' and value[-1:] == '"':
        value = value[1:-1]
    if alt_dec in value and app_dec == alt_dec:
        value = value.replace(alt_dec, local_dec)
    if vba_is_numeric(value, loc):
        v = vba_cdbl(value, loc)
        return -v if is_negative else v
    return 0.0                                  # invalid input -> silent zero


def wfp_row_is_processed(fields: list[str]) -> bool:
    """Port of the guard ``If UBound(data) < 8 Then GoTo NextRow``."""
    return (len(fields) - 1) >= 8


# ---------------------------------------------------------------------------
# Self-Employed Ledger, module "Macro-DoImportCSV"
# ---------------------------------------------------------------------------
class LedgerCsvAbort(Exception):
    """Stands in for MsgBox + ``End``. Upstream, ``End`` halts all VBA."""


def ledger_parse_csv_line(line: str, delimiter: str = ",", quote_char: str = '"',
                          escape_char: str = "\\") -> list[str]:
    """Port of ``Private Function ParseCSVLine(...) As Collection``."""
    items: list[str] = []
    state = 0
    temp = ""
    line = line + delimiter
    counter = 0

    def mid(pos: int) -> str:                   # Mid(line, pos, 1), 1-based
        return line[pos - 1] if 1 <= pos <= len(line) else ""

    while counter < len(line):
        counter += 1
        thischar = mid(counter)
        if state == 0:
            if thischar == delimiter:
                items.append("")
            elif thischar == quote_char:
                state, temp = 2, ""
            else:
                state, temp = 1, thischar
        elif state == 1:
            if thischar == delimiter:
                items.append(temp)
                state = 0
            else:
                temp += thischar
        elif state == 2:
            if thischar == escape_char:
                counter += 1
                temp += mid(counter)
            elif thischar == quote_char:
                counter += 1
                nextchar = mid(counter)
                if nextchar == quote_char:
                    temp += quote_char
                elif nextchar != delimiter:
                    raise LedgerCsvAbort("delimiter should immediately follow the paired quote char")
                else:
                    state = 0
                    items.append(temp)
            else:
                temp += thischar
    if state != 0:
        raise LedgerCsvAbort("incomplete end of line")
    return items


def ledger_period_overlaps(existing_start: _dt.date, existing_end: _dt.date,
                           new_min: _dt.date, new_max: _dt.date) -> bool:
    """Port of the DCount criterion used to reject overlapping CSV imports.

    ``(StartDate <= Min AND Min <= EndDate) OR (StartDate <= Max AND Max <= EndDate)``
    """
    return ((existing_start <= new_min <= existing_end)
            or (existing_start <= new_max <= existing_end))


def ledger_fido_date(ymd: str, loc: VbaLocale) -> _dt.date:
    """Port of the Fido/Costco date build: ``CDate(m & "/" & d & "/" & y)``."""
    y, m, d = ymd.split("-")
    return vba_cdate_numeric(f"{m}/{d}/{y}", loc)
