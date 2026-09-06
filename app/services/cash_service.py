"""Cash calculation helpers shared by the cash register and financial reports.

All datetimes are stored in UTC. Business logic here works with the period
[start, end] provided by the caller.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import local_hour_label
from app.models.cash_register_session import CashRegisterSession
from app.models.consignment import ConsignmentPayment
from app.models.order import Order
from app.models.payment import OrderPayment, PaymentRefund
from app.services.money_service import ZERO, as_float, money


async def compute_cash_inflows(
    session: CashRegisterSession,
    start: datetime,
    end: datetime,
    db: AsyncSession,
) -> float:
    """Return the cash inflows for a cash register session/period.

    Includes:
    - Final cash payments for orders closed in the period.
    - Partial cash payments recorded in the period (including open orders).
    - Cash payments received for consignment balances in the period.

    The lower bound is capped at the session opening time, when available, so
    cash received before the current session is never double-counted.
    """
    period_start = max(start, session.opened_at) if session.opened_at else start
    period_end = end

    order_cash = await db.scalar(
        select(func.coalesce(func.sum(OrderPayment.gross_amount), 0))
        .join(Order, Order.id == OrderPayment.order_id)
        .where(
            OrderPayment.cash_session_id == session.id,
            OrderPayment.payment_method == "dinheiro",
            OrderPayment.created_at >= period_start,
            OrderPayment.created_at <= period_end,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
    )
    cash_inflows = money(order_cash)

    # Cash payments received for consignment balances in the period.
    consignment_cash = await db.scalar(
        select(func.coalesce(func.sum(ConsignmentPayment.amount), 0)).where(
            ConsignmentPayment.cash_session_id == session.id,
            ConsignmentPayment.payment_method == "dinheiro",
            ConsignmentPayment.created_at >= period_start,
            ConsignmentPayment.created_at <= period_end,
        )
    )
    cash_inflows = money(cash_inflows + money(consignment_cash))

    cash_refunds = await db.scalar(
        select(func.coalesce(func.sum(PaymentRefund.gross_amount), 0)).where(
            PaymentRefund.cash_session_id == session.id,
            PaymentRefund.payment_method == "dinheiro",
            PaymentRefund.created_at >= period_start,
            PaymentRefund.created_at <= period_end,
        )
    )
    return as_float(money(cash_inflows - money(cash_refunds)))


async def compute_session_cash_summary(
    session: CashRegisterSession,
    start: datetime,
    end: datetime,
    db: AsyncSession,
    movements: list | None = None,
) -> dict:
    """Return the full cash summary for a session/period.

    Expenses are intentionally NOT included in the expected cash because
    expenses are not necessarily paid from the cash drawer.
    """
    if movements is None:
        movements = session.movements or []
    total_sangria = money(
        sum((money(m.amount) for m in movements if m.type == "sangria"), ZERO)
    )
    total_suprimento = money(
        sum((money(m.amount) for m in movements if m.type == "suprimento"), ZERO)
    )

    cash_inflows = money(await compute_cash_inflows(session, start, end, db))
    initial_cash = money(session.initial_cash)
    expected_cash = money(
        initial_cash + cash_inflows - total_sangria + total_suprimento
    )

    return {
        "initial_cash": as_float(initial_cash),
        "cash_inflows": as_float(cash_inflows),
        "total_sangria": as_float(total_sangria),
        "total_suprimento": as_float(total_suprimento),
        "expected_cash": as_float(expected_cash),
    }


def _partial_paid_at(detail: dict, fallback: datetime | None = None) -> datetime | None:
    """Return when a partial payment detail was recorded."""
    raw = detail.get("created_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return fallback
    if isinstance(raw, datetime):
        return raw
    return fallback


async def compute_payment_breakdown(
    start: datetime,
    end: datetime,
    db: AsyncSession,
) -> tuple[dict, dict]:
    """Break canonical payments and refunds down by method and hour.

    Returns (method_totals, hour_totals) where each value is
    {"gross": float, "count": int}.
    """
    method_totals: dict[str, dict] = {}
    hour_totals: dict[str, dict] = {}

    def _add_method(method: str, amount: Decimal, count: bool = True) -> None:
        entry = method_totals.setdefault(method, {"gross": ZERO, "count": 0})
        entry["gross"] = money(entry["gross"] + amount)
        if count:
            entry["count"] += 1

    def _add_hour(hour_key: str, amount: Decimal, count: bool = True) -> None:
        entry = hour_totals.setdefault(hour_key, {"gross": ZERO, "count": 0})
        entry["gross"] = money(entry["gross"] + amount)
        if count:
            entry["count"] += 1

    direct_result = await db.execute(
        select(OrderPayment)
        .join(Order, Order.id == OrderPayment.order_id)
        .where(
            OrderPayment.created_at >= start,
            OrderPayment.created_at <= end,
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
        )
    )
    for payment in direct_result.scalars().all():
        method = payment.payment_method or "nao_informado"
        _add_method(method, payment.gross_amount)
        _add_hour(local_hour_label(payment.created_at), payment.gross_amount)

    consignment_result = await db.execute(
        select(ConsignmentPayment).where(
            ConsignmentPayment.created_at >= start,
            ConsignmentPayment.created_at <= end,
        )
    )
    for payment in consignment_result.scalars().all():
        method = payment.payment_method or "nao_informado"
        _add_method(method, payment.amount)
        if payment.created_at:
            _add_hour(local_hour_label(payment.created_at), payment.amount)

    refund_result = await db.execute(
        select(PaymentRefund).where(
            PaymentRefund.created_at >= start,
            PaymentRefund.created_at <= end,
        )
    )
    for refund in refund_result.scalars().all():
        if money(refund.gross_amount) == ZERO:
            continue
        method = refund.payment_method or "nao_informado"
        negative_amount = -money(refund.gross_amount)
        _add_method(method, negative_amount, count=False)
        _add_hour(
            local_hour_label(refund.created_at), negative_amount, count=False
        )

    for totals_map in (method_totals, hour_totals):
        for entry in totals_map.values():
            entry["gross"] = as_float(entry["gross"])

    return method_totals, hour_totals
