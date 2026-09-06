"""Decimal helpers for every financial calculation in the application."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


MONEY_QUANTUM = Decimal("0.01")
COST_QUANTUM = Decimal("0.0001")
RATE_QUANTUM = Decimal("0.0001")
ZERO = Decimal("0.00")


def decimal_value(value: Any, default: Decimal = ZERO) -> Decimal:
    """Convert values without passing through binary floating-point arithmetic."""
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def money(value: Any) -> Decimal:
    return decimal_value(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def cost(value: Any) -> Decimal:
    return decimal_value(value).quantize(COST_QUANTUM, rounding=ROUND_HALF_UP)


def rate(value: Any) -> Decimal:
    return decimal_value(value).quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)


def percentage_amount(base: Any, percentage: Any) -> Decimal:
    return money(decimal_value(base) * decimal_value(percentage) / Decimal("100"))


def product_amount(unit_value: Any, quantity: int) -> Decimal:
    return money(decimal_value(unit_value) * Decimal(quantity))


def non_negative(value: Any) -> Decimal:
    return max(ZERO, money(value))


def as_float(value: Any) -> float:
    """Serialize Decimal values through the existing JSON-compatible API shape."""
    return float(money(value))
