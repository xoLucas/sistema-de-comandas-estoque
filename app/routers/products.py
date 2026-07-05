from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.product import Product
from app.models.user import User
from app.routers.auth_deps import get_current_user

router = APIRouter(prefix="/api", tags=["products"])


@router.get("/produtos")
async def list_products(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Product)
    if active_only:
        query = query.where(Product.active == True)
    result = await db.execute(query.order_by(Product.name))
    products = result.scalars().all()

    return [
        {
            "id": p.id,
            "code": p.code,
            "name": p.name,
            "category": p.category,
            "cost": float(p.cost),
            "margin_pct": float(p.margin_pct),
            "price": float(p.price),
            "stock": p.stock,
            "min_stock": p.min_stock,
            "active": p.active,
        }
        for p in products
    ]


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

    return {
        "id": product.id,
        "code": product.code,
        "name": product.name,
        "category": product.category,
        "cost": float(product.cost),
        "margin_pct": float(product.margin_pct),
        "price": float(product.price),
        "stock": product.stock,
        "min_stock": product.min_stock,
        "active": product.active,
        "suppliers": [
            {"id": s.id, "name": s.name}
            for s in product.suppliers
        ],
    }
