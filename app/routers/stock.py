from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.product import Product
from app.models.stock_history import StockHistory
from app.models.supplier import Supplier
from app.models.user import User
from app.routers.auth_deps import get_current_user

router = APIRouter(prefix="/api/estoque", tags=["estoque"])


class StockBatchItem(BaseModel):
    product_id: int
    quantity: int


class StockBatchRequest(BaseModel):
    items: list[StockBatchItem]


class ProductUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    category: str | None = None
    cost: float | None = None
    margin_pct: float | None = None
    price: float | None = None
    stock: int | None = None
    min_stock: int | None = None
    active: bool | None = None
    supplier_ids: list[int] | None = None


class ProductCreate(BaseModel):
    code: str | None = None
    name: str
    category: str
    cost: float = 0.0
    margin_pct: float = 0.0
    price: float
    stock: int = 0
    min_stock: int = 10
    active: bool = True
    supplier_ids: list[int] = []


class StockMovementRequest(BaseModel):
    type: str  # entrada or saida
    quantity: int
    note: str | None = None


def _stock_status(product: Product) -> str:
    if product.stock <= 2:
        return "em_falta"
    elif product.stock <= product.min_stock:
        return "em_risco"
    else:
        return "em_conformidade"


def _product_to_dict(p: Product, include_suppliers: bool = False) -> dict:
    data = {
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
        "status": _stock_status(p),
        "pct_of_min": round((p.stock / p.min_stock * 100) if p.min_stock > 0 else 100, 1),
    }
    if include_suppliers:
        data["suppliers"] = [{"id": s.id, "name": s.name} for s in p.suppliers]
    return data


@router.get("")
async def list_stock(
    category: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("name"),
    show_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Product)

    if category:
        query = query.where(Product.category == category)
    if not show_inactive:
        query = query.where(Product.active == True)

    result = await db.execute(query)
    products = result.scalars().all()

    data = []
    for p in products:
        st = _stock_status(p)
        if status and st != status:
            continue
        data.append(_product_to_dict(p))

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


@router.get("/{product_id}")
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
    return _product_to_dict(product)


@router.post("")
async def create_product(
    req: ProductCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("estoquista", "gerente"):
        return {"error": "Acesso não permitido"}

    product = Product(
        code=req.code,
        name=req.name,
        category=req.category,
        cost=req.cost,
        margin_pct=req.margin_pct,
        price=req.price,
        stock=req.stock,
        min_stock=req.min_stock,
        active=req.active,
    )
    if req.supplier_ids:
        supplier_result = await db.execute(select(Supplier).where(Supplier.id.in_(req.supplier_ids)))
        product.suppliers = supplier_result.scalars().all()

    db.add(product)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {"error": "Código do produto já cadastrado"}

    if req.stock > 0:
        db.add(StockHistory(product_id=product.id, type="entrada", quantity=req.stock, note="Estoque inicial"))
        await db.commit()

    result = await db.execute(
        select(Product).where(Product.id == product.id).options(selectinload(Product.suppliers))
    )
    product = result.scalars().first()
    return _product_to_dict(product, include_suppliers=True)


@router.put("/{product_id}")
async def update_product(
    product_id: int,
    req: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("estoquista", "gerente"):
        return {"error": "Acesso não permitido"}

    result = await db.execute(
        select(Product).where(Product.id == product_id).options(selectinload(Product.suppliers))
    )
    product = result.scalars().first()
    if not product:
        return {"error": "Produto não encontrado"}

    if req.code is not None:
        product.code = req.code or None
    if req.name is not None:
        product.name = req.name
    if req.category is not None:
        product.category = req.category
    if req.cost is not None:
        product.cost = req.cost
    if req.margin_pct is not None:
        product.margin_pct = req.margin_pct
    if req.price is not None:
        product.price = req.price
    if req.stock is not None:
        product.stock = req.stock
    if req.min_stock is not None:
        product.min_stock = req.min_stock
    if req.active is not None:
        product.active = req.active
    if req.supplier_ids is not None:
        supplier_result = await db.execute(select(Supplier).where(Supplier.id.in_(req.supplier_ids)))
        product.suppliers = supplier_result.scalars().all()

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {"error": "Código do produto já cadastrado"}

    result = await db.execute(
        select(Product).where(Product.id == product.id).options(selectinload(Product.suppliers))
    )
    product = result.scalars().first()
    return _product_to_dict(product, include_suppliers=True)


@router.post("/{product_id}/movimentacao")
async def add_stock_movement(
    product_id: int,
    req: StockMovementRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("estoquista", "gerente", "caixa"):
        return {"error": "Acesso não permitido"}

    if req.type not in ("entrada", "saida"):
        return {"error": "Tipo deve ser entrada ou saida"}
    if req.quantity <= 0:
        return {"error": "Quantidade deve ser maior que zero"}

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalars().first()
    if not product:
        return {"error": "Produto não encontrado"}

    if req.type == "saida" and product.stock < req.quantity:
        return {"error": "Estoque insuficiente"}

    if req.type == "entrada":
        product.stock += req.quantity
    else:
        product.stock -= req.quantity

    history = StockHistory(
        product_id=product.id,
        type=req.type,
        quantity=req.quantity,
        note=req.note,
    )
    db.add(history)
    await db.commit()
    await db.refresh(product)

    result = await db.execute(
        select(Product).where(Product.id == product.id).options(selectinload(Product.suppliers))
    )
    product = result.scalars().first()

    return {
        "product": _product_to_dict(product, include_suppliers=True),
        "movement": {
            "id": history.id,
            "type": history.type,
            "quantity": history.quantity,
            "note": history.note,
            "created_at": history.created_at.isoformat() if history.created_at else None,
        },
    }


@router.get("/{product_id}/historico")
async def get_stock_history(
    product_id: int,
    type_filter: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )
    product = result.scalars().first()
    if not product:
        return {"error": "Produto não encontrado"}

    query = select(StockHistory).where(StockHistory.product_id == product_id)
    if type_filter in ("entrada", "saida"):
        query = query.where(StockHistory.type == type_filter)
    query = query.order_by(StockHistory.created_at.desc())

    result = await db.execute(query)
    history = result.scalars().all()

    return {
        "product_id": product_id,
        "items": [
            {
                "id": h.id,
                "type": h.type,
                "quantity": h.quantity,
                "note": h.note,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in history
        ],
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
            db.add(StockHistory(
                product_id=product.id,
                type="entrada",
                quantity=entry.quantity,
                note="Carregamento em lote",
            ))
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
