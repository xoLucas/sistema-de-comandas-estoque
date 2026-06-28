from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.routers.ws import broadcast_table_update
from app.models.table import Table
from app.models.product import Product
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_round import OrderRound
from app.models.user import User
from app.routers.auth_deps import get_current_user

router = APIRouter(prefix="/api", tags=["orders"])


class OpenOrderRequest(BaseModel):
    table_id: int
    customer_name: str | None = None


class OrderItemRequest(BaseModel):
    table_id: int
    product_id: int
    quantity: int = 1
    order_round_id: int | None = None


class CloseOrderRequest(BaseModel):
    table_id: int
    apply_service_charge: bool = False
    payment_method: str | None = None


class PartialPaymentRequest(BaseModel):
    table_id: int
    amount: float
    payment_method: str | None = None
    apply_service_charge: bool = False


class PedidoItem(BaseModel):
    product_id: int
    quantity: int = 1


class CreatePedidoRequest(BaseModel):
    table_id: int
    items: list[PedidoItem]


def _print_kitchen_ticket(
    table_number: int,
    round_number: int,
    prep_items: list[dict],
    waiter_name: str,
    customer_name: str | None = None,
) -> None:
    if not prep_items:
        return
    now = datetime.now().strftime("%H:%M:%S")
    print()
    print("---------------------------------")
    print("        LADS BEER - COZINHA      ")
    print("---------------------------------")
    print(f"MESA: {table_number}")
    print(f"PEDIDO: {round_number}")
    if customer_name:
        print(f"CLIENTE: {customer_name}")
    print("ITENS:")
    for p in prep_items:
        print(f"  {p['quantity']}x {p['name']}")
    print(f"HORA: {now}")
    print(f"GARÇOM: {waiter_name}")
    print("---------------------------------")
    print()


def _print_bar_ticket(
    table_number: int,
    round_number: int,
    bar_items: list[dict],
    waiter_name: str,
    customer_name: str | None = None,
) -> None:
    if not bar_items:
        return
    now = datetime.now().strftime("%H:%M:%S")
    print()
    print("=================================")
    print("         LADS BEER - BAR         ")
    print("=================================")
    print(f"MESA: {table_number}")
    print(f"PEDIDO: {round_number}")
    if customer_name:
        print(f"CLIENTE: {customer_name}")
    print("BEBIDAS:")
    for b in bar_items:
        print(f"  {b['quantity']}x {b['name']}")
    print(f"HORA: {now}")
    print(f"GARÇOM: {waiter_name}")
    print("=================================")
    print()


@router.post("/comanda/abrir")
async def open_order(
    req: OpenOrderRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Table).where(Table.id == req.table_id))
    table = result.scalars().first()

    if not table:
        return {"error": "Mesa não encontrada"}

    if table.status == "ocupada":
        return {"error": "Mesa já possui comanda aberta"}

    existing = await db.execute(
        select(Order).where(Order.table_id == req.table_id, Order.status == "aberta")
    )
    if existing.scalars().first():
        return {"error": "Já existe uma comanda aberta para esta mesa"}

    table.status = "ocupada"

    order = Order(
        table_id=req.table_id,
        waiter_id=user.id,
        customer_name=req.customer_name,
        status="aberta",
        total=0.0,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    await broadcast_table_update(req.table_id)

    return {
        "order_id": order.id,
        "table_id": table.id,
        "table_number": table.number,
        "status": order.status,
        "waiter_name": user.name,
    }


@router.post("/comanda/pedido")
async def create_pedido(
    req: CreatePedidoRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order)
        .where(Order.table_id == req.table_id, Order.status == "aberta")
        .options(selectinload(Order.rounds))
    )
    order = result.scalars().first()

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    if not req.items:
        return {"error": "Pedido deve conter ao menos 1 item"}

    round_number = len(order.rounds) + 1

    rnd = OrderRound(order_id=order.id, round_number=round_number)
    db.add(rnd)
    await db.flush()

    prep_items = []
    bar_items = []
    for entry in req.items:
        result = await db.execute(select(Product).where(Product.id == entry.product_id))
        product = result.scalars().first()
        if not product:
            continue
        if product.stock < entry.quantity:
            return {
                "error": f"Estoque insuficiente para {product.name}. Disponível: {product.stock}"
            }

        item = OrderItem(
            order_id=order.id,
            order_round_id=rnd.id,
            product_id=product.id,
            quantity=entry.quantity,
            unit_price=product.price,
        )
        db.add(item)
        product.stock -= entry.quantity

        if product.category in ("Carnes", "Acompanhamentos"):
            prep_items.append({"name": product.name, "quantity": entry.quantity})
        elif product.category == "Bebidas":
            bar_items.append({"name": product.name, "quantity": entry.quantity})

    await db.flush()

    total_result = await db.execute(
        select(func.coalesce(func.sum(OrderItem.unit_price * OrderItem.quantity), 0.0))
        .where(OrderItem.order_id == order.id)
    )
    order.total = float(total_result.scalar_one())

    table_result = await db.execute(select(Table).where(Table.id == req.table_id))
    table = table_result.scalars().first()

    await db.commit()

    if prep_items:
        _print_kitchen_ticket(
            table.number, round_number, prep_items, user.name, order.customer_name
        )

    if bar_items:
        _print_bar_ticket(
            table.number, round_number, bar_items, user.name, order.customer_name
        )

    items_out = []
    for entry in req.items:
        result = await db.execute(select(Product).where(Product.id == entry.product_id))
        product = result.scalars().first()
        if product:
            items_out.append(
                {
                    "product_id": product.id,
                    "product_name": product.name,
                    "quantity": entry.quantity,
                    "unit_price": float(product.price),
                    "category": product.category,
                }
            )

    return {
        "pedido_id": rnd.id,
        "round_number": round_number,
        "order_id": order.id,
        "total": float(order.total),
        "items": items_out,
    }


