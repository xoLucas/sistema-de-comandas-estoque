from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.category import Category
from app.models.product import Product
from app.models.stock_history import StockHistory
from app.models.notification import Notification
from app.models.supplier import Supplier
from app.models.user import User
from app.routers.auth_deps import get_current_user, can_manage_stock, can_view_product_cost
from app.routers.ws import broadcast_stock_update
from app.services.pricing_service import calculate_selling_price
from app.services.stock_service import is_pack, pack_stock_for_product, stock_status
from app.services.notification_service import notify_stock_alert, broadcast_stock_notification


def _build_stock_broadcast_info(product: Product) -> tuple[int, int, str]:
    """Return (product_id, stock, status) for a product, handling packs correctly."""
    if is_pack(product):
        return product.id, pack_stock_for_product(product), stock_status(product)
    return product.id, product.stock, stock_status(product)

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
    printer: str | None = None
    active: bool | None = None
    supplier_ids: list[int] | None = None
    pack_unit_product_id: int | None = None
    pack_size: int | None = None


class ProductCreate(BaseModel):
    code: str | None = None
    name: str
    category: str
    cost: float = 0.0
    margin_pct: float = 0.0
    price: float | None = None
    stock: int = 0
    min_stock: int = 10
    printer: str | None = None
    active: bool = True
    supplier_ids: list[int] = []
    pack_unit_product_id: int | None = None
    pack_size: int = 1


class StockMovementRequest(BaseModel):
    type: str  # entrada or saida
    quantity: int
    note: str | None = None


def _apply_pricing(
    product: Product,
    cost: float | None,
    margin_pct: float | None,
    price: float | None,
) -> None:
    """Apply cost/margin/price ensuring selling_price = cost / (1 - margin_pct / 100).

    If a price is explicitly provided it is respected. The formula is only used
    to recalculate the price when no price is supplied and cost/margin are set.
    """
    if cost is not None:
        product.cost = cost
    if margin_pct is not None:
        product.margin_pct = margin_pct
    if price is not None:
        product.price = price

    if (price is None or price <= 0) and product.cost > 0 and product.margin_pct >= 0:
        calculated = calculate_selling_price(product.cost, product.margin_pct)
        if calculated > 0:
            product.price = calculated


async def _notify_stock_status(db: AsyncSession, product: Product) -> Notification | None:
    return await notify_stock_alert(db, product)


async def _default_printer_for_category(
    db: AsyncSession, category: str
) -> str | None:
    category_name = (category or "").strip()
    if not category_name:
        return None
    result = await db.execute(
        select(Category.printer).where(func.lower(Category.name) == func.lower(category_name))
    )
    printer = result.scalar_one_or_none()
    if printer:
        return printer
    # Fallback heuristic while categories are being populated
    category_lower = category_name.lower()
    if any(k in category_lower for k in ("carnes", "acompanhamentos", "espetinho", "salgadinho", "cozinha")):
        return "cozinha"
    if any(
        k in category_lower
        for k in (
            "bebidas",
            "cerveja",
            "dose",
            "whisky",
            "gin",
            "vodka",
            "rum",
            "água",
            "refrigerante",
            "gelo",
            "carvão",
            "bar",
        )
    ):
        return "bar"
    return None


async def _apply_pack_stock_change(
    product: Product,
    quantity: int,
    movement_type: str,
    note: str,
    db: AsyncSession,
) -> tuple[Product, int, Notification | None]:
    """Apply stock movement to a product. For packs, adjust the linked unit product.

    Returns the product whose physical stock changed, the quantity moved, and an optional stock notification.
    """
    notification = None
    if is_pack(product):
        await db.refresh(product, ["pack_unit_product"])
        unit = product.pack_unit_product
        size = product.pack_size or 1
        unit_quantity = quantity * size

        if movement_type == "saida" and unit.stock < unit_quantity:
            raise ValueError(
                f"Estoque insuficiente no produto unitário {unit.name}. "
                f"Disponível: {unit.stock}, necessário: {unit_quantity}"
            )

        if movement_type == "entrada":
            unit.stock += unit_quantity
        else:
            unit.stock -= unit_quantity

        db.add(StockHistory(
            product_id=unit.id,
            type=movement_type,
            quantity=unit_quantity,
            note=f"{note} (engradado: {product.name}, {quantity} x {size})",
        ))
        notification = await _notify_stock_status(db, product)
        return unit, unit_quantity, notification
    else:
        if movement_type == "saida" and product.stock < quantity:
            raise ValueError(
                f"Estoque insuficiente para {product.name}. Disponível: {product.stock}"
            )

        if movement_type == "entrada":
            product.stock += quantity
        else:
            product.stock -= quantity

        db.add(StockHistory(
            product_id=product.id,
            type=movement_type,
            quantity=quantity,
            note=note,
        ))
        notification = await _notify_stock_status(db, product)
        return product, quantity, notification


