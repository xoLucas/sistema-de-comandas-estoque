from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.supplier import Supplier
from app.models.product import Product
from app.models.user import User
from app.routers.auth_deps import get_current_user, can_view_suppliers

router = APIRouter(prefix="/api/fornecedores", tags=["fornecedores"])


class SupplierCreate(BaseModel):
    name: str
    contact: str | None = None
    active: bool = True
    product_ids: list[int] = []


class SupplierUpdate(BaseModel):
    name: str | None = None
    contact: str | None = None
    active: bool | None = None
    product_ids: list[int] | None = None


@router.get("")
async def list_suppliers(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_suppliers(user):
        return {"error": "Acesso restrito ao gerente ou estoquista"}

    query = select(Supplier).options(selectinload(Supplier.products))
    if active_only:
        query = query.where(Supplier.active == True)
    query = query.order_by(Supplier.name)
    result = await db.execute(query)
    suppliers = result.scalars().all()

    return [
        {
            "id": s.id,
            "name": s.name,
            "contact": s.contact,
            "active": s.active,
            "products": [
                {"id": p.id, "name": p.name, "category": p.category}
                for p in s.products
            ],
        }
        for s in suppliers
    ]


@router.post("")
async def create_supplier(
    req: SupplierCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_suppliers(user):
        return {"error": "Acesso restrito ao gerente ou estoquista"}

    supplier = Supplier(
        name=req.name,
        contact=req.contact,
        active=req.active,
    )

    if req.product_ids:
        result = await db.execute(select(Product).where(Product.id.in_(req.product_ids)))
        supplier.products = result.scalars().all()

    db.add(supplier)
    await db.commit()

    result = await db.execute(
        select(Supplier).where(Supplier.id == supplier.id).options(selectinload(Supplier.products))
    )
    supplier = result.scalars().first()

    return {
        "id": supplier.id,
        "name": supplier.name,
        "contact": supplier.contact,
        "active": supplier.active,
        "products": [
            {"id": p.id, "name": p.name, "category": p.category}
            for p in supplier.products
        ],
    }


@router.put("/{supplier_id}")
async def update_supplier(
    supplier_id: int,
    req: SupplierUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_suppliers(user):
        return {"error": "Acesso restrito ao gerente ou estoquista"}

    result = await db.execute(
        select(Supplier).where(Supplier.id == supplier_id).options(selectinload(Supplier.products))
    )
    supplier = result.scalars().first()
    if not supplier:
        return {"error": "Fornecedor não encontrado"}

    if req.name is not None:
        supplier.name = req.name
    if req.contact is not None:
        supplier.contact = req.contact
    if req.active is not None:
        supplier.active = req.active
    if req.product_ids is not None:
        product_result = await db.execute(select(Product).where(Product.id.in_(req.product_ids)))
        supplier.products = product_result.scalars().all()

    await db.commit()

    result = await db.execute(
        select(Supplier).where(Supplier.id == supplier.id).options(selectinload(Supplier.products))
    )
    supplier = result.scalars().first()

    return {
        "id": supplier.id,
        "name": supplier.name,
        "contact": supplier.contact,
        "active": supplier.active,
        "products": [
            {"id": p.id, "name": p.name, "category": p.category}
            for p in supplier.products
        ],
    }


@router.delete("/{supplier_id}")
async def delete_supplier(
    supplier_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_suppliers(user):
        return {"error": "Acesso restrito ao gerente ou estoquista"}

    result = await db.execute(select(Supplier).where(Supplier.id == supplier_id))
    supplier = result.scalars().first()
    if not supplier:
        return {"error": "Fornecedor não encontrado"}

    await db.delete(supplier)
    await db.commit()
    return {"message": "Fornecedor removido"}
