from datetime import datetime, date, timezone, timedelta
from collections import defaultdict
from io import StringIO
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select, func, cast, Date, or_, extract
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.timezone import (
    as_local,
    format_local_date,
    local_date,
    parse_local_date_range,
    today_local,
)
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_round import OrderRound
from app.models.product import Product
from app.models.table import Table
from app.models.user import User
from app.models.customer import Customer
from app.models.consignment import ConsignmentOrder, ConsignmentOrderItem, ConsignmentPayment
from app.models.cash_register_session import CashRegisterSession
from app.models.cash_register_movement import CashRegisterMovement
from app.models.expense import Expense
from app.models.stock_history import StockHistory
from app.routers.auth_deps import get_current_user
from app.services.stock_service import stock_status, is_pack, pack_stock_for_product

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])


def _require_manager(user: User) -> bool:
    return user.role == "gerente"


def _default_ranges() -> tuple[date, date]:
    today = today_local()
    return today, today


def _parse_dates(
    start_date: str | None,
    end_date: str | None,
    default_days: int = 7,
) -> tuple[datetime, datetime, date, date]:
    return parse_local_date_range(start_date, end_date, default_days=default_days)


def _csv_response(filename: str, headers: list[str], rows: list[list[Any]]) -> StreamingResponse:
    output = StringIO()
    output.write(";".join(headers) + "\n")
    for row in rows:
        output.write(";".join(str(cell) for cell in row) + "\n")
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/geral")
async def dashboard_geral(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    format: str = Query("json"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _require_manager(user):
        return {"error": "Acesso restrito ao gerente"}

    start_dt, end_dt, start_local, end_local = _parse_dates(start_date, end_date, default_days=1)

    # Vendas no período
    sales_result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total), 0.0),
            func.coalesce(func.sum(Order.total * Order.service_charge_pct / 100), 0.0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
    )
    sales_total, service_charge, sales_count = sales_result.one()

    # Comandas abertas agora
    open_orders_result = await db.execute(
        select(func.coalesce(func.sum(Order.total), 0.0), func.count(Order.id)).where(
            Order.status == "aberta"
        )
    )
    open_total, open_count = open_orders_result.one()

    # Consignados pendentes (todos, não filtrados por data)
    consignments_result = await db.execute(
        select(
            func.count(ConsignmentOrder.id),
            func.coalesce(func.sum(ConsignmentOrder.balance), 0.0),
        ).where(
            ConsignmentOrder.status != "cancelado",
            ConsignmentOrder.balance > 0,
        )
    )
    consignments_count, consignments_total = consignments_result.one()

    # Consignados criados no período
    consignments_period_result = await db.execute(
        select(
            func.count(ConsignmentOrder.id),
            func.coalesce(func.sum(ConsignmentOrder.total), 0.0),
        ).where(
            ConsignmentOrder.status != "cancelado",
            ConsignmentOrder.created_at >= start_dt,
            ConsignmentOrder.created_at <= end_dt,
        )
    )
    consignments_period_count, consignments_period_total = consignments_period_result.one()

    # Caixa aberto
    cash_result = await db.execute(
        select(CashRegisterSession).where(CashRegisterSession.status == "open")
    )
    cash_session = cash_result.scalar_one_or_none()
    cash_info = None
    if cash_session:
        movements_result = await db.execute(
            select(CashRegisterMovement).where(CashRegisterMovement.session_id == cash_session.id)
        )
        movements = movements_result.scalars().all()
        sangria = sum(float(m.amount) for m in movements if m.type == "sangria")
        suprimento = sum(float(m.amount) for m in movements if m.type == "suprimento")
        cash_info = {
            "id": cash_session.id,
            "opened_by": cash_session.opened_by.name if cash_session.opened_by else "N/A",
            "initial_cash": float(cash_session.initial_cash),
            "sangria": round(sangria, 2),
            "suprimento": round(suprimento, 2),
        }

    # Produtos em falta/risco
    products_result = await db.execute(select(Product))
    products = products_result.scalars().all()
    stock_counts = {"em_conformidade": 0, "em_risco": 0, "em_falta": 0}
    stock_risk_items = []
    stock_out_items = []
    for p in products:
        status = stock_status(p)
        stock_counts[status] = stock_counts.get(status, 0) + 1
        if status == "em_risco":
            stock_risk_items.append({
                "id": p.id,
                "name": p.name,
                "stock": pack_stock_for_product(p) if is_pack(p) else p.stock,
                "min_stock": p.min_stock,
            })
        elif status == "em_falta":
            stock_out_items.append({
                "id": p.id,
                "name": p.name,
                "stock": pack_stock_for_product(p) if is_pack(p) else p.stock,
                "min_stock": p.min_stock,
            })

    # Vendas por hora
    hour_expr = func.to_char(func.timezone("America/Sao_Paulo", Order.closed_at), "HH24:00").label("hour")
    orders_by_hour_result = await db.execute(
        select(
            hour_expr,
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        ).group_by(hour_expr)
        .order_by(hour_expr)
    )
    sales_by_hour = [
        {"hour": hour, "total": round(float(total), 2), "orders": count}
        for hour, total, count in orders_by_hour_result.all()
    ]

    # Formas de pagamento
    payments_result = await db.execute(
        select(
            Order.payment_method,
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        ).group_by(Order.payment_method)
    )
    payment_methods = []
    payment_labels = {
        "dinheiro": "Dinheiro",
        "pix": "Pix",
        "cartao_debito": "Cartão Débito",
        "cartao_credito": "Cartão Crédito",
        "nao_informado": "Não Informado",
    }
    for method, total, count in payments_result.all():
        payment_methods.append({
            "method": method or "nao_informado",
            "label": payment_labels.get(method or "nao_informado", method or "Não Informado"),
            "total": round(float(total), 2),
            "count": count,
        })

    # Top produtos
    items_result = await db.execute(
        select(
            Product.name,
            func.sum(OrderItem.quantity),
            func.sum(OrderItem.unit_price * OrderItem.quantity),
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .group_by(Product.name)
        .order_by(func.sum(OrderItem.unit_price * OrderItem.quantity).desc())
        .limit(10)
    )
    top_products = [
        {"name": name, "quantity": int(quantity or 0), "total": round(float(total or 0), 2)}
        for name, quantity, total in items_result.all()
    ]

    if format.lower() == "csv":
        headers = [
            "Indicador", "Valor", "Periodo Inicio", "Periodo Fim"
        ]
        rows = [
            ["Faturamento", round(float(sales_total), 2), start_local.isoformat(), end_local.isoformat()],
            ["Taxa de Servico", round(float(service_charge), 2), start_local.isoformat(), end_local.isoformat()],
            ["Comandas Finalizadas", sales_count, start_local.isoformat(), end_local.isoformat()],
            ["Comandas Abertas", open_count, start_local.isoformat(), end_local.isoformat()],
            ["Total Comandas Abertas", round(float(open_total), 2), start_local.isoformat(), end_local.isoformat()],
            ["Consignados Pendentes", consignments_count, "", ""],
            ["Total Consignados Pendentes", round(float(consignments_total), 2), "", ""],
            ["Consignados no Periodo", consignments_period_count, start_local.isoformat(), end_local.isoformat()],
            ["Total Consignados no Periodo", round(float(consignments_period_total), 2), start_local.isoformat(), end_local.isoformat()],
            ["Produtos em Falta", stock_counts.get("em_falta", 0), "", ""],
            ["Produtos em Risco", stock_counts.get("em_risco", 0), "", ""],
        ]
        return _csv_response("dashboard_geral.csv", headers, rows)

    return {
        "period": {"start": start_local.isoformat(), "end": end_local.isoformat()},
        "sales": {
            "total": round(float(sales_total), 2),
            "service_charge": round(float(service_charge), 2),
            "orders_count": sales_count,
        },
        "open_orders": {
            "count": open_count,
            "total": round(float(open_total), 2),
        },
        "consignments": {
            "pending_count": consignments_count,
            "pending_total": round(float(consignments_total), 2),
            "period_count": consignments_period_count,
            "period_total": round(float(consignments_period_total), 2),
        },
        "cash": cash_info,
        "stock": {
            "counts": stock_counts,
            "out_items": stock_out_items[:10],
            "risk_items": stock_risk_items[:10],
        },
        "sales_by_hour": sales_by_hour,
        "payment_methods": payment_methods,
        "top_products": top_products,
    }


@router.get("/vendas")
async def dashboard_vendas(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    format: str = Query("json"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _require_manager(user):
        return {"error": "Acesso restrito ao gerente"}

    start_dt, end_dt, start_local, end_local = _parse_dates(start_date, end_date, default_days=7)

    # Vendas por dia
    daily_expr = cast(func.timezone("America/Sao_Paulo", Order.closed_at), Date)
    daily_result = await db.execute(
        select(
            daily_expr,
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        ).group_by(daily_expr)
        .order_by(daily_expr)
    )
    sales_by_day = [
        {"date": str(day), "total": round(float(total), 2), "orders": count}
        for day, total, count in daily_result.all()
    ]

    # Por categoria
    category_result = await db.execute(
        select(
            Product.category,
            func.sum(OrderItem.quantity),
            func.sum(OrderItem.unit_price * OrderItem.quantity),
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .group_by(Product.category)
        .order_by(func.sum(OrderItem.unit_price * OrderItem.quantity).desc())
    )
    by_category = [
        {"category": cat, "quantity": int(quantity or 0), "total": round(float(total or 0), 2)}
        for cat, quantity, total in category_result.all()
    ]

    # Por produto
    products_result = await db.execute(
        select(
            Product.name,
            func.sum(OrderItem.quantity),
            func.sum(OrderItem.unit_price * OrderItem.quantity),
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .group_by(Product.name)
        .order_by(func.sum(OrderItem.unit_price * OrderItem.quantity).desc())
    )
    by_product = [
        {"name": name, "quantity": int(quantity or 0), "total": round(float(total or 0), 2)}
        for name, quantity, total in products_result.all()
    ]

    # Por garçom
    waiter_result = await db.execute(
        select(
            User.name,
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        )
        .join(Order, Order.waiter_id == User.id)
        .where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .group_by(User.name)
        .order_by(func.coalesce(func.sum(Order.total), 0.0).desc())
    )
    by_waiter = [
        {"name": name, "total": round(float(total), 2), "orders": count}
        for name, total, count in waiter_result.all()
    ]

    # Por mesa/balcão
    table_result = await db.execute(
        select(
            Table.id,
            Table.number,
            Table.is_balcao,
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        )
        .join(Order, Order.table_id == Table.id)
        .where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .group_by(Table.id, Table.number, Table.is_balcao)
        .order_by(func.coalesce(func.sum(Order.total), 0.0).desc())
    )
    by_table = []
    for tid, number, is_balcao_flag, total, count in table_result.all():
        label = "Balcão" if is_balcao_flag else f"Mesa {number}"
        by_table.append({
            "id": tid,
            "label": label,
            "total": round(float(total), 2),
            "orders": count,
        })

    # Formas de pagamento
    payment_result = await db.execute(
        select(
            Order.payment_method,
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        ).group_by(Order.payment_method)
    )
    payment_labels = {
        "dinheiro": "Dinheiro",
        "pix": "Pix",
        "cartao_debito": "Cartão Débito",
        "cartao_credito": "Cartão Crédito",
        "nao_informado": "Não Informado",
    }
    by_payment = [
        {
            "method": method or "nao_informado",
            "label": payment_labels.get(method or "nao_informado", method or "Não Informado"),
            "total": round(float(total), 2),
            "count": count,
        }
        for method, total, count in payment_result.all()
    ]

    # Resumo
    summary_result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
    )
    total_sales, orders_count = summary_result.one()
    ticket_medio = round(float(total_sales) / orders_count, 2) if orders_count else 0.0

    if format.lower() == "csv":
        headers = ["Nome", "Quantidade", "Total"]
        rows = [[p["name"], p["quantity"], p["total"]] for p in by_product]
        return _csv_response("dashboard_vendas_produtos.csv", headers, rows)

    return {
        "period": {"start": start_local.isoformat(), "end": end_local.isoformat()},
        "summary": {
            "total_sales": round(float(total_sales), 2),
            "orders_count": orders_count,
            "ticket_medio": ticket_medio,
        },
        "sales_by_day": sales_by_day,
        "by_category": by_category,
        "by_product": by_product,
        "by_waiter": by_waiter,
        "by_table": by_table,
        "by_payment": by_payment,
    }


@router.get("/estoque")
async def dashboard_estoque(
    format: str = Query("json"),
    table_id: int | None = Query(None),
    product_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _require_manager(user):
        return {"error": "Acesso restrito ao gerente"}

    products_result = await db.execute(select(Product).options(selectinload(Product.pack_unit_product)))
    products = products_result.scalars().all()

    status_counts = {"em_conformidade": 0, "em_risco": 0, "em_falta": 0}
    risk_items = []
    out_items = []
    total_stock_cost = 0.0

    for p in products:
        status = stock_status(p)
        status_counts[status] = status_counts.get(status, 0) + 1
        current_stock = pack_stock_for_product(p) if is_pack(p) else p.stock
        cost = float(p.cost) if p.cost else 0.0
        total_stock_cost += cost * current_stock

        item = {
            "id": p.id,
            "name": p.name,
            "category": p.category,
            "stock": current_stock,
            "min_stock": p.min_stock,
            "cost": cost,
            "status": status,
        }
        if status == "em_risco":
            risk_items.append(item)
        elif status == "em_falta":
            out_items.append(item)

    # Últimas movimentações
    movements_query = (
        select(StockHistory, Product)
        .join(Product, StockHistory.product_id == Product.id)
        .order_by(StockHistory.created_at.desc())
    )
    if table_id is not None:
        movements_query = movements_query.where(StockHistory.table_id == table_id)
    if product_id is not None:
        movements_query = movements_query.where(StockHistory.product_id == product_id)

    total_movements_result = await db.execute(
        select(func.count(StockHistory.id)).select_from(movements_query.subquery())
    )
    total_movements = total_movements_result.scalar_one()

    offset = (page - 1) * page_size
    movements_result = await db.execute(movements_query.offset(offset).limit(page_size))
    recent_movements = []
    for history, product in movements_result.all():
        recent_movements.append({
            "id": history.id,
            "product_name": product.name if product else "N/A",
            "type": history.type,
            "quantity": history.quantity,
            "note": history.note,
            "created_at": history.created_at.isoformat() if history.created_at else None,
        })

    if format.lower() == "csv":
        headers = ["ID", "Nome", "Categoria", "Estoque", "Minimo", "Custo", "Status"]
        rows = []
        for p in products:
            status = stock_status(p)
            current_stock = pack_stock_for_product(p) if is_pack(p) else p.stock
            rows.append([
                p.id,
                p.name,
                p.category,
                current_stock,
                p.min_stock,
                float(p.cost) if p.cost else 0.0,
                status,
            ])
        return _csv_response("dashboard_estoque.csv", headers, rows)

    return {
        "status_counts": status_counts,
        "total_stock_cost": round(total_stock_cost, 2),
        "risk_items": sorted(risk_items, key=lambda x: x["stock"])[:20],
        "out_items": sorted(out_items, key=lambda x: x["stock"])[:20],
        "recent_movements": recent_movements,
        "movements_pagination": {
            "page": page,
            "page_size": page_size,
            "total": total_movements,
            "total_pages": max(1, (total_movements + page_size - 1) // page_size),
        },
    }


@router.get("/clientes")
async def dashboard_clientes(
    format: str = Query("json"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _require_manager(user):
        return {"error": "Acesso restrito ao gerente"}

    # Consignados pendentes
    pending_result = await db.execute(
        select(ConsignmentOrder, Customer)
        .outerjoin(Customer, ConsignmentOrder.customer_id == Customer.id)
        .where(
            ConsignmentOrder.status != "cancelado",
            ConsignmentOrder.balance > 0,
        )
        .options(selectinload(ConsignmentOrder.items))
        .order_by(ConsignmentOrder.balance.desc())
    )
    pending_consignments = []
    total_pending = 0.0
    for c, customer in pending_result.all():
        total_pending += float(c.balance)
        pending_consignments.append({
            "id": c.id,
            "customer_name": customer.name if customer else (c.customer_name or "N/A"),
            "total": float(c.total),
            "balance": float(c.balance),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })

    # Top clientes por consumo
    top_customers_result = await db.execute(
        select(
            Customer.id,
            Customer.name,
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        )
        .join(Order, Order.customer_id == Customer.id)
        .where(Order.status == "finalizada")
        .group_by(Customer.id, Customer.name)
        .order_by(func.coalesce(func.sum(Order.total), 0.0).desc())
        .limit(10)
    )
    top_customers = [
        {"id": cid, "name": name, "total": round(float(total), 2), "orders": count}
        for cid, name, total, count in top_customers_result.all()
    ]

    # Aniversariantes do mês
    today = date.today()
    month = today.month
    birthday_result = await db.execute(
        select(Customer).where(
            Customer.birth_date.isnot(None),
            extract("month", Customer.birth_date) == month,
        )
    )
    birthdays = [
        {
            "id": c.id,
            "name": c.name,
            "birth_date": c.birth_date.isoformat() if c.birth_date else None,
            "phone": c.phone,
        }
        for c in birthday_result.scalars().all()
    ]

    if format.lower() == "csv":
        headers = ["ID Consignado", "Cliente", "Total", "Saldo Devedor", "Data"]
        rows = [
            [c["id"], c["customer_name"], c["total"], c["balance"], c["created_at"]]
            for c in pending_consignments
        ]
        return _csv_response("dashboard_clientes.csv", headers, rows)

    return {
        "pending_total": round(total_pending, 2),
        "pending_count": len(pending_consignments),
        "pending_consignments": pending_consignments[:20],
        "top_customers": top_customers,
        "birthdays": birthdays,
    }


@router.get("/funcionarios")
async def dashboard_funcionarios(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    format: str = Query("json"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _require_manager(user):
        return {"error": "Acesso restrito ao gerente"}

    start_dt, end_dt, start_local, end_local = _parse_dates(start_date, end_date, default_days=7)

    # Vendas por garçom
    waiter_result = await db.execute(
        select(
            User.id,
            User.name,
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        )
        .join(Order, Order.waiter_id == User.id)
        .where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .group_by(User.id, User.name)
        .order_by(func.coalesce(func.sum(Order.total), 0.0).desc())
    )
    by_waiter = []
    for uid, name, total, count in waiter_result.all():
        by_waiter.append({
            "id": uid,
            "name": name,
            "total": round(float(total), 2),
            "orders": count,
            "ticket_medio": round(float(total) / count, 2) if count else 0.0,
        })

    # Vendas por hora (horário de pico)
    hour_expr = func.to_char(func.timezone("America/Sao_Paulo", Order.closed_at), "HH24:00").label("hour")
    hour_result = await db.execute(
        select(
            hour_expr,
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        ).group_by(hour_expr)
        .order_by(hour_expr)
    )
    by_hour = [
        {"hour": hour, "total": round(float(total), 2), "orders": count}
        for hour, total, count in hour_result.all()
    ]

    if format.lower() == "csv":
        headers = ["ID", "Nome", "Total", "Comandas", "Ticket Medio"]
        rows = [[w["id"], w["name"], w["total"], w["orders"], w["ticket_medio"]] for w in by_waiter]
        return _csv_response("dashboard_funcionarios.csv", headers, rows)

    return {
        "period": {"start": start_local.isoformat(), "end": end_local.isoformat()},
        "by_waiter": by_waiter,
        "by_hour": by_hour,
    }
