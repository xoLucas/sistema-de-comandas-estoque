"""Consignment payment helpers shared by dashboards and financial reports.

Only paid installments (ConsignmentPayment.amount) count as revenue. Pending
balances are receivables and must never be added to sales totals.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.consignment import ConsignmentPayment, ConsignmentOrder, ConsignmentOrderItem
from app.models.product import Product


async def fetch_consignment_payments(
    start: datetime,
    end: datetime,
    db: AsyncSession,
    with_items: bool = True,
) -> list[ConsignmentPayment]:
    """Return consignment payments received in [start, end] with relations loaded."""
    query = (
        select(ConsignmentPayment)
        .where(
            ConsignmentPayment.created_at >= start,
            ConsignmentPayment.created_at <= end,
        )
        .options(
            selectinload(ConsignmentPayment.consignment_order)
            .selectinload(ConsignmentOrder.customer),
            selectinload(ConsignmentPayment.consignment_order)
            .selectinload(ConsignmentOrder.waiter),
        )
    )
    if with_items:
        query = query.options(
            selectinload(ConsignmentPayment.consignment_order)
            .selectinload(ConsignmentOrder.items)
            .selectinload(ConsignmentOrderItem.product),
        )
    result = await db.execute(query)
    return result.scalars().all()


async def fetch_consignment_payments_for_customer(
    customer_id: int,
    db: AsyncSession,
) -> list[ConsignmentPayment]:
    """Return all consignment payments for a given customer."""
    result = await db.execute(
        select(ConsignmentPayment)
        .join(ConsignmentOrder, ConsignmentOrder.id == ConsignmentPayment.consignment_order_id)
        .where(ConsignmentOrder.customer_id == customer_id)
    )
    return result.scalars().all()