from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, extract, cast, case, Date, or_, and_, desc
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
from app.models.cash_position_movement import CashPositionMovement
from app.models.stock_history import StockHistory
from app.models.consignment import ConsignmentOrder, ConsignmentOrderItem, ConsignmentPayment
from app.models.payment import OrderPayment, PaymentRefund, PaymentRefundItem
from app.routers.auth_deps import get_current_user, can_view_financial
from app.routers.ws import broadcast_stock_update
from app.services.cash_service import compute_session_cash_summary
from app.services.stock_service import is_pack
from app.services.consignment_service import fetch_consignment_payments
from app.services.money_service import ZERO, as_float, money, rate
from app.services.refund_service import refund_full_order

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
    canonical_payments = list(order.payments or [])
    product_remaining = money(max(ZERO, money(order.total) - money(order.partial_payment)))
    service_amount = money(order.service_charge_amount)
    final = money(
        sum(
            (
                payment.gross_amount
                for payment in canonical_payments
                if payment.payment_type == "final"
            ),
            ZERO,
        )
    )

    payment_method_label = PAYMENT_LABELS.get(
        order.payment_method or "nao_informado", order.payment_method or "Não Informado"
    )
    payment_details = []
    if canonical_payments:
        for idx, payment in enumerate(canonical_payments, start=1):
            payment_details.append({
                "payment_id": payment.id,
                "type": payment.payment_type,
                "index": idx,
                "method": payment.payment_method,
                "method_label": PAYMENT_LABELS.get(
                    payment.payment_method, payment.payment_method
                ),
                "amount": as_float(payment.gross_amount),
                "product_portion": as_float(payment.product_amount),
                "service_portion": as_float(payment.service_amount),
                "card_machine": payment.card_machine,
                "apply_service_charge": payment.service_amount > ZERO,
                "created_at": (
                    payment.created_at.isoformat() if payment.created_at else None
                ),
            })
    else:
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
    if order.payment_method == "fiado" and not canonical_payments:
        payment_details.append({
            "type": "fiado",
            "method": "fiado",
            "method_label": "Fiado (quitado)",
            "amount": 0.0,
            "card_machine": None,
        })
    elif not canonical_payments:
        payment_details.append({
            "type": "final",
            "method": order.payment_method or "nao_informado",
            "method_label": payment_method_label,
            "amount": round(float(final), 2),
            "card_machine": order.card_machine,
        })

    return {
        "order_id": order.id,
        "is_fiado": order.payment_method == "fiado",
        "table_number": order.table.number if order.table else 0,
        "table_label": order.table.label if order.table else "",
        "is_balcao": order.table.is_balcao if order.table else False,
        "waiter_name": _resolve_waiter_name(order),
        "customer_id": order.customer_id,
        "customer_name": order.customer_name or (order.customer.name if order.customer else None),
        "items_count": sum(item.quantity for item in order.items),
        "total": as_float(order.total),
        "service_charge_pct": float(order.service_charge_pct),
        "service_charge_amount": as_float(service_amount),
        "partial_payment": as_float(order.partial_payment),
        "partial_service_charge": as_float(order.partial_service_charge),
        "final_total": as_float(final),
        "payment_method": order.payment_method or "nao_informado",
        "payment_method_label": payment_method_label,
        "card_machine": order.card_machine,
        "closed_at": order.closed_at.isoformat() if order.closed_at else None,
        "is_estorno": bool(order.is_estorno),
        "can_estornar": order.status == "finalizada" and not order.is_estorno,
        "refunds": [
            {
                "refund_id": refund.id,
                "amount": as_float(refund.gross_amount),
                "product_portion": as_float(refund.product_amount),
                "service_portion": as_float(refund.service_amount),
                "method": refund.payment_method,
                "method_label": PAYMENT_LABELS.get(
                    refund.payment_method, refund.payment_method
                ),
                "reason": refund.reason,
                "created_at": refund.created_at.isoformat() if refund.created_at else None,
            }
            for refund in (order.refunds or [])
        ],
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


async def _direct_service_in_period(
    start: datetime | None,
    end: datetime | None,
    db: AsyncSession,
) -> Decimal:
    query = (
        select(func.coalesce(func.sum(OrderPayment.service_amount), 0))
        .join(Order, Order.id == OrderPayment.order_id)
        .where(or_(Order.payment_method != "fiado", Order.payment_method.is_(None)))
    )
    if start is not None:
        query = query.where(OrderPayment.created_at >= start)
    if end is not None:
        query = query.where(OrderPayment.created_at <= end)
    return money(await db.scalar(query))


async def compute_session_close_metrics(session, db: AsyncSession) -> dict:
    """Compute the faturamento/card-fees/service-charge for a closed session.

    Mirrors the summary computed by _build_session_report but returns only the
    three values needed to feed the cash position movements on close.
    """
    direct_result = await db.execute(
        select(OrderPayment)
        .join(Order, Order.id == OrderPayment.order_id)
        .where(
            OrderPayment.cash_session_id == session.id,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
    )
    direct_payments = direct_result.scalars().all()

    consignment_result = await db.execute(
        select(ConsignmentPayment).where(
            ConsignmentPayment.cash_session_id == session.id
        )
    )
    consignment_payments = consignment_result.scalars().all()

    gross_total = money(
        sum((payment.gross_amount for payment in direct_payments), ZERO)
        + sum((payment.amount for payment in consignment_payments), ZERO)
    )
    card_fees = money(
        sum((payment.card_fee_amount for payment in direct_payments), ZERO)
        + sum((payment.card_fee_amount for payment in consignment_payments), ZERO)
    )
    direct_service = money(
        sum((payment.service_amount for payment in direct_payments), ZERO)
    )
    paid_consignment_service = await db.scalar(
        select(func.coalesce(func.sum(ConsignmentOrder.service_total), 0)).where(
            ConsignmentOrder.status == "pago",
            ConsignmentOrder.closed_at >= session.opened_at,
            ConsignmentOrder.closed_at <= (session.closed_at or datetime.now(timezone.utc)),
        )
    )

    return {
        "gross_total": as_float(gross_total),
        "card_fees": as_float(card_fees),
        "service_charge": as_float(money(direct_service + money(paid_consignment_service))),
    }


async def compute_period_profit(start: datetime, end: datetime, db: AsyncSession) -> dict:
    """Compute profit metrics for an arbitrary period (same semantics as the reports)."""
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

    total_sales = ZERO
    total_cogs = ZERO

    for o in orders:
        total_sales = money(total_sales + o.total)
        total_cogs = money(
            total_cogs
            + sum(
                (
                    money(
                        (
                            item.unit_cost
                            if item.unit_cost is not None
                            else (item.product.cost if item.product else ZERO)
                        )
                        * item.quantity
                    )
                    for item in o.items
                ),
                ZERO,
            )
        )

    consignment_result = await db.execute(
        select(ConsignmentPayment)
        .where(
            ConsignmentPayment.created_at >= start,
            ConsignmentPayment.created_at <= end,
        )
    )
    consignment_payments = consignment_result.scalars().all()
    total_sales = money(
        total_sales
        + sum((payment.product_portion for payment in consignment_payments), ZERO)
    )

    direct_fee = await db.scalar(
        select(func.coalesce(func.sum(OrderPayment.card_fee_amount), 0))
        .join(Order, Order.id == OrderPayment.order_id)
        .where(
            OrderPayment.created_at >= start,
            OrderPayment.created_at <= end,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
    )
    total_card_fees = money(
        money(direct_fee)
        + sum((payment.card_fee_amount for payment in consignment_payments), ZERO)
    )

    total_cogs = money(total_cogs + money(await _consignment_cogs_in_period(start, end, db)))

    refund_result = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            PaymentRefund.sale_was_recognized == True,
                            PaymentRefund.product_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (PaymentRefund.service_already_repassed == True, PaymentRefund.service_amount),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(
            PaymentRefund.created_at >= start,
            PaymentRefund.created_at <= end,
        )
    )
    refunded_product, retained_service_loss = refund_result.one()
    refund_cogs = await db.scalar(
        select(
            func.coalesce(
                func.sum(PaymentRefundItem.unit_cost * PaymentRefundItem.quantity), 0
            )
        )
        .join(PaymentRefund, PaymentRefund.id == PaymentRefundItem.refund_id)
        .where(
            PaymentRefund.created_at >= start,
            PaymentRefund.created_at <= end,
            PaymentRefund.sale_was_recognized == True,
        )
    )
    total_sales = money(total_sales - money(refunded_product))
    total_cogs = money(total_cogs - money(refund_cogs))

    expenses_result = await db.execute(
        select(Expense).where(Expense.expense_date >= start, Expense.expense_date <= end)
    )
    total_expenses = sum(
        (money(expense.amount) for expense in expenses_result.scalars().all()),
        ZERO,
    )
    _, perdas_total = await _get_perdas(start, end, db)
    total_expenses = money(total_expenses + perdas_total)

    gross_profit = money(total_sales - total_cogs)
    net_profit = money(
        gross_profit
        - total_card_fees
        - total_expenses
        - money(retained_service_loss)
    )

    return {
        "total_sales": as_float(total_sales),
        "total_cogs": as_float(total_cogs),
        "gross_profit": as_float(gross_profit),
        "total_card_fees": as_float(total_card_fees),
        "total_expenses": as_float(total_expenses),
        "retained_service_loss": as_float(retained_service_loss),
        "net_profit": as_float(net_profit),
    }


async def _get_perdas(
    start: datetime,
    end: datetime,
    db: AsyncSession,
) -> tuple[list[dict], Decimal]:
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
    total = ZERO
    for history, product in result.all():
        unit_cost = history.unit_cost_snapshot
        if unit_cost is None:
            unit_cost = product.cost or ZERO
        amount = money(unit_cost * history.quantity)
        total = money(total + amount)
        items.append({
            "id": f"perda_{history.id}",
            "description": f"Perda: {product.name} ({history.quantity} un.)",
            "amount": as_float(amount),
            "category": "perdas",
            "expense_date": _fmt_datetime(history.created_at),
            "quantity": history.quantity,
            "product_name": product.name,
            "note": history.note,
        })
    return items, money(total)


async def _consignment_cogs_in_period(
    start: datetime,
    end: datetime,
    db: AsyncSession,
) -> Decimal:
    """Full COGS (frozen unit_cost) of consignments CREATED in the period.

    Cost is recognized when the credit sale happens, not when payments arrive.
    Canceled consignments with returned stock are excluded unless they were
    canceled by a financial refund, which is reversed in the refund period.
    """
    result = await db.execute(
        select(ConsignmentOrderItem)
        .join(ConsignmentOrder, ConsignmentOrder.id == ConsignmentOrderItem.consignment_order_id)
        .where(
            ConsignmentOrder.created_at >= start,
            ConsignmentOrder.created_at <= end,
            or_(
                ConsignmentOrder.status != "cancelado",
                ConsignmentOrder.source_order.has(Order.is_estorno == True),
                ConsignmentOrder.refunds.any(),
            ),
        )
        .options(selectinload(ConsignmentOrderItem.product))
    )
    items = result.scalars().all()
    total = ZERO
    for item in items:
        unit_cost = item.unit_cost if item.unit_cost is not None else (item.product.cost if item.product else ZERO)
        total = money(total + money(unit_cost * item.quantity))
    return money(total)


async def _consignment_tips_paid_in_period(
    start: datetime,
    end: datetime,
    db: AsyncSession,
) -> dict[str, Decimal]:
    """Return service tips when consignments become fully paid in the period."""
    result = await db.execute(
        select(ConsignmentOrder)
        .where(ConsignmentOrder.total > 0)
        .options(
            selectinload(ConsignmentOrder.payments),
            selectinload(ConsignmentOrder.waiter),
            selectinload(ConsignmentOrder.credited_waiter),
        )
    )
    consignments = result.scalars().all()
    tips: dict[str, Decimal] = {}
    for consignment in consignments:
        running_total = ZERO
        payoff_at = None
        for payment in sorted(
            consignment.payments,
            key=lambda entry: (entry.created_at or consignment.created_at, entry.id),
        ):
            running_total = money(running_total + payment.amount)
            if running_total >= money(consignment.total):
                payoff_at = payment.created_at
                break
        if payoff_at is None or not (start <= payoff_at <= end):
            continue
        total = money(consignment.service_total)
        waiter_name = consignment.credited_waiter_name or "N/A"
        tips[waiter_name] = money(tips.get(waiter_name, ZERO) + total)
    return tips


async def _add_consignment_payments_to_report(
    start: datetime,
    end: datetime,
    db: AsyncSession,
    report: dict,
    method_totals: dict,
    hour_totals: dict | None = None,
    item_totals: dict | None = None,
    waiter_totals: dict | None = None,
) -> int:
    """Add consignment payments received in the period as revenue (faturamento).

    Only paid installments count as revenue. The payment method is grouped
    together with regular sales (e.g. Dinheiro, Pix, Cartão).

    Each payment splits: the product portion (amount - service_portion) is
    revenue/sales. COGS is NOT recognized here — it is recognized when the
    consignment is CREATED (see _consignment_cogs_in_period), and the
    service_portion (repasse) is credited only when the consignment is fully
    paid (see _consignment_tips_paid_in_period).
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

    for payment in payments:
        amount = money(payment.amount)
        product_amount = money(payment.product_portion)
        method = payment.payment_method or "nao_informado"
        fee = money(payment.card_fee_amount)

        report["summary"]["total_sales"] = money(report["summary"]["total_sales"] + product_amount)
        report["summary"]["gross_total"] = money(report["summary"]["gross_total"] + amount)
        report["summary"]["total_card_fees"] = money(report["summary"]["total_card_fees"] + fee)

        bucket = _method_bucket(
            method_totals, method, float(payment.card_fee_rate)
        )
        bucket["gross"] = money(bucket["gross"] + amount)
        bucket["fee_base"] = money(bucket["fee_base"] + amount)
        bucket["fee"] = money(bucket["fee"] + fee)
        bucket["net"] = money(bucket["net"] + amount - fee)
        bucket["count"] += 1

        if hour_totals is not None and payment.created_at:
            hour_key = local_hour_label(payment.created_at)
            hour_totals[hour_key] = money(hour_totals[hour_key] + amount)

    return len(payments)


def _method_bucket(method_totals: dict, method: str, fee_pct: float = 0.0) -> dict:
    bucket = method_totals.setdefault(
        method,
        {
            "gross": ZERO,
            "fee_pct": fee_pct,
            "fee_base": ZERO,
            "fee": ZERO,
            "net": ZERO,
            "count": 0,
            "refunds_count": 0,
        },
    )
    bucket.setdefault("refunds_count", 0)
    return bucket


async def _add_direct_payments_to_report(
    start: datetime,
    end: datetime,
    db: AsyncSession,
    report: dict,
    method_totals: dict,
    hour_totals: dict,
    waiter_totals: dict,
) -> None:
    result = await db.execute(
        select(OrderPayment)
        .join(Order, Order.id == OrderPayment.order_id)
        .where(
            OrderPayment.created_at >= start,
            OrderPayment.created_at <= end,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
        .options(
            selectinload(OrderPayment.order).selectinload(Order.waiter),
            selectinload(OrderPayment.order).selectinload(Order.closed_by),
            selectinload(OrderPayment.order).selectinload(Order.closed_waiter),
        )
    )
    for payment in result.scalars().all():
        gross = money(payment.gross_amount)
        fee = money(payment.card_fee_amount)
        report["summary"]["gross_total"] = money(report["summary"]["gross_total"] + gross)
        report["summary"]["total_card_fees"] = money(report["summary"]["total_card_fees"] + fee)
        report["summary"]["total_service_charge"] = money(
            report["summary"]["total_service_charge"] + money(payment.service_amount)
        )
        if payment.payment_type == "partial":
            report["summary"]["total_partial_payments"] = money(
                report["summary"]["total_partial_payments"] + gross
            )

        bucket = _method_bucket(
            method_totals, payment.payment_method, float(payment.card_fee_rate)
        )
        bucket["gross"] = money(bucket["gross"] + gross)
        bucket["fee_base"] = money(bucket["fee_base"] + gross)
        bucket["fee"] = money(bucket["fee"] + fee)
        bucket["net"] = money(bucket["net"] + gross - fee)
        bucket["count"] += 1
        waiter_name = _resolve_waiter_name(payment.order)
        waiter_totals[waiter_name]["service_charge"] = money(
            waiter_totals[waiter_name]["service_charge"] + money(payment.service_amount)
        )
        if payment.created_at:
            hour_key = local_hour_label(payment.created_at)
            hour_totals[hour_key] = money(hour_totals[hour_key] + gross)


async def _add_consignment_sale_rankings(
    start: datetime,
    end: datetime,
    db: AsyncSession,
    item_totals: dict,
    waiter_totals: dict,
) -> None:
    result = await db.execute(
        select(ConsignmentOrder)
        .where(
            ConsignmentOrder.created_at >= start,
            ConsignmentOrder.created_at <= end,
            or_(
                ConsignmentOrder.status != "cancelado",
                ConsignmentOrder.source_order.has(Order.is_estorno == True),
                ConsignmentOrder.refunds.any(),
            ),
        )
        .options(
            selectinload(ConsignmentOrder.items).selectinload(
                ConsignmentOrderItem.product
            ),
            selectinload(ConsignmentOrder.waiter),
            selectinload(ConsignmentOrder.credited_waiter),
        )
    )
    for consignment in result.scalars().all():
        waiter_name = consignment.credited_waiter_name or "N/A"
        waiter_totals[waiter_name]["orders"] += 1
        waiter_totals[waiter_name]["sales"] = money(
            waiter_totals[waiter_name]["sales"] + money(consignment.product_total)
        )
        for item in consignment.items:
            if not item.product:
                continue
            item_totals[item.product.name]["quantity"] += item.quantity
            item_totals[item.product.name]["total"] = money(
                item_totals[item.product.name]["total"]
                + money(item.unit_price * item.quantity)
            )


async def _apply_refunds_to_report(
    start: datetime,
    end: datetime,
    db: AsyncSession,
    report: dict,
    method_totals: dict,
    hour_totals: dict,
    item_totals: dict,
    waiter_totals: dict,
    table_totals: dict,
) -> None:
    result = await db.execute(
        select(PaymentRefund)
        .where(
            PaymentRefund.created_at >= start,
            PaymentRefund.created_at <= end,
        )
        .options(
            selectinload(PaymentRefund.items).selectinload(
                PaymentRefundItem.product
            ),
            selectinload(PaymentRefund.order).selectinload(Order.table),
            selectinload(PaymentRefund.order).selectinload(Order.waiter),
            selectinload(PaymentRefund.order).selectinload(Order.closed_by),
            selectinload(PaymentRefund.order).selectinload(Order.closed_waiter),
            selectinload(PaymentRefund.consignment_order).selectinload(
                ConsignmentOrder.waiter
            ),
            selectinload(PaymentRefund.consignment_order).selectinload(
                ConsignmentOrder.credited_waiter
            ),
        )
        .order_by(PaymentRefund.created_at, PaymentRefund.id)
    )
    refunds = result.scalars().all()
    report["refunds"] = []
    report["summary"].setdefault("total_refunds", ZERO)
    report["summary"].setdefault("retained_service_loss", ZERO)

    for refund in refunds:
        gross = money(refund.gross_amount)
        product_amount = money(refund.product_amount)
        service_amount = money(refund.service_amount)
        report["summary"]["total_refunds"] = money(report["summary"]["total_refunds"] + gross)
        report["summary"]["gross_total"] = money(report["summary"]["gross_total"] - gross)
        if refund.sale_was_recognized:
            report["summary"]["total_sales"] = money(report["summary"]["total_sales"] - product_amount)
        if refund.service_already_repassed:
            report["summary"]["retained_service_loss"] = money(
                report["summary"]["retained_service_loss"] + service_amount
            )
        elif refund.service_was_recognized:
            report["summary"]["total_service_charge"] = money(
                report["summary"]["total_service_charge"] - service_amount
            )

        if gross > 0:
            bucket = _method_bucket(method_totals, refund.payment_method)
            bucket["gross"] = money(bucket["gross"] - gross)
            bucket["net"] = money(bucket["net"] - gross)
            bucket["refunds_count"] += 1
            if refund.created_at:
                hour_key = local_hour_label(refund.created_at)
                hour_totals[hour_key] = money(hour_totals[hour_key] - gross)

        order = refund.order
        reversed_sale_product = money(
            sum((item.product_amount for item in refund.items), ZERO)
        )
        if order:
            waiter_name = _resolve_waiter_name(order)
            if refund.sale_was_recognized:
                waiter_totals[waiter_name]["sales"] = money(
                    waiter_totals[waiter_name]["sales"] - reversed_sale_product
                )
            if refund.service_was_recognized and not refund.service_already_repassed:
                waiter_totals[waiter_name]["service_charge"] = money(
                    waiter_totals[waiter_name]["service_charge"] - service_amount
                )
            if refund.sale_was_recognized and refund.payment_id is not None:
                table_label = order.table.label if order.table else "Balcão"
                table_totals[table_label]["total"] = money(
                    table_totals[table_label]["total"] - reversed_sale_product
                )
        elif refund.consignment_order:
            waiter_name = refund.consignment_order.credited_waiter_name or "N/A"
            if refund.sale_was_recognized:
                waiter_totals[waiter_name]["sales"] = money(
                    waiter_totals[waiter_name]["sales"] - reversed_sale_product
                )
            if refund.service_was_recognized and not refund.service_already_repassed:
                waiter_totals[waiter_name]["service_charge"] = money(
                    waiter_totals[waiter_name]["service_charge"] - service_amount
                )

        if refund.sale_was_recognized:
            for item in refund.items:
                item_cost = money(item.unit_cost * item.quantity)
                report["summary"]["total_cogs"] = money(
                    report["summary"]["total_cogs"] - item_cost
                )
                name = (
                    item.product.name
                    if item.product
                    else f"Produto #{item.product_id}"
                )
                item_totals[name]["quantity"] -= item.quantity
                item_totals[name]["total"] = money(
                    item_totals[name]["total"] - money(item.product_amount)
                )

        report["refunds"].append(
            {
                "id": refund.id,
                "order_id": refund.order_id,
                "consignment_order_id": refund.consignment_order_id,
                "amount": as_float(gross),
                "product_amount": as_float(product_amount),
                "service_amount": as_float(service_amount),
                "payment_method": refund.payment_method,
                "reason": refund.reason,
                "sale_was_recognized": refund.sale_was_recognized,
                "service_was_recognized": refund.service_was_recognized,
                "service_already_repassed": refund.service_already_repassed,
                "created_at": _fmt_datetime(refund.created_at),
            }
        )


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


def _finalize_method_totals(method_totals: dict) -> None:
    """Round method totals and derive the effective frozen fee percentage."""
    for values in method_totals.values():
        fee_base = money(values.pop("fee_base", ZERO))
        gross = money(values["gross"])
        fee = money(values["fee"])
        net = money(values["net"])
        values["gross"] = as_float(gross)
        values["fee"] = as_float(fee)
        values["net"] = as_float(net)
        values["fee_pct"] = float(
            rate((fee / fee_base) * Decimal("100") if fee_base > ZERO else ZERO)
        )


def _finalize_report_totals(
    report: dict,
    method_totals: dict,
    waiter_totals: dict,
    table_totals: dict,
    hour_totals: dict,
    item_totals: dict,
) -> None:
    summary = report["summary"]
    summary["total_sales"] = money(summary["total_sales"])
    summary["total_cogs"] = money(summary["total_cogs"])
    summary["gross_profit"] = money(
        summary["total_sales"] - summary["total_cogs"]
    )
    summary["total_service_charge"] = money(summary["total_service_charge"])
    summary["total_partial_payments"] = money(summary["total_partial_payments"])
    summary["total_card_fees"] = money(summary["total_card_fees"])
    summary["total_expenses"] = money(summary["total_expenses"])
    summary["operating_expenses"] = money(
        summary["total_card_fees"]
        + summary["total_expenses"]
        + money(summary.get("retained_service_loss", ZERO))
    )
    summary["net_profit"] = money(
        summary["gross_profit"] - summary["operating_expenses"]
    )
    summary["gross_total"] = money(summary["gross_total"])
    summary["net_total"] = money(
        summary["gross_total"]
        - summary["total_service_charge"]
        - summary["total_card_fees"]
        - summary["total_expenses"]
    )

    for key, value in list(summary.items()):
        if isinstance(value, Decimal):
            summary[key] = as_float(value)

    _finalize_method_totals(method_totals)

    for values in waiter_totals.values():
        values["service_charge"] = as_float(values["service_charge"])
        values["sales"] = as_float(values["sales"])

    for values in table_totals.values():
        values["total"] = as_float(values["total"])

    report["by_payment_method"] = method_totals
    report["by_waiter"] = dict(waiter_totals)
    report["by_table"] = dict(table_totals)
    report["by_hour"] = {
        key: as_float(value)
        for key, value in sorted(hour_totals.items())
    }
    report["items_ranking"] = sorted(
        [
            {
                "name": key,
                "quantity": value["quantity"],
                "total": as_float(value["total"]),
            }
            for key, value in item_totals.items()
        ],
        key=lambda entry: entry["total"],
        reverse=True,
    )


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
            selectinload(Order.payments),
        )
        .order_by(Order.closed_at)
    )
    orders = result.scalars().all()
    expenses_result = await db.execute(
        select(Expense).where(
            Expense.expense_date >= day_start,
            Expense.expense_date <= day_end,
        )
    )
    expenses = expenses_result.scalars().all()
    cash_expenses = money(sum((money(e.amount) for e in expenses), ZERO))

    perdas_items, perdas_total = await _get_perdas(day_start, day_end, db)
    total_expenses = money(cash_expenses + perdas_total)

    report = {
        "date": format_local_date(close_date),
        "closed_by": closed_by,
        "generated_at": local_datetime_str(datetime.now(timezone.utc)),
        "orders": [],
        "summary": {
            "total_sales": ZERO,
            "total_cogs": ZERO,
            "gross_profit": ZERO,
            "total_service_charge": ZERO,
            "total_partial_payments": ZERO,
            "total_card_fees": ZERO,
            "total_expenses": total_expenses,
            "perdas_total": perdas_total,
            "operating_expenses": ZERO,
            "net_profit": ZERO,
            "gross_total": ZERO,
            "net_total": ZERO,
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
                "amount": as_float(e.amount),
                "category": e.category,
                "expense_date": _fmt_datetime(e.expense_date),
            }
            for e in expenses
        ] + perdas_items,
    }

    method_totals = {}
    waiter_totals = defaultdict(lambda: {"service_charge": ZERO, "orders": 0, "sales": ZERO})
    table_totals = defaultdict(lambda: {"total": ZERO, "orders": 0})
    hour_totals = defaultdict(lambda: ZERO)
    item_totals = defaultdict(lambda: {"quantity": 0, "total": ZERO})

    for o in orders:
        service_amount = money(o.service_charge_amount)
        final = money(
            sum(
                (
                    payment.gross_amount
                    for payment in o.payments
                    if payment.payment_type == "final"
                ),
                ZERO,
            )
        )
        close_method = o.payment_method or "nao_informado"

        report["summary"]["total_sales"] = money(report["summary"]["total_sales"] + money(o.total))
        report["summary"]["total_cogs"] = money(
            report["summary"]["total_cogs"] + sum(
                money(
                    (item.unit_cost if item.unit_cost is not None else (item.product.cost if item.product else ZERO))
                    * item.quantity
                )
                for item in o.items
            )
        )
        waiter_name = _resolve_waiter_name(o)
        waiter_totals[waiter_name]["orders"] += 1
        waiter_totals[waiter_name]["sales"] = money(waiter_totals[waiter_name]["sales"] + money(o.total))

        table_label = o.table.label if o.table else "Balcão"
        table_totals[table_label]["total"] = money(table_totals[table_label]["total"] + money(o.total))
        table_totals[table_label]["orders"] += 1

        for item in o.items:
            item_totals[item.product.name]["quantity"] += item.quantity
            item_totals[item.product.name]["total"] = money(
                item_totals[item.product.name]["total"] + money(item.unit_price * item.quantity)
            )

        report["orders"].append(
            {
                "order_id": o.id,
                "table": table_label,
                "waiter": waiter_name,
                "total": as_float(o.total),
                "service_charge": as_float(service_amount),
                "partial_payment": as_float(o.partial_payment),
                "partial_service_charge": as_float(o.partial_service_charge),
                "final_total": as_float(final),
                "payment_method": close_method,
                "closed_at": as_local(o.closed_at).strftime("%H:%M") if o.closed_at else "",
            }
        )

    await _add_direct_payments_to_report(
        day_start,
        day_end,
        db,
        report,
        method_totals,
        hour_totals,
        waiter_totals,
    )
    await _add_consignment_payments_to_report(
        day_start,
        day_end,
        db,
        report,
        method_totals,
        hour_totals,
        item_totals,
        waiter_totals,
    )
    # Recognize frozen consignment COGS when the credit sale is created.
    report["summary"]["total_cogs"] = money(
        report["summary"]["total_cogs"]
        + await _consignment_cogs_in_period(day_start, day_end, db)
    )
    # Credit the waiter only after the consignment is fully paid.
    tips = await _consignment_tips_paid_in_period(day_start, day_end, db)
    report["summary"]["total_service_charge"] = money(
        report["summary"]["total_service_charge"] + sum(tips.values(), ZERO)
    )
    for waiter_name, tip_amount in tips.items():
        waiter_totals[waiter_name]["service_charge"] = money(
            waiter_totals[waiter_name]["service_charge"] + tip_amount
        )
    await _add_consignment_sale_rankings(
        day_start, day_end, db, item_totals, waiter_totals
    )
    await _apply_refunds_to_report(
        day_start,
        day_end,
        db,
        report,
        method_totals,
        hour_totals,
        item_totals,
        waiter_totals,
        table_totals,
    )
    await _add_consignment_summary(day_start, day_end, db, report)

    _finalize_report_totals(
        report,
        method_totals,
        waiter_totals,
        table_totals,
        hour_totals,
        item_totals,
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
            selectinload(Order.payments),
        )
        .order_by(Order.closed_at)
    )
    orders = result.scalars().all()
    expenses_result = await db.execute(
        select(Expense).where(
            Expense.expense_date >= start,
            Expense.expense_date <= end,
        )
    )
    expenses = expenses_result.scalars().all()
    cash_expenses = money(sum((money(e.amount) for e in expenses), ZERO))

    perdas_items, perdas_total = await _get_perdas(start, end, db)
    total_expenses = money(cash_expenses + perdas_total)

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
            "total_sales": ZERO,
            "total_cogs": ZERO,
            "gross_profit": ZERO,
            "total_service_charge": ZERO,
            "total_partial_payments": ZERO,
            "total_card_fees": ZERO,
            "total_expenses": total_expenses,
            "perdas_total": perdas_total,
            "operating_expenses": ZERO,
            "net_profit": ZERO,
            "gross_total": ZERO,
            "net_total": ZERO,
            "orders_count": len(orders),
            "consignments_count": 0,
        },
        "cash_summary": cash_summary,
        "movements": [
            {
                "id": m.id,
                "type": m.type,
                "amount": as_float(m.amount),
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
                "amount": as_float(e.amount),
                "category": e.category,
                "expense_date": _fmt_datetime(e.expense_date),
            }
            for e in expenses
        ] + perdas_items,
    }

    method_totals = {}
    waiter_totals = defaultdict(lambda: {"service_charge": ZERO, "orders": 0, "sales": ZERO})
    table_totals = defaultdict(lambda: {"total": ZERO, "orders": 0})
    hour_totals = defaultdict(lambda: ZERO)
    item_totals = defaultdict(lambda: {"quantity": 0, "total": ZERO})

    for o in orders:
        service_amount = money(o.service_charge_amount)
        final = money(
            sum(
                (
                    payment.gross_amount
                    for payment in o.payments
                    if payment.payment_type == "final"
                ),
                ZERO,
            )
        )
        close_method = o.payment_method or "nao_informado"

        report["summary"]["total_sales"] = money(report["summary"]["total_sales"] + money(o.total))
        report["summary"]["total_cogs"] = money(
            report["summary"]["total_cogs"] + sum(
                money(
                    (item.unit_cost if item.unit_cost is not None else (item.product.cost if item.product else ZERO))
                    * item.quantity
                )
                for item in o.items
            )
        )
        waiter_name = _resolve_waiter_name(o)
        waiter_totals[waiter_name]["orders"] += 1
        waiter_totals[waiter_name]["sales"] = money(waiter_totals[waiter_name]["sales"] + money(o.total))

        table_label = o.table.label if o.table else "Balcão"
        table_totals[table_label]["total"] = money(table_totals[table_label]["total"] + money(o.total))
        table_totals[table_label]["orders"] += 1

        for item in o.items:
            item_totals[item.product.name]["quantity"] += item.quantity
            item_totals[item.product.name]["total"] = money(
                item_totals[item.product.name]["total"] + money(item.unit_price * item.quantity)
            )

        report["orders"].append(
            {
                "order_id": o.id,
                "table": table_label,
                "waiter": waiter_name,
                "total": as_float(o.total),
                "service_charge": as_float(service_amount),
                "partial_payment": as_float(o.partial_payment),
                "partial_service_charge": as_float(o.partial_service_charge),
                "final_total": as_float(final),
                "payment_method": close_method,
                "closed_at": as_local(o.closed_at).strftime("%H:%M") if o.closed_at else "",
            }
        )

    await _add_direct_payments_to_report(
        start,
        end,
        db,
        report,
        method_totals,
        hour_totals,
        waiter_totals,
    )
    await _add_consignment_payments_to_report(
        start,
        end,
        db,
        report,
        method_totals,
        hour_totals,
        item_totals,
        waiter_totals,
    )
    # Recognize frozen consignment COGS when the credit sale is created.
    report["summary"]["total_cogs"] = money(
        report["summary"]["total_cogs"]
        + await _consignment_cogs_in_period(start, end, db)
    )
    # Credit the waiter only after the consignment is fully paid.
    tips = await _consignment_tips_paid_in_period(start, end, db)
    report["summary"]["total_service_charge"] = money(
        report["summary"]["total_service_charge"] + sum(tips.values(), ZERO)
    )
    for waiter_name, tip_amount in tips.items():
        waiter_totals[waiter_name]["service_charge"] = money(
            waiter_totals[waiter_name]["service_charge"] + tip_amount
        )
    await _add_consignment_sale_rankings(
        start, end, db, item_totals, waiter_totals
    )
    await _apply_refunds_to_report(
        start,
        end,
        db,
        report,
        method_totals,
        hour_totals,
        item_totals,
        waiter_totals,
        table_totals,
    )
    await _add_consignment_summary(start, end, db, report)

    _finalize_report_totals(
        report,
        method_totals,
        waiter_totals,
        table_totals,
        hour_totals,
        item_totals,
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
        .where(Order.status == "finalizada", Order.is_estorno == False)
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
    )

    day_start, day_end = None, None
    if date_filter:
        filter_date = parse_local_date(date_filter)
        if filter_date:
            day_start, day_end = local_day_to_utc_range(filter_date)
            query = query.where(Order.closed_at >= day_start, Order.closed_at <= day_end)

    result = await db.execute(query)
    orders = result.scalars().all()

    data = []
    total_day = ZERO
    total_service = await _direct_service_in_period(day_start, day_end, db)
    counted_orders = 0

    for o in orders:
        if o.payment_method == "fiado":
            continue
        data.append(serialize_order_sale(o))
        counted_orders += 1

    sales_total_query = select(func.coalesce(func.sum(Order.total), 0)).where(
        Order.status == "finalizada",
        or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
    )
    if day_start is not None and day_end is not None:
        sales_total_query = sales_total_query.where(
            Order.closed_at >= day_start,
            Order.closed_at <= day_end,
        )
    total_day = money(await db.scalar(sales_total_query))

    consignment_paid_total = ZERO
    if day_start is not None and day_end is not None:
        consignment_payments = await fetch_consignment_payments(day_start, day_end, db)
        consignment_paid_total = money(
            sum((payment.product_portion for payment in consignment_payments), ZERO)
        )
        total_day = money(total_day + consignment_paid_total)
        total_service = money(
            total_service
            + money(
                sum(
                    (await _consignment_tips_paid_in_period(day_start, day_end, db)).values(),
                    ZERO,
                )
            )
        )

    refund_query = select(
        func.coalesce(
            func.sum(
                case(
                    (
                        PaymentRefund.sale_was_recognized == True,
                        PaymentRefund.product_amount,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            PaymentRefund.service_was_recognized == True,
                            PaymentRefund.service_already_repassed == False,
                        ),
                        PaymentRefund.service_amount,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
    )
    if day_start is not None and day_end is not None:
        refund_query = refund_query.where(
            PaymentRefund.created_at >= day_start,
            PaymentRefund.created_at <= day_end,
        )
    refunded_product, refundable_service = (await db.execute(refund_query)).one()
    total_day = money(total_day - money(refunded_product))
    total_service = money(total_service - money(refundable_service))

    return {
        "sales": data,
        "summary": {
            "total_sales": as_float(total_day),
            "total_service_charge": as_float(total_service),
            "orders_count": counted_orders,
            "consignment_paid": round(consignment_paid_total, 2),
        },
    }


class RefundSaleRequest(BaseModel):
    reason: str = Field(default="Estorno solicitado pelo gerente", min_length=3, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=64)


@router.delete("/vendas/{order_id}")
async def estornar_venda(
    order_id: int,
    req: RefundSaleRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "gerente":
        raise HTTPException(status_code=403, detail="Acesso restrito ao gerente")

    open_session = await db.scalar(
        select(CashRegisterSession)
        .where(CashRegisterSession.status == "open")
        .with_for_update()
    )
    if not open_session:
        return {"error": "Abra o caixa antes de registrar o estorno"}

    payload = req or RefundSaleRequest()
    try:
        refund = await refund_full_order(
            db,
            order_id=order_id,
            user=user,
            cash_session=open_session,
            reason=payload.reason.strip(),
            idempotency_key=payload.idempotency_key,
        )
    except ValueError as exc:
        return {"error": str(exc)}

    await db.commit()

    seen = set()
    for pid, pstock, pstatus in refund.stock_updates:
        if pid in seen:
            continue
        seen.add(pid)
        await broadcast_stock_update(pid, pstock, pstatus)

    return {
        "message": "Venda estornada com sucesso",
        "order_id": order_id,
        "refund_group_key": refund.group_key,
        "refund_ids": refund.refund_ids,
        "refunded_amount": as_float(refund.gross_amount),
        "idempotent_replay": refund.replayed,
    }


@router.post("/vendas/{order_id}/reabrir")
async def reabrir_venda(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role != "gerente":
        raise HTTPException(status_code=403, detail="Acesso restrito ao gerente")

    return {
        "error": (
            "Estornos financeiros são imutáveis e não podem ser reabertos. "
            "Registre uma nova venda se necessário."
        )
    }


@router.get("/vendas/estornadas")
async def list_estornadas(
    date_filter: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_financial(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    query = (
        select(Order)
        .where(Order.is_estorno == True)
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
        .order_by(desc(Order.closed_at))
    )

    if date_filter:
        filter_date = parse_local_date(date_filter)
        if filter_date:
            day_start, day_end = local_day_to_utc_range(filter_date)
            query = query.where(
                or_(
                    Order.refunds.any(
                        PaymentRefund.created_at.between(day_start, day_end)
                    ),
                    and_(
                        ~Order.refunds.any(),
                        Order.closed_at.between(day_start, day_end),
                    ),
                )
            )

    result = await db.execute(query)
    orders = result.scalars().all()

    data = []
    for o in orders:
        payload = serialize_order_sale(o)
        payload["can_estornar"] = False
        payload["can_reabrir"] = False
        data.append(payload)

    return {"estornadas": data}


@router.get("/vendas/consignados-pagos")
async def list_consignment_payments(
    date_filter: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_financial(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    if date_filter:
        filter_date = parse_local_date(date_filter)
        if filter_date:
            day_start, day_end = local_day_to_utc_range(filter_date)
        else:
            day_start, day_end = local_day_to_utc_range(today_local())
    else:
        day_start, day_end = local_day_to_utc_range(today_local())

    payments = await fetch_consignment_payments(day_start, day_end, db)

    data = []
    for p in payments:
        consignment = p.consignment_order
        method = p.payment_method or "nao_informado"
        data.append({
            "payment_id": p.id,
            "consignment_id": p.consignment_order_id,
            "customer_name": (
                consignment.customer.name
                if consignment and consignment.customer
                else None
            ),
            "waiter_name": (
                consignment.credited_waiter_name if consignment else None
            ),
            "amount": round(float(p.amount), 2),
            "payment_method": method,
            "payment_method_label": PAYMENT_LABELS.get(method, method),
            "card_machine": p.card_machine,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "consignment_total": round(float(consignment.total), 2) if consignment else 0.0,
            "consignment_balance": round(float(consignment.balance), 2) if consignment else 0.0,
        })

    return {"pagamentos": data}


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
                func.count(Order.id),
            ).where(
                Order.status == "finalizada",
                Order.closed_at >= start,
                Order.closed_at <= end,
                or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
            )
        )
        sales_total, sales_count = sales_result.one()
        service_charge = await _direct_service_in_period(start, end, db)

        payments_result = await db.execute(
            select(
                func.coalesce(func.sum(ConsignmentPayment.product_portion), 0),
            ).where(
                ConsignmentPayment.created_at >= start,
                ConsignmentPayment.created_at <= end,
            )
        )
        payments_product = payments_result.scalar_one()
        payments_total = float(payments_product)

        refund_result = await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                PaymentRefund.sale_was_recognized == True,
                                PaymentRefund.product_amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    PaymentRefund.service_was_recognized == True,
                                    PaymentRefund.service_already_repassed == False,
                                ),
                                PaymentRefund.service_amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(
                PaymentRefund.created_at >= start,
                PaymentRefund.created_at <= end,
            )
        )
        refunded_product, refunded_service = refund_result.one()
        consignment_tips = await _consignment_tips_paid_in_period(start, end, db)

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
            "total": as_float(
                money(sales_total) + money(payments_total) - money(refunded_product)
            ),
            "service_charge": as_float(
                money(service_charge)
                + money(sum(consignment_tips.values()))
                - money(refunded_service)
            ),
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