def _product_to_dict(p: Product, user: User, include_suppliers: bool = False) -> dict:
    pack = is_pack(p)
    data = {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "category": p.category,
        "price": float(p.price),
        "stock": pack_stock_for_product(p) if pack else p.stock,
        "min_stock": p.min_stock,
        "printer": p.printer,
        "active": p.active,
        "is_pack": pack,
        "pack_size": p.pack_size if pack else None,
        "pack_unit_product_id": p.pack_unit_product_id,
        "pack_unit_product_name": p.pack_unit_product.name if pack and p.pack_unit_product else None,
        "status": stock_status(p),
        "pct_of_min": round((p.stock / p.min_stock * 100) if p.min_stock > 0 and not pack else 100, 1),
    }
    if pack:
        data["pct_of_min"] = round(
            (pack_stock_for_product(p) / p.min_stock * 100) if p.min_stock > 0 else 100, 1
        )
    if can_view_product_cost(user):
        data["cost"] = float(p.cost)
        data["margin_pct"] = float(p.margin_pct)
        if include_suppliers:
            data["suppliers"] = [{"id": s.id, "name": s.name} for s in p.suppliers]
    return data


@router.get("")
async def list_stock(
    category: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    sort: str = Query("name"),
    show_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Product).options(selectinload(Product.pack_unit_product))

    if category:
        query = query.where(Product.category == category)
    if search:
        query = query.where(Product.name.ilike(f"%{search}%"))
    if not show_inactive:
        query = query.where(Product.active == True)

    result = await db.execute(query)
    products = result.scalars().all()

    data = []
    for p in products:
        st = stock_status(p)
        if status and st != status:
            continue
        data.append(_product_to_dict(p, user))

    if sort == "name":
        data.sort(key=lambda x: x["name"])
    elif sort == "stock":
        data.sort(key=lambda x: x["stock"])
    elif sort == "pct":
        data.sort(key=lambda x: x["pct_of_min"])

    categories_result = await db.execute(select(Category.name).order_by(Category.name))
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
        select(Product).where(Product.id == product_id).options(
            selectinload(Product.suppliers),
            selectinload(Product.pack_unit_product),
        )
    )
    product = result.scalars().first()
    if not product:
        return {"error": "Produto não encontrado"}
    return _product_to_dict(product, user, include_suppliers=True)


