from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.consignment import (
    ConsignmentOrder,
    ConsignmentOrderItem,
    ConsignmentPayment,
)
from app.models.customer import Customer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.stock_history import StockHistory
from app.models.table import Table
from app.models.user import User
from app.routers.auth_deps import get_current_user, require_role
from app.routers.orders import (
    _check_and_consume_stock,
    _check_and_consume_stock_consignment,
    _get_promotional_price,
    _resolve_pack_stock,
    _get_open_order_for_table,
)
from app.routers.ws import broadcast_table_update, broadcast_stock_update
from app.services.notification_service import broadcast_stock_notification
from app.services.stock_service import is_pack, pack_stock_for_product, stock_status


def _build_stock_broadcast_info(product):
    """Return (product_id, stock, status) for a product, handling packs correctly."""
    if is_pack(product):
        return product.id, pack_stock_for_product(product), stock_status(product)
    return product.id, product.stock, stock_status(product)

router = APIRouter(prefix="/api", tags=["consignments"])


def _can_manage(user: User) -> bool:
    return user.role in ("gerente", "caixa")


def _can_initiate(user: User) -> bool:
    return user.role in ("gerente", "caixa", "garcom")


class ConsignmentItemRequest(BaseModel):
    product_id: int
    quantity: int = Field(..., ge=1)
    unit_price: float | None = None


class ConsignmentCreateRequest(BaseModel):
    customer_id: int
    order_type: str = "pf"
    due_date: str | None = None
    notes: str | None = None
    items: list[ConsignmentItemRequest]


class ConsignmentUpdateRequest(BaseModel):
    order_type: str | None = None
    due_date: str | None = None
    notes: str | None = None


class ConsignmentPaymentRequest(BaseModel):
    amount: float = Field(..., gt=0)
    payment_method: str
    card_machine: str | None = None
    notes: str | None = None


class ConvertToFiadoRequest(BaseModel):
    customer_id: int | None = None


async def _consume_stock_for_items(
    db: AsyncSession,
    items: list[ConsignmentItemRequest],
    consignment_id: int,
    note: str,
) -> list[dict]:
    created_items = []
    stock_notifications = []
    products_to_broadcast = set()
    for entry in items:
        product = await db.execute(select(Product).where(Product.id == entry.product_id))
        product = product.scalars().first()
        if not product:
            continue

        unit_price = entry.unit_price if entry.unit_price is not None else await _get_promotional_price(product, db)

        try:
            stock_product, notification = await _check_and_consume_stock_consignment(
                db,
                product,
                entry.quantity,
                consignment_id,
                note,
            )
        except ValueError as e:
            raise ValueError(str(e))

        products_to_broadcast.add(stock_product)
        if is_pack(product):
            products_to_broadcast.add(product)

        if notification:
            stock_notifications.append(notification)

        created_items.append({
            "product_id": product.id,
            "product_name": product.name,
            "quantity": entry.quantity,
            "unit_price": unit_price,
            "subtotal": round(unit_price * entry.quantity, 2),
            "stock_remaining": stock_product.stock,
        })

        db.add(ConsignmentOrderItem(
            consignment_order_id=consignment_id,
            product_id=product.id,
            quantity=entry.quantity,
            unit_price=unit_price,
        ))
    return created_items, stock_notifications, products_to_broadcast


async def _return_stock_for_items(db: AsyncSession, consignment_id: int) -> set:
    result = await db.execute(
        select(ConsignmentOrderItem)
        .where(ConsignmentOrderItem.consignment_order_id == consignment_id)
        .options(selectinload(ConsignmentOrderItem.product))
    )
    items = result.scalars().all()

    products_to_broadcast = set()
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
        products_to_broadcast.add(stock_product)
        if is_pack(product):
            products_to_broadcast.add(product)
        db.add(StockHistory(
            product_id=stock_product.id,
            consignment_order_id=consignment_id,
            type="entrada",
            quantity=unit_quantity,
            note=f"Cancelamento consignado {consignment_id}",
        ))
    return products_to_broadcast


async def _recalculate_totals(db: AsyncSession, consignment_id: int) -> None:
    total_result = await db.execute(
        select(func.coalesce(func.sum(ConsignmentOrderItem.unit_price * ConsignmentOrderItem.quantity), 0.0))
        .where(ConsignmentOrderItem.consignment_order_id == consignment_id)
    )
    total = float(total_result.scalar_one())

    consignment_result = await db.execute(select(ConsignmentOrder).where(ConsignmentOrder.id == consignment_id))
    consignment = consignment_result.scalar_one()
    consignment.total = round(total, 2)
    consignment.balance = round(max(0.0, consignment.total - consignment.amount_paid), 2)


