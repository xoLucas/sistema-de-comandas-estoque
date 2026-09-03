from datetime import datetime, date, timezone, timedelta
from collections import defaultdict
from io import StringIO
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select, func, cast, Date, or_, extract, case, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, aliased

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
from app.models.employee import Employee
from app.models.consignment import ConsignmentOrder, ConsignmentOrderItem, ConsignmentPayment
from app.models.cash_register_session import CashRegisterSession
from app.models.cash_register_movement import CashRegisterMovement
from app.models.expense import Expense
from app.models.stock_history import StockHistory
from app.models.cash_position_movement import CashPositionMovement
from app.routers.auth_deps import get_current_user
from app.routers.financial import compute_period_profit
from app.services.stock_service import stock_status, is_pack, pack_stock_for_product
from app.services.consignment_service import fetch_consignment_payments

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
            func.coalesce(func.sum(Order.service_charge_amount), 0.0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
    )
    sales_total, service_charge, sales_count = sales_result.one()

    # Pagamentos de consignação recebidos no período (só contam como faturamento)
    consignment_payments = await fetch_consignment_payments(start_dt, end_dt, db)
    consignment_paid_total = sum(float(p.amount) for p in consignment_payments)

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
        select(CashRegisterSession)
        .where(CashRegisterSession.status == "open")
        .options(selectinload(CashRegisterSession.opened_by))
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
    products_result = await db.execute(
        select(Product).options(selectinload(Product.pack_unit_product))
    )
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

    # Merge pagamentos de consignação nas vendas por hora
    consignment_hours: dict[str, float] = {}
    for p in consignment_payments:
        if p.created_at:
            hour_key = as_local(p.created_at).strftime("%H:00")
            consignment_hours[hour_key] = consignment_hours.get(hour_key, 0.0) + float(p.amount)
    sales_by_hour_map = {item["hour"]: item for item in sales_by_hour}
    for hour_key, amount in consignment_hours.items():
        if hour_key in sales_by_hour_map:
            sales_by_hour_map[hour_key]["total"] = round(sales_by_hour_map[hour_key]["total"] + amount, 2)
        else:
            sales_by_hour_map[hour_key] = {"hour": hour_key, "total": round(amount, 2), "orders": 0}
    sales_by_hour = [sales_by_hour_map[k] for k in sorted(sales_by_hour_map.keys())]

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

    # Merge pagamentos de consignação nas formas de pagamento
    consignment_methods: dict[str, float] = {}
    for p in consignment_payments:
        method = p.payment_method or "nao_informado"
        consignment_methods[method] = consignment_methods.get(method, 0.0) + float(p.amount)
    for method, amount in consignment_methods.items():
        existing = next((pm for pm in payment_methods if pm["method"] == method), None)
        if existing:
            existing["total"] = round(existing["total"] + amount, 2)
            existing["count"] += 1
        else:
            payment_methods.append({
                "method": method,
                "label": payment_labels.get(method, method or "Não Informado"),
                "total": round(amount, 2),
                "count": 1,
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

    # Merge itens dos consignados pagos no top produtos
    processed_consignment_ids: set[int] = set()
    consignment_product_totals: dict[str, dict] = {}
    for p in consignment_payments:
        consignment = p.consignment_order
        if not consignment or consignment.id in processed_consignment_ids:
            continue
        processed_consignment_ids.add(consignment.id)
        for item in consignment.items:
            product = item.product
            if not product:
                continue
            entry = consignment_product_totals.setdefault(product.name, {"quantity": 0, "total": 0.0})
            entry["quantity"] += item.quantity
            entry["total"] += float(item.unit_price or 0) * item.quantity
    top_product_map = {item["name"]: item for item in top_products}
    for name, entry in consignment_product_totals.items():
        if name in top_product_map:
            top_product_map[name]["quantity"] += entry["quantity"]
            top_product_map[name]["total"] = round(top_product_map[name]["total"] + entry["total"], 2)
        else:
            top_product_map[name] = {
                "name": name,
                "quantity": entry["quantity"],
                "total": round(entry["total"], 2),
            }
    top_products = sorted(top_product_map.values(), key=lambda x: x["total"], reverse=True)[:10]

    if format.lower() == "csv":
        headers = [
            "Indicador", "Valor", "Periodo Inicio", "Periodo Fim"
        ]
        rows = [
            ["Faturamento", round(float(sales_total) + consignment_paid_total, 2), start_local.isoformat(), end_local.isoformat()],
            ["Pagamentos de Consignados", round(float(consignment_paid_total), 2), start_local.isoformat(), end_local.isoformat()],
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
            "total": round(float(sales_total) + consignment_paid_total, 2),
            "service_charge": round(float(service_charge), 2),
            "orders_count": sales_count,
            "consignment_paid": round(float(consignment_paid_total), 2),
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

    # Pagamentos de consignação recebidos no período (só pagos contam como faturamento)
    consignment_payments = await fetch_consignment_payments(start_dt, end_dt, db)
    consignment_paid_total = sum(float(p.amount) for p in consignment_payments)

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

    # Merge pagamentos de consignação nas vendas por dia
    consignment_by_day: dict[str, float] = {}
    for p in consignment_payments:
        if p.created_at:
            day_key = as_local(p.created_at).date().isoformat()
            consignment_by_day[day_key] = consignment_by_day.get(day_key, 0.0) + float(p.amount)
    sales_by_day_map = {item["date"]: item for item in sales_by_day}
    for day_key, amount in consignment_by_day.items():
        if day_key in sales_by_day_map:
            sales_by_day_map[day_key]["total"] = round(sales_by_day_map[day_key]["total"] + amount, 2)
        else:
            sales_by_day_map[day_key] = {"date": day_key, "total": round(amount, 2), "orders": 0}
    sales_by_day = [sales_by_day_map[k] for k in sorted(sales_by_day_map.keys())]

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
    waiter_user = aliased(User)
    closer_user = aliased(User)
    waiter_name_expr = func.coalesce(
        Employee.name,
        case(
            (closer_user.role != "gerente", closer_user.name),
            else_=waiter_user.name,
        ),
    )
    waiter_result = await db.execute(
        select(
            waiter_name_expr,
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        )
        .join(waiter_user, Order.waiter_id == waiter_user.id)
        .join(closer_user, Order.closed_by_id == closer_user.id)
        .outerjoin(Employee, Order.closed_waiter_id == Employee.id)
        .where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .group_by(waiter_name_expr)
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
            Table.name,
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
        .group_by(Table.id, Table.number, Table.name, Table.is_balcao)
        .order_by(func.coalesce(func.sum(Order.total), 0.0).desc())
    )
    by_table = []
    for tid, number, name, is_balcao_flag, total, count in table_result.all():
        label = "Balcão" if is_balcao_flag else (name or f"Mesa {number}")
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

    # Merge pagamentos de consignação nas agregações (só pagamentos contam)
    processed_consignment_ids: set[int] = set()
    consignment_product_totals: dict[str, dict] = {}
    for p in consignment_payments:
        method = p.payment_method or "nao_informado"
        existing_payment = next((b for b in by_payment if b["method"] == method), None)
        if existing_payment:
            existing_payment["total"] = round(existing_payment["total"] + float(p.amount), 2)
            existing_payment["count"] += 1
        else:
            by_payment.append({
                "method": method,
                "label": payment_labels.get(method, method or "Não Informado"),
                "total": round(float(p.amount), 2),
                "count": 1,
            })
        consignment = p.consignment_order
        if not consignment or consignment.id in processed_consignment_ids:
            continue
        processed_consignment_ids.add(consignment.id)
        for item in consignment.items:
            product = item.product
            if not product:
                continue
            entry = consignment_product_totals.setdefault(product.name, {"quantity": 0, "total": 0.0, "category": product.category})
            entry["quantity"] += item.quantity
            entry["total"] += float(item.unit_price or 0) * item.quantity

    # Merge em by_product
    by_product_map = {prod["name"]: prod for prod in by_product}
    for name, entry in consignment_product_totals.items():
        if name in by_product_map:
            by_product_map[name]["quantity"] += entry["quantity"]
            by_product_map[name]["total"] = round(by_product_map[name]["total"] + entry["total"], 2)
        else:
            by_product_map[name] = {
                "name": name,
                "quantity": entry["quantity"],
                "total": round(entry["total"], 2),
            }
    by_product = sorted(by_product_map.values(), key=lambda x: x["total"], reverse=True)

    # Merge em by_category
    consignment_category_totals: dict[str, dict] = {}
    for entry in consignment_product_totals.values():
        cat = entry["category"]
        cat_entry = consignment_category_totals.setdefault(cat, {"quantity": 0, "total": 0.0})
        cat_entry["quantity"] += entry["quantity"]
        cat_entry["total"] += entry["total"]
    by_category_map = {c["category"]: c for c in by_category}
    for cat, entry in consignment_category_totals.items():
        if cat in by_category_map:
            by_category_map[cat]["quantity"] += entry["quantity"]
            by_category_map[cat]["total"] = round(by_category_map[cat]["total"] + entry["total"], 2)
        else:
            by_category_map[cat] = {
                "category": cat,
                "quantity": entry["quantity"],
                "total": round(entry["total"], 2),
            }
    by_category = sorted(by_category_map.values(), key=lambda x: x["total"], reverse=True)

    # Merge em by_waiter (atribuído ao garçom do consignado)
    consignment_waiter_totals: dict[str, float] = {}
    for p in consignment_payments:
        consignment = p.consignment_order
        if not consignment or not consignment.waiter:
            consignment_waiter_totals["N/A"] = consignment_waiter_totals.get("N/A", 0.0) + float(p.amount)
            continue
        waiter_name = consignment.waiter.name or "N/A"
        consignment_waiter_totals[waiter_name] = consignment_waiter_totals.get(waiter_name, 0.0) + float(p.amount)
    by_waiter_map = {w["name"]: w for w in by_waiter}
    for waiter_name, amount in consignment_waiter_totals.items():
        if waiter_name in by_waiter_map:
            by_waiter_map[waiter_name]["total"] = round(by_waiter_map[waiter_name]["total"] + amount, 2)
        else:
            by_waiter_map[waiter_name] = {"name": waiter_name, "total": round(amount, 2), "orders": 0}
    by_waiter = sorted(by_waiter_map.values(), key=lambda x: x["total"], reverse=True)

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
            "total_sales": round(float(total_sales) + consignment_paid_total, 2),
            "orders_count": orders_count,
            "ticket_medio": ticket_medio,
            "consignment_paid": round(float(consignment_paid_total), 2),
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

    # Merge pagamentos de consignação por cliente (só pagamentos contam)
    consignment_payments = await fetch_consignment_payments(
        datetime.min.replace(tzinfo=timezone.utc),
        datetime.max.replace(tzinfo=timezone.utc),
        db,
    )
    consignment_customer_totals: dict[int, float] = {}
    for p in consignment_payments:
        consignment = p.consignment_order
        if not consignment or not consignment.customer_id:
            continue
        consignment_customer_totals[consignment.customer_id] = (
            consignment_customer_totals.get(consignment.customer_id, 0.0) + float(p.amount)
        )
    top_customers_map = {c["id"]: c for c in top_customers}
    for customer_id, amount in consignment_customer_totals.items():
        if customer_id in top_customers_map:
            top_customers_map[customer_id]["total"] = round(top_customers_map[customer_id]["total"] + amount, 2)
        else:
            customer_result = await db.execute(select(Customer).where(Customer.id == customer_id))
            customer = customer_result.scalars().first()
            if customer:
                top_customers_map[customer_id] = {
                    "id": customer.id,
                    "name": customer.name,
                    "total": round(amount, 2),
                    "orders": 0,
                }
    top_customers = sorted(top_customers_map.values(), key=lambda x: x["total"], reverse=True)[:10]

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

    # Pagamentos de consignação recebidos no período
    consignment_payments = await fetch_consignment_payments(start_dt, end_dt, db)

    # Vendas por garçom
    waiter_user = aliased(User)
    closer_user = aliased(User)
    waiter_id_expr = func.coalesce(
        Employee.id,
        case(
            (closer_user.role != "gerente", closer_user.id),
            else_=waiter_user.id,
        ),
    )
    waiter_name_expr = func.coalesce(
        Employee.name,
        case(
            (closer_user.role != "gerente", closer_user.name),
            else_=waiter_user.name,
        ),
    )
    waiter_result = await db.execute(
        select(
            waiter_id_expr,
            waiter_name_expr,
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
        )
        .join(waiter_user, Order.waiter_id == waiter_user.id)
        .join(closer_user, Order.closed_by_id == closer_user.id)
        .outerjoin(Employee, Order.closed_waiter_id == Employee.id)
        .where(
            Order.status == "finalizada",
            Order.closed_at >= start_dt,
            Order.closed_at <= end_dt,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .group_by(waiter_id_expr, waiter_name_expr)
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

    # Merge pagamentos de consignação por garçom
    consignment_waiter_totals: dict[str, float] = {}
    for p in consignment_payments:
        consignment = p.consignment_order
        if not consignment or not consignment.waiter:
            consignment_waiter_totals["N/A"] = consignment_waiter_totals.get("N/A", 0.0) + float(p.amount)
            continue
        waiter_name = consignment.waiter.name or "N/A"
        consignment_waiter_totals[waiter_name] = consignment_waiter_totals.get(waiter_name, 0.0) + float(p.amount)
    by_waiter_map = {w["name"]: w for w in by_waiter}
    for waiter_name, amount in consignment_waiter_totals.items():
        if waiter_name in by_waiter_map:
            by_waiter_map[waiter_name]["total"] = round(by_waiter_map[waiter_name]["total"] + amount, 2)
        else:
            by_waiter_map[waiter_name] = {
                "id": None,
                "name": waiter_name,
                "total": round(amount, 2),
                "orders": 0,
                "ticket_medio": 0.0,
            }
    by_waiter = sorted(by_waiter_map.values(), key=lambda x: x["total"], reverse=True)

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

    # Merge pagamentos de consignação por hora
    consignment_hours: dict[str, float] = {}
    for p in consignment_payments:
        if p.created_at:
            hour_key = as_local(p.created_at).strftime("%H:00")
            consignment_hours[hour_key] = consignment_hours.get(hour_key, 0.0) + float(p.amount)
    by_hour_map = {item["hour"]: item for item in by_hour}
    for hour_key, amount in consignment_hours.items():
        if hour_key in by_hour_map:
            by_hour_map[hour_key]["total"] = round(by_hour_map[hour_key]["total"] + amount, 2)
        else:
            by_hour_map[hour_key] = {"hour": hour_key, "total": round(amount, 2), "orders": 0}
    by_hour = [by_hour_map[k] for k in sorted(by_hour_map.keys())]

    if format.lower() == "csv":
        headers = ["ID", "Nome", "Total", "Comandas", "Ticket Medio"]
        rows = [[w["id"], w["name"], w["total"], w["orders"], w["ticket_medio"]] for w in by_waiter]
        return _csv_response("dashboard_funcionarios.csv", headers, rows)

    return {
        "period": {"start": start_local.isoformat(), "end": end_local.isoformat()},
        "by_waiter": by_waiter,
        "by_hour": by_hour,
    }


@router.get("/gestao")
async def dashboard_gestao(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    format: str = Query("json"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not _require_manager(user):
        return {"error": "Acesso restrito ao gerente"}

    start_dt, end_dt, start_local, end_local = _parse_dates(start_date, end_date, default_days=7)
    profit = await compute_period_profit(start_dt, end_dt, db)

    totals_result = await db.execute(
        select(CashPositionMovement.type, func.sum(CashPositionMovement.amount))
        .group_by(CashPositionMovement.type)
    )
    totals = {t: float(a or 0) for t, a in totals_result.all()}
    cash_position = round(totals.get("entrada", 0.0) - totals.get("saida", 0.0), 2)

    count_result = await db.execute(select(func.count(CashPositionMovement.id)))
    total = int(count_result.scalar_one())

    offset = (page - 1) * page_size
    movements_result = await db.execute(
        select(CashPositionMovement)
        .options(selectinload(CashPositionMovement.created_by))
        .order_by(desc(CashPositionMovement.created_at), desc(CashPositionMovement.id))
        .offset(offset)
        .limit(page_size)
    )
    movements = movements_result.scalars().all()

    movements_payload = [
        {
            "id": m.id,
            "type": m.type,
            "source": m.source,
            "title": m.title,
            "amount": float(m.amount),
            "observation": m.observation,
            "created_by": m.created_by.name if m.created_by else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in movements
    ]

    if format.lower() == "csv":
        headers = ["Tipo", "Origem", "Título", "Valor", "Observação", "Usuário", "Data"]
        rows = [
            [
                m["type"], m["source"], m["title"], m["amount"],
                m["observation"] or "", m["created_by"] or "", m["created_at"] or "",
            ]
            for m in movements_payload
        ]
        return _csv_response("dashboard_gestao.csv", headers, rows)

    return {
        "period": {"start": start_local.isoformat(), "end": end_local.isoformat()},
        "net_profit": profit["net_profit"],
        "gross_profit": profit["gross_profit"],
        "total_sales": profit["total_sales"],
        "total_cogs": profit["total_cogs"],
        "total_card_fees": profit["total_card_fees"],
        "total_expenses": profit["total_expenses"],
        "cash_position": cash_position,
        "movements": movements_payload,
        "movements_pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        },
    }
