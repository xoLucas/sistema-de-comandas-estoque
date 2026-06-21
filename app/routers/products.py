from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.product import Product
from app.models.user import User
from app.routers.auth_deps import get_current_user

router = APIRouter(prefix="/api", tags=["products"])


@router.get("/produtos")
async def list_products(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Product).order_by(Product.name))
    products = result.scalars().all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "price": float(p.price),
            "stock": p.stock,
            "min_stock": p.min_stock,
        }
        for p in products
    ]
