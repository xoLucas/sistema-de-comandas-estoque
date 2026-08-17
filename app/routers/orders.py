from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.routers.ws import broadcast_table_update, broadcast_stock_update
from app.services.stock_service import is_pack
from app.models.table import Table
from app.models.category import Category
from app.models.product import Product
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_round import OrderRound
from app.models.stock_history import StockHistory
from app.models.notification import Notification
from app.models.user import User
from app.models.customer import Customer
from app.models.employee import Employee
from app.models.cash_register_session import CashRegisterSession
from app.routers.auth_deps import get_current_user
from app.services.promotion_service import get_discounted_price
from app.services.settings_service import get_setting_as_float, get_setting
from app.services.stock_service import is_pack, pack_stock_for_product, stock_status
from app.services.printer_service import build_order_receipt, build_kitchen_ticket, build_bar_ticket, build_ficha_ticket, schedule_function_printer_send, get_printer_for_function
from app.services.notification_service import notify_stock_alert, broadcast_stock_notification

router = APIRouter(prefix="/api", tags=["orders"])

_PAYMENT_METHODS = {"dinheiro", "pix", "cartao_debito", "cartao_credito", "nao_informado"}
_CLOSE_PAYMENT_METHODS = _PAYMENT_METHODS | {"fiado"}


async def _require_open_cash_register(db: AsyncSession) -> CashRegisterSession | None:
    result = await db.execute(
        select(CashRegisterSession).where(CashRegisterSession.status == "open")
    )
    return result.scalar_one_or_none()


async def _notify_stock_status(db: AsyncSession, product: Product) -> Notification | None:
    return await notify_stock_alert(db, product)


def _build_stock_broadcast_info(product: Product) -> tuple[int, int, str]:
    """Return (product_id, stock, status) for a product, handling packs correctly."""
    if is_pack(product):
        return product.id, pack_stock_for_product(product), stock_status(product)
    return product.id, product.stock, stock_status(product)


async def _resolve_printer(db: AsyncSession, product: Product) -> str | None:
    if product.printer:
        return product.printer
    result = await db.execute(
        select(Category.printer).where(
            func.lower(Category.name) == func.lower(product.category)
        )
    )
    return result.scalar_one_or_none()


async def _resolve_pack_stock(
    db: AsyncSession,
    product: Product,
    requested_quantity: int,
) -> tuple[Product, int]:
    """Return the product whose physical stock should be changed and the unit quantity.

    If product is a pack, the unit product stock is used; requested_quantity is in packs.
    """
    if product.pack_unit_product_id is not None:
        result = await db.execute(
            select(Product).where(Product.id == product.pack_unit_product_id)
        )
        unit_product = result.scalars().first()
        if not unit_product:
            raise ValueError("Produto unitário do engradado não encontrado")
        size = product.pack_size or 1
        unit_quantity = requested_quantity * size
        return unit_product, unit_quantity
    return product, requested_quantity


async def _check_and_consume_stock(
    db: AsyncSession,
    product: Product,
    quantity: int,
    order_id: int,
    table_id: int,
    note: str,
) -> tuple[Product, Notification | None]:
    """Check stock availability, consume it, and write StockHistory.

    For pack products, consumes from the linked unit product.
    Returns the product whose stock was actually changed and an optional stock notification.
    """
    stock_product, unit_quantity = await _resolve_pack_stock(db, product, quantity)

    if stock_product.stock < unit_quantity:
        available_packs = (
            stock_product.stock // (product.pack_size or 1)
            if product.pack_unit_product_id
            else stock_product.stock
        )
        raise ValueError(
            f"Estoque insuficiente para {product.name}. "
            f"Disponível: {available_packs}"
        )

    stock_product.stock -= unit_quantity
    db.add(StockHistory(
        product_id=stock_product.id,
        order_id=order_id,
        table_id=table_id,
        type="saida",
        quantity=unit_quantity,
        note=note,
    ))
    notification = await _notify_stock_status(db, product)
    return stock_product, notification


async def _return_order_stock(
    db: AsyncSession,
    order_id: int,
    table_id: int,
    note: str,
) -> None:
    """Return all items from an order back to stock and write StockHistory."""
    result = await db.execute(
        select(OrderItem)
        .where(OrderItem.order_id == order_id)
        .options(selectinload(OrderItem.product))
    )
    items = result.scalars().all()

    for item in items:
        product = item.product
        if not product:
            continue
        try:
            stock_product, unit_quantity = await _resolve_pack_stock(db, product, item.quantity)
        except ValueError:
            stock_product = product
            unit_quantity = item.quantity

        stock_product.stock += unit_quantity
        db.add(StockHistory(
            product_id=stock_product.id,
            order_id=order_id,
            table_id=table_id,
            type="entrada",
            quantity=unit_quantity,
            note=note,
        ))


