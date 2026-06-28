from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.table import Table
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_round import OrderRound
from app.models.user import User
from app.routers.auth_deps import get_current_user

router = APIRouter(prefix="/api", tags=["tables"])


@router.get("/mesas")
async def list_tables(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Table).order_by(Table.is_balcao, Table.number))
    tables = result.scalars().all()

    data = []
    for t in tables:
        order_result = await db.execute(
            select(Order)
            .where(Order.table_id == t.id, Order.status == "aberta")
            .options(
                selectinload(Order.items),
                selectinload(Order.rounds).selectinload(OrderRound.items),
            )
        )
        open_order = order_result.scalars().first()

        data.append(
            {
                "id": t.id,
                "number": t.number,
                "status": t.status,
                "is_balcao": t.is_balcao,
                "total": float(open_order.total) if open_order else 0.0,
                "partial_payment": float(open_order.partial_payment) if open_order else 0.0,
                "partial_service_charge": float(open_order.partial_service_charge) if open_order else 0.0,
                "has_open_order": open_order is not None,
                "label": "Balcão" if t.is_balcao else f"Mesa {t.number}",
            }
        )

    return data


@router.get("/mesa/{table_id}")
async def get_table_detail(
    table_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Table).where(Table.id == table_id))
    table = result.scalars().first()

    if not table:
        return {"error": "Mesa não encontrada"}

    order_result = await db.execute(
        select(Order)
        .where(Order.table_id == table_id, Order.status == "aberta")
        .options(
            selectinload(Order.waiter),
            selectinload(Order.rounds)
            .selectinload(OrderRound.items)
            .selectinload(OrderItem.product),
        )
    )
    order = order_result.scalars().first()

    pedidos = []
    if order:
        for rnd in sorted(order.rounds, key=lambda r: r.round_number):
            round_items = []
            for item in rnd.items:
                round_items.append(
                    {
                        "id": item.id,
                        "product_id": item.product_id,
                        "product_name": item.product.name,
                        "quantity": item.quantity,
                        "unit_price": float(item.unit_price),
                        "subtotal": float(item.unit_price * item.quantity),
                        "category": item.product.category,
                    }
                )

            pedidos.append(
                {
                    "id": rnd.id,
                    "round_number": rnd.round_number,
                    "created_at": rnd.created_at.strftime("%H:%M") if rnd.created_at else "",
                    "items": round_items,
                }
            )

    return {
        "id": table.id,
        "number": table.number,
        "is_balcao": table.is_balcao,
        "label": "Balcão" if table.is_balcao else f"Mesa {table.number}",
        "status": table.status,
        "total": float(order.total) if order else 0.0,
        "partial_payment": float(order.partial_payment) if order else 0.0,
        "partial_service_charge": float(order.partial_service_charge) if order else 0.0,
        "service_charge_pct": float(order.service_charge_pct) if order else 0.0,
        "service_charge_applied": order.service_charge_applied if order else False,
        "customer_name": order.customer_name if order else None,
        "waiter_name": order.waiter.name if (order and order.waiter) else None,
        "order_id": order.id if order else None,
        "pedidos": pedidos,
    }
