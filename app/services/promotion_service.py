from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.product import Product
from app.models.promotion import Promotion


def _utc_now():
    return datetime.now(timezone.utc)


async def get_discounted_price(product: Product, db: AsyncSession) -> float:
    now = _utc_now()
    result = await db.execute(
        select(Promotion)
        .join(Promotion.products)
        .where(
            Product.id == product.id,
            Promotion.is_active == True,
            (Promotion.start_at == None) | (Promotion.start_at <= now),
            (Promotion.end_at == None) | (Promotion.end_at >= now),
        )
    )
    promotions = result.scalars().all()
    if not promotions:
        return float(product.price)
    best_discount = max(p.discount_pct for p in promotions)
    return round(float(product.price) * (1 - best_discount / 100), 2)


async def get_active_promotion_map(db: AsyncSession) -> dict[int, tuple[float, str | None]]:
    now = _utc_now()
    result = await db.execute(
        select(Promotion)
        .options(selectinload(Promotion.products))
        .where(
            Promotion.is_active == True,
            (Promotion.start_at == None) | (Promotion.start_at <= now),
            (Promotion.end_at == None) | (Promotion.end_at >= now),
        )
    )
    promotions = result.scalars().all()
    product_promo: dict[int, tuple[float, str | None]] = {}
    for promo in promotions:
        for product in promo.products:
            current = product_promo.get(product.id)
            if not current or promo.discount_pct > current[0]:
                product_promo[product.id] = (promo.discount_pct, promo.name)
    return product_promo