@router.get("/consignados")
async def list_consignments(
    status: str | None = "todos",
    order_type: str | None = None,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(user):
        return {"error": "Acesso restrito ao gerente ou caixa"}

    query = select(ConsignmentOrder).options(
        selectinload(ConsignmentOrder.customer),
        selectinload(ConsignmentOrder.items).selectinload(ConsignmentOrderItem.product),
        selectinload(ConsignmentOrder.payments),
        selectinload(ConsignmentOrder.waiter),
    )

    if status and status != "todos":
        query = query.where(ConsignmentOrder.status == status)
    if order_type:
        query = query.where(ConsignmentOrder.order_type == order_type)
    if search:
        query = query.where(ConsignmentOrder.customer.has(Customer.name.ilike(f"%{search}%")))

    if sort_by == "pending_days":
        order_expr = ConsignmentOrder.created_at.asc() if sort_order == "asc" else ConsignmentOrder.created_at.desc()
    elif sort_by == "total":
        order_expr = ConsignmentOrder.total.asc() if sort_order == "asc" else ConsignmentOrder.total.desc()
    else:
        order_expr = ConsignmentOrder.created_at.asc() if sort_order == "asc" else ConsignmentOrder.created_at.desc()
    query = query.order_by(order_expr)

    result = await db.execute(query)
    consignments = result.scalars().all()

    now = datetime.now(timezone.utc)
    out = []
    for c in consignments:
        created_at = c.created_at
        pending_days = 0
        if created_at:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            pending_days = max(0, (now - created_at).days)

        out.append({
            "id": c.id,
            "customer_id": c.customer_id,
            "customer_name": c.customer.name if c.customer else None,
            "customer_phone": c.customer.phone if c.customer else None,
            "customer_document": c.customer.document if c.customer else None,
            "order_type": c.order_type,
            "status": c.status,
            "total": float(c.total),
            "amount_paid": float(c.amount_paid),
            "balance": float(c.balance),
            "pending_days": pending_days,
            "due_date": c.due_date.isoformat() if c.due_date else None,
            "notes": c.notes,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "closed_at": c.closed_at.isoformat() if c.closed_at else None,
            "waiter_name": c.waiter.name if c.waiter else None,
            "items_count": len(c.items),
            "payments_count": len(c.payments),
        })

    return out


@router.post("/consignados")
async def create_consignment(
    req: ConsignmentCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(user):
        return {"error": "Acesso restrito ao gerente ou caixa"}

    customer = await db.execute(select(Customer).where(Customer.id == req.customer_id))
    customer = customer.scalars().first()
    if not customer:
        return {"error": "Cliente não encontrado"}
    if not customer.active:
        return {"error": "Cliente inativo"}

    if not req.items:
        return {"error": "Informe ao menos um item"}

    due_date = None
    if req.due_date:
        try:
            due_date = date.fromisoformat(req.due_date)
        except ValueError:
            return {"error": "Data de vencimento inválida"}

    consignment = ConsignmentOrder(
        customer_id=customer.id,
        order_type=req.order_type or "pf",
        due_date=due_date,
        notes=req.notes,
        waiter_id=user.id,
        status="pendente",
        total=0.0,
        amount_paid=0.0,
        balance=0.0,
    )
    db.add(consignment)
    await db.flush()
    await db.refresh(consignment)

    try:
        items_out, stock_notifications, products_to_broadcast = await _consume_stock_for_items(
            db,
            req.items,
            consignment.id,
            f"Consignado {consignment.id}",
        )
    except ValueError as e:
        return {"error": str(e)}

    if not items_out:
        return {"error": "Nenhum item válido encontrado"}

    await _recalculate_totals(db, consignment.id)
    await db.commit()
    await db.refresh(consignment)

    for notification in stock_notifications:
        await broadcast_stock_notification(notification.id)

    for p in products_to_broadcast:
        await broadcast_stock_update(*_build_stock_broadcast_info(p))

    return {
        "id": consignment.id,
        "customer_id": consignment.customer_id,
        "customer_name": customer.name,
        "order_type": consignment.order_type,
        "status": consignment.status,
        "total": float(consignment.total),
        "balance": float(consignment.balance),
        "items": items_out,
    }


@router.get("/consignados/{consignment_id}")
async def get_consignment(
    consignment_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(user):
        return {"error": "Acesso restrito ao gerente ou caixa"}

    result = await db.execute(
        select(ConsignmentOrder)
        .where(ConsignmentOrder.id == consignment_id)
        .options(
            selectinload(ConsignmentOrder.customer),
            selectinload(ConsignmentOrder.items).selectinload(ConsignmentOrderItem.product),
            selectinload(ConsignmentOrder.payments).selectinload(ConsignmentPayment.user),
            selectinload(ConsignmentOrder.waiter),
            selectinload(ConsignmentOrder.source_order),
        )
    )
    consignment = result.scalars().first()
    if not consignment:
        return {"error": "Consignado não encontrado"}

    created_at = consignment.created_at
    pending_days = 0
    now = datetime.now(timezone.utc)
    if created_at:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        pending_days = max(0, (now - created_at).days)

    return {
        "id": consignment.id,
        "customer_id": consignment.customer_id,
        "customer_name": consignment.customer.name if consignment.customer else None,
        "customer_phone": consignment.customer.phone if consignment.customer else None,
        "customer_document": consignment.customer.document if consignment.customer else None,
        "customer_type": consignment.customer.customer_type if consignment.customer else None,
        "order_type": consignment.order_type,
        "status": consignment.status,
        "total": float(consignment.total),
        "amount_paid": float(consignment.amount_paid),
        "balance": float(consignment.balance),
        "pending_days": pending_days,
        "due_date": consignment.due_date.isoformat() if consignment.due_date else None,
        "notes": consignment.notes,
        "created_at": consignment.created_at.isoformat() if consignment.created_at else None,
        "closed_at": consignment.closed_at.isoformat() if consignment.closed_at else None,
        "waiter_name": consignment.waiter.name if consignment.waiter else None,
        "source_order_id": consignment.source_order_id,
        "items": [
            {
                "id": item.id,
                "product_id": item.product_id,
                "product_name": item.product.name if item.product else None,
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "subtotal": float(item.unit_price * item.quantity),
            }
            for item in consignment.items
        ],
        "payments": [
            {
                "id": p.id,
                "amount": float(p.amount),
                "payment_method": p.payment_method,
                "card_machine": p.card_machine,
                "notes": p.notes,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "user_name": p.user.name if p.user else None,
            }
            for p in consignment.payments
        ],
    }


@router.put("/consignados/{consignment_id}")
async def update_consignment(
    consignment_id: int,
    req: ConsignmentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(user):
        return {"error": "Acesso restrito ao gerente ou caixa"}

    result = await db.execute(
        select(ConsignmentOrder).where(ConsignmentOrder.id == consignment_id)
    )
    consignment = result.scalars().first()
    if not consignment:
        return {"error": "Consignado não encontrado"}

    if consignment.status not in ("pendente", "pago"):
        return {"error": "Não é possível editar um consignado cancelado"}

    if req.order_type is not None:
        consignment.order_type = req.order_type
    if req.due_date is not None:
        try:
            consignment.due_date = date.fromisoformat(req.due_date) if req.due_date else None
        except ValueError:
            return {"error": "Data de vencimento inválida"}
    if req.notes is not None:
        consignment.notes = req.notes

    await db.commit()
    await db.refresh(consignment)
    return {"id": consignment.id, "status": consignment.status}


@router.post("/consignados/{consignment_id}/pagamento")
async def add_payment(
    consignment_id: int,
    req: ConsignmentPaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_manage(user):
        return {"error": "Acesso restrito ao gerente ou caixa"}

    result = await db.execute(
        select(ConsignmentOrder).where(ConsignmentOrder.id == consignment_id)
    )
    consignment = result.scalars().first()
    if not consignment:
        return {"error": "Consignado não encontrado"}

    if consignment.status == "cancelado":
        return {"error": "Consignado cancelado"}

    if req.amount > consignment.balance + 0.01:
        return {"error": "Valor maior que o saldo devedor"}

    if req.amount <= 0:
        return {"error": "Valor deve ser maior que zero"}

    payment = ConsignmentPayment(
        consignment_order_id=consignment.id,
        user_id=user.id,
        amount=req.amount,
        payment_method=req.payment_method,
        card_machine=req.card_machine,
        notes=req.notes,
    )
    db.add(payment)

    consignment.amount_paid = round(consignment.amount_paid + req.amount, 2)
    consignment.balance = round(max(0.0, consignment.total - consignment.amount_paid), 2)

    if consignment.balance <= 0.01:
        consignment.status = "pago"
        consignment.closed_at = datetime.now(timezone.utc)
    else:
        consignment.status = "pendente"

    await db.commit()
    await db.refresh(consignment)

    return {
        "id": payment.id,
        "consignment_id": consignment.id,
        "amount": float(payment.amount),
        "payment_method": payment.payment_method,
        "balance": float(consignment.balance),
        "status": consignment.status,
    }


@router.post("/consignados/{consignment_id}/cancelar")
async def cancel_consignment(
    consignment_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "gerente":
        return {"error": "Apenas gerente pode cancelar"}

    result = await db.execute(
        select(ConsignmentOrder)
        .where(ConsignmentOrder.id == consignment_id)
        .options(selectinload(ConsignmentOrder.items).selectinload(ConsignmentOrderItem.product))
    )
    consignment = result.scalars().first()
    if not consignment:
        return {"error": "Consignado não encontrado"}

    if consignment.status == "cancelado":
        return {"error": "Consignado já cancelado"}

    if consignment.amount_paid > 0:
        return {"error": "Não é possível cancelar consignado com pagamentos registrados"}

    products_to_broadcast = await _return_stock_for_items(db, consignment.id)

    consignment.status = "cancelado"
    consignment.closed_at = datetime.now(timezone.utc)
    consignment.balance = 0.0

    await db.commit()

    for p in products_to_broadcast:
        await broadcast_stock_update(*_build_stock_broadcast_info(p))

    return {"id": consignment.id, "status": consignment.status}


@router.post("/comanda/{order_id}/converter-fiado")
async def convert_order_to_consignment(
    order_id: int,
    req: ConvertToFiadoRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _can_initiate(user):
        return {"error": "Acesso restrito"}

    order = await db.execute(
        select(Order)
        .where(Order.id == order_id, Order.status == "aberta")
        .options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.customer),
            selectinload(Order.table),
        )
    )
    order = order.scalars().first()
    if not order:
        return {"error": "Comanda não encontrada ou já finalizada"}

    customer_id = req.customer_id or order.customer_id
    if not customer_id:
        return {"error": "vincular_cliente", "detail": "Vincule ou crie um cliente para continuar"}

    customer = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = customer.scalars().first()
    if not customer:
        return {"error": "Cliente não encontrado"}
    if not customer.active:
        return {"error": "Cliente inativo"}

    confirmed_items = [item for item in order.items if not item.is_pending]
    if not confirmed_items:
        return {"error": "Comanda não possui itens confirmados"}

    consignment = ConsignmentOrder(
        customer_id=customer.id,
        source_order_id=order.id,
        order_type="pf",
        status="pendente",
        total=float(order.total),
        amount_paid=float(order.partial_payment),
        balance=max(0.0, float(order.total) - float(order.partial_payment)),
        waiter_id=user.id,
        notes=f"Gerado da comanda da mesa {order.table.label if order.table else order.table_id}",
    )
    db.add(consignment)
    await db.flush()
    await db.refresh(consignment)

    for item in confirmed_items:
        db.add(ConsignmentOrderItem(
            consignment_order_id=consignment.id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=float(item.unit_price),
        ))

    # Registra como pagamentos de consignação os pagamentos parciais já feitos na
    # comanda. Sem isso, o valor já pago não entra no faturamento (que lê
    # ConsignmentPayment.amount) e ficaria fora dos relatórios e dashboards.
    for partial in order.partial_payments_detail or []:
        paid_at = None
        if partial.get("created_at"):
            try:
                paid_at = datetime.fromisoformat(partial["created_at"])
            except ValueError:
                paid_at = None
        db.add(ConsignmentPayment(
            consignment_order_id=consignment.id,
            user_id=user.id,
            amount=round(float(partial.get("amount", 0)), 2),
            payment_method=partial.get("method") or "nao_informado",
            card_machine=partial.get("card_machine"),
            notes=f"Pagamento parcial da comanda #{order.id}",
            created_at=paid_at,
        ))

    await _recalculate_totals(db, consignment.id)

    # Return stock for any pending items and remove them before finalizing the order
    pending_items = [item for item in order.items if item.is_pending]
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
            table_id=order.table_id,
            type="entrada",
            quantity=unit_quantity,
            note=f"Cancelamento itens pendentes na conversão para consignado mesa {order.table.label if order.table else order.table_id}",
        ))
        await db.delete(item)

    order.status = "finalizada"
    order.closed_at = datetime.now(timezone.utc)
    order.payment_method = "fiado"

    if order.table:
        has_open = await db.execute(
            select(func.count(Order.id)).where(
                Order.table_id == order.table_id, Order.status == "aberta"
            )
        )
        if (has_open.scalar_one() or 0) == 0:
            order.table.status = "vazia"

    await db.commit()

    for product_id, stock, status in stock_broadcast_infos:
        await broadcast_stock_update(product_id, stock, status)

    if order.table_id:
        await broadcast_table_update(order.table_id)

    return {
        "success": True,
        "consignment_id": consignment.id,
        "order_id": order.id,
        "customer_id": customer.id,
        "customer_name": customer.name,
        "total": float(consignment.total),
    }
