from app.models.product import Product


def is_pack(product: Product) -> bool:
    return product.pack_unit_product_id is not None


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
