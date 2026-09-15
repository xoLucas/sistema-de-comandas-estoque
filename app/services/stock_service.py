from collections.abc import Iterable
from decimal import Decimal

from app.models.product import Product
from app.services.money_service import ZERO, cost, money


def is_pack(product: Product) -> bool:
    return product.pack_unit_product_id is not None


def resolved_sale_unit_cost(
    product: Product, stock_product: Product | None = None
) -> Decimal:
    """Return the unit cost snapshot for a sold/consigned item.

    Packs are sold in pack units, so their cost is the linked unit product cost
    multiplied by the pack size. Falls back to the stored pack cost when the
    linked unit is unavailable.
    """
    if is_pack(product):
        unit = stock_product or product.pack_unit_product
        if unit is not None and unit.cost is not None:
            return cost((unit.cost or ZERO) * (product.pack_size or 1))
        return cost(product.cost or ZERO)
    return cost(product.cost or ZERO)


def validate_pack_configuration(product: Product) -> None:
    if is_pack(product) and (product.pack_size is None or product.pack_size < 2):
        raise ValueError(
            f"Engradado '{product.name}' possui quantidade por engradado inválida. "
            "Corrija o cadastro antes de vender ou movimentar o produto."
        )


def pack_stock_for_product(product: Product) -> int:
    """Return computed pack stock based on linked unit product."""
    if not is_pack(product) or not product.pack_unit_product:
        return 0
    unit = product.pack_unit_product
    size = product.pack_size or 1
    if size <= 0:
        return 0
    return unit.stock // size


def inventory_cost_for_product(product: Product) -> Decimal:
    """Return the physical inventory value represented by one product record."""
    if is_pack(product):
        return ZERO
    return money((product.cost or ZERO) * product.stock)


def total_inventory_cost(products: Iterable[Product]) -> Decimal:
    """Return the total physical inventory value without counting derived packs twice."""
    return money(sum((inventory_cost_for_product(product) for product in products), ZERO))


def stock_status(product: Product) -> str:
    if is_pack(product):
        pack_stock = pack_stock_for_product(product)
        if pack_stock <= 0:
            return "em_falta"
        elif pack_stock <= product.min_stock:
            return "em_risco"
        else:
            return "em_conformidade"

    if product.stock <= 2:
        return "em_falta"
    elif product.stock <= product.min_stock:
        return "em_risco"
    else:
        return "em_conformidade"
