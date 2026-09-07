"""Consistency tests for the per-payment waiter credit attribution.

Business rules covered:
- A non-manager executor (garcom/caixa) is credited for every payment they close.
- A manager-executed payment is deferred; it is resolved at the table close:
  * order closed by a non-manager -> credited to the manager executor;
  * order closed by a manager with a chosen waiter -> credited to the chosen;
  * order closed by a manager without a choice -> credited to the opener.
- An open order with a manager-executed partial stays in "Pendente/Aguardando".
- Refunds (estornos) debit the same credited waiter (fixes the A5 mismatch for
  consignment-converted orders).
- Financial invariants: sum of credited product == order.total, sum of credited
  service == service_charge_amount, fractional order count sums to 1.0.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from sqlalchemy import delete, select, or_
from sqlalchemy.engine import make_url
from sqlalchemy.orm import selectinload

from app.core.database import async_session, engine
from app.core.seed import run_seed
from app.core.timezone import as_local
from app.models.cash_register_session import CashRegisterSession
from app.models.cash_position_movement import CashPositionMovement
from app.models.consignment import (
    ConsignmentOrder,
    ConsignmentOrderItem,
    ConsignmentPayment,
)
from app.models.customer import Customer
from app.models.employee import Employee
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
from app.models.table import Table
from app.models.user import User
from app.routers.consignments import ConvertToFiadoRequest, convert_order_to_consignment
from app.routers.dashboards import dashboard_vendas
from app.routers.financial import _direct_payment_waiter_totals
from app.routers.orders import (
    CloseOrderRequest,
    PartialPaymentRequest,
    close_order,
    partial_payment,
)
from app.services.money_service import ZERO, money
from app.services.payment_service import PENDING_CREDIT_LABEL
from app.services.refund_service import refund_full_order


RUN_INTEGRATION = os.getenv("RUN_DATABASE_INTEGRATION_TESTS") == "1"
DATABASE_NAME = make_url(os.getenv("DATABASE_URL", "sqlite:///unsafe")).database
SAFE_DATABASE = DATABASE_NAME == "ladsbeer_codex_test"


@unittest.skipUnless(
    RUN_INTEGRATION and SAFE_DATABASE,
    "requires RUN_DATABASE_INTEGRATION_TESTS=1 and database ladsbeer_codex_test",
)
class PaymentWaiterCreditIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await run_seed()

    async def asyncTearDown(self) -> None:
        await engine.dispose()

    async def _world(self, db, suffix):
        now = datetime.now(timezone.utc)
        manager = await db.scalar(
            select(User).where(User.role == "gerente").order_by(User.id)
        )
        for existing_session in (
            await db.execute(
                select(CashRegisterSession).where(
                    CashRegisterSession.status == "open"
                )
            )
        ).scalars().all():
            existing_session.status = "closed"
            existing_session.closed_at = now
            existing_session.closed_by_id = manager.id
            existing_session.final_cash = existing_session.initial_cash
        await db.flush()

        garcom_a = User(
            username=f"garcom_a_{suffix}",
            name=f"Garcom A {suffix}",
            role="garcom",
            password_hash="x",
            is_registered=True,
        )
        garcom_b = User(
            username=f"garcom_b_{suffix}",
            name=f"Garcom B {suffix}",
            role="garcom",
            password_hash="x",
            is_registered=True,
        )
        chosen = Employee(
            name=f"Chosen {suffix}",
            role="garcom",
            active=True,
            user_id=None,
        )
        customer = Customer(name=f"Credit Customer {suffix}")
        table = Table(
            number=800000 + int(suffix[:5], 16),
            name=f"Credit Table {suffix}",
            status="ocupada",
            is_balcao=False,
        )
        product = Product(
            name=f"Credit Product {suffix}",
            category="Integration",
            price=Decimal("100.00"),
            cost=Decimal("40.0000"),
            stock=5,
            min_stock=1,
        )
        cash_session = CashRegisterSession(
            opened_by_id=manager.id,
            initial_cash=ZERO,
            status="open",
            opened_at=now,
        )
        db.add_all([garcom_a, garcom_b, chosen, customer, table, product, cash_session])
        await db.flush()
        return {
            "now": now,
            "manager": manager,
            "garcom_a": garcom_a,
            "garcom_b": garcom_b,
            "chosen": chosen,
            "customer": customer,
            "table": table,
            "product": product,
            "session": cash_session,
        }

    async def _make_order(self, db, world, opener) -> Order:
        order = Order(
            table_id=world["table"].id,
            waiter_id=opener.id,
            customer_id=world["customer"].id,
            status="aberta",
            total=Decimal("100.00"),
        )
        db.add(order)
        await db.flush()
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=world["product"].id,
                quantity=1,
                unit_price=Decimal("100.00"),
                unit_cost=Decimal("40.0000"),
                is_pending=False,
            )
        )
        await db.commit()
        return order

    async def _cleanup(self, db, world, order_ids, consignment_ids=None):
        consignment_ids = consignment_ids or []
        payment_ids = [
            row[0]
            for row in (
                await db.execute(
                    select(OrderPayment.id).where(
                        OrderPayment.order_id.in_(order_ids)
                    )
                )
            ).all()
        ]
        if payment_ids:
            await db.execute(
                delete(OrderPaymentAllocation).where(
                    OrderPaymentAllocation.payment_id.in_(payment_ids)
                )
            )
        refund_ids = [
            row[0]
            for row in (
                await db.execute(
                    select(PaymentRefund.id).where(
                        PaymentRefund.order_id.in_(order_ids)
                    )
                )
            ).all()
        ]
        if refund_ids:
            await db.execute(
                delete(CashPositionMovement).where(
                    CashPositionMovement.refund_id.in_(refund_ids)
                )
            )
            await db.execute(
                delete(PaymentRefundItem).where(
                    PaymentRefundItem.refund_id.in_(refund_ids)
                )
            )
            await db.execute(
                delete(PaymentRefund).where(PaymentRefund.id.in_(refund_ids))
            )
        if consignment_ids:
            await db.execute(
                delete(ConsignmentPayment).where(
                    ConsignmentPayment.consignment_order_id.in_(consignment_ids)
                )
            )
            await db.execute(
                delete(ConsignmentOrderItem).where(
                    ConsignmentOrderItem.consignment_order_id.in_(consignment_ids)
                )
            )
            await db.execute(
                delete(ConsignmentOrder).where(
                    ConsignmentOrder.id.in_(consignment_ids)
                )
            )
        if payment_ids:
            await db.execute(
                delete(OrderPaymentAllocation).where(
                    OrderPaymentAllocation.payment_id.in_(payment_ids)
                )
            )
            await db.execute(
                delete(OrderPayment).where(OrderPayment.id.in_(payment_ids))
            )
        await db.execute(
            delete(StockHistory).where(
                or_(
                    StockHistory.order_id.in_(order_ids),
                    StockHistory.consignment_order_id.in_(consignment_ids),
                )
            )
        )
        await db.execute(delete(OrderItem).where(OrderItem.order_id.in_(order_ids)))
        await db.execute(delete(Order).where(Order.id.in_(order_ids)))
        await db.execute(
            delete(CashRegisterSession).where(
                CashRegisterSession.id == world["session"].id
            )
        )
        await db.execute(
            delete(Product).where(Product.id == world["product"].id)
        )
        await db.execute(delete(Table).where(Table.id == world["table"].id))
        await db.execute(
            delete(Customer).where(Customer.id == world["customer"].id)
        )
        await db.execute(
            delete(Employee).where(Employee.id == world["chosen"].id)
        )
        await db.execute(
            delete(User).where(
                User.id.in_([world["garcom_a"].id, world["garcom_b"].id])
            )
        )
        await db.commit()

    async def _payments_of(self, db, order_id):
        return (
            await db.execute(
                select(OrderPayment)
                .where(OrderPayment.order_id == order_id)
                .options(selectinload(OrderPayment.user))
                .order_by(OrderPayment.id)
            )
        ).scalars().all()

    async def test_garcom_partial_and_close_all_credited_to_garcom(self) -> None:
        suffix = uuid4().hex[:10]
        async with async_session() as db:
            world = await self._world(db, suffix)
            order = await self._make_order(db, world, world["garcom_a"])

            resp = await partial_payment(
                PartialPaymentRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    amount=Decimal("30.00"),
                    payment_method="pix",
                ),
                db,
                world["garcom_a"],
            )
            self.assertNotIn("error", resp)

            resp = await close_order(
                CloseOrderRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    apply_service_charge=True,
                    payment_method="pix",
                ),
                db,
                world["garcom_a"],
            )
            self.assertNotIn("error", resp)

            payments = await self._payments_of(db, order.id)
            self.assertEqual(len(payments), 2)
            for payment in payments:
                self.assertEqual(
                    payment.credited_waiter_name, world["garcom_a"].name
                )

            product_total = money(
                sum((payment.product_amount for payment in payments), ZERO)
            )
            service_total = money(
                sum((payment.service_amount for payment in payments), ZERO)
            )
            closed = await db.get(Order, order.id)
            self.assertEqual(product_total, money(closed.total))
            self.assertEqual(service_total, money(closed.service_charge_amount))

            totals = await _direct_payment_waiter_totals(
                world["now"] - timedelta(minutes=1),
                datetime.now(timezone.utc) + timedelta(minutes=1),
                db,
            )
            self.assertEqual(totals[world["garcom_a"].name]["sales"], 100.0)
            self.assertEqual(totals[world["garcom_a"].name]["orders"], 1.0)

            await self._cleanup(db, world, [order.id])

    async def test_manager_partial_then_garcom_closes_partials_go_to_manager(self) -> None:
        suffix = uuid4().hex[:10]
        async with async_session() as db:
            world = await self._world(db, suffix)
            order = await self._make_order(db, world, world["garcom_a"])

            resp = await partial_payment(
                PartialPaymentRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    amount=Decimal("30.00"),
                    payment_method="pix",
                ),
                db,
                world["manager"],
            )
            self.assertNotIn("error", resp)

            resp = await close_order(
                CloseOrderRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    apply_service_charge=True,
                    payment_method="pix",
                ),
                db,
                world["garcom_a"],
            )
            self.assertNotIn("error", resp)

            payments = await self._payments_of(db, order.id)
            self.assertEqual(len(payments), 2)
            self.assertEqual(payments[0].credited_waiter_name, world["manager"].name)
            self.assertEqual(
                payments[1].credited_waiter_name, world["garcom_a"].name
            )

            totals = await _direct_payment_waiter_totals(
                world["now"] - timedelta(minutes=1),
                datetime.now(timezone.utc) + timedelta(minutes=1),
                db,
            )
            self.assertEqual(totals[world["manager"].name]["sales"], 30.0)
            self.assertEqual(totals[world["garcom_a"].name]["sales"], 70.0)

            await self._cleanup(db, world, [order.id])

    async def test_garcom_partial_then_manager_closes_with_chosen(self) -> None:
        suffix = uuid4().hex[:10]
        async with async_session() as db:
            world = await self._world(db, suffix)
            order = await self._make_order(db, world, world["garcom_a"])

            resp = await partial_payment(
                PartialPaymentRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    amount=Decimal("30.00"),
                    payment_method="pix",
                ),
                db,
                world["garcom_a"],
            )
            self.assertNotIn("error", resp)

            resp = await close_order(
                CloseOrderRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    apply_service_charge=True,
                    payment_method="pix",
                    waiter_id=world["chosen"].id,
                ),
                db,
                world["manager"],
            )
            self.assertNotIn("error", resp)

            payments = await self._payments_of(db, order.id)
            self.assertEqual(len(payments), 2)
            self.assertEqual(
                payments[0].credited_waiter_name, world["garcom_a"].name
            )
            self.assertEqual(
                payments[1].credited_waiter_name, world["chosen"].name
            )

            await self._cleanup(db, world, [order.id])

    async def test_manager_partial_and_close_without_choice_goes_to_opener(self) -> None:
        suffix = uuid4().hex[:10]
        async with async_session() as db:
            world = await self._world(db, suffix)
            order = await self._make_order(db, world, world["garcom_a"])

            resp = await partial_payment(
                PartialPaymentRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    amount=Decimal("30.00"),
                    payment_method="pix",
                ),
                db,
                world["manager"],
            )
            self.assertNotIn("error", resp)

            resp = await close_order(
                CloseOrderRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    apply_service_charge=True,
                    payment_method="pix",
                ),
                db,
                world["manager"],
            )
            self.assertNotIn("error", resp)

            payments = await self._payments_of(db, order.id)
            self.assertEqual(len(payments), 2)
            for payment in payments:
                self.assertEqual(
                    payment.credited_waiter_name, world["garcom_a"].name
                )

            await self._cleanup(db, world, [order.id])

    async def test_manager_partial_and_close_with_choice_goes_to_chosen(self) -> None:
        suffix = uuid4().hex[:10]
        async with async_session() as db:
            world = await self._world(db, suffix)
            order = await self._make_order(db, world, world["garcom_a"])

            resp = await partial_payment(
                PartialPaymentRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    amount=Decimal("30.00"),
                    payment_method="pix",
                ),
                db,
                world["manager"],
            )
            self.assertNotIn("error", resp)

            resp = await close_order(
                CloseOrderRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    apply_service_charge=True,
                    payment_method="pix",
                    waiter_id=world["chosen"].id,
                ),
                db,
                world["manager"],
            )
            self.assertNotIn("error", resp)

            payments = await self._payments_of(db, order.id)
            self.assertEqual(len(payments), 2)
            for payment in payments:
                self.assertEqual(
                    payment.credited_waiter_name, world["chosen"].name
                )

            await self._cleanup(db, world, [order.id])

    async def test_manager_partial_on_open_order_stays_pending(self) -> None:
        suffix = uuid4().hex[:10]
        async with async_session() as db:
            world = await self._world(db, suffix)
            order = await self._make_order(db, world, world["garcom_a"])

            resp = await partial_payment(
                PartialPaymentRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    amount=Decimal("30.00"),
                    payment_method="pix",
                ),
                db,
                world["manager"],
            )
            self.assertNotIn("error", resp)

            payments = await self._payments_of(db, order.id)
            self.assertEqual(len(payments), 1)
            self.assertIsNone(payments[0].credited_waiter_name)

            paid_at = payments[0].created_at
            totals = await _direct_payment_waiter_totals(
                paid_at - timedelta(seconds=1),
                paid_at + timedelta(seconds=1),
                db,
            )
            self.assertEqual(totals[PENDING_CREDIT_LABEL]["sales"], 30.0)

            await self._cleanup(db, world, [order.id])

    async def test_dashboard_vendas_by_waiter_splits_payments(self) -> None:
        suffix = uuid4().hex[:10]
        async with async_session() as db:
            world = await self._world(db, suffix)
            order = await self._make_order(db, world, world["garcom_a"])

            resp = await partial_payment(
                PartialPaymentRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    amount=Decimal("30.00"),
                    payment_method="pix",
                ),
                db,
                world["garcom_a"],
            )
            self.assertNotIn("error", resp)

            resp = await close_order(
                CloseOrderRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    apply_service_charge=True,
                    payment_method="pix",
                ),
                db,
                world["garcom_b"],
            )
            self.assertNotIn("error", resp)

            today = as_local(datetime.now(timezone.utc)).date().isoformat()
            result = await dashboard_vendas(
                today, today, "json", 1, 50, db, world["manager"]
            )
            self.assertNotIn("error", result)
            by_waiter = {entry["name"]: entry for entry in result["by_waiter"]}
            self.assertEqual(
                by_waiter[world["garcom_a"].name]["total"], 30.0
            )
            self.assertEqual(
                by_waiter[world["garcom_b"].name]["total"], 70.0
            )

            await self._cleanup(db, world, [order.id])

    async def test_consignment_converted_refund_debits_credited_waiter(self) -> None:
        suffix = uuid4().hex[:10]
        async with async_session() as db:
            world = await self._world(db, suffix)
            order = await self._make_order(db, world, world["garcom_a"])

            resp = await partial_payment(
                PartialPaymentRequest(
                    table_id=world["table"].id,
                    order_id=order.id,
                    amount=Decimal("30.00"),
                    payment_method="pix",
                ),
                db,
                world["garcom_a"],
            )
            self.assertNotIn("error", resp)

            converted_response = await convert_order_to_consignment(
                order.id,
                ConvertToFiadoRequest(customer_id=world["customer"].id),
                db,
                world["manager"],
            )
            self.assertNotIn("error", converted_response)
            consignment_id = converted_response["consignment_id"]

            consignment = await db.scalar(
                select(ConsignmentOrder).where(
                    ConsignmentOrder.id == consignment_id
                )
            )
            self.assertEqual(
                consignment.credited_waiter_name, world["garcom_a"].name
            )

            # Detach the opener and the consignment from the identity map so the
            # refund path must resolve the consignment waiter through a real
            # load (regression guard for MissingGreenlet on lazy IO).
            db.expunge(world["garcom_a"])
            db.expunge(consignment)

            refund = await refund_full_order(
                db,
                order_id=order.id,
                user=world["manager"],
                cash_session=world["session"],
                reason="Consistency estorno",
                idempotency_key=f"credit-estorno-{suffix}",
            )
            await db.commit()

            refund_rows = (
                await db.execute(
                    select(PaymentRefund).where(
                        PaymentRefund.order_id == order.id
                    )
                )
            ).scalars().all()
            self.assertTrue(refund_rows)
            for row in refund_rows:
                self.assertEqual(
                    row.credited_waiter_name, world["garcom_a"].name
                )
            self.assertEqual(money(refund.gross_amount), Decimal("30.00"))

            await self._cleanup(
                db, world, [order.id], consignment_ids=[consignment_id]
            )