@router.post("/comanda/item")
async def add_order_item(
    req: OrderItemRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order)
        .where(Order.table_id == req.table_id, Order.status == "aberta")
        .options(selectinload(Order.items))
    )
    order = result.scalars().first()

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    result = await db.execute(select(Product).where(Product.id == req.product_id))
    product = result.scalars().first()

    if not product:
        return {"error": "Produto não encontrado"}

    if req.quantity > 0 and product.stock < req.quantity:
        return {"error": f"Estoque insuficiente. Disponível: {product.stock}"}

    existing_item = None
    for item in order.items:
        if item.product_id == req.product_id and item.order_round_id == req.order_round_id:
            existing_item = item
            break

    if req.quantity > 0:
        if existing_item:
            existing_item.quantity += req.quantity
        else:
            order_item = OrderItem(
                order_id=order.id,
                order_round_id=req.order_round_id,
                product_id=product.id,
                quantity=req.quantity,
                unit_price=product.price,
            )
            db.add(order_item)
        product.stock -= req.quantity
    else:
        qty_change = abs(req.quantity)
        if existing_item:
            if existing_item.quantity <= qty_change:
                await db.delete(existing_item)
            else:
                existing_item.quantity -= qty_change
            product.stock += qty_change
        else:
            return {"error": "Item não encontrado na comanda"}

    await db.flush()

    total_result = await db.execute(
        select(func.coalesce(func.sum(OrderItem.unit_price * OrderItem.quantity), 0.0))
        .where(OrderItem.order_id == order.id)
    )
    total = float(total_result.scalar_one())
    order.total = total

    table_result = await db.execute(select(Table).where(Table.id == req.table_id))
    table = table_result.scalars().first()

    await db.commit()
    await broadcast_table_update(req.table_id)

    if product.category in ("Carnes", "Acompanhamentos"):
        _print_kitchen_ticket(
            table.number,
            req.order_round_id or 0,
            [{"name": product.name, "quantity": abs(req.quantity)}],
            user.name,
            order.customer_name,
        )
    elif product.category == "Bebidas":
        _print_bar_ticket(
            table.number,
            req.order_round_id or 0,
            [{"name": product.name, "quantity": abs(req.quantity)}],
            user.name,
            order.customer_name,
        )

    return {
        "order_id": order.id,
        "total": float(total),
        "product": product.name,
        "quantity": req.quantity,
        "stock_remaining": product.stock,
    }


@router.post("/comanda/pagamento-parcial")
async def partial_payment(
    req: PartialPaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order).where(Order.table_id == req.table_id, Order.status == "aberta")
    )
    order = result.scalars().first()

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    if req.apply_service_charge:
        product_portion = round(req.amount / 1.10, 2)
        service_portion = round(req.amount - product_portion, 2)
    else:
        product_portion = req.amount
        service_portion = 0.0

    order.partial_payment += product_portion
    order.partial_service_charge += service_portion

    detail = order.partial_payments_detail or []
    detail.append({
        "amount": req.amount,
        "product_portion": product_portion,
        "service_portion": service_portion,
        "method": req.payment_method or "nao_informado",
        "apply_service_charge": req.apply_service_charge,
    })
    order.partial_payments_detail = detail

    await db.commit()
    await broadcast_table_update(req.table_id)

    remaining_product = max(0.0, order.total - order.partial_payment)
    return {
        "order_id": order.id,
        "partial_payment": float(order.partial_payment),
        "partial_service_charge": float(order.partial_service_charge),
        "total": float(order.total),
        "remaining": float(remaining_product),
    }


@router.post("/comanda/fechar")
async def close_order(
    req: CloseOrderRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order)
        .where(Order.table_id == req.table_id, Order.status == "aberta")
        .options(selectinload(Order.items))
    )
    order = result.scalars().first()

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    table_result = await db.execute(select(Table).where(Table.id == req.table_id))
    table = table_result.scalars().first()

    if req.apply_service_charge:
        order.service_charge_pct = 10.0
        order.service_charge_applied = True
    else:
        order.service_charge_pct = 0.0
        order.service_charge_applied = False

    service_charge_amount = order.total * (order.service_charge_pct / 100)
    remaining_product = max(0.0, order.total - order.partial_payment)
    remaining_service = max(0.0, service_charge_amount - order.partial_service_charge)
    final_total = remaining_product + remaining_service

    order.status = "finalizada"
    order.closed_at = datetime.now()
    order.payment_method = req.payment_method
    table.status = "vazia"

    await db.commit()
    await broadcast_table_update(req.table_id)

    return {
        "order_id": order.id,
        "table_id": table.id,
        "table_number": table.number,
        "total": float(order.total),
        "service_charge_pct": float(order.service_charge_pct),
        "service_charge_amount": round(float(service_charge_amount), 2),
        "partial_payment": float(order.partial_payment),
        "partial_service_charge": float(order.partial_service_charge),
        "final_total": round(float(final_total), 2),
        "payment_method": order.payment_method,
        "status": "finalizada",
    }
