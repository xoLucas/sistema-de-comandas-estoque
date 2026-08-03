from app.models.product import Product


def is_pack(product: Product) -> bool:
    return product.pack_unit_product_id is not None


def pack_stock_for_product(product: Product) -> int:
    """Return computed pack stock based on linked unit product."""
    if not is_pack(product) or not product.pack_unit_product:
        return 0
    unit = product.pack_unit_product
    size = product.pack_size or 1
    if size <= 0:
        return 0
    return unit.stock // size


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