async def _release_pending_items(
    db: AsyncSession,
    order: Order,
    table_id: int,
    note: str,
) -> list[tuple[int, int, str]]:
    """Return stock for unconfirmed (pending) items and delete them.

    Returns (product_id, stock, status) tuples for WebSocket broadcasting.
    """
    pending_items = [item for item in order.items if item.is_pending]
    if not pending_items:
        return []

    stock_broadcast_infos = []
    for item in pending_items:
        product = item.product
        if not product:
            continue
        try:
            stock_product, unit_quantity = await _resolve_pack_stock(db, product, item.quantity)
        except ValueError:
            stock_product = product
            unit_quantity = item.quantity

        stock_product.stock += unit_quantity
        stock_broadcast_infos.append(_build_stock_broadcast_info(product))
        if is_pack(product):
            stock_broadcast_infos.append(_build_stock_broadcast_info(stock_product))
        db.add(StockHistory(
            product_id=stock_product.id,
            order_id=order.id,
            table_id=table_id,
            type="entrada",
            quantity=unit_quantity,
            note=note,
        ))
        await db.delete(item)

    return stock_broadcast_infos


async def _check_and_consume_stock_consignment(
    db: AsyncSession,
    product: Product,
    quantity: int,
    consignment_order_id: int,
    note: str,
) -> tuple[Product, Notification | None]:
    """Check stock availability, consume it, and write StockHistory for a consignment."""
    stock_product, unit_quantity = await _resolve_pack_stock(db, product, quantity)

    if stock_product.stock < unit_quantity:
        available_packs = (
            stock_product.stock // (product.pack_size or 1)
            if product.pack_unit_product_id
            else stock_product.stock
        )
        raise ValueError(
            f"Estoque insuficiente para {product.name}. "
            f"Disponível: {available_packs}"
        )

    stock_product.stock -= unit_quantity
    db.add(StockHistory(
        product_id=stock_product.id,
        consignment_order_id=consignment_order_id,
        type="saida",
        quantity=unit_quantity,
        note=note,
    ))
    notification = await _notify_stock_status(db, product)
    return stock_product, notification


async def _get_promotional_price(product: Product, db: AsyncSession) -> float:
    return await get_discounted_price(product, db)


async def _get_open_order_for_table(
    db: AsyncSession,
    table_id: int,
    order_id: int | None = None,
    options: list | None = None,
    for_update: bool = False,
) -> Order | None:
    query = select(Order).where(
        Order.table_id == table_id, Order.status == "aberta"
    )
    if order_id:
        query = query.where(Order.id == order_id)
    if options:
        for opt in options:
            query = query.options(opt)
    if for_update:
        query = query.with_for_update()
    query = query.order_by(Order.id)
    result = await db.execute(query)
    return result.scalars().first()


async def _has_open_orders(db: AsyncSession, table_id: int) -> bool:
    result = await db.execute(
        select(func.count(Order.id)).where(
            Order.table_id == table_id, Order.status == "aberta"
        )
    )
    return (result.scalar_one() or 0) > 0


class OpenOrderRequest(BaseModel):
    table_id: int
    customer_id: int | None = None
    customer_name: str | None = None


class UpdateOrderCustomerRequest(BaseModel):
    customer_id: int | None = None
    customer_name: str | None = None


class OrderItemRequest(BaseModel):
    table_id: int
    product_id: int
    quantity: int = 1
    order_round_id: int | None = None
    order_id: int | None = None


class CloseOrderRequest(BaseModel):
    table_id: int
    apply_service_charge: bool = False
    payment_method: str | None = None
    card_machine: str | None = None
    order_id: int | None = None
    amount: float | None = None
    waiter_id: int | None = None
    ficha_mode: bool = False


class PartialPaymentRequest(BaseModel):
    table_id: int
    amount: float
    payment_method: str | None = None
    card_machine: str | None = None
    apply_service_charge: bool = False
    order_id: int | None = None


class PedidoItem(BaseModel):
    product_id: int
    quantity: int = 1


class CreatePedidoRequest(BaseModel):
    table_id: int
    order_id: int | None = None
    items: list[PedidoItem]
    observation: str | None = None


class PendingOrderItemRequest(BaseModel):
    table_id: int
    order_id: int | None = None
    product_id: int
    quantity: int = 1


class PrintReceiptItem(BaseModel):
    product_name: str
    quantity: float
    unit_price: float
    subtotal: float | None = None


class PrintReceiptRequest(BaseModel):
    """Optional print-only overrides. Never persisted to the database."""
    items: list[PrintReceiptItem] | None = None
    customer_name: str | None = None
    table_label: str | None = None
    total: float | None = None
    service_charge_pct: float | None = None
    service_charge_amount: float | None = None
    partial_payment: float | None = None
    final_total: float | None = None
    payment_method: str | None = None


async def _send_kitchen_ticket(
    table_number: int,
    round_number: int,
    prep_items: list[dict],
    waiter_name: str,
    customer_name: str | None = None,
    order_id: int | None = None,
    table_id: int | None = None,
    table_label: str | None = None,
    observation: str | None = None,
) -> None:
    if not prep_items:
        return

    printer = await get_printer_for_function("cozinha")
    width = printer["width"] if printer else 32
    data = build_kitchen_ticket(
        table_number, round_number, prep_items, waiter_name, customer_name, order_id, width, observation
    )
    context = {
        "function": "cozinha",
        "failed_printer_id": printer.get("id") if printer else "",
        "failed_printer_name": printer.get("name") if printer else "",
        "order_id": order_id,
        "table_id": table_id,
        "table_number": table_number,
        "table_label": table_label or f"Mesa {table_number}",
        "round_number": round_number,
        "items": prep_items,
        "customer_name": customer_name,
        "waiter_name": waiter_name,
        "observation": observation,
    }
    schedule_function_printer_send(data, "cozinha", context)


