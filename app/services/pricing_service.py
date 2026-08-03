def calculate_selling_price(cost: float, margin_pct: float) -> float:
    """Calculate selling price based on cost and margin over selling price.

    Formula: selling_price = cost / (1 - margin_pct / 100)
    """
    if cost <= 0:
        return 0.0
    margin_rate = margin_pct / 100
    if margin_rate >= 1:
        return 0.0
    return round(cost / (1 - margin_rate), 2)


def calculate_margin_pct(cost: float, selling_price: float) -> float:
    """Calculate margin percentage over selling price from cost and price.

    Formula: margin_pct = ((selling_price - cost) / selling_price) * 100
    """
    if cost <= 0 or selling_price <= 0:
        return 0.0
    return round(((selling_price - cost) / selling_price) * 100, 2)
