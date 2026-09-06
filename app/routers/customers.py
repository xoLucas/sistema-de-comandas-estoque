from datetime import datetime, date, timezone
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func, extract, cast, Date, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.customer import Customer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.user import User
from app.models.consignment import (
    ConsignmentOrder,
    ConsignmentOrderItem,
    ConsignmentPayment,
)
from app.models.payment import PaymentRefund, PaymentRefundItem
from app.core.timezone import as_local
from app.routers.auth_deps import get_current_user, require_role
from app.routers.financial import serialize_order_sale
from app.services.money_service import ZERO, as_float, money
from app.validators.pydantic_mixins import CustomerValidationMixin

router = APIRouter(prefix="/api", tags=["customers"])


class CustomerCreate(CustomerValidationMixin, BaseModel):
    name: str
    customer_type: str = "pf"
    phone: str | None = None
    email: str | None = None
    document: str | None = None
    birth_date: str | None = None
    notes: str | None = None
    active: bool = True


class CustomerUpdate(CustomerValidationMixin, BaseModel):
    name: str
    customer_type: str = "pf"
    phone: str | None = None
    email: str | None = None
    document: str | None = None
    birth_date: str | None = None
    notes: str | None = None
    active: bool = True


@router.get("/clientes")
async def list_customers(
    active_only: bool = False,
    search: str | None = None,
    customer_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("gerente", "caixa", "garcom"):
        return {"error": "Acesso restrito"}

    query = select(Customer)
    if active_only:
        query = query.where(Customer.active == True)
    if search:
        query = query.where(Customer.name.ilike(f"%{search}%"))
    if customer_type:
        query = query.where(Customer.customer_type == customer_type)
    result = await db.execute(query.order_by(Customer.name))
    customers = result.scalars().all()

    return [
        {
            "id": c.id,
            "name": c.name,
            "phone": c.phone,
            "email": c.email,
            "document": c.document,
            "birth_date": c.birth_date.isoformat() if c.birth_date else None,
            "customer_type": c.customer_type,
            "notes": c.notes,
            "active": c.active,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in customers
    ]


@router.get("/clientes/{customer_id}")
async def get_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("gerente", "caixa", "garcom"):
        return {"error": "Acesso restrito"}

    result = await db.execute(
        select(Customer).where(Customer.id == customer_id)
    )
    customer = result.scalars().first()
    if not customer:
        return {"error": "Cliente não encontrado"}

    return {
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "document": customer.document,
        "birth_date": customer.birth_date.isoformat() if customer.birth_date else None,
        "customer_type": customer.customer_type,
        "notes": customer.notes,
        "active": customer.active,
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
    }


@router.post("/clientes")
async def create_customer(
    req: CustomerCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente", "caixa", "garcom")),
):
    if not req.name:
        return {"error": "Nome é obrigatório"}

    birth_date = None
    if req.birth_date:
        try:
            birth_date = datetime.fromisoformat(req.birth_date).date()
        except ValueError:
            return {"error": "Data de nascimento inválida"}

    customer = Customer(
        name=req.name,
        phone=req.phone,
        email=req.email,
        document=req.document,
        birth_date=birth_date,
        customer_type=req.customer_type or "pf",
        notes=req.notes,
        active=req.active,
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)

    return {
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "document": customer.document,
        "birth_date": customer.birth_date.isoformat() if customer.birth_date else None,
        "customer_type": customer.customer_type,
        "active": customer.active,
    }


@router.put("/clientes/{customer_id}")
async def update_customer(
    customer_id: int,
    req: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente", "caixa")),
):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalars().first()
    if not customer:
        return {"error": "Cliente não encontrado"}

    if not req.name:
        return {"error": "Nome é obrigatório"}

    birth_date = customer.birth_date
    if req.birth_date:
        try:
            birth_date = datetime.fromisoformat(req.birth_date).date()
        except ValueError:
            return {"error": "Data de nascimento inválida"}

    customer.name = req.name
    customer.phone = req.phone
    customer.email = req.email
    customer.document = req.document
    customer.birth_date = birth_date
    customer.customer_type = req.customer_type or "pf"
    customer.notes = req.notes
    customer.active = req.active

    await db.commit()
    await db.refresh(customer)

    return {
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "email": customer.email,
        "document": customer.document,
        "birth_date": customer.birth_date.isoformat() if customer.birth_date else None,
        "customer_type": customer.customer_type,
        "active": customer.active,
    }


@router.delete("/clientes/{customer_id}")
async def delete_customer(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalars().first()
    if not customer:
        return {"error": "Cliente não encontrado"}

    await db.delete(customer)
    await db.commit()
    return {"message": "Cliente removido"}


@router.get("/clientes/{customer_id}/resumo")
async def customer_summary(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("gerente", "caixa", "garcom"):
        return {"error": "Acesso restrito"}

    result = await db.execute(
        select(Customer).where(Customer.id == customer_id)
    )
    customer = result.scalars().first()
    if not customer:
        return {"error": "Cliente não encontrado"}

    result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
            func.max(Order.closed_at),
        ).where(
            Order.customer_id == customer_id,
            Order.status == "finalizada",
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
    )
    total_spent, visit_count, last_visit = result.one()

    consignment_result = await db.execute(
        select(
            func.coalesce(func.sum(ConsignmentOrder.product_total), 0),
            func.count(ConsignmentOrder.id),
            func.max(ConsignmentOrder.created_at),
        ).where(
            ConsignmentOrder.customer_id == customer_id,
            or_(
                ConsignmentOrder.status != "cancelado",
                ConsignmentOrder.source_order.has(Order.is_estorno == True),
                ConsignmentOrder.refunds.any(),
            ),
        )
    )
    consignment_total, consignment_count, last_consignment = consignment_result.one()

    refund_customer_id = func.coalesce(
        Order.customer_id,
        ConsignmentOrder.customer_id,
    )
    refund_total = await db.scalar(
        select(func.coalesce(func.sum(PaymentRefundItem.product_amount), 0))
        .join(PaymentRefund, PaymentRefund.id == PaymentRefundItem.refund_id)
        .outerjoin(Order, Order.id == PaymentRefund.order_id)
        .outerjoin(
            ConsignmentOrder,
            ConsignmentOrder.id == PaymentRefund.consignment_order_id,
        )
        .where(
            refund_customer_id == customer_id,
            PaymentRefund.sale_was_recognized == True,
        )
    )
    paid_consignment_product = await db.scalar(
        select(func.coalesce(func.sum(ConsignmentPayment.product_portion), 0))
        .join(
            ConsignmentOrder,
            ConsignmentOrder.id == ConsignmentPayment.consignment_order_id,
        )
        .where(ConsignmentOrder.customer_id == customer_id)
    )
    pending_balance = await db.scalar(
        select(func.coalesce(func.sum(ConsignmentOrder.balance), 0)).where(
            ConsignmentOrder.customer_id == customer_id,
            ConsignmentOrder.status != "cancelado",
            ConsignmentOrder.balance > 0,
        )
    )
    total_consumption = money(total_spent) + money(consignment_total) - money(refund_total)
    last_activity = max(
        (value for value in (last_visit, last_consignment) if value is not None),
        default=None,
    )

    return {
        "customer_id": customer.id,
        "name": customer.name,
        "total_spent": as_float(total_consumption),
        "visit_count": int(visit_count) + int(consignment_count),
        "last_visit": last_activity.isoformat() if last_activity else None,
        "consignment_product_paid": as_float(paid_consignment_product),
        "consignment_balance": as_float(pending_balance),
    }


@router.get("/clientes/{customer_id}/dashboard")
async def customer_dashboard(
    customer_id: int,
    year: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("gerente", "caixa"):
        return {"error": "Acesso restrito"}

    result = await db.execute(
        select(Customer).where(Customer.id == customer_id)
    )
    customer = result.scalars().first()
    if not customer:
        return {"error": "Cliente não encontrado"}

    if not year:
        year_max_result = await db.execute(
            select(
                func.coalesce(func.max(extract("year", func.timezone("America/Sao_Paulo", Order.closed_at))), 0)
            ).where(
                Order.customer_id == customer_id,
                Order.status == "finalizada",
            )
        )
        year_max_value = year_max_result.scalar_one()
        consignment_year_result = await db.execute(
            select(
                func.coalesce(func.max(extract("year", func.timezone("America/Sao_Paulo", ConsignmentOrder.created_at))), 0)
            ).where(
                ConsignmentOrder.customer_id == customer_id,
                or_(
                    ConsignmentOrder.status != "cancelado",
                    ConsignmentOrder.source_order.has(Order.is_estorno == True),
                    ConsignmentOrder.refunds.any(),
                ),
            )
        )
        consignment_year_value = consignment_year_result.scalar_one()
        refund_customer_id = func.coalesce(
            Order.customer_id,
            ConsignmentOrder.customer_id,
        )
        refund_year_value = await db.scalar(
            select(
                func.coalesce(
                    func.max(
                        extract(
                            "year",
                            func.timezone(
                                "America/Sao_Paulo", PaymentRefund.created_at
                            ),
                        )
                    ),
                    0,
                )
            )
            .outerjoin(Order, Order.id == PaymentRefund.order_id)
            .outerjoin(
                ConsignmentOrder,
                ConsignmentOrder.id == PaymentRefund.consignment_order_id,
            )
            .where(
                refund_customer_id == customer_id,
                PaymentRefund.sale_was_recognized == True,
            )
        )
        year = int(
            max(
                year_max_value or 0,
                consignment_year_value or 0,
                refund_year_value or 0,
            )
        ) or as_local(datetime.now(timezone.utc)).year

    orders_result = await db.execute(
        select(Order)
        .where(
            Order.customer_id == customer_id,
            Order.status == "finalizada",
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
            extract("year", func.timezone("America/Sao_Paulo", Order.closed_at)) == year,
        )
        .options(selectinload(Order.table))
        .order_by(Order.closed_at)
    )
    orders = orders_result.scalars().all()

    consignment_result = await db.execute(
        select(ConsignmentOrder)
        .where(
            ConsignmentOrder.customer_id == customer_id,
            or_(
                ConsignmentOrder.status != "cancelado",
                ConsignmentOrder.source_order.has(Order.is_estorno == True),
                ConsignmentOrder.refunds.any(),
            ),
            extract("year", func.timezone("America/Sao_Paulo", ConsignmentOrder.created_at)) == year,
        )
        .options(selectinload(ConsignmentOrder.items))
        .order_by(ConsignmentOrder.created_at)
    )
    consignments = consignment_result.scalars().all()

    refund_customer_id = func.coalesce(
        Order.customer_id,
        ConsignmentOrder.customer_id,
    )
    refunds_result = await db.execute(
        select(PaymentRefund)
        .outerjoin(Order, Order.id == PaymentRefund.order_id)
        .outerjoin(
            ConsignmentOrder,
            ConsignmentOrder.id == PaymentRefund.consignment_order_id,
        )
        .where(
            refund_customer_id == customer_id,
            PaymentRefund.sale_was_recognized == True,
            extract(
                "year", func.timezone("America/Sao_Paulo", PaymentRefund.created_at)
            )
            == year,
        )
        .options(selectinload(PaymentRefund.items))
        .order_by(PaymentRefund.created_at)
    )
    refunds = refunds_result.scalars().all()

    months = {i: {"count": 0, "total": 0.0, "label": _month_label(i)} for i in range(1, 13)}
    weekdays = {i: {"count": 0, "total": 0.0, "label": _weekday_label(i)} for i in range(7)}
    yearly_total = 0.0

    for order in orders:
        if not order.closed_at:
            continue
        closed_local = as_local(order.closed_at)
        month = closed_local.month
        weekday = closed_local.weekday()
        total = float(order.total)

        months[month]["count"] += 1
        months[month]["total"] += total
        weekdays[weekday]["count"] += 1
        weekdays[weekday]["total"] += total
        yearly_total += total

    for consignment in consignments:
        if not consignment.created_at:
            continue
        created_local = as_local(consignment.created_at)
        month = created_local.month
        weekday = created_local.weekday()
        total = as_float(consignment.product_total)

        months[month]["count"] += 1
        months[month]["total"] += total
        weekdays[weekday]["count"] += 1
        weekdays[weekday]["total"] += total
        yearly_total += total

    for refund in refunds:
        if not refund.created_at or not refund.sale_was_recognized:
            continue
        refunded_local = as_local(refund.created_at)
        month = refunded_local.month
        weekday = refunded_local.weekday()
        total = as_float(
            money(sum((item.product_amount for item in refund.items), ZERO))
        )

        months[month]["total"] -= total
        weekdays[weekday]["total"] -= total
        yearly_total -= total

    return {
        "customer_id": customer.id,
        "name": customer.name,
        "year": year,
        "yearly_total": round(yearly_total, 2),
        "yearly_visits": len(orders) + len(consignments),
        "by_month": [
            {"month": i, "label": months[i]["label"], "count": months[i]["count"], "total": round(months[i]["total"], 2)}
            for i in range(1, 13)
        ],
        "by_weekday": [
            {"weekday": i, "label": weekdays[i]["label"], "count": weekdays[i]["count"], "total": round(weekdays[i]["total"], 2)}
            for i in range(7)
        ],
        "orders": [
            {
                "id": o.id,
                "table": o.table.label if o.table else "Balcão",
                "total": float(o.total),
                "closed_at": o.closed_at.isoformat() if o.closed_at else None,
            }
            for o in orders
        ],
        "consignments": [
            {
                "id": c.id,
                "total": float(c.total),
                "balance": float(c.balance),
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in consignments
        ],
    }


def _month_label(month: int) -> str:
    labels = {
        1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
        7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
    }
    return labels.get(month, str(month))


@router.get("/clientes/{customer_id}/comandas")
async def customer_orders(
    customer_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("gerente", "caixa"):
        return {"error": "Acesso restrito"}

    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalars().first()
    if not customer:
        return {"error": "Cliente não encontrado"}

    count_result = await db.execute(
        select(func.count(Order.id)).where(
            Order.customer_id == customer_id,
            Order.status == "finalizada",
        )
    )
    total = int(count_result.scalar_one())

    offset = (page - 1) * page_size
    orders_result = await db.execute(
        select(Order)
        .where(
            Order.customer_id == customer_id,
            Order.status == "finalizada",
        )
        .options(
            selectinload(Order.table),
            selectinload(Order.waiter),
            selectinload(Order.closed_by),
            selectinload(Order.closed_waiter),
            selectinload(Order.customer),
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.payments),
            selectinload(Order.refunds),
        )
        .order_by(Order.closed_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    orders = orders_result.scalars().all()

    return {
        "sales": [serialize_order_sale(o) for o in orders],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        },
    }


def _weekday_label(weekday: int) -> str:
    labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    return labels[weekday]


@router.get("/clientes/{customer_id}/itens-consumo")
async def customer_item_ranking(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("gerente", "caixa"):
        return {"error": "Acesso restrito"}

    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    customer = result.scalars().first()
    if not customer:
        return {"error": "Cliente não encontrado"}

    items_result = await db.execute(
        select(
            Product.name,
            func.sum(OrderItem.quantity),
            func.sum(OrderItem.unit_price * OrderItem.quantity),
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.customer_id == customer_id,
            Order.status == "finalizada",
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .group_by(Product.name)
        .order_by(
            func.sum(OrderItem.quantity).desc(),
            func.sum(OrderItem.unit_price * OrderItem.quantity).desc(),
        )
    )

    items = [
        {
            "product_name": name,
            "quantity": int(qty or 0),
            "total": round(float(total or 0), 2),
        }
        for name, qty, total in items_result.all()
    ]

    consignment_items_result = await db.execute(
        select(
            Product.name,
            func.sum(ConsignmentOrderItem.quantity),
            func.sum(ConsignmentOrderItem.unit_price * ConsignmentOrderItem.quantity),
        )
        .join(ConsignmentOrderItem, ConsignmentOrderItem.product_id == Product.id)
        .join(ConsignmentOrder, ConsignmentOrder.id == ConsignmentOrderItem.consignment_order_id)
        .where(
            ConsignmentOrder.customer_id == customer_id,
            or_(
                ConsignmentOrder.status != "cancelado",
                ConsignmentOrder.source_order.has(Order.is_estorno == True),
                ConsignmentOrder.refunds.any(),
            ),
        )
        .group_by(Product.name)
        .order_by(
            func.sum(ConsignmentOrderItem.quantity).desc(),
            func.sum(ConsignmentOrderItem.unit_price * ConsignmentOrderItem.quantity).desc(),
        )
    )
    for name, qty, total in consignment_items_result.all():
        existing = next((item for item in items if item["product_name"] == name), None)
        if existing:
            existing["quantity"] += int(qty or 0)
            existing["total"] = round(existing["total"] + float(total or 0), 2)
        else:
            items.append({
                "product_name": name,
                "quantity": int(qty or 0),
                "total": round(float(total or 0), 2),
            })

    refund_customer_id = func.coalesce(
        Order.customer_id,
        ConsignmentOrder.customer_id,
    )
    refunded_items_result = await db.execute(
        select(
            Product.name,
            func.sum(PaymentRefundItem.quantity),
            func.sum(PaymentRefundItem.product_amount),
        )
        .join(PaymentRefundItem, PaymentRefundItem.product_id == Product.id)
        .join(PaymentRefund, PaymentRefund.id == PaymentRefundItem.refund_id)
        .outerjoin(Order, Order.id == PaymentRefund.order_id)
        .outerjoin(
            ConsignmentOrder,
            ConsignmentOrder.id == PaymentRefund.consignment_order_id,
        )
        .where(
            refund_customer_id == customer_id,
            PaymentRefund.sale_was_recognized == True,
        )
        .group_by(Product.name)
    )
    for name, qty, total in refunded_items_result.all():
        existing = next((item for item in items if item["product_name"] == name), None)
        if existing:
            existing["quantity"] -= int(qty or 0)
            existing["total"] = as_float(
                money(existing["total"]) - money(total)
            )
        else:
            items.append(
                {
                    "product_name": name,
                    "quantity": -int(qty or 0),
                    "total": -as_float(total),
                }
            )

    items.sort(key=lambda x: (x["quantity"], x["total"]), reverse=True)

    return {
        "customer_id": customer.id,
        "name": customer.name,
        "items": items,
    }
