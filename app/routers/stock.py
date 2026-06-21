from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.product import Product
from app.models.user import User
from app.routers.auth_deps import get_current_user

router = APIRouter(prefix="/api/estoque", tags=["estoque"])


class StockBatchItem(BaseModel):
    product_id: int
    quantity: int


class StockBatchRequest(BaseModel):
    items: list[StockBatchItem]


def _stock_status(product: Product) -> str:
    if product.stock <= 2:
        return "em_falta"
    elif product.stock <= product.min_stock:
        return "em_risco"
    else:
        return "em_conformidade"


@router.get("")
async def list_stock(
    category: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("name"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Product)

    if category:
        query = query.where(Product.category == category)

    result = await db.execute(query)
    products = result.scalars().all()

    data = []
    for p in products:
        st = _stock_status(p)
        if status and st != status:
            continue
        data.append(
            {
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "price": float(p.price),
                "stock": p.stock,
                "min_stock": p.min_stock,
                "status": st,
                "pct_of_min": round((p.stock / p.min_stock * 100) if p.min_stock > 0 else 100, 1),
            }
        )

    if sort == "name":
        data.sort(key=lambda x: x["name"])
    elif sort == "stock":
        data.sort(key=lambda x: x["stock"])
    elif sort == "pct":
        data.sort(key=lambda x: x["pct_of_min"])

    categories_result = await db.execute(
        select(Product.category).distinct().order_by(Product.category)
    )
    categories = [row[0] for row in categories_result.all()]

    counts = {"em_falta": 0, "em_risco": 0, "em_conformidade": 0}
    for item in data:
        counts[item["status"]] += 1

    return {
        "items": data,
        "categories": categories,
        "counts": counts,
    }


@router.post("/carregamento")
async def add_stock_batch(
    req: StockBatchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("estoquista", "gerente", "caixa"):
        return {"error": "Acesso não permitido"}

    updated = []
    for entry in req.items:
        result = await db.execute(select(Product).where(Product.id == entry.product_id))
        product = result.scalars().first()
        if product:
            product.stock += entry.quantity
            updated.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "added": entry.quantity,
                    "new_stock": product.stock,
                }
            )

    await db.commit()

    return {"message": "Carregamento realizado com sucesso", "items": updated}


@router.put("/{product_id}/min-stock")
async def update_min_stock(
    product_id: int,
    min_stock: int = Query(ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("estoquista", "gerente"):
        return {"error": "Acesso não permitido"}

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalars().first()

    if not product:
        return {"error": "Produto não encontrado"}

    product.min_stock = min_stock
    await db.commit()

    return {
        "id": product.id,
        "name": product.name,
        "min_stock": product.min_stock,
    }
