"""Immutable payment refund workflow with stock and cash-position audit records."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cash_position_movement import CashPositionMovement
from app.models.cash_register_session import CashRegisterSession
from app.models.consignment import (
    ConsignmentOrder,
    ConsignmentOrderItem,
    ConsignmentPayment,
)
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.payment import (
    OrderPayment,
    OrderPaymentAllocation,
    PaymentRefund,
    PaymentRefundItem,
)
from app.models.product import Product
from app.models.stock_history import StockHistory
from app.models.user import User
from app.services.money_service import ZERO, cost, money
from app.services.payment_service import order_net_paid, refunded_payment_amounts
from app.services.stock_service import is_pack, stock_status, validate_pack_configuration


@dataclass(frozen=True)
class RefundResult:
    group_key: str
    refund_ids: list[int]
    gross_amount: Decimal
    product_amount: Decimal
    service_amount: Decimal
    stock_updates: list[tuple[int, int, str]]
    replayed: bool = False


def _normalized_group_key(value: str | None) -> str:
    normalized = (value or "").strip()
    return normalized[:64] if normalized else str(uuid4())


def _source_idempotency_key(group_key: str, source: str, source_id: int) -> str:
    digest = sha256(f"{group_key}:{source}:{source_id}".encode("utf-8")).hexdigest()
    return f"refund:{digest[:57]}"


async def _existing_refund_result(
    db: AsyncSession, order_id: int, group_key: str
) -> RefundResult | None:
    result = await db.execute(
        select(PaymentRefund).where(PaymentRefund.refund_group_key == group_key)
    )
    refunds = result.scalars().all()
    if not refunds:
        return None
    if any(refund.order_id != order_id for refund in refunds):
        raise ValueError("Identificador de estorno já utilizado")
    return RefundResult(
        group_key=group_key,
        refund_ids=[refund.id for refund in refunds],
        gross_amount=money(sum((refund.gross_amount for refund in refunds), ZERO)),
        product_amount=money(sum((refund.product_amount for refund in refunds), ZERO)),
        service_amount=money(sum((refund.service_amount for refund in refunds), ZERO)),
        stock_updates=[],
        replayed=True,
    )


async def _service_was_repassed(
    db: AsyncSession, source_session_id: int | None
) -> bool:
    if source_session_id is None:
        return False
    source_session = await db.get(CashRegisterSession, source_session_id)
    return bool(source_session and source_session.status == "closed")


async def _create_refund(
    db: AsyncSession,
    *,
    group_key: str,
    order_id: int | None,
    consignment_order_id: int | None = None,
    user: User,
    cash_session: CashRegisterSession,
    reason: str,
    gross_amount: Decimal,
    product_amount: Decimal,
    service_amount: Decimal,
    payment_method: str,
    source_session_id: int | None,
    service_was_recognized: bool = True,
    sale_was_recognized: bool = True,
    service_already_repassed: bool | None = None,
    payment_id: int | None = None,
    consignment_payment_id: int | None = None,
) -> PaymentRefund:
    if payment_id is not None:
        source = "order"
        source_id = payment_id
    elif consignment_payment_id is not None:
        source = "consignment"
        source_id = consignment_payment_id
    else:
        source = "unpaid-consignment"
        source_id = consignment_order_id or order_id
    if source_id is None or (order_id is None and consignment_order_id is None):
        raise ValueError("Origem do estorno não encontrada")

    refund = PaymentRefund(
        refund_group_key=group_key,
        payment_id=payment_id,
        consignment_payment_id=consignment_payment_id,
        order_id=order_id,
        consignment_order_id=consignment_order_id,
        user_id=user.id,
        cash_session_id=cash_session.id,
        gross_amount=money(gross_amount),
        product_amount=money(product_amount),
        service_amount=money(service_amount),
        payment_method=payment_method,
        service_was_recognized=service_was_recognized,
        sale_was_recognized=sale_was_recognized,
        service_already_repassed=(
            service_already_repassed
            if service_already_repassed is not None
            else await _service_was_repassed(db, source_session_id)
        ),
        reason=reason,
        idempotency_key=_source_idempotency_key(group_key, source, source_id),
    )
    db.add(refund)
    await db.flush()
    if refund.gross_amount > ZERO:
        db.add(
            CashPositionMovement(
                type="saida",
                source="automatico",
                title=(
                    f"Estorno venda #{order_id}"
                    if order_id is not None
                    else f"Estorno consignado #{consignment_order_id}"
                ),
                amount=refund.gross_amount,
                observation=f"Mesmo meio do pagamento original: {payment_method}. {reason}",
                session_id=cash_session.id,
                refund_id=refund.id,
                created_by_id=user.id,
            )
        )
    return refund


async def _consignment_service_status(
    db: AsyncSession,
    consignment: ConsignmentOrder,
    payments: list[ConsignmentPayment],
) -> tuple[bool, bool]:
    """Return whether the tip was recognized and whether it was repassed."""
    if consignment.status != "pago" or money(consignment.balance) > ZERO:
        return False, False

    cumulative = ZERO
    for payment in sorted(
        payments,
        key=lambda value: (value.created_at or consignment.created_at, value.id),
    ):
        cumulative = money(cumulative + money(payment.amount))
        if cumulative >= money(consignment.total):
            return True, await _service_was_repassed(db, payment.cash_session_id)
    return False, False


async def _return_stock(
    db: AsyncSession,
    *,
    order: Order,
    item: OrderItem,
    quantity: int,
    note: str,
) -> list[tuple[int, int, str]]:
    product_result = await db.execute(
        select(Product)
        .where(Product.id == item.product_id)
        .options(selectinload(Product.pack_unit_product))
    )
    product = product_result.scalar_one()
    validate_pack_configuration(product)
    target_id = product.pack_unit_product_id or product.id
    stock_product = await db.scalar(
        select(Product).where(Product.id == target_id).with_for_update()
    )
    if not stock_product:
        raise ValueError(f"Produto físico vinculado a {product.name} não encontrado")

    factor = product.pack_size if is_pack(product) else 1
    physical_quantity = quantity * factor
    stock_product.stock += physical_quantity
    db.add(
        StockHistory(
            product_id=stock_product.id,
            source_product_id=product.id if is_pack(product) else None,
            order_id=order.id,
            table_id=order.table_id,
            type="entrada",
            quantity=physical_quantity,
            source_quantity=quantity,
            conversion_factor=factor,
            unit_cost_snapshot=stock_product.cost,
            note=note,
        )
    )

    updates = [(stock_product.id, stock_product.stock, stock_status(stock_product))]
    if is_pack(product):
        pack_stock = stock_product.stock // factor
        pack_status = (
            "em_falta"
            if pack_stock <= 0
            else "em_risco"
            if pack_stock <= product.min_stock
            else "em_conformidade"
        )
        updates.append((product.id, pack_stock, pack_status))
    return updates


async def _remaining_consignment_payment(
    db: AsyncSession, payment: ConsignmentPayment
) -> tuple[Decimal, Decimal, Decimal]:
    refunded = await db.execute(
        select(
            func.coalesce(func.sum(PaymentRefund.gross_amount), 0),
            func.coalesce(func.sum(PaymentRefund.product_amount), 0),
            func.coalesce(func.sum(PaymentRefund.service_amount), 0),
        ).where(PaymentRefund.consignment_payment_id == payment.id)
    )
    refunded_gross, refunded_product, refunded_service = refunded.one()
    return (
        money(payment.amount - money(refunded_gross)),
        money(payment.product_portion - money(refunded_product)),
        money(payment.service_portion - money(refunded_service)),
    )


async def _existing_consignment_refund_result(
    db: AsyncSession, consignment_id: int, group_key: str
) -> RefundResult | None:
    result = await db.execute(
        select(PaymentRefund).where(PaymentRefund.refund_group_key == group_key)
    )
    refunds = result.scalars().all()
    if not refunds:
        return None
    if any(refund.consignment_order_id != consignment_id for refund in refunds):
        raise ValueError("Identificador de estorno já utilizado")
    return RefundResult(
        group_key=group_key,
        refund_ids=[refund.id for refund in refunds],
        gross_amount=money(sum((refund.gross_amount for refund in refunds), ZERO)),
        product_amount=money(
            sum((refund.product_amount for refund in refunds), ZERO)
        ),
        service_amount=money(
            sum((refund.service_amount for refund in refunds), ZERO)
        ),
        stock_updates=[],
        replayed=True,
    )


async def _return_consignment_stock(
    db: AsyncSession,
    *,
    consignment: ConsignmentOrder,
    item: ConsignmentOrderItem,
    note: str,
) -> list[tuple[int, int, str]]:
    product = await db.scalar(
        select(Product)
        .where(Product.id == item.product_id)
        .options(selectinload(Product.pack_unit_product))
    )
    if not product:
        raise ValueError("Produto do consignado não encontrado")
    validate_pack_configuration(product)

    target_id = product.pack_unit_product_id or product.id
    stock_product = await db.scalar(
        select(Product).where(Product.id == target_id).with_for_update()
    )
    if not stock_product:
        raise ValueError(f"Produto físico vinculado a {product.name} não encontrado")

    factor = product.pack_size if is_pack(product) else 1
    physical_quantity = item.quantity * factor
    stock_product.stock += physical_quantity
    db.add(
        StockHistory(
            product_id=stock_product.id,
            source_product_id=product.id if is_pack(product) else None,
            consignment_order_id=consignment.id,
            type="entrada",
            quantity=physical_quantity,
            source_quantity=item.quantity,
            conversion_factor=factor,
            unit_cost_snapshot=stock_product.cost,
            note=note,
        )
    )

    updates = [(stock_product.id, stock_product.stock, stock_status(stock_product))]
    if is_pack(product):
        pack_stock = stock_product.stock // factor
        pack_status = (
            "em_falta"
            if pack_stock <= 0
            else "em_risco"
            if pack_stock <= product.min_stock
            else "em_conformidade"
        )
        updates.append((product.id, pack_stock, pack_status))
    return updates


async def refund_full_consignment(
    db: AsyncSession,
    *,
    consignment_id: int,
    user: User,
    cash_session: CashRegisterSession,
    reason: str,
    idempotency_key: str | None,
) -> RefundResult:
    group_key = _normalized_group_key(idempotency_key)
    replay = await _existing_consignment_refund_result(
        db, consignment_id, group_key
    )
    if replay:
        return replay

    consignment = await db.scalar(
        select(ConsignmentOrder)
        .where(ConsignmentOrder.id == consignment_id)
        .options(selectinload(ConsignmentOrder.items))
        .with_for_update()
    )
    if not consignment:
        raise ValueError("Consignado não encontrado")
    replay = await _existing_consignment_refund_result(
        db, consignment_id, group_key
    )
    if replay:
        return replay
    if consignment.source_order_id is not None:
        raise ValueError("Estorne este consignado pela venda de origem")
    if consignment.status == "cancelado":
        raise ValueError("Consignado já cancelado")

    payments_result = await db.execute(
        select(ConsignmentPayment)
        .where(ConsignmentPayment.consignment_order_id == consignment.id)
        .order_by(ConsignmentPayment.id)
        .with_for_update()
    )
    payments = list(payments_result.scalars().all())
    service_was_recognized, service_already_repassed = await _consignment_service_status(
        db, consignment, payments
    )
    refunds: list[PaymentRefund] = []
    for payment in payments:
        gross_amount, product_amount, service_amount = (
            await _remaining_consignment_payment(db, payment)
        )
        if gross_amount <= ZERO:
            continue
        refunds.append(
            await _create_refund(
                db,
                group_key=group_key,
                order_id=None,
                consignment_order_id=consignment.id,
                user=user,
                cash_session=cash_session,
                reason=reason,
                gross_amount=gross_amount,
                product_amount=product_amount,
                service_amount=service_amount,
                payment_method=payment.payment_method or "nao_informado",
                source_session_id=payment.cash_session_id,
                service_was_recognized=service_was_recognized,
                service_already_repassed=service_already_repassed,
                consignment_payment_id=payment.id,
            )
        )
    if not refunds:
        refunds.append(
            await _create_refund(
                db,
                group_key=group_key,
                order_id=None,
                consignment_order_id=consignment.id,
                user=user,
                cash_session=cash_session,
                reason=reason,
                gross_amount=ZERO,
                product_amount=ZERO,
                service_amount=ZERO,
                payment_method="fiado",
                source_session_id=None,
                service_was_recognized=False,
            )
        )

    item_refund_owner = refunds[0]
    paid_service = money(sum((refund.service_amount for refund in refunds), ZERO))
    item_product_total = money(
        sum((money(item.unit_price * item.quantity) for item in consignment.items), ZERO)
    )
    assigned_service = ZERO
    stock_updates: list[tuple[int, int, str]] = []
    for index, item in enumerate(consignment.items):
        product_amount = money(item.unit_price * item.quantity)
        if index == len(consignment.items) - 1:
            service_amount = money(paid_service - assigned_service)
        elif item_product_total > ZERO:
            service_amount = money(paid_service * product_amount / item_product_total)
            assigned_service = money(assigned_service + service_amount)
        else:
            service_amount = ZERO
        db.add(
            PaymentRefundItem(
                refund_id=item_refund_owner.id,
                order_item_id=None,
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=money(item.unit_price),
                unit_cost=cost(item.unit_cost),
                product_amount=product_amount,
                service_amount=service_amount,
            )
        )
        stock_updates.extend(
            await _return_consignment_stock(
                db,
                consignment=consignment,
                item=item,
                note=f"Estorno do consignado #{consignment.id}",
            )
        )

    consignment.status = "cancelado"
    consignment.balance = ZERO
    consignment.closed_at = datetime.now(timezone.utc)

    return RefundResult(
        group_key=group_key,
        refund_ids=[refund.id for refund in refunds],
        gross_amount=money(sum((refund.gross_amount for refund in refunds), ZERO)),
        product_amount=money(
            sum((refund.product_amount for refund in refunds), ZERO)
        ),
        service_amount=money(
            sum((refund.service_amount for refund in refunds), ZERO)
        ),
        stock_updates=stock_updates,
    )
async def refund_full_order(
    db: AsyncSession,
    *,
    order_id: int,
    user: User,
    cash_session: CashRegisterSession,
    reason: str,
    idempotency_key: str | None,
    allow_open_order: bool = False,
) -> RefundResult:
    group_key = _normalized_group_key(idempotency_key)
    replay = await _existing_refund_result(db, order_id, group_key)
    if replay:
        return replay

    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
        .with_for_update()
    )
    if not order:
        raise ValueError("Venda não encontrada")
    replay = await _existing_refund_result(db, order_id, group_key)
    if replay:
        return replay
    if order.status != "finalizada" and not (
        allow_open_order and order.status == "aberta"
    ):
        raise ValueError("Apenas vendas finalizadas podem ser estornadas")
    if order.is_estorno:
        raise ValueError("Esta venda já foi estornada")

    linked_consignment = await db.scalar(
        select(ConsignmentOrder)
        .where(ConsignmentOrder.source_order_id == order.id)
        .with_for_update()
    )

    refunds: list[PaymentRefund] = []
    sale_was_recognized = order.status == "finalizada"
    if linked_consignment:
        payments_result = await db.execute(
            select(ConsignmentPayment)
            .where(ConsignmentPayment.consignment_order_id == linked_consignment.id)
            .order_by(ConsignmentPayment.id)
            .with_for_update()
        )
        payments = list(payments_result.scalars().all())
        service_was_recognized, service_already_repassed = (
            await _consignment_service_status(db, linked_consignment, payments)
        )
        for payment in payments:
            gross_amount, product_amount, service_amount = (
                await _remaining_consignment_payment(db, payment)
            )
            if gross_amount <= ZERO:
                continue
            refunds.append(
                await _create_refund(
                    db,
                    group_key=group_key,
                    order_id=order.id,
                    consignment_order_id=linked_consignment.id,
                    user=user,
                    cash_session=cash_session,
                    reason=reason,
                    gross_amount=gross_amount,
                    product_amount=product_amount,
                    service_amount=service_amount,
                    payment_method=payment.payment_method or "nao_informado",
                    source_session_id=payment.cash_session_id,
                    service_was_recognized=service_was_recognized,
                    sale_was_recognized=True,
                    service_already_repassed=service_already_repassed,
                    consignment_payment_id=payment.id,
                )
            )
        if not refunds:
            refunds.append(
                await _create_refund(
                    db,
                    group_key=group_key,
                    order_id=order.id,
                    consignment_order_id=linked_consignment.id,
                    user=user,
                    cash_session=cash_session,
                    reason=reason,
                    gross_amount=ZERO,
                    product_amount=ZERO,
                    service_amount=ZERO,
                    payment_method="fiado",
                    source_session_id=None,
                    service_was_recognized=False,
                    sale_was_recognized=True,
                )
            )
        linked_consignment.status = "cancelado"
        linked_consignment.balance = ZERO
    else:
        payments_result = await db.execute(
            select(OrderPayment)
            .where(OrderPayment.order_id == order.id)
            .order_by(OrderPayment.id)
            .with_for_update()
        )
        for payment in payments_result.scalars().all():
            refunded_gross, refunded_product, refunded_service = (
                await refunded_payment_amounts(db, payment.id)
            )
            gross_amount = money(payment.gross_amount - refunded_gross)
            product_amount = money(payment.product_amount - refunded_product)
            service_amount = money(payment.service_amount - refunded_service)
            if gross_amount <= ZERO:
                continue
            refunds.append(
                await _create_refund(
                    db,
                    group_key=group_key,
                    order_id=order.id,
                    user=user,
                    cash_session=cash_session,
                    reason=reason,
                    gross_amount=gross_amount,
                    product_amount=product_amount,
                    service_amount=service_amount,
                    payment_method=payment.payment_method,
                    source_session_id=payment.cash_session_id,
                    sale_was_recognized=sale_was_recognized,
                    payment_id=payment.id,
                )
            )

    refunded_quantities_result = await db.execute(
        select(
            PaymentRefundItem.order_item_id,
            func.coalesce(func.sum(PaymentRefundItem.quantity), 0),
        )
        .join(PaymentRefund, PaymentRefund.id == PaymentRefundItem.refund_id)
        .where(PaymentRefund.order_id == order.id)
        .group_by(PaymentRefundItem.order_item_id)
    )
    already_refunded = {
        item_id: int(quantity)
        for item_id, quantity in refunded_quantities_result.all()
        if item_id is not None
    }

    stock_updates: list[tuple[int, int, str]] = []
    item_refund_owner = refunds[0] if refunds else None
    total_service = money(sum((refund.service_amount for refund in refunds), ZERO))
    item_amounts: list[tuple[OrderItem, int, Decimal]] = []
    for item in order.items:
        quantity = max(0, item.quantity - already_refunded.get(item.id, 0))
        if quantity:
            item_amounts.append((item, quantity, money(item.unit_price * quantity)))
    total_item_amount = money(sum((entry[2] for entry in item_amounts), ZERO))
    assigned_service = ZERO
    for index, (item, quantity, product_amount) in enumerate(item_amounts):
        if index == len(item_amounts) - 1:
            service_amount = money(total_service - assigned_service)
        elif total_item_amount > ZERO:
            service_amount = money(total_service * product_amount / total_item_amount)
            assigned_service = money(assigned_service + service_amount)
        else:
            service_amount = ZERO
        if item_refund_owner:
            db.add(
                PaymentRefundItem(
                    refund_id=item_refund_owner.id,
                    order_item_id=item.id,
                    product_id=item.product_id,
                    quantity=quantity,
                    unit_price=money(item.unit_price),
                    unit_cost=cost(item.unit_cost),
                    product_amount=product_amount,
                    service_amount=service_amount,
                )
            )
        stock_updates.extend(
            await _return_stock(
                db,
                order=order,
                item=item,
                quantity=quantity,
                note=f"Estorno da venda #{order.id}",
            )
        )

    if order.status == "finalizada":
        order.is_estorno = True
    else:
        order.status = "cancelada"
        order.total = ZERO
    if linked_consignment:
        linked_consignment.closed_at = datetime.now(timezone.utc)

    if linked_consignment:
        order.partial_payment = ZERO
        order.partial_service_charge = ZERO
    else:
        net_product, net_service = await order_net_paid(db, order.id)
        order.partial_payment = net_product
        order.partial_service_charge = net_service

    return RefundResult(
        group_key=group_key,
        refund_ids=[refund.id for refund in refunds],
        gross_amount=money(sum((refund.gross_amount for refund in refunds), ZERO)),
        product_amount=money(sum((refund.product_amount for refund in refunds), ZERO)),
        service_amount=money(sum((refund.service_amount for refund in refunds), ZERO)),
        stock_updates=stock_updates,
    )


async def refund_paid_items(
    db: AsyncSession,
    *,
    order_id: int,
    quantities: dict[int, int],
    user: User,
    cash_session: CashRegisterSession,
    reason: str,
    idempotency_key: str | None,
) -> RefundResult:
    group_key = _normalized_group_key(idempotency_key)
    replay = await _existing_refund_result(db, order_id, group_key)
    if replay:
        return replay
    if not quantities or any(quantity <= 0 for quantity in quantities.values()):
        raise ValueError("Informe ao menos um item e uma quantidade válida")

    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
        .with_for_update()
    )
    if not order or order.status not in {"aberta", "finalizada"}:
        raise ValueError("Comanda não encontrada ou indisponível para estorno")
    replay = await _existing_refund_result(db, order_id, group_key)
    if replay:
        return replay
    if order.is_estorno:
        raise ValueError("Esta venda já foi totalmente estornada")

    item_map = {item.id: item for item in order.items}
    if any(item_id not in item_map for item_id in quantities):
        raise ValueError("Um dos itens não pertence à comanda")

    allocations_result = await db.execute(
        select(OrderPaymentAllocation)
        .join(OrderPayment, OrderPayment.id == OrderPaymentAllocation.payment_id)
        .where(
            OrderPayment.order_id == order.id,
            OrderPaymentAllocation.order_item_id.in_(sorted(quantities)),
        )
        .order_by(OrderPaymentAllocation.id)
        .with_for_update()
    )
    allocations = allocations_result.scalars().all()
    remaining_requested = dict(quantities)
    refund_lines: dict[int, list[tuple[OrderItem, int, Decimal, Decimal]]] = defaultdict(list)

    for allocation in allocations:
        requested = remaining_requested.get(allocation.order_item_id, 0)
        if requested <= 0:
            continue
        previous_result = await db.execute(
            select(
                func.coalesce(func.sum(PaymentRefundItem.quantity), 0),
                func.coalesce(func.sum(PaymentRefundItem.service_amount), 0),
            )
            .join(PaymentRefund, PaymentRefund.id == PaymentRefundItem.refund_id)
            .where(
                PaymentRefund.payment_id == allocation.payment_id,
                PaymentRefundItem.order_item_id == allocation.order_item_id,
            )
        )
        previous_quantity, previous_service = previous_result.one()
        available_quantity = max(0, allocation.quantity - int(previous_quantity or 0))
        take = min(requested, available_quantity)
        if take <= 0:
            continue
        available_service = money(allocation.service_amount - money(previous_service))
        service_amount = (
            available_service
            if take == available_quantity
            else min(
                available_service,
                money(allocation.service_amount * take / allocation.quantity),
            )
        )
        item = item_map[allocation.order_item_id]
        refund_lines[allocation.payment_id].append(
            (item, take, money(allocation.unit_price * take), service_amount)
        )
        remaining_requested[allocation.order_item_id] -= take

    if any(quantity > 0 for quantity in remaining_requested.values()):
        raise ValueError("A quantidade solicitada excede os itens pagos selecionados")

    refunds: list[PaymentRefund] = []
    stock_updates: list[tuple[int, int, str]] = []
    returned_by_item: dict[int, int] = defaultdict(int)
    for payment_id, lines in refund_lines.items():
        payment = await db.scalar(
            select(OrderPayment).where(OrderPayment.id == payment_id).with_for_update()
        )
        if not payment:
            raise ValueError("Pagamento original não encontrado")
        product_amount = money(sum((line[2] for line in lines), ZERO))
        service_amount = money(sum((line[3] for line in lines), ZERO))
        refund = await _create_refund(
            db,
            group_key=group_key,
            order_id=order.id,
            user=user,
            cash_session=cash_session,
            reason=reason,
            gross_amount=money(product_amount + service_amount),
            product_amount=product_amount,
            service_amount=service_amount,
            payment_method=payment.payment_method,
            source_session_id=payment.cash_session_id,
            sale_was_recognized=order.status == "finalizada",
            payment_id=payment.id,
        )
        refunds.append(refund)
        for item, quantity, line_product, line_service in lines:
            db.add(
                PaymentRefundItem(
                    refund_id=refund.id,
                    order_item_id=item.id,
                    product_id=item.product_id,
                    quantity=quantity,
                    unit_price=money(item.unit_price),
                    unit_cost=cost(item.unit_cost),
                    product_amount=line_product,
                    service_amount=line_service,
                )
            )
            returned_by_item[item.id] += quantity

    for item_id, quantity in returned_by_item.items():
        item = item_map[item_id]
        stock_updates.extend(
            await _return_stock(
                db,
                order=order,
                item=item,
                quantity=quantity,
                note=f"Estorno parcial da venda #{order.id}",
            )
        )
        if order.status == "aberta":
            if quantity == item.quantity:
                await db.delete(item)
            else:
                item.quantity -= quantity

    if order.status == "aberta":
        await db.flush()
        total = await db.scalar(
            select(func.coalesce(func.sum(OrderItem.unit_price * OrderItem.quantity), 0))
            .where(OrderItem.order_id == order.id, OrderItem.is_pending == False)
        )
        order.total = money(total)
    net_product, net_service = await order_net_paid(db, order.id)
    order.partial_payment = net_product
    order.partial_service_charge = net_service

    return RefundResult(
        group_key=group_key,
        refund_ids=[refund.id for refund in refunds],
        gross_amount=money(sum((refund.gross_amount for refund in refunds), ZERO)),
        product_amount=money(sum((refund.product_amount for refund in refunds), ZERO)),
        service_amount=money(sum((refund.service_amount for refund in refunds), ZERO)),
        stock_updates=stock_updates,
    )