async def _send_bar_ticket(
    table_number: int,
    round_number: int,
    bar_items: list[dict],
    waiter_name: str,
    customer_name: str | None = None,
    order_id: int | None = None,
    table_id: int | None = None,
    table_label: str | None = None,
    observation: str | None = None,
) -> None:
    if not bar_items:
        return

    printer = await get_printer_for_function("bar")
    width = printer["width"] if printer else 32
    data = build_bar_ticket(
        table_number, round_number, bar_items, waiter_name, customer_name, order_id, width, observation
    )
    context = {
        "function": "bar",
        "failed_printer_id": printer.get("id") if printer else "",
        "failed_printer_name": printer.get("name") if printer else "",
        "order_id": order_id,
        "table_id": table_id,
        "table_number": table_number,
        "table_label": table_label or f"Mesa {table_number}",
        "round_number": round_number,
        "items": bar_items,
        "customer_name": customer_name,
        "waiter_name": waiter_name,
        "observation": observation,
    }
    schedule_function_printer_send(data, "bar", context)


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

    if not table.active:
        return {"error": "Mesa arquivada"}

    if not await _require_open_cash_register(db):
        return {"error": "caixa_fechado", "detail": "O caixa está fechado. Abra o caixa para abrir a mesa."}

    if table.is_balcao:
        existing_orders_result = await db.execute(
            select(Order)
            .where(Order.table_id == req.table_id, Order.status == "aberta")
            .order_by(Order.id.desc())
            .options(selectinload(Order.items).selectinload(OrderItem.product))
        )
        existing_orders = existing_orders_result.scalars().all()

        if existing_orders:
            latest_order = existing_orders[0]
            if len(existing_orders) > 1:
                for extra_order in existing_orders[1:]:
                    for item in extra_order.items:
                        product = item.product
                        if not product:
                            continue
                        try:
                            stock_product, unit_quantity = await _resolve_pack_stock(db, product, item.quantity)
                            stock_product.stock += unit_quantity
                            db.add(StockHistory(
                                product_id=stock_product.id,
                                order_id=extra_order.id,
                                table_id=extra_order.table_id,
                                type="entrada",
                                quantity=unit_quantity,
                                note=f"Cancelamento comanda duplicada Balcão {table.number if table else extra_order.table_id}",
                            ))
                        except ValueError:
                            pass
                    extra_order.status = "cancelada"
                    extra_order.closed_at = datetime.now(timezone.utc)
                await db.commit()
                await broadcast_table_update(req.table_id)

            return {
                "order_id": latest_order.id,
                "table_id": table.id,
                "table_number": table.number,
                "status": latest_order.status,
                "waiter_name": user.name,
                "customer_id": latest_order.customer_id,
                "customer_name": latest_order.customer_name,
            }

    customer = None
    if req.customer_id:
        customer_result = await db.execute(
            select(Customer).where(Customer.id == req.customer_id)
        )
        customer = customer_result.scalars().first()

    table.status = "ocupada"

    order = Order(
        table_id=req.table_id,
        waiter_id=user.id,
        customer_id=customer.id if customer else None,
        customer_name=req.customer_name or (customer.name if customer else None),
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
        "customer_id": order.customer_id,
        "customer_name": order.customer_name,
    }


