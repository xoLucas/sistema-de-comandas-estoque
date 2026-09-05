"""Cash calculation helpers shared by the cash register and financial reports.

All datetimes are stored in UTC. Business logic here works with the period
[start, end] provided by the caller.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone import local_hour_label
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
    # Orders converted to consignment (fiado) have their partials registered as
    # ConsignmentPayment rows, so they must not be double-counted here.
    partial_orders_result = await db.execute(
        select(Order).where(
            Order.partial_payments_detail.is_not(None),
            Order.status.in_(["aberta", "finalizada"]),
            or_(Order.payment_method != "fiado", Order.payment_method.is_(None)),
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
    orders: list,
    consignment_payments: list,
    start: datetime,
    end: datetime,
) -> tuple[dict, dict]:
    """Break finalized orders down by payment method and hour using the same
    semantics as the financial reports: the close "final" amount goes into the
    close method/hour, and each partial goes into its own method/hour (only for
    partials paid within [start, end]).

    Consignment installments received in the period are aggregated too.

    Returns (method_totals, hour_totals) where each value is
    {"gross": float, "count": int}.
    """
    method_totals: dict[str, dict] = {}
    hour_totals: dict[str, dict] = {}

    def _add_method(method: str, amount: float) -> None:
        entry = method_totals.setdefault(method, {"gross": 0.0, "count": 0})
        entry["gross"] += amount
        entry["count"] += 1

    def _add_hour(hour_key: str, amount: float) -> None:
        entry = hour_totals.setdefault(hour_key, {"gross": 0.0, "count": 0})
        entry["gross"] += amount
        entry["count"] += 1

    for o in orders:
        product_remaining = max(0.0, o.total - o.partial_payment)
        service_remaining = (
            product_remaining * (o.service_charge_pct / 100)
            if o.service_charge_applied
            else 0.0
        )
        final = product_remaining + service_remaining
        close_method = o.payment_method or "nao_informado"

        if final > 0:
            _add_method(close_method, final)
            close_hour = local_hour_label(o.closed_at) if o.closed_at else "00:00"
            _add_hour(close_hour, final)

        for pd in o.partial_payments_detail or []:
            amount = float(pd.get("amount", 0))
            if amount <= 0:
                continue
            paid_at = _partial_paid_at(pd, o.closed_at)
            if paid_at is None or not (start <= paid_at <= end):
                continue
            p_method = pd.get("method", "nao_informado")
            _add_method(p_method, amount)
            hour_key = local_hour_label(paid_at)
            _add_hour(hour_key, amount)

    for payment in consignment_payments:
        amount = float(payment.amount)
        method = payment.payment_method or "nao_informado"
        _add_method(method, amount)
        if payment.created_at:
            _add_hour(local_hour_label(payment.created_at), amount)

    for totals_map in (method_totals, hour_totals):
        for entry in totals_map.values():
            entry["gross"] = round(entry["gross"], 2)

    return method_totals, hour_totals
