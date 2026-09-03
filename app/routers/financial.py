from datetime import datetime, date, timezone, timedelta
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func, extract, cast, Date, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fpdf import FPDF
import io

from app.core.database import get_db
from app.core.timezone import (
    as_local,
    ensure_utc,
    format_local_date,
    format_local_period,
    local_datetime_str,
    local_hour_label,
    local_day_to_utc_range,
    parse_local_date,
    today_local,
)
from app.models.order import Order
from app.models.table import Table
from app.models.user import User
from app.models.customer import Customer
from app.models.expense import Expense
from app.models.cash_register_session import CashRegisterSession
from app.models.cash_register_movement import CashRegisterMovement
from app.models.stock_history import StockHistory
from app.models.consignment import ConsignmentOrder, ConsignmentOrderItem, ConsignmentPayment
from app.routers.auth_deps import get_current_user, can_view_financial
from app.services.settings_service import get_setting_as_float, get_card_fee_for_machine
from app.services.cash_service import compute_session_cash_summary

router = APIRouter(prefix="/api/financeiro", tags=["financeiro"])


from app.models.order_item import OrderItem
from app.models.product import Product


def _resolve_waiter_name(order: Order) -> str:
    """Resolve the waiter credited for a closed order.

    - Explicitly selected employee (manager override) always wins.
    - A non-manager closer (garçom/caixa/estoquista) is credited themselves.
    - A manager closing without selecting anyone credits the waiter who opened.
    """
    if order.closed_waiter:
        return order.closed_waiter.name
    if order.closed_by and order.closed_by.role != "gerente":
        return order.closed_by.name
    if order.waiter:
        return order.waiter.name
    if order.closed_by:
        return order.closed_by.name
    return "N/A"


def serialize_order_sale(order: Order) -> dict:
    """Serialize a finalized order into the same shape returned by /financeiro/vendas.

    The order must have its relationships loaded (table, waiter, closed_by,
    closed_waiter, customer and items -> product).
    """
    product_remaining = max(0.0, order.total - order.partial_payment)
    service_remaining = (
        product_remaining * (order.service_charge_pct / 100)
        if order.service_charge_applied
        else 0.0
    )
    service_amount = order.service_charge_amount
    final = product_remaining + service_remaining

    payment_method_label = PAYMENT_LABELS.get(
        order.payment_method or "nao_informado", order.payment_method or "Não Informado"
    )
    payment_details = []
    for idx, pd in enumerate(order.partial_payments_detail or [], start=1):
        p_method = pd.get("method", "nao_informado")
        payment_details.append({
            "type": "parcial",
            "index": idx,
            "method": p_method,
            "method_label": PAYMENT_LABELS.get(p_method, p_method),
            "amount": round(float(pd.get("amount", 0)), 2),
            "product_portion": round(float(pd.get("product_portion", pd.get("amount", 0))), 2),
            "service_portion": round(float(pd.get("service_portion", 0)), 2),
            "card_machine": pd.get("card_machine"),
            "apply_service_charge": pd.get("apply_service_charge", False),
            "created_at": pd.get("created_at"),
        })
    payment_details.append({
        "type": "final",
        "method": order.payment_method or "nao_informado",
        "method_label": payment_method_label,
        "amount": round(float(final), 2),
        "card_machine": order.card_machine,
    })

    return {
        "order_id": order.id,
        "table_number": order.table.number if order.table else 0,
        "table_label": order.table.label if order.table else "",
        "is_balcao": order.table.is_balcao if order.table else False,
        "waiter_name": _resolve_waiter_name(order),
        "customer_id": order.customer_id,
        "customer_name": order.customer_name or (order.customer.name if order.customer else None),
        "items_count": sum(item.quantity for item in order.items),
        "total": float(order.total),
        "service_charge_pct": float(order.service_charge_pct),
        "service_charge_amount": round(float(service_amount), 2),
        "partial_payment": float(order.partial_payment),
        "partial_service_charge": float(order.partial_service_charge),
        "final_total": float(final),
        "payment_method": order.payment_method or "nao_informado",
        "payment_method_label": payment_method_label,
        "card_machine": order.card_machine,
        "closed_at": order.closed_at.isoformat() if order.closed_at else None,
        "items": [
            {
                "product_name": item.product.name if item.product else "N/A",
                "quantity": item.quantity,
                "unit_price": float(item.unit_price),
                "total": round(float(item.unit_price) * item.quantity, 2),
            }
            for item in order.items
        ],
        "payment_details": payment_details,
    }


