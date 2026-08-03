from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.category import Category
from app.models.product import Product
from app.models.user import User
from app.routers.auth_deps import get_current_user, can_manage_stock

router = APIRouter(prefix="/api/categorias", tags=["categorias"])


class CategoryCreate(BaseModel):
    name: str
    printer: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = None
    printer: str | None = None


@router.get("")
async def list_categories(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Category).order_by(Category.name))
    categories = result.scalars().all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "printer": c.printer,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in categories
    ]


@router.post("")
async def create_category(
    req: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_stock(user):
        return {"error": "Acesso não permitido"}

    name = req.name.strip()
    if not name:
        return {"error": "Nome da categoria é obrigatório"}

    existing = await db.execute(
        select(Category).where(func.lower(Category.name) == func.lower(name))
    )
    if existing.scalar_one_or_none():
        return {"error": "Categoria já existe"}

    category = Category(name=name, printer=req.printer)
    db.add(category)
    await db.commit()
    return {
        "id": category.id,
        "name": category.name,
        "printer": category.printer,
    }


@router.put("/{category_id}")
async def update_category(
    category_id: int,
    req: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_stock(user):
        return {"error": "Acesso não permitido"}

    result = await db.execute(select(Category).where(Category.id == category_id))
    category = result.scalar_one_or_none()
    if not category:
        return {"error": "Categoria não encontrada"}

    if req.name is not None:
        name = req.name.strip()
        if not name:
            return {"error": "Nome da categoria é obrigatório"}
        existing = await db.execute(
            select(Category).where(
                func.lower(Category.name) == func.lower(name),
                Category.id != category_id,
            )
        )
        if existing.scalar_one_or_none():
            return {"error": "Categoria já existe"}
        category.name = name

    if req.printer is not None:
        category.printer = req.printer

    await db.commit()
    return {
        "id": category.id,
        "name": category.name,
        "printer": category.printer,
    }


@router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_stock(user):
        return {"error": "Acesso não permitido"}

    result = await db.execute(select(Category).where(Category.id == category_id))
    category = result.scalar_one_or_none()
    if not category:
        return {"error": "Categoria não encontrada"}

    products_count = await db.execute(
        select(func.count(Product.id)).where(
            func.lower(Product.category) == func.lower(category.name)
        )
    )
    if products_count.scalar_one() > 0:
        return {
            "error": "Categoria possui produtos vinculados. Mova ou exclua os produtos antes."
        }

    await db.delete(category)
    await db.commit()
    return {"ok": True}
