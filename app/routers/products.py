from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.product import Product
from app.models.user import User
from app.routers.auth_deps import get_current_user, can_view_product_cost
from app.services.promotion_service import get_active_promotion_map


def _is_pack(product: Product) -> bool:
    return product.pack_unit_product_id is not None


def _pack_stock_for_product(product: Product) -> int:
    if not _is_pack(product) or not product.pack_unit_product:
        return 0
    size = product.pack_size or 1
    if size <= 0:
        return 0
    return product.pack_unit_product.stock // size

router = APIRouter(prefix="/api", tags=["products"])


def _serialize_product_list(p: Product, promo_map: dict, user: User) -> dict:
    is_pack = _is_pack(p)
    discount_pct, promo_name = promo_map.get(p.id, (0, None))
    discounted_price = round(float(p.price) * (1 - discount_pct / 100), 2) if discount_pct else float(p.price)
    item = {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "category": p.category,
        "price": float(p.price),
        "discounted_price": discounted_price,
        "active_promotion": promo_name,
        "stock": _pack_stock_for_product(p) if is_pack else p.stock,
        "min_stock": p.min_stock,
        "active": p.active,
        "is_pack": is_pack,
        "pack_size": p.pack_size if is_pack else None,
        "pack_unit_product_id": p.pack_unit_product_id,
        "pack_unit_product_name": p.pack_unit_product.name if is_pack and p.pack_unit_product else None,
    }
    if can_view_product_cost(user):
        item["cost"] = float(p.cost)
        item["margin_pct"] = float(p.margin_pct)
    return item


@router.get("/produtos")
async def list_products(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Product).options(selectinload(Product.pack_unit_product))
    if active_only:
        query = query.where(Product.active == True)
    result = await db.execute(query.order_by(Product.name))
    products = result.scalars().all()

    promo_map = await get_active_promotion_map(db)

    return [_serialize_product_list(p, promo_map, user) for p in products]


@router.get("/produtos/{product_id}")
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Product).where(Product.id == product_id).options(selectinload(Product.suppliers))
    )
    product = result.scalars().first()
    if not product:
        return {"error": "Produto não encontrado"}

    item = {
        "id": product.id,
        "code": product.code,
        "name": product.name,
        "category": product.category,
        "price": float(product.price),
        "stock": product.stock,
        "min_stock": product.min_stock,
        "active": product.active,
    }
    if can_view_product_cost(user):
        item["cost"] = float(product.cost)
        item["margin_pct"] = float(product.margin_pct)
        item["suppliers"] = [
            {"id": s.id, "name": s.name}
            for s in product.suppliers
        ]
    return item
