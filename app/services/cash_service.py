"""Cash calculation helpers shared by the cash register and financial reports.

All datetimes are stored in UTC. Business logic here works with the period
[start, end] provided by the caller.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_register_session import CashRegisterSession
from app.models.consignment import ConsignmentPayment
from app.models.order import Order


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

    cash_inflows = Decimal("0.0")

    # Final cash payments for orders closed in the period.
    closed_orders_result = await db.execute(
        select(Order).where(
            Order.status == "finalizada",
            Order.closed_at >= period_start,
            Order.closed_at <= period_end,
        )
    )
    for order in closed_orders_result.scalars().all():
        if order.payment_method == "dinheiro":
            remaining_product = max(0.0, order.total - order.partial_payment)
            remaining_service = (
                remaining_product * (order.service_charge_pct / 100)
                if order.service_charge_applied
                else 0.0
            )
            cash_inflows += Decimal(str(remaining_product + remaining_service))

    # Partial cash payments recorded in the period.
    partial_orders_result = await db.execute(
        select(Order).where(
            Order.partial_payments_detail.is_not(None),
            Order.status.in_(["aberta", "finalizada"]),
        )
    )
    for order in partial_orders_result.scalars().all():
        for detail in order.partial_payments_detail or []:
            if detail.get("method") != "dinheiro":
                continue
            paid_at_str = detail.get("created_at")
            paid_at = None
            if paid_at_str:
                try:
                    paid_at = datetime.fromisoformat(paid_at_str)
                except ValueError:
                    paid_at = None
            if paid_at is None:
                paid_at = order.created_at
            if paid_at is None:
                continue
            if period_start <= paid_at <= period_end:
                cash_inflows += Decimal(str(detail.get("amount", 0)))

    # Cash payments received for consignment balances in the period.
    consignment_payments_result = await db.execute(
        select(ConsignmentPayment).where(
            ConsignmentPayment.payment_method == "dinheiro",
            ConsignmentPayment.created_at >= period_start,
            ConsignmentPayment.created_at <= period_end,
        )
    )
    for payment in consignment_payments_result.scalars().all():
        cash_inflows += Decimal(str(payment.amount))

    return float(round(cash_inflows, 2))


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
    total_sangria = float(sum(float(m.amount) for m in movements if m.type == "sangria"))
    total_suprimento = float(sum(float(m.amount) for m in movements if m.type == "suprimento"))

    cash_inflows = await compute_cash_inflows(session, start, end, db)
    initial_cash = float(session.initial_cash)
    expected_cash = round(
        initial_cash + cash_inflows - total_sangria + total_suprimento,
        2,
    )

    return {
        "initial_cash": initial_cash,
        "cash_inflows": cash_inflows,
        "total_sangria": round(total_sangria, 2),
        "total_suprimento": round(total_suprimento, 2),
        "expected_cash": expected_cash,
    }