async def compute_session_close_metrics(session, db: AsyncSession) -> dict:
    """Compute the faturamento/card-fees/service-charge for a closed session.

    Mirrors the summary computed by _build_session_report but returns only the
    three values needed to feed the cash position movements on close.
    """
    start = session.opened_at
    end = session.closed_at or datetime.now(timezone.utc)
    card_fee_rates = await _get_card_fee_rates(db)

    result = await db.execute(
        select(Order).where(
            Order.status == "finalizada",
            Order.closed_at >= start,
            Order.closed_at <= end,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
    )
    orders = result.scalars().all()

    gross_total = 0.0
    card_fees = 0.0
    service_charge = 0.0

    for o in orders:
        product_remaining = max(0.0, o.total - o.partial_payment)
        service_remaining = (
            product_remaining * (o.service_charge_pct / 100)
            if o.service_charge_applied
            else 0.0
        )
        final = product_remaining + service_remaining
        close_method = o.payment_method or "nao_informado"

        gross_total += final
        card_fees += await _card_fee_for_order_payment(
            final, close_method, o.card_machine, db, card_fee_rates
        )
        service_charge += o.service_charge_amount

        for pd in o.partial_payments_detail or []:
            p_amount = float(pd.get("amount", 0))
            if p_amount <= 0:
                continue
            gross_total += p_amount
            card_fees += await _card_fee_for_order_payment(
                p_amount, pd.get("method", "nao_informado"), pd.get("card_machine"), db, card_fee_rates
            )

    consignment_result = await db.execute(
        select(ConsignmentPayment).where(
            ConsignmentPayment.created_at >= start,
            ConsignmentPayment.created_at <= end,
        )
    )
    for payment in consignment_result.scalars().all():
        amount = float(payment.amount)
        gross_total += amount
        card_fees += await _card_fee_for_order_payment(
            amount, payment.payment_method or "nao_informado", payment.card_machine, db, card_fee_rates
        )

    return {
        "gross_total": round(gross_total, 2),
        "card_fees": round(card_fees, 2),
        "service_charge": round(service_charge, 2),
    }


async def compute_period_profit(start: datetime, end: datetime, db: AsyncSession) -> dict:
    """Compute profit metrics for an arbitrary period (same semantics as the reports)."""
    card_fee_rates = await _get_card_fee_rates(db)

    orders_result = await db.execute(
        select(Order)
        .where(
            Order.status == "finalizada",
            Order.closed_at >= start,
            Order.closed_at <= end,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .options(selectinload(Order.items).selectinload(OrderItem.product))
    )
    orders = orders_result.scalars().all()

    total_sales = 0.0
    total_cogs = 0.0
    total_card_fees = 0.0

    for o in orders:
        total_sales += o.total
        total_cogs += sum(
            ((item.unit_cost if item.unit_cost is not None else (item.product.cost if item.product else 0.0)) * item.quantity)
            for item in o.items
        )

        product_remaining = max(0.0, o.total - o.partial_payment)
        service_remaining = (
            product_remaining * (o.service_charge_pct / 100)
            if o.service_charge_applied
            else 0.0
        )
        final = product_remaining + service_remaining
        close_method = o.payment_method or "nao_informado"
        total_card_fees += await _card_fee_for_order_payment(
            final, close_method, o.card_machine, db, card_fee_rates
        )

        for pd in o.partial_payments_detail or []:
            p_amount = float(pd.get("amount", 0))
            if p_amount <= 0:
                continue
            total_card_fees += await _card_fee_for_order_payment(
                p_amount, pd.get("method", "nao_informado"), pd.get("card_machine"), db, card_fee_rates
            )

    consignment_result = await db.execute(
        select(ConsignmentPayment).where(
            ConsignmentPayment.created_at >= start,
            ConsignmentPayment.created_at <= end,
        )
    )
    for payment in consignment_result.scalars().all():
        amount = float(payment.amount)
        total_sales += amount
        total_card_fees += await _card_fee_for_order_payment(
            amount, payment.payment_method or "nao_informado", payment.card_machine, db, card_fee_rates
        )

    expenses_result = await db.execute(
        select(Expense).where(Expense.expense_date >= start, Expense.expense_date <= end)
    )
    total_expenses = sum(float(e.amount) for e in expenses_result.scalars().all())
    _, perdas_total = await _get_perdas(start, end, db)
    total_expenses = round(total_expenses + perdas_total, 2)

    gross_profit = round(total_sales - total_cogs, 2)
    net_profit = round(gross_profit - total_card_fees - total_expenses, 2)

    return {
        "total_sales": round(total_sales, 2),
        "total_cogs": round(total_cogs, 2),
        "gross_profit": gross_profit,
        "total_card_fees": round(total_card_fees, 2),
        "total_expenses": total_expenses,
        "net_profit": net_profit,
    }


async def _get_perdas(
    start: datetime,
    end: datetime,
    db: AsyncSession,
) -> tuple[list[dict], float]:
    """Return manual stock exits (losses) in the period and their total cost."""
    result = await db.execute(
        select(StockHistory, Product)
        .join(Product, StockHistory.product_id == Product.id)
        .where(
            StockHistory.type == "saida",
            StockHistory.order_id.is_(None),
            StockHistory.consignment_order_id.is_(None),
            StockHistory.created_at >= start,
            StockHistory.created_at <= end,
        )
        .order_by(StockHistory.created_at)
    )
    items = []
    total = 0.0
    for history, product in result.all():
        cost = float(product.cost) if product.cost else 0.0
        amount = round(cost * history.quantity, 2)
        total += amount
        items.append({
            "id": f"perda_{history.id}",
            "description": f"Perda: {product.name} ({history.quantity} un.)",
            "amount": amount,
            "category": "perdas",
            "expense_date": _fmt_datetime(history.created_at),
            "quantity": history.quantity,
            "product_name": product.name,
            "note": history.note,
        })
    return items, round(total, 2)


async def _add_consignment_payments_to_report(
    start: datetime,
    end: datetime,
    db: AsyncSession,
    report: dict,
    method_totals: dict,
    card_fee_rates: dict,
    hour_totals: dict | None = None,
    item_totals: dict | None = None,
) -> int:
    """Add consignment payments received in the period as revenue.

    Only paid installments count as revenue. The payment method is grouped
    together with regular sales (e.g. Dinheiro, Pix, Cartão).
    """
    result = await db.execute(
        select(ConsignmentPayment)
        .where(
            ConsignmentPayment.created_at >= start,
            ConsignmentPayment.created_at <= end,
        )
        .options(
            selectinload(ConsignmentPayment.consignment_order)
            .selectinload(ConsignmentOrder.items)
            .selectinload(ConsignmentOrderItem.product),
        )
    )
    payments = result.scalars().all()
    if not payments:
        return 0

    processed_consignment_ids = set()
    for payment in payments:
        consignment = payment.consignment_order
        amount = float(payment.amount)
        method = payment.payment_method or "nao_informado"
        card_machine = payment.card_machine

        fee = await _card_fee_for_order_payment(amount, method, card_machine, db, card_fee_rates)

        allocated_cogs = 0.0
        if consignment and consignment.total > 0:
            total_cogs = sum(
                (item.product.cost if item.product else 0.0) * item.quantity
                for item in consignment.items
            )
            allocated_cogs = round(total_cogs * (amount / consignment.total), 2)

        report["summary"]["total_sales"] += amount
        report["summary"]["total_cogs"] += allocated_cogs
        report["summary"]["gross_total"] += amount
        report["summary"]["total_card_fees"] += fee

        if method not in method_totals:
            method_totals[method] = {
                "gross": 0.0,
                "fee_pct": card_fee_rates.get(method, 0.0),
                "fee": 0.0,
                "net": 0.0,
                "count": 0,
            }
        method_totals[method]["gross"] += amount
        method_totals[method]["fee"] += fee
        method_totals[method]["net"] += amount - fee
        method_totals[method]["count"] += 1

        if hour_totals is not None and payment.created_at:
            hour_key = local_hour_label(payment.created_at)
            hour_totals[hour_key] += amount

        if item_totals is not None and consignment and consignment.id not in processed_consignment_ids:
            for item in consignment.items:
                product = item.product
                if not product:
                    continue
                item_totals[product.name]["quantity"] += item.quantity
                item_totals[product.name]["total"] += item.unit_price * item.quantity
            processed_consignment_ids.add(consignment.id)

    return len(payments)


async def _add_consignment_summary(
    start: datetime,
    end: datetime,
    db: AsyncSession,
    report: dict,
) -> None:
    """Add consignment totals/paid/balance to the report summary."""
    result = await db.execute(
        select(
            func.count(ConsignmentOrder.id),
            func.coalesce(func.sum(ConsignmentOrder.total), 0.0),
            func.coalesce(func.sum(ConsignmentOrder.amount_paid), 0.0),
            func.coalesce(func.sum(ConsignmentOrder.balance), 0.0),
        ).where(
            ConsignmentOrder.status != "cancelado",
            ConsignmentOrder.created_at >= start,
            ConsignmentOrder.created_at <= end,
        )
    )
    count, total, paid, balance = result.one()
    report["summary"]["consignments_count"] = int(count)
    report["summary"]["consignments_total"] = round(float(total), 2)
    report["summary"]["consignments_paid"] = round(float(paid), 2)
    report["summary"]["consignments_balance"] = round(float(balance), 2)


PAYMENT_LABELS = {
    "dinheiro": "Dinheiro",
    "pix": "Pix",
    "cartao_debito": "Cartão Débito",
    "cartao_credito": "Cartão Crédito",
    "nao_informado": "Não Informado",
}


def _method_label(method: str) -> str:
    return PAYMENT_LABELS.get(method, method)


def _fmt_datetime(value: str | datetime | None) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return local_datetime_str(value)


async def _get_card_fee_rates(db: AsyncSession) -> dict[str, float]:
    debit = await get_setting_as_float(db, "card_fee_debit_pct", 1.5)
    credit = await get_setting_as_float(db, "card_fee_credit_pct", 3.5)
    return {
        "dinheiro": 0.0,
        "pix": 0.0,
        "cartao_debito": debit,
        "cartao_credito": credit,
        "nao_informado": 0.0,
    }


def _card_fee_for_payment(amount: float, method: str, rates: dict[str, float]) -> float:
    return amount * (rates.get(method, 0.0) / 100)


async def _card_fee_for_order_payment(
    amount: float,
    method: str,
    card_machine: str | None,
    db: AsyncSession,
    default_rates: dict[str, float] | None = None,
) -> float:
    if method not in ("cartao_debito", "cartao_credito"):
        return 0.0
    rate = await get_card_fee_for_machine(db, card_machine, method, default_rates)
    return round(amount * (rate / 100), 2)


async def _build_daily_report(
    close_date: date, db: AsyncSession, closed_by: str
) -> dict:
    day_start, day_end = local_day_to_utc_range(close_date)

    result = await db.execute(
        select(Order)
        .where(
            Order.status == "finalizada",
            Order.closed_at >= day_start,
            Order.closed_at <= day_end,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .options(
            selectinload(Order.table),
            selectinload(Order.waiter),
            selectinload(Order.closed_by),
            selectinload(Order.closed_waiter),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .order_by(Order.closed_at)
    )
    orders = result.scalars().all()
    card_fee_rates = await _get_card_fee_rates(db)

    expenses_result = await db.execute(
        select(Expense).where(
            Expense.expense_date >= day_start,
            Expense.expense_date <= day_end,
        )
    )
    expenses = expenses_result.scalars().all()
    cash_expenses = sum(e.amount for e in expenses)

    perdas_items, perdas_total = await _get_perdas(day_start, day_end, db)
    total_expenses = round(cash_expenses + perdas_total, 2)

    if not orders and not expenses and not perdas_items:
        return {"error": "Nenhuma venda ou despesa encontrada nesta data"}

    report = {
        "date": format_local_date(close_date),
        "closed_by": closed_by,
        "generated_at": local_datetime_str(datetime.now(timezone.utc)),
        "orders": [],
        "summary": {
            "total_sales": 0.0,
            "total_cogs": 0.0,
            "gross_profit": 0.0,
            "total_service_charge": 0.0,
            "total_partial_payments": 0.0,
            "total_card_fees": 0.0,
            "total_expenses": round(float(total_expenses), 2),
            "perdas_total": perdas_total,
            "operating_expenses": 0.0,
            "net_profit": 0.0,
            "gross_total": 0.0,
            "net_total": 0.0,
            "orders_count": len(orders),
            "consignments_count": 0,
        },
        "by_payment_method": {},
        "by_waiter": {},
        "by_table": {},
        "by_hour": {},
        "items_ranking": [],
        "expenses": [
            {
                "id": e.id,
                "description": e.description,
                "amount": float(e.amount),
                "category": e.category,
                "expense_date": _fmt_datetime(e.expense_date),
            }
            for e in expenses
        ] + perdas_items,
    }

    method_totals = {}
    waiter_totals = defaultdict(lambda: {"service_charge": 0.0, "orders": 0, "sales": 0.0})
    table_totals = defaultdict(lambda: {"total": 0.0, "orders": 0})
    hour_totals = defaultdict(float)
    item_totals = defaultdict(lambda: {"quantity": 0, "total": 0.0})

    for o in orders:
        product_remaining = max(0.0, o.total - o.partial_payment)
        service_remaining = (
            product_remaining * (o.service_charge_pct / 100) if o.service_charge_applied else 0.0
        )
        service_amount = o.service_charge_amount
        final = product_remaining + service_remaining
        close_method = o.payment_method or "nao_informado"
        close_fee = await _card_fee_for_order_payment(final, close_method, o.card_machine, db, card_fee_rates)

        report["summary"]["total_sales"] += o.total
        report["summary"]["total_cogs"] += sum(
            ((item.unit_cost if item.unit_cost is not None else (item.product.cost if item.product else 0.0)) * item.quantity)
            for item in o.items
        )
        report["summary"]["total_service_charge"] += service_amount
        report["summary"]["total_partial_payments"] += o.partial_payment + o.partial_service_charge
        report["summary"]["total_card_fees"] += close_fee
        report["summary"]["gross_total"] += final

        waiter_name = _resolve_waiter_name(o)
        waiter_totals[waiter_name]["service_charge"] += service_amount
        waiter_totals[waiter_name]["orders"] += 1
        waiter_totals[waiter_name]["sales"] += o.total

        table_label = o.table.label if o.table else "Balcão"
        table_totals[table_label]["total"] += o.total
        table_totals[table_label]["orders"] += 1

        for item in o.items:
            item_totals[item.product.name]["quantity"] += item.quantity
            item_totals[item.product.name]["total"] += item.unit_price * item.quantity

        # Final payment grouped by the method chosen at close.
        if final > 0:
            close_hour = local_hour_label(o.closed_at) if o.closed_at else "00:00"
            hour_totals[close_hour] += final
            if close_method not in method_totals:
                method_totals[close_method] = {
                    "gross": 0.0,
                    "fee_pct": card_fee_rates.get(close_method, 0.0),
                    "fee": 0.0,
                    "net": 0.0,
                    "count": 0,
                }
            method_totals[close_method]["gross"] += final
            method_totals[close_method]["fee"] += close_fee
            method_totals[close_method]["net"] += final - close_fee
            method_totals[close_method]["count"] += 1

        # Partial payments grouped by their actual method and hour.
        for pd in o.partial_payments_detail or []:
            p_amount = float(pd.get("amount", 0))
            if p_amount <= 0:
                continue
            p_method = pd.get("method", "nao_informado")
            p_card_machine = pd.get("card_machine")
            p_fee = await _card_fee_for_order_payment(p_amount, p_method, p_card_machine, db, card_fee_rates)

            report["summary"]["total_card_fees"] += p_fee
            report["summary"]["gross_total"] += p_amount

            p_created_at = pd.get("created_at")
            if isinstance(p_created_at, str):
                try:
                    p_paid_at = datetime.fromisoformat(p_created_at)
                except ValueError:
                    p_paid_at = o.closed_at
            else:
                p_paid_at = p_created_at or o.closed_at
            p_hour = local_hour_label(p_paid_at) if p_paid_at else "00:00"
            hour_totals[p_hour] += p_amount

            if p_method not in method_totals:
                method_totals[p_method] = {
                    "gross": 0.0,
                    "fee_pct": card_fee_rates.get(p_method, 0.0),
                    "fee": 0.0,
                    "net": 0.0,
                    "count": 0,
                }
            method_totals[p_method]["gross"] += p_amount
            method_totals[p_method]["fee"] += p_fee
            method_totals[p_method]["net"] += p_amount - p_fee
            method_totals[p_method]["count"] += 1

        report["orders"].append(
            {
                "order_id": o.id,
                "table": table_label,
                "waiter": waiter_name,
                "total": float(o.total),
                "service_charge": round(service_amount, 2),
                "partial_payment": float(o.partial_payment),
                "partial_service_charge": float(o.partial_service_charge),
                "final_total": round(final, 2),
                "payment_method": close_method,
                "closed_at": as_local(o.closed_at).strftime("%H:%M") if o.closed_at else "",
            }
        )

    await _add_consignment_payments_to_report(
        day_start, day_end, db, report, method_totals, card_fee_rates, hour_totals, item_totals
    )
    await _add_consignment_summary(day_start, day_end, db, report)

    report["summary"]["total_sales"] = round(report["summary"]["total_sales"], 2)
    report["summary"]["total_cogs"] = round(report["summary"]["total_cogs"], 2)
    report["summary"]["gross_profit"] = round(
        report["summary"]["total_sales"] - report["summary"]["total_cogs"], 2
    )
    report["summary"]["total_service_charge"] = round(report["summary"]["total_service_charge"], 2)
    report["summary"]["total_partial_payments"] = round(report["summary"]["total_partial_payments"], 2)
    report["summary"]["total_card_fees"] = round(report["summary"]["total_card_fees"], 2)
    report["summary"]["total_expenses"] = round(report["summary"]["total_expenses"], 2)
    report["summary"]["operating_expenses"] = round(
        report["summary"]["total_card_fees"] + report["summary"]["total_expenses"], 2
    )
    report["summary"]["net_profit"] = round(
        report["summary"]["gross_profit"] - report["summary"]["operating_expenses"], 2
    )
    report["summary"]["gross_total"] = round(report["summary"]["gross_total"], 2)
    report["summary"]["net_total"] = round(
        report["summary"]["gross_total"]
        - report["summary"]["total_service_charge"]
        - report["summary"]["total_card_fees"]
        - report["summary"]["total_expenses"],
        2,
    )

    for method, values in method_totals.items():
        method_totals[method]["gross"] = round(values["gross"], 2)
        method_totals[method]["fee"] = round(values["fee"], 2)
        method_totals[method]["net"] = round(values["net"], 2)

    for waiter, values in waiter_totals.items():
        waiter_totals[waiter]["service_charge"] = round(values["service_charge"], 2)
        waiter_totals[waiter]["sales"] = round(values["sales"], 2)

    for table, values in table_totals.items():
        table_totals[table]["total"] = round(values["total"], 2)

    report["by_payment_method"] = method_totals
    report["by_waiter"] = dict(waiter_totals)
    report["by_table"] = dict(table_totals)
    report["by_hour"] = dict(sorted(hour_totals.items()))
    report["items_ranking"] = sorted(
        [
            {"name": k, "quantity": v["quantity"], "total": round(v["total"], 2)}
            for k, v in item_totals.items()
        ],
        key=lambda x: x["total"],
        reverse=True,
    )

    return report


async def _build_session_report(
    session: CashRegisterSession,
    start: datetime,
    end: datetime,
    report_type: str,
    db: AsyncSession,
    generated_by: str,
) -> dict:
    result = await db.execute(
        select(Order)
        .where(
            Order.status == "finalizada",
            Order.closed_at >= start,
            Order.closed_at <= end,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .options(
            selectinload(Order.table),
            selectinload(Order.waiter),
            selectinload(Order.closed_by),
            selectinload(Order.closed_waiter),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .order_by(Order.closed_at)
    )
    orders = result.scalars().all()
    card_fee_rates = await _get_card_fee_rates(db)

    expenses_result = await db.execute(
        select(Expense).where(
            Expense.expense_date >= start,
            Expense.expense_date <= end,
        )
    )
    expenses = expenses_result.scalars().all()
    cash_expenses = sum(e.amount for e in expenses)

    perdas_items, perdas_total = await _get_perdas(start, end, db)
    total_expenses = round(cash_expenses + perdas_total, 2)

    movements_result = await db.execute(
        select(CashRegisterMovement).where(CashRegisterMovement.session_id == session.id)
    )
    movements = movements_result.scalars().all()
    cash_summary = await compute_session_cash_summary(session, start, end, db, movements=movements)
    cash_summary["final_cash"] = float(session.final_cash) if session.final_cash is not None else None
    if cash_summary["final_cash"] is not None:
        cash_summary["discrepancy"] = round(
            cash_summary["final_cash"] - cash_summary["expected_cash"], 2
        )
    else:
        cash_summary["discrepancy"] = None

    report = {
        "report_type": report_type,
        "period": {
            "start": local_datetime_str(start),
            "end": local_datetime_str(end),
        },
        "session": {
            "id": session.id,
            "opened_at": session.opened_at.isoformat() if session.opened_at else None,
            "closed_at": session.closed_at.isoformat() if session.closed_at else None,
            "opened_by": session.opened_by.name if session.opened_by else "N/A",
            "closed_by": session.closed_by.name if session.closed_by else None,
            "initial_cash": float(session.initial_cash),
            "final_cash": float(session.final_cash) if session.final_cash is not None else None,
            "status": session.status,
            "observations": session.observations,
        },
        "generated_by": generated_by,
        "generated_at": local_datetime_str(datetime.now(timezone.utc)),
        "orders": [],
        "summary": {
            "total_sales": 0.0,
            "total_cogs": 0.0,
            "gross_profit": 0.0,
            "total_service_charge": 0.0,
            "total_partial_payments": 0.0,
            "total_card_fees": 0.0,
            "total_expenses": round(float(total_expenses), 2),
            "perdas_total": perdas_total,
            "operating_expenses": 0.0,
            "net_profit": 0.0,
            "gross_total": 0.0,
            "net_total": 0.0,
            "orders_count": len(orders),
            "consignments_count": 0,
        },
        "cash_summary": cash_summary,
        "movements": [
            {
                "id": m.id,
                "type": m.type,
                "amount": float(m.amount),
                "note": m.note,
                "created_at": _fmt_datetime(m.created_at),
            }
            for m in movements
        ],
        "by_payment_method": {},
        "by_waiter": {},
        "by_table": {},
        "by_hour": {},
        "items_ranking": [],
        "expenses": [
            {
                "id": e.id,
                "description": e.description,
                "amount": float(e.amount),
                "category": e.category,
                "expense_date": _fmt_datetime(e.expense_date),
            }
            for e in expenses
        ] + perdas_items,
    }

    method_totals = {}
    waiter_totals = defaultdict(lambda: {"service_charge": 0.0, "orders": 0, "sales": 0.0})
    table_totals = defaultdict(lambda: {"total": 0.0, "orders": 0})
    hour_totals = defaultdict(float)
    item_totals = defaultdict(lambda: {"quantity": 0, "total": 0.0})

    for o in orders:
        product_remaining = max(0.0, o.total - o.partial_payment)
        service_remaining = (
            product_remaining * (o.service_charge_pct / 100) if o.service_charge_applied else 0.0
        )
        service_amount = o.service_charge_amount
        final = product_remaining + service_remaining
        close_method = o.payment_method or "nao_informado"
        close_fee = await _card_fee_for_order_payment(final, close_method, o.card_machine, db, card_fee_rates)

        report["summary"]["total_sales"] += o.total
        report["summary"]["total_cogs"] += sum(
            ((item.unit_cost if item.unit_cost is not None else (item.product.cost if item.product else 0.0)) * item.quantity)
            for item in o.items
        )
        report["summary"]["total_service_charge"] += service_amount
        report["summary"]["total_partial_payments"] += o.partial_payment + o.partial_service_charge
        report["summary"]["total_card_fees"] += close_fee
        report["summary"]["gross_total"] += final

        waiter_name = _resolve_waiter_name(o)
        waiter_totals[waiter_name]["service_charge"] += service_amount
        waiter_totals[waiter_name]["orders"] += 1
        waiter_totals[waiter_name]["sales"] += o.total

        table_label = o.table.label if o.table else "Balcão"
        table_totals[table_label]["total"] += o.total
        table_totals[table_label]["orders"] += 1

        for item in o.items:
            item_totals[item.product.name]["quantity"] += item.quantity
            item_totals[item.product.name]["total"] += item.unit_price * item.quantity

        # Final payment grouped by the method chosen at close.
        if final > 0:
            close_hour = local_hour_label(o.closed_at) if o.closed_at else "00:00"
            hour_totals[close_hour] += final
            if close_method not in method_totals:
                method_totals[close_method] = {
                    "gross": 0.0,
                    "fee_pct": card_fee_rates.get(close_method, 0.0),
                    "fee": 0.0,
                    "net": 0.0,
                    "count": 0,
                }
            method_totals[close_method]["gross"] += final
            method_totals[close_method]["fee"] += close_fee
            method_totals[close_method]["net"] += final - close_fee
            method_totals[close_method]["count"] += 1

        # Partial payments grouped by their actual method and hour.
        for pd in o.partial_payments_detail or []:
            p_amount = float(pd.get("amount", 0))
            if p_amount <= 0:
                continue
            p_method = pd.get("method", "nao_informado")
            p_card_machine = pd.get("card_machine")
            p_fee = await _card_fee_for_order_payment(p_amount, p_method, p_card_machine, db, card_fee_rates)

            report["summary"]["total_card_fees"] += p_fee
            report["summary"]["gross_total"] += p_amount

            p_created_at = pd.get("created_at")
            if isinstance(p_created_at, str):
                try:
                    p_paid_at = datetime.fromisoformat(p_created_at)
                except ValueError:
                    p_paid_at = o.closed_at
            else:
                p_paid_at = p_created_at or o.closed_at
            p_hour = local_hour_label(p_paid_at) if p_paid_at else "00:00"
            hour_totals[p_hour] += p_amount

            if p_method not in method_totals:
                method_totals[p_method] = {
                    "gross": 0.0,
                    "fee_pct": card_fee_rates.get(p_method, 0.0),
                    "fee": 0.0,
                    "net": 0.0,
                    "count": 0,
                }
            method_totals[p_method]["gross"] += p_amount
            method_totals[p_method]["fee"] += p_fee
            method_totals[p_method]["net"] += p_amount - p_fee
            method_totals[p_method]["count"] += 1

        report["orders"].append(
            {
                "order_id": o.id,
                "table": table_label,
                "waiter": waiter_name,
                "total": float(o.total),
                "service_charge": round(service_amount, 2),
                "partial_payment": float(o.partial_payment),
                "partial_service_charge": float(o.partial_service_charge),
                "final_total": round(final, 2),
                "payment_method": close_method,
                "closed_at": as_local(o.closed_at).strftime("%H:%M") if o.closed_at else "",
            }
        )

    await _add_consignment_payments_to_report(
        start, end, db, report, method_totals, card_fee_rates, hour_totals, item_totals
    )
    await _add_consignment_summary(start, end, db, report)

    report["summary"]["total_sales"] = round(report["summary"]["total_sales"], 2)
    report["summary"]["total_cogs"] = round(report["summary"]["total_cogs"], 2)
    report["summary"]["gross_profit"] = round(
        report["summary"]["total_sales"] - report["summary"]["total_cogs"], 2
    )
    report["summary"]["total_service_charge"] = round(report["summary"]["total_service_charge"], 2)
    report["summary"]["total_partial_payments"] = round(report["summary"]["total_partial_payments"], 2)
    report["summary"]["total_card_fees"] = round(report["summary"]["total_card_fees"], 2)
    report["summary"]["total_expenses"] = round(report["summary"]["total_expenses"], 2)
    report["summary"]["operating_expenses"] = round(
        report["summary"]["total_card_fees"] + report["summary"]["total_expenses"], 2
    )
    report["summary"]["net_profit"] = round(
        report["summary"]["gross_profit"] - report["summary"]["operating_expenses"], 2
    )
    report["summary"]["gross_total"] = round(report["summary"]["gross_total"], 2)
    report["summary"]["net_total"] = round(
        report["summary"]["gross_total"]
        - report["summary"]["total_service_charge"]
        - report["summary"]["total_card_fees"]
        - report["summary"]["total_expenses"],
        2,
    )

    for method, values in method_totals.items():
        method_totals[method]["gross"] = round(values["gross"], 2)
        method_totals[method]["fee"] = round(values["fee"], 2)
        method_totals[method]["net"] = round(values["net"], 2)

    for waiter, values in waiter_totals.items():
        waiter_totals[waiter]["service_charge"] = round(values["service_charge"], 2)
        waiter_totals[waiter]["sales"] = round(values["sales"], 2)

    for table, values in table_totals.items():
        table_totals[table]["total"] = round(values["total"], 2)

    report["by_payment_method"] = method_totals
    report["by_waiter"] = dict(waiter_totals)
    report["by_table"] = dict(table_totals)
    report["by_hour"] = dict(sorted(hour_totals.items()))
    report["items_ranking"] = sorted(
        [
            {"name": k, "quantity": v["quantity"], "total": round(v["total"], 2)}
            for k, v in item_totals.items()
        ],
        key=lambda x: x["total"],
        reverse=True,
    )

    return report


@router.get("/vendas")
async def list_sales(
    date_filter: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_financial(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    query = (
        select(Order)
        .where(Order.status == "finalizada")
        .options(
            selectinload(Order.table),
            selectinload(Order.waiter),
            selectinload(Order.closed_by),
            selectinload(Order.closed_waiter),
            selectinload(Order.customer),
            selectinload(Order.items).selectinload(OrderItem.product),
        )
        .order_by(Order.closed_at.desc())
    )

    if date_filter:
        filter_date = parse_local_date(date_filter)
        if filter_date:
            day_start, day_end = local_day_to_utc_range(filter_date)
            query = query.where(Order.closed_at >= day_start, Order.closed_at <= day_end)

    result = await db.execute(query)
    orders = result.scalars().all()

    data = []
    total_day = 0.0
    total_service = 0.0

    for o in orders:
        total_day += o.total
        total_service += o.service_charge_amount
        data.append(serialize_order_sale(o))

    return {
        "sales": data,
        "summary": {
            "total_sales": round(total_day, 2),
            "total_service_charge": round(total_service, 2),
            "orders_count": len(data),
        },
    }


@router.get("/dashboard")
async def dashboard(
    period: str = Query("daily"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_financial(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    today = today_local()

    def _range_for(period_name):
        if period_name == "day":
            return local_day_to_utc_range(today)
        elif period_name == "week":
            monday = today - timedelta(days=today.weekday())
            sunday = monday + timedelta(days=6)
            start, _ = local_day_to_utc_range(monday)
            _, end = local_day_to_utc_range(sunday)
            return start, end
        elif period_name == "month":
            start_month = date(today.year, today.month, 1)
            month_start, _ = local_day_to_utc_range(start_month)
            next_month = (start_month + timedelta(days=32)).replace(day=1)
            next_month_start, _ = local_day_to_utc_range(next_month)
            month_end = next_month_start - timedelta(seconds=1)
            return month_start, month_end
        else:
            return local_day_to_utc_range(today)

    async def _period_totals(start, end):
        sales_result = await db.execute(
            select(
                func.coalesce(func.sum(Order.total), 0),
                func.coalesce(func.sum(Order.service_charge_amount), 0),
                func.count(Order.id),
            ).where(
                Order.status == "finalizada",
                Order.closed_at >= start,
                Order.closed_at <= end,
                or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
            )
        )
        sales_total, service_charge, sales_count = sales_result.one()

        payments_result = await db.execute(
            select(func.coalesce(func.sum(ConsignmentPayment.amount), 0))
            .where(
                ConsignmentPayment.created_at >= start,
                ConsignmentPayment.created_at <= end,
            )
        )
        payments_total = payments_result.scalar()

        pending_result = await db.execute(
            select(
                func.count(ConsignmentOrder.id),
                func.coalesce(func.sum(ConsignmentOrder.balance), 0),
            ).where(
                ConsignmentOrder.status != "cancelado",
                ConsignmentOrder.created_at >= start,
                ConsignmentOrder.created_at <= end,
                ConsignmentOrder.balance > 0,
            )
        )
        pending_count, pending_total = pending_result.one()

        return {
            "total": round(float(sales_total) + float(payments_total), 2),
            "service_charge": round(float(service_charge), 2),
            "orders": sales_count,
            "consignments": pending_count,
            "consignments_total": round(float(pending_total), 2),
        }

    day_start, day_end = _range_for("day")
    week_start, week_end = _range_for("week")
    month_start, month_end = _range_for("month")

    return {
        "today": await _period_totals(day_start, day_end),
        "week": await _period_totals(week_start, week_end),
        "month": await _period_totals(month_start, month_end),
    }


class DailyCloseRequest(BaseModel):
    date: str


@router.post("/fechamento-diario")
async def daily_close(
    req: DailyCloseRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_financial(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    close_date = parse_local_date(req.date)
    if close_date is None:
        return {"error": "Data inválida. Use formato YYYY-MM-DD"}

    return await _build_daily_report(close_date, db, user.name)


@router.post("/relatorio-parcial")
async def partial_report(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_financial(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    result = await db.execute(
        select(CashRegisterSession)
        .where(CashRegisterSession.status == "open")
        .options(selectinload(CashRegisterSession.opened_by))
        .order_by(CashRegisterSession.opened_at.desc())
    )
    session = result.scalar_one_or_none()

    if not session:
        return {"error": "Não há caixa aberto. Abra o caixa para gerar o relatório parcial."}

    return await _build_session_report(
        session=session,
        start=session.opened_at,
        end=datetime.now(timezone.utc),
        report_type="parcial",
        db=db,
        generated_by=user.name,
    )


@router.get("/sessao/{session_id}/relatorio-final")
async def final_report(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_financial(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    result = await db.execute(
        select(CashRegisterSession)
        .where(CashRegisterSession.id == session_id)
        .options(
            selectinload(CashRegisterSession.opened_by),
            selectinload(CashRegisterSession.closed_by),
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        return {"error": "Sessão de caixa não encontrada"}

    if session.status != "closed" or not session.closed_at:
        return {"error": "O caixa ainda não foi fechado para esta sessão"}

    return await _build_session_report(
        session=session,
        start=session.opened_at,
        end=session.closed_at,
        report_type="final",
        db=db,
        generated_by=user.name,
    )


class ReportPdfRequest(BaseModel):
    date: str | None = None
    session_id: int | None = None


@router.post("/relatorio-pdf")
async def report_pdf(
    req: ReportPdfRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_financial(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    report = None
    filename_suffix = ""

    if req.session_id:
        result = await db.execute(
            select(CashRegisterSession)
            .where(CashRegisterSession.id == req.session_id)
            .options(
                selectinload(CashRegisterSession.opened_by),
                selectinload(CashRegisterSession.closed_by),
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            return {"error": "Sessão de caixa não encontrada"}

        end = session.closed_at if session.closed_at else datetime.now(timezone.utc)
        report_type = "final" if session.status == "closed" else "parcial"
        report = await _build_session_report(
            session=session,
            start=session.opened_at,
            end=end,
            report_type=report_type,
            db=db,
            generated_by=user.name,
        )
        filename_suffix = f"sessao_{session.id}"
    elif req.date:
        close_date = parse_local_date(req.date)
        if close_date is None:
            return {"error": "Data inválida. Use formato YYYY-MM-DD"}
        report = await _build_daily_report(close_date, db, user.name)
        filename_suffix = close_date.isoformat()
    else:
        return {"error": "Informe date ou session_id"}

    if report is None or "error" in report:
        raise HTTPException(
            status_code=400,
            detail=report.get("error") if report else "Erro ao gerar relatório",
        )

    buffer = _build_pdf_bytes(report, filename_suffix)

    filename = f"relatorio_ladsbeer_{filename_suffix}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _build_pdf_bytes(report: dict, filename_suffix: str) -> io.BytesIO:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)

    if report.get("report_type") == "parcial":
        title = "LADS BEER - Relatório Parcial de Caixa"
    elif report.get("report_type") == "final":
        title = "LADS BEER - Relatório Final de Caixa"
    else:
        title = "LADS BEER - Relatório Financeiro Diário"

    pdf.cell(0, 10, title, ln=True, align="C")
    pdf.set_font("Arial", "", 11)

    if "session" in report:
        session_info = report["session"]
        opened = _fmt_datetime(session_info.get("opened_at"))
        closed = _fmt_datetime(session_info.get("closed_at")) or "Em aberto"
        pdf.cell(0, 6, f"Caixa aberto em: {opened}  |  Fechado em: {closed}", ln=True, align="C")
        pdf.cell(0, 6, f"Aberto por: {session_info.get('opened_by', 'N/A')}  |  Gerado por: {report.get('generated_by', 'Sistema')}", ln=True, align="C")
    else:
        pdf.cell(0, 6, f"Data: {report['date']}  |  Fechado por: {report['closed_by']}", ln=True, align="C")

    pdf.cell(0, 6, f"Gerado em: {local_datetime_str(datetime.now(timezone.utc))}", ln=True, align="C")
    pdf.ln(8)

    # Resumo geral
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Resumo Geral", ln=True)
    pdf.set_font("Arial", "", 11)
    summary = report["summary"]
    rows = [
        ("Vendas Brutas", f"R$ {summary['total_sales']:.2f}"),
        ("Custo dos Produtos", f"R$ {summary['total_cogs']:.2f}"),
        ("Lucro Bruto", f"R$ {summary['gross_profit']:.2f}"),
        ("Taxa de Servico", f"R$ {summary['total_service_charge']:.2f}"),
        ("Taxas de Cartao", f"R$ {summary['total_card_fees']:.2f}"),
        ("Despesas", f"R$ {summary['total_expenses']:.2f}"),
        ("Total Bruto Recebido", f"R$ {summary['gross_total']:.2f}"),
        ("Total Liquido (caixa)", f"R$ {summary['net_total']:.2f}"),
        ("Lucro Liquido", f"R$ {summary['net_profit']:.2f}"),
        ("Comandas", str(summary["orders_count"])),
        ("Consignados", str(summary.get("consignments_count", 0))),
    ]
    if summary.get("consignments_count", 0) > 0:
        rows.extend([
            ("Consignado (periodo)", f"R$ {summary.get('consignments_total', 0):.2f}"),
            ("Pago", f"R$ {summary.get('consignments_paid', 0):.2f}"),
            ("Saldo Devedor", f"R$ {summary.get('consignments_balance', 0):.2f}"),
        ])
    for label, value in rows:
        pdf.cell(90, 7, label, border=0)
        pdf.cell(0, 7, value, border=0, ln=True)
    pdf.ln(6)

    if "cash_summary" in report:
        pdf.set_font("Arial", "B", 13)
        pdf.cell(0, 8, "Fechamento de Caixa", ln=True)
        pdf.set_font("Arial", "", 11)
        cash = report["cash_summary"]
        cash_rows = [
            ("Dinheiro Inicial", f"R$ {cash['initial_cash']:.2f}"),
            ("Entradas em Dinheiro", f"R$ {cash['cash_inflows']:.2f}"),
            ("Sangria (cofre)", f"R$ {cash.get('total_sangria', 0):.2f}"),
            ("Suprimento (troco)", f"R$ {cash.get('total_suprimento', 0):.2f}"),
            ("Dinheiro Esperado", f"R$ {cash['expected_cash']:.2f}"),
        ]
        if cash.get("final_cash") is not None:
            cash_rows.append(("Dinheiro Contado", f"R$ {cash['final_cash']:.2f}"))
            discrepancy = cash.get("discrepancy")
            if discrepancy is not None:
                label = "Diferenca (sobra)" if discrepancy >= 0 else "Diferenca (falta)"
                cash_rows.append((label, f"R$ {abs(discrepancy):.2f}"))
        for label, value in cash_rows:
            pdf.cell(90, 7, label, border=0)
            pdf.cell(0, 7, value, border=0, ln=True)
        pdf.ln(6)

    # Por forma de pagamento
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Por Forma de Pagamento", ln=True)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(60, 7, "Forma", border="B")
    pdf.cell(30, 7, "Bruto", border="B", align="R")
    pdf.cell(30, 7, "Taxa", border="B", align="R")
    pdf.cell(30, 7, "Liquido", border="B", align="R")
    pdf.cell(20, 7, "Qtd", border="B", align="R", ln=True)
    pdf.set_font("Arial", "", 10)
    for method, vals in report["by_payment_method"].items():
        label = vals.get("label", _method_label(method))
        pdf.cell(60, 6, label)
        pdf.cell(30, 6, f"R$ {vals['gross']:.2f}", align="R")
        pdf.cell(30, 6, f"R$ {vals['fee']:.2f}", align="R")
        pdf.cell(30, 6, f"R$ {vals['net']:.2f}", align="R")
        pdf.cell(20, 6, str(vals["count"]), align="R", ln=True)
    pdf.ln(6)

    # Por garçom
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Por Garçom", ln=True)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(70, 7, "Garçom", border="B")
    pdf.cell(35, 7, "Taxa a Receber", border="B", align="R")
    pdf.cell(35, 7, "Vendas", border="B", align="R")
    pdf.cell(30, 7, "Comandas", border="B", align="R", ln=True)
    pdf.set_font("Arial", "", 10)
    for waiter, vals in report["by_waiter"].items():
        pdf.cell(70, 6, waiter)
        pdf.cell(35, 6, f"R$ {vals['service_charge']:.2f}", align="R")
        pdf.cell(35, 6, f"R$ {vals['sales']:.2f}", align="R")
        pdf.cell(30, 6, str(vals["orders"]), align="R", ln=True)
    pdf.ln(6)

    # Por mesa
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Por Mesa", ln=True)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(80, 7, "Mesa", border="B")
    pdf.cell(50, 7, "Total", border="B", align="R")
    pdf.cell(40, 7, "Comandas", border="B", align="R", ln=True)
    pdf.set_font("Arial", "", 10)
    for table, vals in report["by_table"].items():
        pdf.cell(80, 6, table)
        pdf.cell(50, 6, f"R$ {vals['total']:.2f}", align="R")
        pdf.cell(40, 6, str(vals["orders"]), align="R", ln=True)
    pdf.ln(6)

    # Ranking de itens
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Ranking de Itens Vendidos", ln=True)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(90, 7, "Item", border="B")
    pdf.cell(35, 7, "Qtd", border="B", align="R")
    pdf.cell(45, 7, "Total", border="B", align="R", ln=True)
    pdf.set_font("Arial", "", 10)
    for item in report["items_ranking"][:15]:
        pdf.cell(90, 6, item["name"])
        pdf.cell(35, 6, str(item["quantity"]), align="R")
        pdf.cell(45, 6, f"R$ {item['total']:.2f}", align="R", ln=True)
    pdf.ln(6)

    # Vendas por hora
    pdf.set_font("Arial", "B", 13)
    pdf.cell(0, 8, "Vendas por Hora", ln=True)
    pdf.set_font("Arial", "", 10)
    for hour, total in report["by_hour"].items():
        pdf.cell(40, 6, hour)
        pdf.cell(0, 6, f"R$ {total:.2f}", ln=True)

    # Despesas e perdas
    if report["expenses"]:
        pdf.ln(6)
        pdf.set_font("Arial", "B", 13)
        pdf.cell(0, 8, "Despesas e Perdas", ln=True)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(90, 7, "Descricao", border="B")
        pdf.cell(35, 7, "Categoria", border="B", align="R")
        pdf.cell(40, 7, "Valor", border="B", align="R", ln=True)
        pdf.set_font("Arial", "", 10)
        for expense in report["expenses"]:
            pdf.cell(90, 6, expense["description"][:45])
            pdf.cell(35, 6, expense.get("category", "").capitalize(), align="R")
            pdf.cell(40, 6, f"R$ {expense['amount']:.2f}", align="R", ln=True)
        pdf.set_font("Arial", "B", 10)
        pdf.cell(90, 7, "Total Despesas e Perdas", border="T")
        pdf.cell(35, 7, "", border="T")
        pdf.cell(40, 7, f"R$ {report['summary']['total_expenses']:.2f}", align="R", border="T", ln=True)

    buffer = io.BytesIO()
    pdf.output(buffer)
    buffer.seek(0)
    return buffer

