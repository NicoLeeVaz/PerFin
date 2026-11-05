"""Exact money conversion between contract minor units and Access CURRENCY.

Contract: money is a JSON integer count of minor units (cents), bounded to
+/-922337203685477. Access stores it in a CURRENCY column holding that integer (not dollars).
CURRENCY is a scaled 64-bit integer with four decimal places, so the integer part of its range
is exactly the contract bound. Conversion goes through Decimal; floats are never produced, and
are accepted from the driver only when they are exactly integral (which every value within the
bound is, since 922337203685477 < 2**53).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

MONEY_MAX = 922337203685477
MONEY_MIN = -MONEY_MAX
CURRENCY_SCALE = Decimal("0.0001")  # Access CURRENCY has four decimal places


class MoneyError(ValueError):
    """A value is not an exact, in-range integer count of minor units."""


def check_minor(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MoneyError("minor units must be an int, got %s" % type(value).__name__)
    if not MONEY_MIN <= value <= MONEY_MAX:
        raise MoneyError("minor units out of the contract range +/-%d" % MONEY_MAX)
    return value


def minor_to_db(value) -> Decimal:
    """int minor units -> Decimal bound to a CURRENCY parameter (exact, no fraction)."""
    return Decimal(check_minor(value))


def db_to_minor(value) -> int:
    """CURRENCY value from the driver (Decimal, int, or an integral float) -> int minor units."""
    if isinstance(value, bool):
        raise MoneyError("boolean is not money")
    if isinstance(value, int):
        return check_minor(value)
    if isinstance(value, float):
        if value != value or not value.is_integer():
            raise MoneyError("CURRENCY value is not an integer count of minor units")
        return check_minor(int(value))
    if isinstance(value, Decimal):
        try:
            integral = value.to_integral_value()
        except InvalidOperation:
            raise MoneyError("CURRENCY value is not finite") from None
        if not value.is_finite() or integral != value:
            raise MoneyError("CURRENCY value is not an integer count of minor units")
        return check_minor(int(integral))
    raise MoneyError("unsupported CURRENCY value type %s" % type(value).__name__)


def minor_to_major(value: int, exponent: int = 2) -> Decimal:
    """Display helper only: 1234 -> Decimal('12.34'). Never used for storage."""
    return Decimal(check_minor(value)).scaleb(-exponent)


def major_to_minor(text: str, exponent: int = 2) -> int:
    """Parse an exact decimal string such as '-12.34' into minor units; rejects extra precision."""
    if not isinstance(text, str):
        raise MoneyError("major-unit amounts must be decimal strings")
    try:
        d = Decimal(text)
    except InvalidOperation:
        raise MoneyError("not a decimal string") from None
    scaled = d.scaleb(exponent)
    if not d.is_finite() or scaled != scaled.to_integral_value():
        raise MoneyError("more precision than the currency's minor unit")
    return check_minor(int(scaled))
