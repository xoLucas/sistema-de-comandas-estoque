"""Idempotent data backfills for the normalized financial records."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cash_register_session import CashRegisterSession
from app.models.consignment import ConsignmentOrder, ConsignmentPayment
from app.models.order import Order
from app.models.payment import OrderPayment
from app.models.product import Product
from app.models.stock_history import StockHistory
from app.services.money_service import ZERO, cost, money, percentage_amount, rate
from app.services.settings_service import get_card_fee_for_machine


BACKFILL_VERSION = "20260905_02_financial_integrity_backfill"
logger = logging.getLogger(__name__)


async def _audit_suspect_modern_consignment_payments(db: AsyncSession) -> None:
    result = await db.execute(
        select(ConsignmentPayment.id)
        .where(
            ConsignmentPayment.is_legacy_inferred == True,
            ConsignmentPayment.idempotency_key.is_not(None),
        )
        .order_by(ConsignmentPayment.id)
        .limit(100)
    )
    suspect_ids = list(result.scalars().all())
    if suspect_ids:
        logger.warning(
            "Detected consignment payments that may have been incorrectly marked "
            "as legacy; no automatic repair was applied. payment_ids=%s",
            suspect_ids,
        )


async def _session_for_timestamp(
    db: AsyncSession, timestamp: datetime | None
) -> CashRegisterSession | None:
    if timestamp is None:
        return None
    result = await db.execute(
        select(CashRegisterSession)
        .where(
            CashRegisterSession.opened_at <= timestamp,
            (
                CashRegisterSession.closed_at.is_(None)
                | (CashRegisterSession.closed_at >= timestamp)
            ),
        )
        .order_by(CashRegisterSession.opened_at.desc())
        .limit(1)
    )
    return result.scalars().first()


def _parse_timestamp(raw: object, fallback: datetime | None) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return fallback
    return fallback


async def _fee_snapshot(
    db: AsyncSession,
    gross_amount: Decimal,
    payment_method: str,
    card_machine: str | None,
) -> tuple[Decimal, Decimal]:
    if payment_method not in {"cartao_credito", "cartao_debito"}:
        return rate(0), money(0)
    fee_rate = rate(
        await get_card_fee_for_machine(db, card_machine, payment_method)
    )
    return fee_rate, percentage_amount(gross_amount, fee_rate)


async def _backfill_order_payments(db: AsyncSession) -> None:
    result = await db.execute(select(Order).order_by(Order.id))
    orders = result.scalars().all()

    for order in orders:
        for index, detail in enumerate(order.partial_payments_detail or [], start=1):
            legacy_key = f"legacy-order-{order.id}-partial-{index}"
            existing = await db.scalar(
                select(OrderPayment.id).where(OrderPayment.idempotency_key == legacy_key)
            )
            if existing:
                continue

            gross_amount = money(detail.get("amount", 0))
            if gross_amount <= ZERO:
                continue
            service_amount = money(detail.get("service_portion", 0))
            product_amount_value = money(
                detail.get("product_portion", gross_amount - service_amount)
            )
            payment_method = detail.get("method") or "nao_informado"
            card_machine = detail.get("card_machine")
            paid_at = _parse_timestamp(detail.get("created_at"), order.created_at)
            cash_session = await _session_for_timestamp(db, paid_at)
            fee_rate, fee_amount = await _fee_snapshot(
                db, gross_amount, payment_method, card_machine
            )
            db.add(
                OrderPayment(
                    order_id=order.id,
                    user_id=order.waiter_id,
                    cash_session_id=cash_session.id if cash_session else None,
                    payment_type="partial",
                    gross_amount=gross_amount,
                    product_amount=product_amount_value,
                    service_amount=service_amount,
                    payment_method=payment_method,
                    card_machine=card_machine,
                    card_fee_rate=fee_rate,
                    card_fee_amount=fee_amount,
                    idempotency_key=legacy_key,
                    is_legacy_inferred=True,
                    created_at=paid_at,
                )
            )

        if order.status != "finalizada" or order.payment_method == "fiado":
            continue
        legacy_key = f"legacy-order-{order.id}-final"
        existing = await db.scalar(
            select(OrderPayment.id).where(OrderPayment.idempotency_key == legacy_key)
        )
        if existing:
            continue

        product_amount_value = money(max(ZERO, money(order.total) - money(order.partial_payment)))
        service_amount = money(
            max(
                ZERO,
                money(order.service_charge_amount)
                - money(order.partial_service_charge),
            )
        )
        gross_amount = money(product_amount_value + service_amount)
        if gross_amount <= ZERO:
            continue
        payment_method = order.payment_method or "nao_informado"
        cash_session = await _session_for_timestamp(db, order.closed_at)
        fee_rate, fee_amount = await _fee_snapshot(
            db, gross_amount, payment_method, order.card_machine
        )
        db.add(
            OrderPayment(
                order_id=order.id,
                user_id=order.closed_by_id or order.waiter_id,
                cash_session_id=cash_session.id if cash_session else None,
                payment_type="final",
                gross_amount=gross_amount,
                product_amount=product_amount_value,
                service_amount=service_amount,
                payment_method=payment_method,
                card_machine=order.card_machine,
                card_fee_rate=fee_rate,
                card_fee_amount=fee_amount,
                idempotency_key=legacy_key,
                is_legacy_inferred=True,
                created_at=order.closed_at or order.created_at,
            )
        )

    await db.flush()


async def _match_source_order_payment(
    db: AsyncSession,
    consignment: ConsignmentOrder,
    payment: ConsignmentPayment,
) -> OrderPayment | None:
    if not consignment.source_order_id or not payment.created_at:
        return None
    candidates = await db.execute(
        select(OrderPayment).where(
            OrderPayment.order_id == consignment.source_order_id,
            OrderPayment.payment_type == "partial",
            OrderPayment.gross_amount == money(payment.amount),
        )
    )
    for candidate in candidates.scalars().all():
        if candidate.created_at and abs(
            (candidate.created_at - payment.created_at).total_seconds()
        ) < 0.01:
            return candidate
    return None


async def _backfill_consignments(db: AsyncSession) -> None:
    result = await db.execute(
        select(ConsignmentOrder)
        .options(
            selectinload(ConsignmentOrder.items),
            selectinload(ConsignmentOrder.payments),
            selectinload(ConsignmentOrder.source_order),
        )
        .order_by(ConsignmentOrder.id)
    )
    consignments = result.scalars().all()

    for consignment in consignments:
        payments = sorted(
            consignment.payments,
            key=lambda payment: (payment.created_at or consignment.created_at, payment.id),
        )
        legacy_candidate_ids = {
            payment.id
            for payment in payments
            if payment.idempotency_key is None
            and payment.source_order_payment_id is None
            and not payment.is_legacy_inferred
        }
        if not legacy_candidate_ids:
            continue

        source = consignment.source_order
        item_product_total = money(
            sum(money(item.unit_price) * item.quantity for item in consignment.items)
        )
        product_total = money(source.total) if source else item_product_total
        if product_total == ZERO and item_product_total != ZERO:
            product_total = item_product_total

        previous_total = money(consignment.total)
        remaining_service = money(
            max(ZERO, previous_total - (money(source.total) if source else product_total))
        )
        already_paid_service = money(source.partial_service_charge) if source else ZERO
        service_total = money(already_paid_service + remaining_service)

        paid_product = ZERO
        paid_service = ZERO
        for payment in payments:
            payment_amount = money(payment.amount)
            if payment.id not in legacy_candidate_ids:
                payment_product = money(payment.product_portion)
                payment_service = money(payment.service_portion)
            else:
                known_service = money(payment.service_portion)
                if known_service > ZERO:
                    payment_service = min(known_service, payment_amount)
                    payment_product = money(payment_amount - payment_service)
                else:
                    outstanding_product = max(ZERO, product_total - paid_product)
                    payment_product = min(payment_amount, outstanding_product)
                    payment_service = money(payment_amount - payment_product)

                payment.product_portion = money(payment_product)
                payment.service_portion = money(payment_service)

                if payment.cash_session_id is None:
                    cash_session = await _session_for_timestamp(db, payment.created_at)
                    payment.cash_session_id = cash_session.id if cash_session else None
                fee_rate, fee_amount = await _fee_snapshot(
                    db,
                    payment_amount,
                    payment.payment_method or "nao_informado",
                    payment.card_machine,
                )
                payment.card_fee_rate = fee_rate
                payment.card_fee_amount = fee_amount
                payment.is_legacy_inferred = True

                source_payment = await _match_source_order_payment(
                    db, consignment, payment
                )
                if source_payment:
                    payment.source_order_payment_id = source_payment.id

            paid_product = money(paid_product + payment_product)
            paid_service = money(paid_service + payment_service)

        contains_modern_payment = any(
            payment.id not in legacy_candidate_ids
            and not (
                payment.is_legacy_inferred
                and payment.idempotency_key is None
            )
            for payment in payments
        )
        if not contains_modern_payment:
            gross_total = money(product_total + service_total)
            gross_paid = money(sum(money(payment.amount) for payment in payments))
            consignment.product_total = product_total
            consignment.service_total = service_total
            consignment.total = gross_total
            consignment.amount_paid = gross_paid
            consignment.balance = money(max(ZERO, gross_total - gross_paid))
            if consignment.status != "cancelado":
                consignment.status = "pago" if consignment.balance == ZERO else "pendente"
                if consignment.status == "pago" and consignment.closed_at is None and payments:
                    consignment.closed_at = payments[-1].created_at


async def _backfill_loss_costs(db: AsyncSession) -> None:
    result = await db.execute(
        select(StockHistory, Product)
        .join(Product, Product.id == StockHistory.product_id)
        .where(
            StockHistory.type == "saida",
            StockHistory.order_id.is_(None),
            StockHistory.consignment_order_id.is_(None),
            StockHistory.unit_cost_snapshot.is_(None),
        )
    )
    for history, product in result.all():
        history.unit_cost_snapshot = cost(product.cost)


async def _add_financial_constraints(db: AsyncSession) -> None:
    constraints = [
        (
            "order_payments",
            "ck_order_payment_amounts",
            "gross_amount = product_amount + service_amount",
        ),
        (
            "order_payment_allocations",
            "ck_order_payment_allocation_quantity",
            "quantity > 0",
        ),
        (
            "payment_refunds",
            "ck_payment_refund_amounts",
            "gross_amount = product_amount + service_amount",
        ),
        (
            "payment_refunds",
            "ck_payment_refund_source",
            "(payment_id IS NOT NULL AND consignment_payment_id IS NULL) "
            "OR (payment_id IS NULL AND consignment_payment_id IS NOT NULL) "
            "OR (payment_id IS NULL AND consignment_payment_id IS NULL "
            "AND gross_amount = 0 AND payment_method = 'fiado')",
        ),
        (
            "payment_refunds",
            "ck_payment_refund_target",
            "order_id IS NOT NULL OR consignment_order_id IS NOT NULL",
        ),
        (
            "payment_refund_items",
            "ck_payment_refund_item_quantity",
            "quantity > 0",
        ),
        (
            "consignment_payments",
            "ck_consignment_payment_amounts",
            "amount = product_portion + service_portion",
        ),
    ]
    for table_name, constraint_name, expression in constraints:
        await db.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = '{constraint_name}'
                    ) THEN
                        ALTER TABLE {table_name}
                        ADD CONSTRAINT {constraint_name} CHECK ({expression});
                    END IF;
                END
                $$
                """
            )
        )


async def run_financial_backfills(db: AsyncSession) -> None:
    await _audit_suspect_modern_consignment_payments(db)
    applied = await db.scalar(
        text("SELECT 1 FROM schema_migrations WHERE version = :version"),
        {"version": BACKFILL_VERSION},
    )
    if applied:
        return

    await _backfill_order_payments(db)
    await _backfill_consignments(db)
    await _backfill_loss_costs(db)
    await _add_financial_constraints(db)
    await db.execute(
        text("INSERT INTO schema_migrations (version) VALUES (:version)"),
        {"version": BACKFILL_VERSION},
    )
    await db.commit()