@router.post("")
async def create_product(
    req: ProductCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_stock(user):
        return {"error": "Acesso não permitido"}

    category_result = await db.execute(
        select(Category).where(func.lower(Category.name) == func.lower(req.category))
    )
    category = category_result.scalar_one_or_none()
    if not category:
        return {"error": "Categoria não cadastrada"}

    if req.pack_unit_product_id is not None:
        unit_result = await db.execute(select(Product).where(Product.id == req.pack_unit_product_id))
        unit_product = unit_result.scalars().first()
        if not unit_product:
            return {"error": "Produto unitário do engradado não encontrado"}
        if unit_product.pack_unit_product_id is not None:
            return {"error": "Não é permitido vincular um engradado a outro engradado"}
        if req.pack_size < 2:
            return {"error": "Engradado deve conter pelo menos 2 unidades"}

    product_printer = req.printer
    if product_printer is None:
        product_printer = category.printer

    product = Product(
        code=req.code,
        name=req.name,
        category=category.name,
        cost=req.cost,
        margin_pct=req.margin_pct,
        price=req.price if req.price is not None else 0.0,
        stock=0,
        min_stock=req.min_stock,
        printer=product_printer,
        active=req.active,
        pack_unit_product_id=req.pack_unit_product_id,
        pack_size=req.pack_size if req.pack_unit_product_id is not None else 1,
    )
    _apply_pricing(product, req.cost, req.margin_pct, req.price)

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
        changed_product, _, notification = await _apply_pack_stock_change(product, req.stock, "entrada", "Estoque inicial", db)
        await db.commit()
        if notification:
            await broadcast_stock_notification(notification.id)
        await broadcast_stock_update(*_build_stock_broadcast_info(changed_product))
        if is_pack(product):
            await broadcast_stock_update(*_build_stock_broadcast_info(product))

    result = await db.execute(
        select(Product).where(Product.id == product.id).options(selectinload(Product.suppliers))
    )
    product = result.scalars().first()
    return _product_to_dict(product, user, include_suppliers=True)


@router.put("/{product_id}")
async def update_product(
    product_id: int,
    req: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_stock(user):
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
        category_result = await db.execute(
            select(Category).where(func.lower(Category.name) == func.lower(req.category))
        )
        category = category_result.scalar_one_or_none()
        if not category:
            return {"error": "Categoria não cadastrada"}
        product.category = category.name
        if req.printer is None:
            product.printer = category.printer
    if req.printer is not None:
        product.printer = req.printer
    _apply_pricing(product, req.cost, req.margin_pct, req.price)
    if req.min_stock is not None:
        product.min_stock = req.min_stock
    if req.active is not None:
        product.active = req.active
    if req.supplier_ids is not None:
        supplier_result = await db.execute(select(Supplier).where(Supplier.id.in_(req.supplier_ids)))
        product.suppliers = supplier_result.scalars().all()

    if req.pack_unit_product_id is not None:
        unit_result = await db.execute(select(Product).where(Product.id == req.pack_unit_product_id))
        unit_product = unit_result.scalars().first()
        if not unit_product:
            return {"error": "Produto unitário do engradado não encontrado"}
        if unit_product.id == product.id:
            return {"error": "Produto não pode ser engradado de si mesmo"}
        if unit_product.pack_unit_product_id is not None:
            return {"error": "Não é permitido vincular um engradado a outro engradado"}
        product.pack_unit_product_id = req.pack_unit_product_id
    if req.pack_size is not None:
        if is_pack(product) and req.pack_size < 2:
            return {"error": "Engradado deve conter pelo menos 2 unidades"}
        product.pack_size = req.pack_size

    stock_changed = False
    if req.stock is not None and req.stock != product.stock:
        if is_pack(product):
            return {"error": "Não é permitido alterar o estoque de um engradado diretamente. Altere o estoque do produto unitário vinculado."}
        product.stock = req.stock
        await _notify_stock_status(db, product)
        stock_changed = True

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return {"error": "Código do produto já cadastrado"}

    if stock_changed:
        await broadcast_stock_update(*_build_stock_broadcast_info(product))

    result = await db.execute(
        select(Product).where(Product.id == product.id).options(selectinload(Product.suppliers))
    )
    product = result.scalars().first()
    return _product_to_dict(product, user, include_suppliers=True)


@router.post("/{product_id}/movimentacao")
async def add_stock_movement(
    product_id: int,
    req: StockMovementRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_stock(user):
        return {"error": "Acesso não permitido"}

    if req.type not in ("entrada", "saida"):
        return {"error": "Tipo deve ser entrada ou saida"}
    if req.quantity <= 0:
        return {"error": "Quantidade deve ser maior que zero"}

    result = await db.execute(
        select(Product).where(Product.id == product_id).options(selectinload(Product.pack_unit_product))
    )
    product = result.scalars().first()
    if not product:
        return {"error": "Produto não encontrado"}

    try:
        changed_product, moved_quantity, notification = await _apply_pack_stock_change(
            product, req.quantity, req.type, req.note or "Movimentação manual", db
        )
        await db.commit()
        await db.refresh(changed_product)
        if notification:
            await broadcast_stock_notification(notification.id)
        await broadcast_stock_update(*_build_stock_broadcast_info(changed_product))
        if is_pack(product):
            await broadcast_stock_update(*_build_stock_broadcast_info(product))
    except ValueError as e:
        await db.rollback()
        return {"error": str(e)}

    result = await db.execute(
        select(Product).where(Product.id == product_id).options(selectinload(Product.suppliers))
    )
    product = result.scalars().first()

    return {
        "product": _product_to_dict(product, user, include_suppliers=True),
        "movement": {
            "type": req.type,
            "quantity": req.quantity,
            "note": req.note,
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
                "table_id": h.table_id,
                "order_id": h.order_id,
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
    if not can_manage_stock(user):
        return {"error": "Acesso não permitido"}

    updated = []
    stock_notifications = []
    products_to_broadcast = set()
    for entry in req.items:
        result = await db.execute(
            select(Product).where(Product.id == entry.product_id).options(selectinload(Product.pack_unit_product))
        )
        product = result.scalars().first()
        if not product:
            continue
        try:
            changed_product, _, notification = await _apply_pack_stock_change(
                product, entry.quantity, "entrada", "Carregamento em lote", db
            )
            products_to_broadcast.add(changed_product)
            if is_pack(product):
                products_to_broadcast.add(product)
            if notification:
                stock_notifications.append(notification)
            updated.append(
                {
                    "id": product.id,
                    "name": product.name,
                    "added": entry.quantity,
                    "new_stock": pack_stock_for_product(product) if is_pack(product) else changed_product.stock,
                }
            )
        except ValueError:
            await db.rollback()
            return {"error": f"Erro ao carregar {product.name}. Estoque insuficiente?"}

    await db.commit()

    for notification in stock_notifications:
        await broadcast_stock_notification(notification.id)

    for p in products_to_broadcast:
        await broadcast_stock_update(*_build_stock_broadcast_info(p))

    return {"message": "Carregamento realizado com sucesso", "items": updated}


@router.put("/{product_id}/min-stock")
async def update_min_stock(
    product_id: int,
    min_stock: int = Query(ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_stock(user):
        return {"error": "Acesso não permitido"}

    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalars().first()

    if not product:
        return {"error": "Produto não encontrado"}

    product.min_stock = min_stock
    notification = await _notify_stock_status(db, product)
    await db.commit()

    if notification:
        await broadcast_stock_notification(notification.id)

    await broadcast_stock_update(*_build_stock_broadcast_info(product))

    return {
        "id": product.id,
        "name": product.name,
        "min_stock": product.min_stock,
    }
