from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
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
from app.models.payment import OrderPayment, OrderPaymentAllocation
from app.routers.auth_deps import get_current_user
from app.services.promotion_service import get_discounted_price
from app.services.settings_service import get_setting_as_float, get_setting
from app.services.stock_service import (
    is_pack,
    pack_stock_for_product,
    stock_status,
    validate_pack_configuration,
)
from app.services.printer_service import build_order_receipt, build_kitchen_ticket, build_bar_ticket, build_ficha_ticket, schedule_function_printer_send, get_printer_for_function
from app.services.notification_service import notify_stock_alert, broadcast_stock_notification
from app.services.money_service import ZERO, as_float, decimal_value, money, percentage_amount, rate
from app.services.payment_service import (
    create_order_payment,
    distribute_service_amount,
    item_net_paid_quantity,
    order_net_paid,
)
from app.services.refund_service import refund_full_order, refund_paid_items

router = APIRouter(prefix="/api", tags=["orders"])

_PAYMENT_METHODS = {"dinheiro", "pix", "cartao_debito", "cartao_credito", "nao_informado"}
_CLOSE_PAYMENT_METHODS = _PAYMENT_METHODS | {"fiado"}


async def _require_open_cash_register(
    db: AsyncSession, *, for_update: bool = False
) -> CashRegisterSession | None:
    query = select(CashRegisterSession).where(CashRegisterSession.status == "open")
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
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
    validate_pack_configuration(product)
    target_id = product.pack_unit_product_id or product.id
    result = await db.execute(
        select(Product).where(Product.id == target_id).with_for_update()
    )
    stock_product = result.scalars().first()
    if not stock_product:
        raise ValueError("Produto físico vinculado não encontrado")
    size = product.pack_size if product.pack_unit_product_id else 1
    return stock_product, requested_quantity * size


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
    if quantity <= 0:
        raise ValueError("A quantidade deve ser maior que zero")
    stock_product, unit_quantity = await _resolve_pack_stock(db, product, quantity)

    if stock_product.stock < unit_quantity:
        available_packs = (
            stock_product.stock // product.pack_size
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
        source_product_id=product.id if is_pack(product) else None,
        order_id=order_id,
        table_id=table_id,
        type="saida",
        quantity=unit_quantity,
        source_quantity=quantity,
        conversion_factor=product.pack_size if is_pack(product) else 1,
        unit_cost_snapshot=stock_product.cost,
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
        stock_product, unit_quantity = await _resolve_pack_stock(db, product, item.quantity)

        stock_product.stock += unit_quantity
        db.add(StockHistory(
            product_id=stock_product.id,
            source_product_id=product.id if is_pack(product) else None,
            order_id=order_id,
            table_id=table_id,
            type="entrada",
            quantity=unit_quantity,
            source_quantity=item.quantity,
            conversion_factor=product.pack_size if is_pack(product) else 1,
            unit_cost_snapshot=stock_product.cost,
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
        stock_product, unit_quantity = await _resolve_pack_stock(db, product, item.quantity)

        stock_product.stock += unit_quantity
        stock_broadcast_infos.append(_build_stock_broadcast_info(product))
        if is_pack(product):
            stock_broadcast_infos.append(_build_stock_broadcast_info(stock_product))
        db.add(StockHistory(
            product_id=stock_product.id,
            source_product_id=product.id if is_pack(product) else None,
            order_id=order.id,
            table_id=table_id,
            type="entrada",
            quantity=unit_quantity,
            source_quantity=item.quantity,
            conversion_factor=product.pack_size if is_pack(product) else 1,
            unit_cost_snapshot=stock_product.cost,
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
    if quantity <= 0:
        raise ValueError("A quantidade deve ser maior que zero")
    stock_product, unit_quantity = await _resolve_pack_stock(db, product, quantity)

    if stock_product.stock < unit_quantity:
        available_packs = (
            stock_product.stock // product.pack_size
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
        source_product_id=product.id if is_pack(product) else None,
        source_quantity=quantity,
        conversion_factor=product.pack_size if is_pack(product) else 1,
        unit_cost_snapshot=stock_product.cost,
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

    @field_validator("quantity")
    @classmethod
    def validate_non_zero_quantity(cls, value: int) -> int:
        if value == 0:
            raise ValueError("A quantidade não pode ser zero")
        return value


class CloseOrderRequest(BaseModel):
    table_id: int
    apply_service_charge: bool = False
    service_charge_custom: Decimal | None = None
    payment_method: str | None = None
    card_machine: str | None = None
    order_id: int | None = None
    amount: Decimal | None = None
    waiter_id: int | None = None
    ficha_mode: bool = False
    idempotency_key: str | None = Field(default=None, max_length=64)


class PartialPaymentItemRequest(BaseModel):
    order_item_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)


class PartialPaymentRequest(BaseModel):
    table_id: int
    amount: Decimal = Field(..., gt=0)
    payment_method: str | None = None
    card_machine: str | None = None
    apply_service_charge: bool = False
    service_charge_custom: Decimal | None = None
    order_id: int | None = None
    items: list[PartialPaymentItemRequest] | None = None
    idempotency_key: str | None = Field(default=None, max_length=64)


class PedidoItem(BaseModel):
    product_id: int
    quantity: int = Field(default=1, gt=0)


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

    @field_validator("quantity")
    @classmethod
    def validate_non_zero_quantity(cls, value: int) -> int:
        if value == 0:
            raise ValueError("A quantidade não pode ser zero")
        return value


class RefundItemsRequest(BaseModel):
    items: list[PartialPaymentItemRequest] = Field(..., min_length=1)
    reason: str = Field(..., min_length=3, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=64)


class CancelOrderRequest(BaseModel):
    reason: str = Field(default="Cancelamento de comanda", min_length=3, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=64)


class PrintReceiptItem(BaseModel):
    product_name: str
    quantity: float = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    subtotal: float | None = None


class PrintReceiptRequest(BaseModel):
    """Optional print-only overrides. Never persisted to the database."""
    is_modified: bool = False
    items: list[PrintReceiptItem] | None = None
    customer_name: str | None = None
    table_label: str | None = None
    amount_received: Decimal | None = Field(default=None, ge=0)
    change_amount: Decimal | None = Field(default=None, ge=0)
    # Legacy client fields are intentionally ignored. The server recomputes every
    # monetary amount from the current order or from the explicit print-only items.
    total: Decimal | None = None
    service_charge_pct: Decimal | None = None
    service_charge_amount: Decimal | None = None
    partial_payment: Decimal | None = None
    partial_service_charge: Decimal | None = None
    final_total: Decimal | None = None
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
        table_number, round_number, prep_items, waiter_name, customer_name, order_id, width, observation, table_label
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
        table_number, round_number, bar_items, waiter_name, customer_name, order_id, width, observation, table_label
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
                                source_product_id=(
                                    product.id if is_pack(product) else None
                                ),
                                order_id=extra_order.id,
                                table_id=extra_order.table_id,
                                type="entrada",
                                quantity=unit_quantity,
                                source_quantity=item.quantity,
                                conversion_factor=(
                                    product.pack_size
                                    if is_pack(product)
                                    else 1
                                ),
                                unit_cost_snapshot=stock_product.cost,
                                note=f"Cancelamento comanda duplicada Balcão {table.number if table else extra_order.table_id}",
                            ))
                        except ValueError as exc:
                            return {"error": str(exc)}
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
        total=ZERO,
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
    if not await _require_open_cash_register(db, for_update=True):
        return {"error": "caixa_fechado", "detail": "O caixa está fechado. Abra o caixa para lançar pedidos."}

    order = await _get_open_order_for_table(
        db,
        req.table_id,
        req.order_id,
        options=[selectinload(Order.rounds)],
        for_update=True,
    )

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

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
            unit_cost=product.cost or ZERO,
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
    order.total = money(total_result.scalar_one())

    await db.commit()

    for notification in stock_notifications:
        await broadcast_stock_notification(notification.id)

    for product_id, stock, status in stock_broadcast_infos:
        await broadcast_stock_update(product_id, stock, status)

    table_label = table.label

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
        "total": as_float(order.total),
        "items": items_out,
    }


@router.post("/comanda/item")
async def add_order_item(
    req: OrderItemRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not await _require_open_cash_register(db, for_update=True):
        return {
            "error": "caixa_fechado",
            "detail": "O caixa está fechado. Abra o caixa para lançar pedidos.",
        }

    order = await _get_open_order_for_table(
        db,
        req.table_id,
        req.order_id,
        options=[selectinload(Order.items)],
        for_update=True,
    )

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    result = await db.execute(
        select(Product)
        .where(Product.id == req.product_id)
        .options(selectinload(Product.pack_unit_product))
    )
    product = result.scalars().first()

    if not product:
        return {"error": "Produto não encontrado"}

    table_result = await db.execute(select(Table).where(Table.id == req.table_id))
    table = table_result.scalars().first()

    unit_price = money(await _get_promotional_price(product, db))

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
            if existing_item.unit_cost is None:
                existing_item.unit_cost = product.cost or ZERO
        else:
            order_item = OrderItem(
                order_id=order.id,
                order_round_id=req.order_round_id,
                product_id=product.id,
                quantity=req.quantity,
                unit_price=unit_price,
                unit_cost=product.cost or ZERO,
            )
            db.add(order_item)
    else:
        if not existing_item:
            return {"error": "Item não encontrado na comanda"}

        qty_change = min(abs(req.quantity), existing_item.quantity)
        paid_quantity = await item_net_paid_quantity(db, existing_item.id)
        remaining_quantity = existing_item.quantity - qty_change
        if remaining_quantity < paid_quantity:
            return {
                "error": (
                    "Não é possível remover uma quantidade já paga. "
                    "Estorne os itens pagos antes de removê-los."
                )
            }

        paid_product, _ = await order_net_paid(db, order.id)
        projected_total = money(
            money(order.total) - money(existing_item.unit_price * qty_change)
        )
        if projected_total < paid_product:
            return {
                "error": (
                    "O ajuste deixaria o total da comanda abaixo do valor já pago. "
                    "Estorne o pagamento antes de remover o item."
                )
            }

        if remaining_quantity == 0:
            await db.delete(existing_item)
        else:
            existing_item.quantity = remaining_quantity

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
                source_product_id=product.id if is_pack(product) else None,
                source_quantity=qty_change,
                conversion_factor=product.pack_size if is_pack(product) else 1,
                unit_cost_snapshot=stock_product.cost,
                note=f"Cancelamento/ajuste mesa {table.number if table else req.table_id}",
            ))
        except ValueError as e:
            return {"error": str(e)}

    await db.flush()

    total_result = await db.execute(
        select(func.coalesce(func.sum(OrderItem.unit_price * OrderItem.quantity), 0))
        .where(OrderItem.order_id == order.id, OrderItem.is_pending == False)
    )
    total = money(total_result.scalar_one())
    order.total = total

    await db.commit()
    await broadcast_table_update(req.table_id)

    if stock_notification:
        await broadcast_stock_notification(stock_notification.id)

    for product_id, stock, status in stock_broadcast_infos:
        await broadcast_stock_update(product_id, stock, status)

    table_label = table.label if table else "Balcão"

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

    stock_product, _ = await _resolve_pack_stock(db, product, 1)
    stock_remaining = (
        stock_product.stock // product.pack_size
        if is_pack(product)
        else stock_product.stock
    )

    return {
        "order_id": order.id,
        "total": as_float(total),
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
    method = req.payment_method or "nao_informado"
    if method not in _PAYMENT_METHODS:
        return {"error": "Forma de pagamento inválida"}

    open_session = await _require_open_cash_register(db, for_update=True)
    if not open_session:
        return {"error": "Não há caixa aberto para receber pagamentos"}

    order = await _get_open_order_for_table(
        db,
        req.table_id,
        req.order_id,
        for_update=True,
        options=[selectinload(Order.items)],
    )

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    if req.idempotency_key:
        existing_payment = await db.scalar(
            select(OrderPayment).where(
                OrderPayment.idempotency_key == req.idempotency_key
            )
        )
        if existing_payment:
            if existing_payment.order_id != order.id:
                return {"error": "Identificador de pagamento já utilizado"}
            paid_product, paid_service = await order_net_paid(db, order.id)
            return {
                "order_id": order.id,
                "payment_id": existing_payment.id,
                "partial_payment": as_float(paid_product),
                "partial_service_charge": as_float(paid_service),
                "total": as_float(order.total),
                "remaining": as_float(max(ZERO, money(order.total) - paid_product)),
                "idempotent_replay": True,
            }

    paid_product, _ = await order_net_paid(db, order.id)
    remaining_product = money(max(ZERO, money(order.total) - paid_product))
    request_amount = money(req.amount)

    custom = req.service_charge_custom
    allocations_to_create: list[tuple[OrderItem, int, Decimal]] = []
    selected_product_amount = ZERO
    if req.items:
        requested_by_id: dict[int, int] = {}
        for selected in req.items:
            requested_by_id[selected.order_item_id] = (
                requested_by_id.get(selected.order_item_id, 0) + selected.quantity
            )
        item_result = await db.execute(
            select(OrderItem)
            .where(OrderItem.id.in_(sorted(requested_by_id)))
            .order_by(OrderItem.id)
            .with_for_update()
        )
        selected_items = {item.id: item for item in item_result.scalars().all()}
        if len(selected_items) != len(requested_by_id):
            return {"error": "Um dos itens selecionados não existe"}
        for item_id, quantity in requested_by_id.items():
            item = selected_items[item_id]
            if item.order_id != order.id or item.is_pending:
                return {"error": "Item não pertence à comanda ou ainda está pendente"}
            paid_quantity = await item_net_paid_quantity(db, item.id)
            if paid_quantity + quantity > item.quantity:
                return {"error": "A quantidade selecionada já foi paga"}
            subtotal = money(item.unit_price * quantity)
            selected_product_amount = money(selected_product_amount + subtotal)
            allocations_to_create.append((item, quantity, subtotal))

    if allocations_to_create:
        product_portion = selected_product_amount
        if req.apply_service_charge and custom is not None and custom > ZERO:
            service_portion = money(custom)
        elif req.apply_service_charge:
            service_pct = rate(
                await get_setting_as_float(db, "service_charge_pct", 10.0)
            )
            service_portion = percentage_amount(product_portion, service_pct)
        else:
            service_portion = ZERO
        if money(product_portion + service_portion) != request_amount:
            return {"error": "O total enviado não corresponde aos itens selecionados"}
    elif req.apply_service_charge and custom is not None and custom > ZERO:
        if money(custom) >= request_amount:
            return {"error": "A gorjeta personalizada não pode ser maior ou igual ao valor a abater"}
        product_portion = money(request_amount - money(custom))
        service_portion = money(custom)
    elif req.apply_service_charge:
        service_charge_pct = rate(
            await get_setting_as_float(db, "service_charge_pct", 10.0)
        )
        divisor = Decimal("1") + (service_charge_pct / Decimal("100"))
        product_portion = money(request_amount / divisor)
        service_portion = money(request_amount - product_portion)
    else:
        product_portion = request_amount
        service_portion = ZERO

    if product_portion > remaining_product:
        return {"error": "O pagamento excede o valor restante da comanda"}

    try:
        payment, created = await create_order_payment(
            db,
            order=order,
            user=user,
            cash_session=open_session,
            payment_type="partial",
            product_amount=product_portion,
            service_amount=service_portion,
            payment_method=method,
            card_machine=req.card_machine,
            idempotency_key=req.idempotency_key,
        )
    except ValueError as exc:
        return {"error": str(exc)}

    if not created:
        return {"error": "Pagamento já registrado"}

    if allocations_to_create:
        service_shares = distribute_service_amount(
            [entry[2] for entry in allocations_to_create], service_portion
        )
        for (item, quantity, subtotal), service_share in zip(
            allocations_to_create, service_shares, strict=True
        ):
            db.add(
                OrderPaymentAllocation(
                    payment_id=payment.id,
                    order_item_id=item.id,
                    product_id=item.product_id,
                    quantity=quantity,
                    unit_price=money(item.unit_price),
                    product_amount=subtotal,
                    service_amount=service_share,
                )
            )

    order.partial_payment = money(money(order.partial_payment) + product_portion)
    order.partial_service_charge = money(
        money(order.partial_service_charge) + service_portion
    )

    detail = list(order.partial_payments_detail or [])
    detail.append({
        "payment_id": payment.id,
        "idempotency_key": payment.idempotency_key,
        "amount": as_float(payment.gross_amount),
        "product_portion": as_float(product_portion),
        "service_portion": as_float(service_portion),
        "method": method,
        "card_machine": req.card_machine,
        "apply_service_charge": req.apply_service_charge,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "items": [
            {"order_item_id": item.id, "quantity": quantity}
            for item, quantity, _ in allocations_to_create
        ],
    })
    order.partial_payments_detail = detail

    await db.commit()
    await broadcast_table_update(req.table_id)

    remaining_product = money(max(ZERO, money(order.total) - money(order.partial_payment)))
    return {
        "order_id": order.id,
        "payment_id": payment.id,
        "partial_payment": as_float(order.partial_payment),
        "partial_service_charge": as_float(order.partial_service_charge),
        "total": as_float(order.total),
        "remaining": as_float(remaining_product),
    }


@router.post("/comanda/fechar")
async def close_order(
    req: CloseOrderRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if req.idempotency_key:
        replay_order = await db.scalar(
            select(Order).where(
                Order.close_idempotency_key == req.idempotency_key
            )
        )
        if replay_order:
            replay_payment = await db.scalar(
                select(OrderPayment)
                .where(
                    OrderPayment.order_id == replay_order.id,
                    OrderPayment.payment_type == "final",
                )
                .order_by(OrderPayment.id.desc())
            )
            return {
                "order_id": replay_order.id,
                "table_id": replay_order.table_id,
                "payment_id": replay_payment.id if replay_payment else None,
                "total": as_float(replay_order.total),
                "service_charge_amount": as_float(replay_order.service_charge_amount),
                "partial_payment": as_float(replay_order.partial_payment),
                "partial_service_charge": as_float(replay_order.partial_service_charge),
                "final_total": as_float(replay_payment.gross_amount if replay_payment else ZERO),
                "payment_method": replay_order.payment_method,
                "status": replay_order.status,
                "idempotent_replay": True,
            }

        replay_payment = await db.scalar(
            select(OrderPayment).where(
                OrderPayment.idempotency_key == req.idempotency_key,
                OrderPayment.payment_type == "final",
            )
        )
        if replay_payment:
            replay_order = await db.get(Order, replay_payment.order_id)
            return {
                "order_id": replay_order.id,
                "table_id": replay_order.table_id,
                "total": as_float(replay_order.total),
                "service_charge_amount": as_float(replay_order.service_charge_amount),
                "partial_payment": as_float(replay_order.partial_payment),
                "partial_service_charge": as_float(replay_order.partial_service_charge),
                "final_total": as_float(replay_payment.gross_amount),
                "payment_method": replay_payment.payment_method,
                "status": replay_order.status,
                "idempotent_replay": True,
            }

    open_session = await _require_open_cash_register(db, for_update=True)
    if not open_session:
        return {"error": "Não há caixa aberto para finalizar a venda"}

    if req.idempotency_key:
        replay_order = await db.scalar(
            select(Order).where(
                Order.close_idempotency_key == req.idempotency_key
            )
        )
        if replay_order:
            return {
                "order_id": replay_order.id,
                "table_id": replay_order.table_id,
                "total": as_float(replay_order.total),
                "service_charge_amount": as_float(replay_order.service_charge_amount),
                "partial_payment": as_float(replay_order.partial_payment),
                "partial_service_charge": as_float(replay_order.partial_service_charge),
                "final_total": 0.0,
                "payment_method": replay_order.payment_method,
                "status": replay_order.status,
                "idempotent_replay": True,
            }

    order = await _get_open_order_for_table(
        db, req.table_id, req.order_id, for_update=True, options=[
            selectinload(Order.table),
            selectinload(Order.items).selectinload(OrderItem.product),
        ]
    )

    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    table_result = await db.execute(select(Table).where(Table.id == req.table_id))
    table = table_result.scalars().first()

    service_charge_pct = rate(
        await get_setting_as_float(db, "service_charge_pct", 10.0)
    )
    paid_product, paid_service = await order_net_paid(db, order.id)
    remaining_product = money(max(ZERO, money(order.total) - paid_product))
    if req.apply_service_charge:
        order.service_charge_applied = True
        custom = req.service_charge_custom
        if custom is not None and custom > ZERO:
            order.service_charge_pct = (
                rate(money(custom) / remaining_product * Decimal("100"))
                if remaining_product > ZERO
                else rate(0)
            )
            service_charge_amount = money(custom)
        else:
            order.service_charge_pct = service_charge_pct
            service_charge_amount = percentage_amount(
                remaining_product, order.service_charge_pct
            )
    else:
        order.service_charge_pct = rate(0)
        order.service_charge_applied = False
        service_charge_amount = ZERO

    remaining_service = money(max(ZERO, service_charge_amount))
    final_total = money(remaining_product + remaining_service)

    close_method = req.payment_method or "nao_informado"
    if close_method == "fiado":
        return {"error": "Para venda fiado, use o fluxo de Fiado/Consignado (vincula o cliente e gera o recebível) — não feche a comanda como fiado"}
    if close_method not in _CLOSE_PAYMENT_METHODS:
        return {"error": "Forma de pagamento inválida"}

    tendered: Decimal | None = None
    if close_method == "dinheiro":
        if req.amount is None:
            return {"error": "Informe o valor pago"}
        tendered = money(req.amount)
        if tendered < final_total:
            return {"error": f"Valor pago (R$ {tendered:.2f}) é menor que o total final (R$ {final_total:.2f})"}

    final_payment = None
    if final_total > ZERO:
        try:
            final_payment, _ = await create_order_payment(
                db,
                order=order,
                user=user,
                cash_session=open_session,
                payment_type="final",
                product_amount=remaining_product,
                service_amount=remaining_service,
                payment_method=close_method,
                card_machine=req.card_machine,
                idempotency_key=req.idempotency_key,
            )
        except ValueError as exc:
            return {"error": str(exc)}

    table_label = table.label if table else "Balcão"
    try:
        stock_broadcast_infos = await _release_pending_items(
            db,
            order,
            req.table_id,
            f"Cancelamento itens pendentes no fechamento da {table_label}",
        )
    except ValueError as exc:
        return {"error": str(exc)}

    order.status = "finalizada"
    order.closed_at = datetime.now(timezone.utc)
    order.payment_method = close_method
    order.card_machine = req.card_machine
    order.close_idempotency_key = (
        req.idempotency_key.strip() if req.idempotency_key else str(uuid4())
    )
    order.closed_by_id = user.id
    order.partial_payment = paid_product
    order.partial_service_charge = paid_service
    order.service_charge_amount = money(paid_service + remaining_service)

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
                amount_received = tendered if tendered is not None else final_total
                change_amount = (
                    money(tendered - final_total)
                    if tendered is not None
                    else ZERO
                )
                receipt_result = await _print_order_receipt(
                    db,
                    order,
                    user,
                    PrintReceiptRequest(
                        payment_method=req.payment_method,
                        amount_received=amount_received,
                        change_amount=change_amount,
                    ),
                )
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
        "payment_id": final_payment.id if final_payment else None,
        "total": as_float(order.total),
        "service_charge_pct": float(order.service_charge_pct),
        "service_charge_amount": as_float(order.service_charge_amount),
        "partial_payment": as_float(order.partial_payment),
        "partial_service_charge": as_float(order.partial_service_charge),
        "final_total": as_float(final_total),
        "payment_method": order.payment_method,
        "status": "finalizada",
        "customer_id": order.customer_id,
        "customer_name": order.customer_name,
    }
    if table.is_balcao:
        response["receipt_result"] = receipt_result
    return response


@router.post("/comanda/{order_id}/estornar-itens")
async def refund_order_items(
    order_id: int,
    req: RefundItemsRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "gerente":
        return {"error": "Acesso restrito ao gerente"}

    open_session = await _require_open_cash_register(db, for_update=True)
    if not open_session:
        return {"error": "Abra o caixa antes de registrar o estorno"}

    quantities: dict[int, int] = {}
    for item in req.items:
        quantities[item.order_item_id] = (
            quantities.get(item.order_item_id, 0) + item.quantity
        )
    try:
        refund = await refund_paid_items(
            db,
            order_id=order_id,
            quantities=quantities,
            user=user,
            cash_session=open_session,
            reason=req.reason.strip(),
            idempotency_key=req.idempotency_key,
        )
    except ValueError as exc:
        return {"error": str(exc)}

    order = await db.get(Order, order_id)
    await db.commit()
    if order:
        await broadcast_table_update(order.table_id)
    seen: set[int] = set()
    for product_id, stock, status in refund.stock_updates:
        if product_id in seen:
            continue
        seen.add(product_id)
        await broadcast_stock_update(product_id, stock, status)
    return {
        "message": "Itens estornados com sucesso",
        "refund_group_key": refund.group_key,
        "refund_ids": refund.refund_ids,
        "refunded_amount": as_float(refund.gross_amount),
        "idempotent_replay": refund.replayed,
    }


@router.post("/comanda/{order_id}/cancelar")
async def cancel_order(
    order_id: int,
    req: CancelOrderRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    open_session = await _require_open_cash_register(db, for_update=True)
    order_result = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .with_for_update()
    )
    order = order_result.scalars().first()

    if not order:
        return {"error": "Comanda não encontrada"}

    if order.status != "aberta":
        return {"error": "Apenas comandas abertas podem ser canceladas"}

    table_result = await db.execute(select(Table).where(Table.id == order.table_id))
    table = table_result.scalars().first()

    paid_product, paid_service = await order_net_paid(db, order.id)
    if money(paid_product + paid_service) > ZERO:
        if user.role != "gerente":
            return {
                "error": (
                    "A comanda possui pagamentos. Solicite ao gerente o cancelamento "
                    "com estorno no mesmo meio de pagamento."
                )
            }
        if not open_session:
            return {"error": "Abra o caixa antes de cancelar pagamentos recebidos"}
        payload = req or CancelOrderRequest()
        try:
            refund = await refund_full_order(
                db,
                order_id=order.id,
                user=user,
                cash_session=open_session,
                reason=payload.reason.strip(),
                idempotency_key=payload.idempotency_key,
                allow_open_order=True,
            )
        except ValueError as exc:
            return {"error": str(exc)}

        if table:
            table.status = "vazia"
        await db.commit()
        await broadcast_table_update(order.table_id)
        seen: set[int] = set()
        for product_id, stock, status in refund.stock_updates:
            if product_id in seen:
                continue
            seen.add(product_id)
            await broadcast_stock_update(product_id, stock, status)
        return {
            "message": "Comanda cancelada e pagamentos estornados",
            "refunded_amount": as_float(refund.gross_amount),
            "refund_group_key": refund.group_key,
        }

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
                source_product_id=product.id if is_pack(product) else None,
                order_id=order.id,
                table_id=order.table_id,
                type="entrada",
                quantity=unit_quantity,
                source_quantity=item.quantity,
                conversion_factor=product.pack_size if is_pack(product) else 1,
                unit_cost_snapshot=stock_product.cost,
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


def _confirmed_receipt_items(order: Order) -> list[dict]:
    return [
        {
            "product_name": item.product.name if item.product else "Produto",
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
            "subtotal": float(item.unit_price * item.quantity),
        }
        for item in order.items
        if not item.is_pending
    ]


async def _print_order_receipt(
    db: AsyncSession,
    order: Order,
    user: User,
    req: PrintReceiptRequest | None = None,
) -> dict:
    """Print a table quote or a definitive counter receipt from canonical values."""
    req = req or PrintReceiptRequest()

    status_text = ""
    if order.is_estorno:
        status_text = "NOTA ESTORNADA"
    elif order.status == "cancelada":
        status_text = "NOTA CANCELADA"
    is_counter_receipt = bool(order.table and order.table.is_balcao)
    use_print_overrides = bool(
        req.is_modified
        and req.items is not None
        and not is_counter_receipt
        and order.status == "aberta"
        and not status_text
    )
    if use_print_overrides:
        items = []
        for item in req.items:
            qty = Decimal(str(item.quantity))
            unit = money(item.unit_price)
            subtotal = money(qty * unit)
            items.append({
                "product_name": item.product_name.strip() or "Item",
                "quantity": float(qty),
                "unit_price": as_float(unit),
                "subtotal": as_float(subtotal),
            })
    else:
        items = _confirmed_receipt_items(order)

    if not items:
        return {"error": "A nota precisa ter ao menos 1 item para imprimir"}

    computed_total = (
        money(sum((money(item["subtotal"]) for item in items), ZERO))
        if use_print_overrides
        else money(order.total)
    )
    default_table_label = (
        order.table.label
        if order.table and not order.table.is_balcao
        else ("Balcão" if order.table else "")
    )

    is_table_quote = not is_counter_receipt and order.status == "aberta" and not status_text
    if is_table_quote:
        paid_product, paid_service = await order_net_paid(db, order.id)
        service_charge_pct = rate(
            await get_setting_as_float(db, "service_charge_pct", 10.0)
        )
        amount_without_service = money(max(ZERO, computed_total - paid_product))
        optional_service_amount = percentage_amount(
            amount_without_service, service_charge_pct
        )
        amount_with_service = money(
            amount_without_service + optional_service_amount
        )
        service_charge_amount = optional_service_amount
        final_total = amount_with_service
        receipt_type = "table_quote"
    else:
        paid_product = money(order.partial_payment)
        paid_service = money(order.partial_service_charge)
        service_charge_pct = rate(order.service_charge_pct)
        service_charge_amount = money(order.service_charge_amount)
        remaining_product = money(max(ZERO, computed_total - paid_product))
        remaining_service = money(max(ZERO, service_charge_amount - paid_service))
        final_total = money(remaining_product + remaining_service)
        amount_without_service = remaining_product
        optional_service_amount = remaining_service
        amount_with_service = final_total
        receipt_type = "counter_receipt"

    order_data = {
        "order_id": order.id,
        "receipt_type": receipt_type,
        "status_text": status_text,
        "printed_at": datetime.now(timezone.utc).isoformat(),
        "table_label": (
            req.table_label
            if use_print_overrides and req.table_label is not None
            else default_table_label
        ),
        "customer_name": (
            req.customer_name
            if use_print_overrides and req.customer_name is not None
            else order.customer_name
        ),
        "items": items,
        "total": as_float(computed_total),
        "service_charge_pct": float(service_charge_pct),
        "service_charge_amount": as_float(service_charge_amount),
        "partial_payment": as_float(paid_product),
        "partial_service_charge": as_float(paid_service),
        "final_total": as_float(final_total),
        "amount_without_service": as_float(amount_without_service),
        "optional_service_amount": as_float(optional_service_amount),
        "amount_with_service": as_float(amount_with_service),
        "payment_method": (
            req.payment_method
            if req.payment_method is not None
            else order.payment_method
        ),
        "amount_received": (
            as_float(req.amount_received)
            if req.amount_received is not None
            else None
        ),
        "change_amount": (
            as_float(req.change_amount) if req.change_amount is not None else None
        ),
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
        "receipt_data": order_data,
        "receipt_store_info": store_info,
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
    if not await _require_open_cash_register(db, for_update=True):
        return {"error": "caixa_fechado", "detail": "O caixa está fechado. Abra o caixa para lançar pedidos."}

    order = await _get_open_order_for_table(
        db,
        req.table_id,
        req.order_id,
        options=[selectinload(Order.items)],
        for_update=True,
    )
    if not order:
        return {"error": "Nenhuma comanda aberta para esta mesa"}

    result = await db.execute(
        select(Product)
        .where(Product.id == req.product_id)
        .options(selectinload(Product.pack_unit_product))
    )
    product = result.scalars().first()
    if not product:
        return {"error": "Produto não encontrado"}

    table_result = await db.execute(select(Table).where(Table.id == req.table_id))
    table = table_result.scalars().first()

    unit_price = money(await _get_promotional_price(product, db))

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
            if existing_item.unit_cost is None:
                existing_item.unit_cost = product.cost or ZERO
        else:
            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=req.quantity,
                unit_price=unit_price,
                unit_cost=product.cost or ZERO,
                is_pending=True,
            )
            db.add(order_item)
    else:
        if not existing_item:
            return {"error": "Item não encontrado no pedido pendente"}
        qty_change = min(abs(req.quantity), existing_item.quantity)

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
                source_product_id=product.id if is_pack(product) else None,
                order_id=order.id,
                table_id=req.table_id,
                type="entrada",
                quantity=unit_quantity,
                source_quantity=qty_change,
                conversion_factor=product.pack_size if is_pack(product) else 1,
                unit_cost_snapshot=stock_product.cost,
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
    if not await _require_open_cash_register(db, for_update=True):
        return {"error": "caixa_fechado", "detail": "O caixa está fechado. Abra o caixa para confirmar pedidos."}

    order = await _get_open_order_for_table(
        db,
        req.table_id,
        req.order_id,
        options=[
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.rounds),
            selectinload(Order.table),
        ],
        for_update=True,
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
    order.total = money(total_result.scalar_one())

    await db.commit()
    await broadcast_table_update(req.table_id)

    table_label = order.table.label if order.table else "Balcão"

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
        "total": as_float(order.total),
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
        for_update=True,
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
        except ValueError as exc:
            return {"error": str(exc)}

        stock_product.stock += unit_quantity
        stock_broadcast_infos.append(_build_stock_broadcast_info(product))
        if is_pack(product):
            stock_broadcast_infos.append(_build_stock_broadcast_info(stock_product))
        db.add(StockHistory(
            product_id=stock_product.id,
            source_product_id=product.id if is_pack(product) else None,
            order_id=order.id,
            table_id=req.table_id,
            type="entrada",
            quantity=unit_quantity,
            source_quantity=item.quantity,
                conversion_factor=product.pack_size if is_pack(product) else 1,
            unit_cost_snapshot=stock_product.cost,
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