@router.post("/comanda/pedido")
async def create_pedido(
    req: CreatePedidoRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = await _get_open_order_for_table(
        db, req.table_id, req.order_id, options=[selectinload(Order.rounds)]
    )

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    if not await _require_open_cash_register(db):
        return {"error": "caixa_fechado", "detail": "O caixa está fechado. Abra o caixa para lançar pedidos."}

    if not req.items:
        return {"error": "Pedido deve conter ao menos 1 item"}

    round_number = len(order.rounds) + 1

    rnd = OrderRound(order_id=order.id, round_number=round_number, observation=req.observation)
    db.add(rnd)
    await db.flush()

    table_result = await db.execute(select(Table).where(Table.id == req.table_id))
    table = table_result.scalars().first()

    prep_items = []
    bar_items = []
    item_price_map = {}
    stock_notifications = []
    stock_broadcast_infos = []
    for entry in req.items:
        result = await db.execute(select(Product).where(Product.id == entry.product_id))
        product = result.scalars().first()
        if not product:
            continue
        unit_price = await _get_promotional_price(product, db)
        item_price_map[product.id] = unit_price

        try:
            stock_product, notification = await _check_and_consume_stock(
                db,
                product,
                entry.quantity,
                order.id,
                req.table_id,
                f"Pedido mesa {table.number if table else req.table_id}",
            )
        except ValueError as e:
            return {"error": str(e)}

        stock_broadcast_infos.append(_build_stock_broadcast_info(product))
        if is_pack(product):
            stock_broadcast_infos.append(_build_stock_broadcast_info(stock_product))

        if notification:
            stock_notifications.append(notification)

        item = OrderItem(
            order_id=order.id,
            order_round_id=rnd.id,
            product_id=product.id,
            quantity=entry.quantity,
            unit_price=unit_price,
            unit_cost=float(product.cost) if product.cost is not None else 0.0,
        )
        db.add(item)

        printer = await _resolve_printer(db, product)

        if printer == "cozinha":
            prep_items.append({"name": product.name, "quantity": entry.quantity})
        elif printer == "bar":
            bar_items.append({"name": product.name, "quantity": entry.quantity})

    await db.flush()

    total_result = await db.execute(
        select(func.coalesce(func.sum(OrderItem.unit_price * OrderItem.quantity), 0.0))
        .where(OrderItem.order_id == order.id, OrderItem.is_pending == False)
    )
    order.total = float(total_result.scalar_one())

    await db.commit()

    for notification in stock_notifications:
        await broadcast_stock_notification(notification.id)

    for product_id, stock, status in stock_broadcast_infos:
        await broadcast_stock_update(product_id, stock, status)

    table_label = "Balcão" if table.is_balcao else f"Mesa {table.number}"

    if not table.is_balcao:
        if prep_items:
            await _send_kitchen_ticket(
                table.number, round_number, prep_items, user.name, order.customer_name, order.id, table.id, table_label, req.observation
            )

        if bar_items:
            await _send_bar_ticket(
                table.number, round_number, bar_items, user.name, order.customer_name, order.id, table.id, table_label, req.observation
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
                    "unit_price": float(item_price_map.get(product.id, product.price)),
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
    order = await _get_open_order_for_table(
        db, req.table_id, req.order_id, options=[selectinload(Order.items)]
    )

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    if not await _require_open_cash_register(db):
        return {"error": "caixa_fechado", "detail": "O caixa está fechado. Abra o caixa para lançar pedidos."}

    result = await db.execute(select(Product).where(Product.id == req.product_id))
    product = result.scalars().first()

    if not product:
        return {"error": "Produto não encontrado"}

    table_result = await db.execute(select(Table).where(Table.id == req.table_id))
    table = table_result.scalars().first()

    unit_price = await _get_promotional_price(product, db)

    existing_item = None
    for item in order.items:
        if item.product_id == req.product_id and item.order_round_id == req.order_round_id:
            existing_item = item
            break

    stock_notification = None
    stock_broadcast_infos = []
    if req.quantity > 0:
        try:
            stock_product, stock_notification = await _check_and_consume_stock(
                db,
                product,
                req.quantity,
                order.id,
                req.table_id,
                f"Pedido mesa {table.number if table else req.table_id}",
            )
            stock_broadcast_infos.append(_build_stock_broadcast_info(product))
            if is_pack(product):
                stock_broadcast_infos.append(_build_stock_broadcast_info(stock_product))
        except ValueError as e:
            return {"error": str(e)}

        if existing_item:
            existing_item.quantity += req.quantity
            existing_item.unit_price = unit_price
            if existing_item.unit_cost is None:
                existing_item.unit_cost = float(product.cost) if product.cost is not None else 0.0
        else:
            order_item = OrderItem(
                order_id=order.id,
                order_round_id=req.order_round_id,
                product_id=product.id,
                quantity=req.quantity,
                unit_price=unit_price,
                unit_cost=float(product.cost) if product.cost is not None else 0.0,
            )
            db.add(order_item)
    else:
        qty_change = abs(req.quantity)
        if not existing_item:
            return {"error": "Item não encontrado na comanda"}

        if existing_item.quantity <= qty_change:
            await db.delete(existing_item)
        else:
            existing_item.quantity -= qty_change

        try:
            stock_product, unit_quantity = await _resolve_pack_stock(db, product, qty_change)
            stock_product.stock += unit_quantity
            stock_broadcast_infos.append(_build_stock_broadcast_info(product))
            if is_pack(product):
                stock_broadcast_infos.append(_build_stock_broadcast_info(stock_product))
            db.add(StockHistory(
                product_id=stock_product.id,
                order_id=order.id,
                table_id=req.table_id,
                type="entrada",
                quantity=unit_quantity,
                note=f"Cancelamento/ajuste mesa {table.number if table else req.table_id}",
            ))
        except ValueError as e:
            return {"error": str(e)}

    await db.flush()

    total_result = await db.execute(
        select(func.coalesce(func.sum(OrderItem.unit_price * OrderItem.quantity), 0.0))
        .where(OrderItem.order_id == order.id, OrderItem.is_pending == False)
    )
    total = float(total_result.scalar_one())
    order.total = total

    await db.commit()
    await broadcast_table_update(req.table_id)

    if stock_notification:
        await broadcast_stock_notification(stock_notification.id)

    for product_id, stock, status in stock_broadcast_infos:
        await broadcast_stock_update(product_id, stock, status)

    table_label = "Balcão" if table and table.is_balcao else f"Mesa {table.number if table else req.table_id}"

    if not table.is_balcao and req.quantity > 0:
        printer = await _resolve_printer(db, product)

        if printer == "cozinha":
            await _send_kitchen_ticket(
                table.number if table else req.table_id,
                req.order_round_id or 0,
                [{"name": product.name, "quantity": abs(req.quantity)}],
                user.name,
                order.customer_name,
                order.id,
                table.id if table else None,
                table_label,
            )
        elif printer == "bar":
            await _send_bar_ticket(
                table.number if table else req.table_id,
                req.order_round_id or 0,
                [{"name": product.name, "quantity": abs(req.quantity)}],
                user.name,
                order.customer_name,
                order.id,
                table.id if table else None,
                table_label,
            )

    try:
        stock_product, _ = await _resolve_pack_stock(db, product, abs(req.quantity))
    except ValueError:
        stock_product = product

    fresh_product_result = await db.execute(select(Product).where(Product.id == product.id))
    fresh_product = fresh_product_result.scalars().first()
    stock_remaining = fresh_product.stock if fresh_product else product.stock

    return {
        "order_id": order.id,
        "total": float(total),
        "product": product.name,
        "quantity": req.quantity,
        "stock_remaining": stock_remaining,
    }


@router.post("/comanda/pagamento-parcial")
async def partial_payment(
    req: PartialPaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if req.amount <= 0:
        return {"error": "O valor do pagamento deve ser maior que zero"}

    method = req.payment_method or "nao_informado"
    if method not in _PAYMENT_METHODS:
        return {"error": "Forma de pagamento inválida"}

    open_session = await _require_open_cash_register(db)
    if not open_session:
        return {"error": "Não há caixa aberto para receber pagamentos"}

    order = await _get_open_order_for_table(
        db, req.table_id, req.order_id, for_update=True
    )

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    remaining_product = max(0.0, order.total - order.partial_payment)

    if req.apply_service_charge:
        service_charge_pct = await get_setting_as_float(db, "service_charge_pct", 10.0)
        divisor = 1 + (service_charge_pct / 100)
        product_portion = round(req.amount / divisor, 2)
        service_portion = round(req.amount - product_portion, 2)
    else:
        product_portion = req.amount
        service_portion = 0.0

    if product_portion > remaining_product:
        return {"error": "O pagamento excede o valor restante da comanda"}

    order.partial_payment += product_portion
    order.partial_service_charge += service_portion

    detail = list(order.partial_payments_detail or [])
    detail.append({
        "amount": req.amount,
        "product_portion": product_portion,
        "service_portion": service_portion,
        "method": method,
        "card_machine": req.card_machine,
        "apply_service_charge": req.apply_service_charge,
        "created_at": datetime.now(timezone.utc).isoformat(),
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
    order = await _get_open_order_for_table(
        db, req.table_id, req.order_id, options=[
            selectinload(Order.table),
            selectinload(Order.items).selectinload(OrderItem.product),
        ]
    )

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    table_result = await db.execute(select(Table).where(Table.id == req.table_id))
    table = table_result.scalars().first()

    service_charge_pct = await get_setting_as_float(db, "service_charge_pct", 10.0)
    if req.apply_service_charge:
        order.service_charge_pct = service_charge_pct
        order.service_charge_applied = True
    else:
        order.service_charge_pct = 0.0
        order.service_charge_applied = False

    remaining_product = max(0.0, order.total - order.partial_payment)
    service_charge_amount = remaining_product * (order.service_charge_pct / 100)
    remaining_service = max(0.0, service_charge_amount)
    final_total = remaining_product + remaining_service

    close_method = req.payment_method or "nao_informado"
    if close_method not in _CLOSE_PAYMENT_METHODS:
        return {"error": "Forma de pagamento inválida"}

    if close_method == "dinheiro":
        if req.amount is None:
            return {"error": "Informe o valor pago"}
        if req.amount < final_total:
            return {"error": f"Valor pago (R$ {req.amount:.2f}) é menor que o total final (R$ {final_total:.2f})"}

    table_label = "Balcão" if table and table.is_balcao else f"Mesa {table.number if table else req.table_id}"
    stock_broadcast_infos = await _release_pending_items(
        db,
        order,
        req.table_id,
        f"Cancelamento itens pendentes no fechamento da {table_label}",
    )

    order.status = "finalizada"
    order.closed_at = datetime.now(timezone.utc)
    order.payment_method = close_method
    order.card_machine = req.card_machine
    order.closed_by_id = user.id
    order.service_charge_amount = round(order.partial_service_charge + remaining_service, 2)

    if req.waiter_id is not None and user.role == "gerente":
        employee_result = await db.execute(select(Employee).where(Employee.id == req.waiter_id))
        employee = employee_result.scalars().first()
        if not employee:
            return {"error": "Funcionário não encontrado"}
        order.closed_waiter_id = employee.id

    await db.flush()
    if not await _has_open_orders(db, req.table_id):
        if table:
            table.status = "vazia"

    await db.commit()

    for product_id, stock, status in stock_broadcast_infos:
        await broadcast_stock_update(product_id, stock, status)

    if table.is_balcao:
        receipt_result = None
        try:
            if req.ficha_mode:
                receipt_result = await _print_ficha_tickets(db, order)
            else:
                receipt_result = await _print_order_receipt(db, order, user, PrintReceiptRequest(payment_method=req.payment_method))
        except Exception as exc:
            import traceback
            print("ERRO AO IMPRIMIR NOTA DO BALCAO:", exc)
            traceback.print_exc()
            receipt_result = {"error": str(exc)}

    await broadcast_table_update(req.table_id)

    response = {
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
        "customer_id": order.customer_id,
        "customer_name": order.customer_name,
    }
    if table.is_balcao:
        response["receipt_result"] = receipt_result
    return response


@router.post("/comanda/{order_id}/cancelar")
async def cancel_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order_result = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
    )
    order = order_result.scalars().first()

    if not order:
        return {"error": "Comanda não encontrada"}

    if order.status != "aberta":
        return {"error": "Apenas comandas abertas podem ser canceladas"}

    table_result = await db.execute(select(Table).where(Table.id == order.table_id))
    table = table_result.scalars().first()

    stock_broadcast_infos = []
    for item in order.items:
        product = item.product
        if not product:
            continue
        try:
            stock_product, unit_quantity = await _resolve_pack_stock(db, product, item.quantity)
            stock_product.stock += unit_quantity
            stock_broadcast_infos.append(_build_stock_broadcast_info(product))
            if is_pack(product):
                stock_broadcast_infos.append(_build_stock_broadcast_info(stock_product))
            db.add(StockHistory(
                product_id=stock_product.id,
                order_id=order.id,
                table_id=order.table_id,
                type="entrada",
                quantity=unit_quantity,
                note=f"Cancelamento comanda {table.number if table else order.table_id}",
            ))
        except ValueError as e:
            return {"error": str(e)}

    order.status = "cancelada"
    order.closed_at = datetime.now(timezone.utc)

    await db.flush()
    if table and not await _has_open_orders(db, table.id):
        table.status = "vazia"

    await db.commit()
    await broadcast_table_update(order.table_id)

    for product_id, stock, status in stock_broadcast_infos:
        await broadcast_stock_update(product_id, stock, status)

    return {"order_id": order.id, "status": "cancelada", "table_id": order.table_id}


@router.post("/comanda/{order_id}/cliente")
async def update_order_customer(
    order_id: int,
    req: UpdateOrderCustomerRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order_result = await db.execute(
        select(Order).where(Order.id == order_id)
    )
    order = order_result.scalars().first()

    if not order:
        return {"error": "Comanda não encontrada"}

    if order.status != "aberta":
        return {"error": "Apenas comandas abertas podem ter o cliente alterado"}

    customer = None
    if req.customer_id:
        customer_result = await db.execute(
            select(Customer).where(Customer.id == req.customer_id)
        )
        customer = customer_result.scalars().first()

    order.customer_id = customer.id if customer else None
    order.customer_name = req.customer_name or (customer.name if customer else None)

    await db.commit()
    await broadcast_table_update(order.table_id)

    return {
        "order_id": order.id,
        "customer_id": order.customer_id,
        "customer_name": order.customer_name,
    }


async def _print_ficha_tickets(db: AsyncSession, order: Order) -> dict:
    """Print one ficha per item unit (ficha mode), each with a paper cut."""
    store_name = await get_setting(db, "store_name", "Lads Beer")
    nota_printer = await get_printer_for_function("nota")
    printer_width = nota_printer["width"] if nota_printer else 32

    tickets = bytearray()
    ficha_count = 0
    for item in order.items:
        product_name = item.product.name if item.product else "Item"
        for _ in range(item.quantity):
            tickets.extend(build_ficha_ticket(store_name, product_name, printer_width))
            ficha_count += 1

    if ficha_count == 0:
        return {"error": "Nenhum item para imprimir"}

    context = {
        "function": "nota",
        "failed_printer_id": nota_printer.get("id") if nota_printer else "",
        "failed_printer_name": nota_printer.get("name") if nota_printer else "",
        "order_id": order.id,
        "table_id": order.table_id,
        "table_number": 0,
        "table_label": "Balcão",
        "items": [{"name": item.product.name if item.product else "Item", "quantity": item.quantity} for item in order.items],
        "waiter_name": "Balcão",
        "ficha_mode": True,
    }
    schedule_function_printer_send(bytes(tickets), "nota", context)

    if nota_printer:
        return {"success": True, "message": f"{ficha_count} ficha(s) enviada(s) para {nota_printer.get('name', 'impressora')}"}
    return {"success": True, "message": f"{ficha_count} ficha(s) exibida(s) no terminal (nenhuma impressora configurada)"}


async def _print_order_receipt(
    db: AsyncSession,
    order: Order,
    user: User,
    req: PrintReceiptRequest | None = None,
) -> dict:
    """Print receipt. Optional body overrides are print-only and never saved."""
    req = req or PrintReceiptRequest()

    if req.items is not None:
        items = []
        for item in req.items:
            qty = float(item.quantity)
            unit = float(item.unit_price)
            subtotal = float(item.subtotal) if item.subtotal is not None else round(qty * unit, 2)
            if qty <= 0:
                continue
            items.append({
                "product_name": item.product_name.strip() or "Item",
                "quantity": qty,
                "unit_price": unit,
                "subtotal": subtotal,
            })
    else:
        items = []
        for item in order.items:
            items.append({
                "product_name": item.product.name if item.product else "Produto",
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "subtotal": float(item.unit_price * item.quantity),
            })

    if not items:
        return {"error": "A nota precisa ter ao menos 1 item para imprimir"}

    default_total = float(order.total)
    default_partial = float(order.partial_payment)
    default_service_pct = float(order.service_charge_pct)
    remaining_product = max(0.0, default_total - default_partial)
    default_service_amount = remaining_product * (default_service_pct / 100)
    default_final = remaining_product + default_service_amount
    default_table_label = (
        f"Mesa {order.table.number}"
        if order.table and not order.table.is_balcao
        else "Balcão"
    )

    if req.items is not None and req.total is None:
        computed_total = round(sum(i["subtotal"] for i in items), 2)
    else:
        computed_total = float(req.total) if req.total is not None else default_total

    partial_payment = float(req.partial_payment) if req.partial_payment is not None else default_partial
    service_charge_pct = (
        float(req.service_charge_pct) if req.service_charge_pct is not None else default_service_pct
    )

    if req.service_charge_amount is not None:
        service_charge_amount = float(req.service_charge_amount)
    elif req.items is not None or req.total is not None:
        remaining = max(0.0, computed_total - partial_payment)
        service_charge_amount = round(remaining * (service_charge_pct / 100), 2) if service_charge_pct > 0 else 0.0
    else:
        service_charge_amount = round(float(default_service_amount), 2)

    if req.final_total is not None:
        final_total = float(req.final_total)
    else:
        remaining = max(0.0, computed_total - partial_payment)
        final_total = round(remaining + service_charge_amount, 2)

    order_data = {
        "order_id": order.id,
        "table_label": req.table_label if req.table_label is not None else default_table_label,
        "customer_name": req.customer_name if req.customer_name is not None else order.customer_name,
        "items": items,
        "total": computed_total,
        "service_charge_pct": service_charge_pct,
        "service_charge_amount": round(service_charge_amount, 2),
        "partial_payment": partial_payment,
        "final_total": round(final_total, 2),
        "payment_method": req.payment_method if req.payment_method is not None else order.payment_method,
    }

    store_info = {
        "name": await get_setting(db, "store_name", "Lads Beer"),
        "address": await get_setting(db, "store_address", ""),
        "phone": await get_setting(db, "store_phone", ""),
        "cnpj": await get_setting(db, "store_cnpj", ""),
        "ticket_footer": await get_setting(db, "ticket_footer", "Obrigado pela preferência!"),
    }

    nota_printer = await get_printer_for_function("nota")
    printer_width = nota_printer["width"] if nota_printer else 32

    receipt_bytes = build_order_receipt(order_data, store_info, printer_width)

    nota_context = {
        "function": "nota",
        "failed_printer_id": nota_printer.get("id") if nota_printer else "",
        "failed_printer_name": nota_printer.get("name") if nota_printer else "",
        "order_id": order.id,
        "table_id": order.table_id,
        "table_number": order.table.number if order.table else None,
        "table_label": order_data["table_label"],
        "round_number": None,
        "items": items,
        "customer_name": order_data.get("customer_name"),
        "waiter_name": user.name,
        "total": order_data["total"],
        "service_charge_pct": order_data["service_charge_pct"],
        "service_charge_amount": order_data["service_charge_amount"],
        "partial_payment": order_data["partial_payment"],
        "final_total": order_data["final_total"],
        "payment_method": order_data.get("payment_method") or "",
    }
    schedule_function_printer_send(receipt_bytes, "nota", nota_context)

    if nota_printer:
        return {"success": True, "message": f"Nota enviada para {nota_printer.get('name', 'impressora')}"}
    return {"success": True, "message": "Nota exibida no terminal (nenhuma impressora configurada)"}


@router.post("/comanda/{order_id}/imprimir-nota")
async def print_order_receipt(
    order_id: int,
    req: PrintReceiptRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Print receipt. Optional body overrides are print-only and never saved."""
    result = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.table),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
    )
    order = result.scalars().first()

    if not order:
        return {"error": "Comanda não encontrada"}

    return await _print_order_receipt(db, order, user, req)


# ====== PENDING ORDER (RESERVA TEMPORÁRIA) ======
class PendingOrderActionRequest(BaseModel):
    table_id: int
    order_id: int | None = None
    observation: str | None = None


@router.post("/pedido-pendente/item")
async def add_pending_order_item(
    req: PendingOrderItemRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add/remove a pending item. Consumes or returns stock immediately but does not print."""
    order = await _get_open_order_for_table(
        db, req.table_id, req.order_id, options=[selectinload(Order.items)]
    )
    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    if not await _require_open_cash_register(db):
        return {"error": "caixa_fechado", "detail": "O caixa está fechado. Abra o caixa para lançar pedidos."}

    result = await db.execute(select(Product).where(Product.id == req.product_id))
    product = result.scalars().first()
    if not product:
        return {"error": "Produto não encontrado"}

    table_result = await db.execute(select(Table).where(Table.id == req.table_id))
    table = table_result.scalars().first()

    unit_price = await _get_promotional_price(product, db)

    existing_item = None
    for item in order.items:
        if item.product_id == req.product_id and item.is_pending:
            existing_item = item
            break

    stock_broadcast_infos = []
    stock_notification = None

    if req.quantity > 0:
        try:
            stock_product, stock_notification = await _check_and_consume_stock(
                db,
                product,
                req.quantity,
                order.id,
                req.table_id,
                f"Reserva pedido mesa {table.number if table else req.table_id}",
            )
        except ValueError as e:
            return {"error": str(e)}

        stock_broadcast_infos.append(_build_stock_broadcast_info(product))
        if is_pack(product):
            stock_broadcast_infos.append(_build_stock_broadcast_info(stock_product))

        if existing_item:
            existing_item.quantity += req.quantity
            existing_item.unit_price = unit_price
            if existing_item.unit_cost is None:
                existing_item.unit_cost = float(product.cost) if product.cost is not None else 0.0
        else:
            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=req.quantity,
                unit_price=unit_price,
                unit_cost=float(product.cost) if product.cost is not None else 0.0,
                is_pending=True,
            )
            db.add(order_item)
    else:
        qty_change = abs(req.quantity)
        if not existing_item:
            return {"error": "Item não encontrado no pedido pendente"}

        if existing_item.quantity <= qty_change:
            await db.delete(existing_item)
        else:
            existing_item.quantity -= qty_change

        try:
            stock_product, unit_quantity = await _resolve_pack_stock(db, product, qty_change)
            stock_product.stock += unit_quantity
            stock_broadcast_infos.append(_build_stock_broadcast_info(product))
            if is_pack(product):
                stock_broadcast_infos.append(_build_stock_broadcast_info(stock_product))
            db.add(StockHistory(
                product_id=stock_product.id,
                order_id=order.id,
                table_id=req.table_id,
                type="entrada",
                quantity=unit_quantity,
                note=f"Cancelamento reserva mesa {table.number if table else req.table_id}",
            ))
        except ValueError as e:
            return {"error": str(e)}

    await db.commit()

    if stock_notification:
        await broadcast_stock_notification(stock_notification.id)

    for product_id, stock, status in stock_broadcast_infos:
        await broadcast_stock_update(product_id, stock, status)

    return {
        "product_id": product.id,
        "product_name": product.name,
        "quantity": req.quantity,
        "stock_remaining": _build_stock_broadcast_info(product)[1],
    }


@router.post("/pedido-pendente/confirmar")
async def confirm_pending_order(
    req: PendingOrderActionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Confirm all pending items: attach to a round, update order total and print."""
    order = await _get_open_order_for_table(
        db,
        req.table_id,
        req.order_id,
        options=[
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.rounds),
            selectinload(Order.table),
        ],
    )
    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    pending_items = [item for item in order.items if item.is_pending]
    if not pending_items:
        return {"error": "Nenhum item pendente para confirmar"}

    round_number = len(order.rounds) + 1
    rnd = OrderRound(order_id=order.id, round_number=round_number, observation=req.observation)
    db.add(rnd)
    await db.flush()

    prep_items = []
    bar_items = []
    confirmed_items = []

    for item in pending_items:
        item.is_pending = False
        item.order_round_id = rnd.id
        confirmed_items.append({
            "product_id": item.product_id,
            "product_name": item.product.name,
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
        })

        printer = await _resolve_printer(db, item.product)
        if printer == "cozinha":
            prep_items.append({"name": item.product.name, "quantity": item.quantity})
        elif printer == "bar":
            bar_items.append({"name": item.product.name, "quantity": item.quantity})

    total_result = await db.execute(
        select(func.coalesce(func.sum(OrderItem.unit_price * OrderItem.quantity), 0.0))
        .where(OrderItem.order_id == order.id, OrderItem.is_pending == False)
    )
    order.total = float(total_result.scalar_one())

    await db.commit()
    await broadcast_table_update(req.table_id)

    table_label = "Balcão" if order.table and order.table.is_balcao else f"Mesa {order.table.number if order.table else req.table_id}"

    if not order.table or not order.table.is_balcao:
        if prep_items:
            await _send_kitchen_ticket(
                order.table.number if order.table else req.table_id,
                round_number,
                prep_items,
                user.name,
                order.customer_name,
                order.id,
                req.table_id,
                table_label,
                req.observation,
            )
        if bar_items:
            await _send_bar_ticket(
                order.table.number if order.table else req.table_id,
                round_number,
                bar_items,
                user.name,
                order.customer_name,
                order.id,
                req.table_id,
                table_label,
                req.observation,
            )

    return {
        "round_number": round_number,
        "order_id": order.id,
        "total": order.total,
        "items": confirmed_items,
    }


@router.post("/pedido-pendente/cancelar")
async def cancel_pending_order(
    req: PendingOrderActionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Cancel all pending items and return stock."""
    order = await _get_open_order_for_table(
        db,
        req.table_id,
        req.order_id,
        options=[selectinload(Order.items).selectinload(OrderItem.product), selectinload(Order.table)],
    )
    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    pending_items = [item for item in order.items if item.is_pending]
    if not pending_items:
        return {"success": True, "message": "Nenhum item pendente para cancelar"}

    stock_broadcast_infos = []
    for item in pending_items:
        product = item.product
        try:
            stock_product, unit_quantity = await _resolve_pack_stock(db, product, item.quantity)
        except ValueError:
            stock_product = product
            unit_quantity = item.quantity

        stock_product.stock += unit_quantity
        stock_broadcast_infos.append(_build_stock_broadcast_info(product))
        if is_pack(product):
            stock_broadcast_infos.append(_build_stock_broadcast_info(stock_product))
        db.add(StockHistory(
            product_id=stock_product.id,
            order_id=order.id,
            table_id=req.table_id,
            type="entrada",
            quantity=unit_quantity,
            note=f"Cancelamento pedido pendente mesa {order.table.number if order.table else req.table_id}",
        ))
        await db.delete(item)

    await db.commit()

    for product_id, stock, status in stock_broadcast_infos:
        await broadcast_stock_update(product_id, stock, status)

    return {"success": True, "message": "Pedido pendente cancelado e estoque devolvido"}


@router.get("/comanda/{order_id}/pendentes")
async def get_pending_order_items(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return pending items for an open order."""
    result = await db.execute(
        select(Order)
        .where(Order.id == order_id, Order.status == "aberta")
        .options(selectinload(Order.items).selectinload(OrderItem.product))
    )
    order = result.scalars().first()
    if not order:
        return {"error": "Comanda não encontrada"}

    pending_items = [item for item in order.items if item.is_pending]
    return {
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product.name,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "category": item.product.category,
            }
            for item in pending_items
        ]
    }
