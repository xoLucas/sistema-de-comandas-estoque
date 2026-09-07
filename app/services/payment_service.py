"""Canonical payment, fee snapshot and refund calculations."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_register_session import CashRegisterSession
from app.models.order import Order
from app.models.payment import (
    OrderPayment,
    OrderPaymentAllocation,
    PaymentRefund,
    PaymentRefundItem,
)
from app.models.user import User
from app.services.money_service import ZERO, money, percentage_amount, rate
from app.services.settings_service import get_card_fee_for_machine


PAYMENT_METHODS = {
    "dinheiro",
    "pix",
    "cartao_debito",
    "cartao_credito",
    "nao_informado",
}

PENDING_CREDIT_LABEL = "Pendente/Aguardando"


def resolve_credited_waiter_name(
    executor: User | None,
    *,
    order_open: bool,
    closer_role: str | None,
    chosen_waiter_name: str | None,
    opener_name: str | None,
) -> str | None:
    """Resolve the waiter credited for a single payment.

    Business rule:
    - A non-manager executor (garcom/caixa/estoquista) is credited themselves.
    - A manager-executed payment on an open order stays unresolved (None).
    - A manager-executed payment on an order closed by a non-manager is credited
      to the manager executor.
    - A manager-executed payment on an order closed by a manager follows the
      close rule: chosen waiter wins, otherwise the waiter who opened the order.
    """
    if executor is None:
        return None
    if executor.role != "gerente":
        return executor.name
    if order_open:
        return None
    if closer_role in ("garcom", "caixa"):
        return executor.name
    if chosen_waiter_name:
        return chosen_waiter_name
    return opener_name or "N/A"


def display_credit_name(credited_waiter_name: str | None) -> str:
    return credited_waiter_name or PENDING_CREDIT_LABEL


async def card_fee_snapshot(
    db: AsyncSession,
    amount: Decimal,
    payment_method: str,
    card_machine: str | None,
) -> tuple[Decimal, Decimal]:
    if payment_method not in {"cartao_debito", "cartao_credito"}:
        return rate(0), money(0)
    fee_rate = rate(
        await get_card_fee_for_machine(db, card_machine, payment_method)
    )
    return fee_rate, percentage_amount(amount, fee_rate)


async def create_order_payment(
    db: AsyncSession,
    *,
    order: Order,
    user: User,
    cash_session: CashRegisterSession,
    payment_type: str,
    product_amount: Decimal,
    service_amount: Decimal,
    payment_method: str,
    card_machine: str | None,
    idempotency_key: str | None,
    credited_waiter_name: str | None = None,
) -> tuple[OrderPayment, bool]:
    normalized_key = idempotency_key.strip() if idempotency_key else None
    if normalized_key:
        existing = await db.scalar(
            select(OrderPayment).where(
                OrderPayment.idempotency_key == normalized_key
            )
        )
        if existing:
            if existing.order_id != order.id:
                raise ValueError("Identificador de pagamento já utilizado")
            return existing, False

    product_amount = money(product_amount)
    service_amount = money(service_amount)
    gross_amount = money(product_amount + service_amount)
    if gross_amount <= ZERO or product_amount < ZERO or service_amount < ZERO:
        raise ValueError("Valor de pagamento inválido")
    fee_rate, fee_amount = await card_fee_snapshot(
        db, gross_amount, payment_method, card_machine
    )
    payment = OrderPayment(
        order_id=order.id,
        user_id=user.id,
        cash_session_id=cash_session.id,
        payment_type=payment_type,
        gross_amount=gross_amount,
        product_amount=product_amount,
        service_amount=service_amount,
        payment_method=payment_method,
        card_machine=card_machine,
        card_fee_rate=fee_rate,
        card_fee_amount=fee_amount,
        credited_waiter_name=credited_waiter_name,
        idempotency_key=normalized_key or str(uuid4()),
    )
    db.add(payment)
    await db.flush()
    return payment, True


async def refunded_payment_amounts(
    db: AsyncSession, payment_id: int
) -> tuple[Decimal, Decimal, Decimal]:
    result = await db.execute(
        select(
            func.coalesce(func.sum(PaymentRefund.gross_amount), 0),
            func.coalesce(func.sum(PaymentRefund.product_amount), 0),
            func.coalesce(func.sum(PaymentRefund.service_amount), 0),
        ).where(PaymentRefund.payment_id == payment_id)
    )
    gross, product, service = result.one()
    return money(gross), money(product), money(service)


async def order_net_paid(db: AsyncSession, order_id: int) -> tuple[Decimal, Decimal]:
    paid_result = await db.execute(
        select(
            func.coalesce(func.sum(OrderPayment.product_amount), 0),
            func.coalesce(func.sum(OrderPayment.service_amount), 0),
        ).where(OrderPayment.order_id == order_id)
    )
    paid_product, paid_service = paid_result.one()
    refund_result = await db.execute(
        select(
            func.coalesce(func.sum(PaymentRefund.product_amount), 0),
            func.coalesce(func.sum(PaymentRefund.service_amount), 0),
        ).where(PaymentRefund.order_id == order_id)
    )
    refunded_product, refunded_service = refund_result.one()
    return (
        money(money(paid_product) - money(refunded_product)),
        money(money(paid_service) - money(refunded_service)),
    )


async def item_net_paid_quantity(
    db: AsyncSession, order_item_id: int
) -> int:
    allocated = await db.scalar(
        select(func.coalesce(func.sum(OrderPaymentAllocation.quantity), 0)).where(
            OrderPaymentAllocation.order_item_id == order_item_id
        )
    )
    refunded = await db.scalar(
        select(func.coalesce(func.sum(PaymentRefundItem.quantity), 0)).where(
            PaymentRefundItem.order_item_id == order_item_id
        )
    )
    return max(0, int(allocated or 0) - int(refunded or 0))


def distribute_service_amount(
    product_amounts: Iterable[Decimal], service_amount: Decimal
) -> list[Decimal]:
    amounts = [money(value) for value in product_amounts]
    service_amount = money(service_amount)
    total = money(sum(amounts, ZERO))
    if not amounts:
        return []
    if service_amount == ZERO or total == ZERO:
        return [ZERO for _ in amounts]

    distributed: list[Decimal] = []
    assigned = ZERO
    for index, amount in enumerate(amounts):
        if index == len(amounts) - 1:
            share = money(service_amount - assigned)
        else:
            share = money(service_amount * amount / total)
            assigned = money(assigned + share)
        distributed.append(share)
    return distributed
