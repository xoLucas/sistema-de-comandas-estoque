"""Regression tests for legacy consignment pre-conversion payment repair."""

from datetime import datetime, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.database import async_session, engine
from app.core.seed import run_seed
from app.models.cash_register_session import CashRegisterSession
from app.models.consignment import ConsignmentOrder, ConsignmentPayment
from app.models.customer import Customer
from app.models.order import Order
from app.models.payment import OrderPayment, PaymentRefund
from app.models.table import Table
from app.models.user import User
from app.services.financial_migration_service import (
    _repair_legacy_preconversion_payments,
)


RUN_INTEGRATION = os.getenv("RUN_DATABASE_INTEGRATION_TESTS") == "1"
DATABASE_NAME = make_url(os.getenv("DATABASE_URL", "sqlite:///unsafe")).database
SAFE_DATABASE = DATABASE_NAME == "ladsbeer_codex_test"


DAY_ONE = datetime(2026, 9, 1, 20, 45, 4, tzinfo=timezone.utc)
DAY_FOUR = datetime(2026, 9, 4, 21, 15, 9, tzinfo=timezone.utc)


@unittest.skipUnless(
    RUN_INTEGRATION and SAFE_DATABASE,
    "requires RUN_DATABASE_INTEGRATION_TESTS=1 and database ladsbeer_codex_test",
)
class LegacyConsignmentPreconversionRepairTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await run_seed()

    async def asyncTearDown(self) -> None:
        await engine.dispose()

    async def _seed_case(self, *, link_existing_payment: bool = False, with_refund: bool = False):
        """Create a converted consignado with a legacy pre-conversion partial.

        The partial paid before the conversion is only represented as an
        OrderPayment (idempotency 'legacy-order-...'), mimicking the client data.
        Returns the ids needed for assertions/cleanup.
        """
        async with async_session() as db:
            manager = await db.scalar(
                select(User).where(User.role == "gerente").order_by(User.id)
            )
            table = await db.scalar(select(Table).order_by(Table.id))
            customer = Customer(
                name="ZEZE TESTE",
                customer_type="pf",
                active=True,
                created_at=DAY_ONE,
                updated_at=DAY_ONE,
            )
            db.add(customer)
            await db.flush()

            order = Order(
                table_id=table.id,
                waiter_id=manager.id,
                customer_id=customer.id,
                customer_name="ZEZE TESTE",
                status="finalizada",
                total=Decimal("20.00"),
                partial_payment=Decimal("10.00"),
                partial_service_charge=Decimal("0.00"),
                payment_method="fiado",
                closed_at=DAY_FOUR,
                created_at=DAY_ONE,
            )
            db.add(order)
            await db.flush()

            order_payment = OrderPayment(
                order_id=order.id,
                user_id=manager.id,
                cash_session_id=None,
                payment_type="partial",
                gross_amount=Decimal("10.00"),
                product_amount=Decimal("10.00"),
                service_amount=Decimal("0.00"),
                payment_method="dinheiro",
                card_fee_rate=Decimal("0.0000"),
                card_fee_amount=Decimal("0.00"),
                idempotency_key=f"legacy-order-{order.id}-partial-1",
                is_legacy_inferred=True,
                created_at=DAY_ONE,
            )
            db.add(order_payment)
            await db.flush()

            consignment = ConsignmentOrder(
                customer_id=customer.id,
                source_order_id=order.id,
                waiter_id=manager.id,
                order_type="pf",
                status="pendente",
                product_total=Decimal("20.00"),
                service_total=Decimal("0.00"),
                total=Decimal("20.00"),
                amount_paid=Decimal("10.00"),
                balance=Decimal("10.00"),
                notes="Gerado da comanda da mesa 1",
                created_at=DAY_ONE,
            )
            db.add(consignment)
            await db.flush()

            existing_payment = ConsignmentPayment(
                consignment_order_id=consignment.id,
                user_id=manager.id,
                amount=Decimal("10.00"),
                product_portion=Decimal("10.00"),
                service_portion=Decimal("0.00"),
                payment_method="dinheiro",
                source_order_payment_id=(
                    order_payment.id if link_existing_payment else None
                ),
                idempotency_key=(
                    f"source-order-payment:{order_payment.id}"
                    if link_existing_payment
                    else "external-quitacao"
                ),
                is_legacy_inferred=True,
                notes="Quitação",
                created_at=DAY_FOUR,
            )
            db.add(existing_payment)
            await db.flush()

            session_id = None
            refund = None
            if with_refund:
                cash_session = CashRegisterSession(
                    opened_by_id=manager.id,
                    initial_cash=Decimal("0.00"),
                    status="open",
                )
                db.add(cash_session)
                await db.flush()
                session_id = cash_session.id
                refund = PaymentRefund(
                    refund_group_key=str(uuid4()),
                    consignment_payment_id=existing_payment.id,
                    consignment_order_id=consignment.id,
                    order_id=None,
                    payment_id=None,
                    user_id=manager.id,
                    cash_session_id=cash_session.id,
                    gross_amount=Decimal("2.00"),
                    product_amount=Decimal("2.00"),
                    service_amount=Decimal("0.00"),
                    payment_method="dinheiro",
                    service_was_recognized=True,
                    sale_was_recognized=True,
                    service_already_repassed=False,
                    reason="teste",
                    idempotency_key=f"refund-{uuid4()}",
                )
                db.add(refund)
                await db.flush()

            await db.commit()
            return {
                "db": db,
                "customer_id": customer.id,
                "order_id": order.id,
                "order_payment_id": order_payment.id,
                "consignment_id": consignment.id,
                "existing_payment_id": existing_payment.id,
                "session_id": session_id,
                "refund_id": refund.id if refund else None,
            }

    async def _cleanup(self, ids: dict) -> None:
        async with async_session() as db:
            if ids["refund_id"] is not None:
                refund = await db.get(PaymentRefund, ids["refund_id"])
                if refund:
                    await db.delete(refund)
            payments = (
                await db.execute(
                    select(ConsignmentPayment).where(
                        ConsignmentPayment.consignment_order_id
                        == ids["consignment_id"]
                    )
                )
            ).scalars().all()
            for payment in payments:
                await db.delete(payment)
            consignment = await db.get(ConsignmentOrder, ids["consignment_id"])
            if consignment:
                await db.delete(consignment)
            order_payment = await db.get(OrderPayment, ids["order_payment_id"])
            if order_payment:
                await db.delete(order_payment)
            order = await db.get(Order, ids["order_id"])
            if order:
                await db.delete(order)
            customer = await db.get(Customer, ids["customer_id"])
            if customer:
                await db.delete(customer)
            if ids["session_id"] is not None:
                session = await db.get(CashRegisterSession, ids["session_id"])
                if session:
                    await db.delete(session)
            await db.commit()

    async def test_repair_materializes_missing_preconversion_payment(self) -> None:
        ids = await self._seed_case()
        try:
            async with async_session() as db:
                await _repair_legacy_preconversion_payments(db)
                await db.commit()

            async with async_session() as db:
                consignment = await db.get(
                    ConsignmentOrder, ids["consignment_id"]
                )
                self.assertEqual(consignment.amount_paid, Decimal("20.00"))
                self.assertEqual(consignment.balance, Decimal("0.00"))
                self.assertEqual(consignment.status, "pago")

                payments = (
                    await db.execute(
                        select(ConsignmentPayment).where(
                            ConsignmentPayment.consignment_order_id
                            == ids["consignment_id"]
                        )
                    )
                ).scalars().all()
                self.assertEqual(len(payments), 2)
                inserted = next(
                    p for p in payments if p.id != ids["existing_payment_id"]
                )
                self.assertEqual(inserted.amount, Decimal("10.00"))
                self.assertEqual(inserted.product_portion, Decimal("10.00"))
                self.assertEqual(inserted.service_portion, Decimal("0.00"))
                self.assertEqual(
                    inserted.source_order_payment_id, ids["order_payment_id"]
                )
                self.assertEqual(
                    inserted.idempotency_key,
                    f"source-order-payment:{ids['order_payment_id']}",
                )
                self.assertTrue(inserted.is_legacy_inferred)
                self.assertEqual(inserted.created_at, DAY_ONE)

            # Idempotency: a second run must not duplicate anything.
            async with async_session() as db:
                await _repair_legacy_preconversion_payments(db)
                await db.commit()
            async with async_session() as db:
                payments = (
                    await db.execute(
                        select(ConsignmentPayment).where(
                            ConsignmentPayment.consignment_order_id
                            == ids["consignment_id"]
                        )
                    )
                ).scalars().all()
                self.assertEqual(len(payments), 2)
        finally:
            await self._cleanup(ids)

    async def test_repair_does_not_duplicate_already_linked_payment(self) -> None:
        ids = await self._seed_case(link_existing_payment=True)
        try:
            async with async_session() as db:
                await _repair_legacy_preconversion_payments(db)
                await db.commit()
            async with async_session() as db:
                payments = (
                    await db.execute(
                        select(ConsignmentPayment).where(
                            ConsignmentPayment.consignment_order_id
                            == ids["consignment_id"]
                        )
                    )
                ).scalars().all()
                self.assertEqual(len(payments), 1)
                self.assertEqual(
                    payments[0].id, ids["existing_payment_id"]
                )
        finally:
            await self._cleanup(ids)

    async def test_repair_skips_totals_update_when_consignment_has_refunds(self) -> None:
        ids = await self._seed_case(with_refund=True)
        try:
            async with async_session() as db:
                await _repair_legacy_preconversion_payments(db)
                await db.commit()
            async with async_session() as db:
                consignment = await db.get(
                    ConsignmentOrder, ids["consignment_id"]
                )
                # Refunded consignados must not have their totals rewritten.
                self.assertEqual(consignment.amount_paid, Decimal("10.00"))
                self.assertEqual(consignment.balance, Decimal("10.00"))
                self.assertEqual(consignment.status, "pendente")
        finally:
            await self._cleanup(ids)


if __name__ == "__main__":
    unittest.main()