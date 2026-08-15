from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.table import Table
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_round import OrderRound
from app.models.product import Product
from app.models.user import User
from app.core.timezone import as_local
from app.routers.auth_deps import get_current_user, require_role
from app.services.stock_service import is_pack, pack_stock_for_product, stock_status

router = APIRouter(prefix="/api", tags=["tables"])


class TableCreate(BaseModel):
    number: int


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
                selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.pack_unit_product),
                selectinload(Order.rounds).selectinload(OrderRound.items).selectinload(OrderItem.product).selectinload(Product.pack_unit_product),
            )
            .order_by(Order.id)
        )
        open_orders = order_result.scalars().all()

        total = sum(float(o.total) for o in open_orders)
        partial_payment = sum(float(o.partial_payment) for o in open_orders)
        partial_service_charge = sum(float(o.partial_service_charge) for o in open_orders)

        data.append(
            {
                "id": t.id,
                "number": t.number,
                "status": t.status,
                "is_balcao": t.is_balcao,
                "total": round(total, 2),
                "partial_payment": round(partial_payment, 2),
                "partial_service_charge": round(partial_service_charge, 2),
                "has_open_order": len(open_orders) > 0,
                "open_orders_count": len(open_orders),
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

    order_query = (
        select(Order)
        .where(Order.table_id == table_id, Order.status == "aberta")
        .options(
            selectinload(Order.waiter),
            selectinload(Order.items).selectinload(OrderItem.product).selectinload(Product.pack_unit_product),
            selectinload(Order.rounds)
            .selectinload(OrderRound.items)
            .selectinload(OrderItem.product)
            .selectinload(Product.pack_unit_product),
        )
    )
    if table.is_balcao:
        order_query = order_query.order_by(Order.id.desc())
    else:
        order_query = order_query.order_by(Order.id.asc())
    order_result = await db.execute(order_query)
    open_orders = order_result.scalars().all()

    def _item_payload(item: OrderItem) -> dict:
        product = item.product
        product_stock = pack_stock_for_product(product) if is_pack(product) else product.stock
        return {
            "id": item.id,
            "product_id": item.product_id,
            "product_name": product.name,
            "quantity": item.quantity,
            "unit_price": float(item.unit_price),
            "subtotal": float(item.unit_price * item.quantity),
            "category": product.category,
            "product_stock": product_stock,
            "product_status": stock_status(product),
        }

    def _build_order_payload(order: Order) -> dict:
        pedidos = []
        for rnd in sorted(order.rounds, key=lambda r: r.round_number):
            round_items = [_item_payload(item) for item in rnd.items if not item.is_pending]
            if round_items:
                pedidos.append(
                    {
                        "id": rnd.id,
                        "round_number": rnd.round_number,
                        "created_at": as_local(rnd.created_at).strftime("%H:%M") if rnd.created_at else "",
                        "items": round_items,
                    }
                )

        # Items added directly without a round (e.g., Balcão quick add)
        direct_items = [item for item in order.items if item.order_round_id is None and not item.is_pending]
        if direct_items:
            round_items = [_item_payload(item) for item in direct_items]
            pedidos.append(
                {
                    "id": None,
                    "round_number": 0,
                    "created_at": "",
                    "items": round_items,
                }
            )

        return {
            "id": order.id,
            "total": float(order.total),
            "partial_payment": float(order.partial_payment),
            "partial_service_charge": float(order.partial_service_charge),
            "service_charge_pct": float(order.service_charge_pct),
            "service_charge_applied": order.service_charge_applied,
            "customer_name": order.customer_name,
            "waiter_name": order.waiter.name if order.waiter else None,
            "pedidos": pedidos,
        }

    orders_payload = [_build_order_payload(o) for o in open_orders]
    first_order = orders_payload[0] if orders_payload else None

    return {
        "id": table.id,
        "number": table.number,
        "is_balcao": table.is_balcao,
        "label": "Balcão" if table.is_balcao else f"Mesa {table.number}",
        "status": table.status,
        "total": first_order["total"] if first_order else 0.0,
        "partial_payment": first_order["partial_payment"] if first_order else 0.0,
        "partial_service_charge": first_order["partial_service_charge"] if first_order else 0.0,
        "service_charge_pct": first_order["service_charge_pct"] if first_order else 0.0,
        "service_charge_applied": first_order["service_charge_applied"] if first_order else False,
        "customer_name": first_order["customer_name"] if first_order else None,
        "waiter_name": first_order["waiter_name"] if first_order else None,
        "order_id": first_order["id"] if first_order else None,
        "orders": orders_payload,
        "pedidos": first_order["pedidos"] if first_order else [],
    }


@router.get("/mesas/admin")
async def list_tables_admin(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    result = await db.execute(select(Table).where(Table.is_balcao == False).order_by(Table.number))
    tables = result.scalars().all()
    return [
        {
            "id": t.id,
            "number": t.number,
            "status": t.status,
            "is_balcao": t.is_balcao,
        }
        for t in tables
    ]


@router.post("/mesas")
async def create_table(
    req: TableCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    if req.number <= 0:
        return {"error": "Número da mesa deve ser maior que zero"}

    existing = await db.execute(select(Table).where(Table.number == req.number))
    if existing.scalars().first():
        return {"error": "Já existe uma mesa com esse número"}

    table = Table(number=req.number, status="vazia", is_balcao=False)
    db.add(table)
    await db.commit()
    await db.refresh(table)
    return {
        "id": table.id,
        "number": table.number,
        "status": table.status,
        "is_balcao": table.is_balcao,
    }


@router.delete("/mesas/{table_id}")
async def delete_table(
    table_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    result = await db.execute(select(Table).where(Table.id == table_id, Table.is_balcao == False))
    table = result.scalars().first()
    if not table:
        return {"error": "Mesa não encontrada"}

    open_orders = await db.execute(
        select(Order).where(Order.table_id == table_id, Order.status == "aberta")
    )
    if open_orders.scalars().first():
        return {"error": "Não é possível excluir mesa com comandas abertas"}

    await db.delete(table)
    await db.commit()
    return {"message": "Mesa excluída com sucesso"}
