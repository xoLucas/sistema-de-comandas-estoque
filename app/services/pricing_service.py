from decimal import Decimal

from app.services.money_service import ZERO, decimal_value, money, rate


def calculate_selling_price(cost_value: Decimal, margin_pct: Decimal) -> Decimal:
    """Calculate selling price based on cost and margin over selling price.

    Formula: selling_price = cost / (1 - margin_pct / 100)
    """
    normalized_cost = decimal_value(cost_value)
    normalized_margin = rate(margin_pct)
    if normalized_cost <= ZERO:
        return ZERO
    margin_rate = normalized_margin / Decimal("100")
    if margin_rate >= Decimal("1"):
        return ZERO
    return money(normalized_cost / (Decimal("1") - margin_rate))


def calculate_margin_pct(cost_value: Decimal, selling_price: Decimal) -> Decimal:
    """Calculate margin percentage over selling price from cost and price.

    Formula: margin_pct = ((selling_price - cost) / selling_price) * 100
    """
    normalized_cost = decimal_value(cost_value)
    normalized_price = money(selling_price)
    if normalized_cost <= ZERO or normalized_price <= ZERO:
        return rate(0)
    return rate(
        ((normalized_price - normalized_cost) / normalized_price) * Decimal("100")
    )
