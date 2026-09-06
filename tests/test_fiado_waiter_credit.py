from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import selectinload

from app.core.database import async_session, engine
from app.core.seed import run_seed
from app.models.cash_register_session import CashRegisterSession
from app.models.consignment import (
    ConsignmentOrder,
    ConsignmentOrderItem,
    ConsignmentPayment,
)
from app.models.customer import Customer
from app.models.employee import Employee
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.table import Table
from app.models.user import User
from app.routers.consignments import (
    ConsignmentPaymentRequest,
    ConvertToFiadoRequest,
    add_payment,
    convert_order_to_consignment,
)
from app.routers.financial import _consignment_tips_paid_in_period
from app.services.money_service import ZERO, money


RUN_INTEGRATION = os.getenv("RUN_DATABASE_INTEGRATION_TESTS") == "1"
DATABASE_NAME = make_url(os.getenv("DATABASE_URL", "sqlite:///unsafe")).database
SAFE_DATABASE = DATABASE_NAME == "ladsbeer_codex_test"


@unittest.skipUnless(
    RUN_INTEGRATION and SAFE_DATABASE,
    "requires RUN_DATABASE_INTEGRATION_TESTS=1 and database ladsbeer_codex_test",
)
class FiadoWaiterCreditIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await run_seed()

    async def asyncTearDown(self) -> None:
        await engine.dispose()

    async def test_manager_selected_employee_receives_fiado_service_credit(self) -> None:
        now = datetime.now(timezone.utc)
        suffix = uuid4().hex[:10]

        async with async_session() as db:
            manager = await db.scalar(
                select(User).where(User.role == "gerente").order_by(User.id)
            )
            original_waiter = await db.scalar(
                select(User).where(User.role == "garcom").order_by(User.id)
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

            selected_waiter = Employee(
                name=f"Selected Waiter {suffix}",
                role="garcom",
                active=True,
                user_id=None,
            )
            customer = Customer(name=f"Fiado Credit Customer {suffix}")
            table = Table(
                number=700000 + int(suffix[:5], 16),
                name=f"Fiado Credit {suffix}",
                status="ocupada",
                is_balcao=False,
            )
            product = Product(
                name=f"Fiado Credit Product {suffix}",
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
            db.add_all(
                [selected_waiter, customer, table, product, cash_session]
            )
            await db.flush()

            selected_order = Order(
                table_id=table.id,
                waiter_id=manager.id,
                customer_id=customer.id,
                status="aberta",
                total=Decimal("100.00"),
                created_at=now,
            )
            db.add(selected_order)
            await db.flush()
            db.add(
                OrderItem(
                    order_id=selected_order.id,
                    product_id=product.id,
                    quantity=1,
                    unit_price=Decimal("100.00"),
                    unit_cost=Decimal("40.0000"),
                    is_pending=False,
                )
            )
            await db.commit()

            converted_response = await convert_order_to_consignment(
                selected_order.id,
                ConvertToFiadoRequest(
                    customer_id=customer.id,
                    apply_service_charge=True,
                    waiter_id=selected_waiter.id,
                ),
                db,
                manager,
            )
            self.assertNotIn("error", converted_response)

            converted = await db.scalar(
                select(ConsignmentOrder)
                .where(
                    ConsignmentOrder.id
                    == converted_response["consignment_id"]
                )
                .options(
                    selectinload(ConsignmentOrder.waiter),
                    selectinload(ConsignmentOrder.credited_waiter),
                )
            )
            self.assertEqual(converted.credited_waiter_id, selected_waiter.id)
            self.assertEqual(
                converted.credited_waiter_name, selected_waiter.name
            )
            self.assertIsNone(converted.credited_waiter.user_id)

            closed_order = await db.get(Order, selected_order.id)
            self.assertEqual(closed_order.closed_by_id, manager.id)
            self.assertEqual(
                closed_order.closed_waiter_id, selected_waiter.id
            )

            payment_response = await add_payment(
                converted.id,
                ConsignmentPaymentRequest(
                    amount=Decimal("110.00"),
                    payment_method="pix",
                    idempotency_key=f"fiado-credit-{suffix}",
                ),
                db,
                manager,
            )
            self.assertNotIn("error", payment_response)
            tips = await _consignment_tips_paid_in_period(
                now - timedelta(minutes=1),
                datetime.now(timezone.utc) + timedelta(minutes=1),
                db,
            )
            self.assertEqual(
                money(tips[selected_waiter.name]), Decimal("10.00")
            )

            fallback_order = Order(
                table_id=table.id,
                waiter_id=original_waiter.id,
                customer_id=customer.id,
                status="aberta",
                total=Decimal("100.00"),
                created_at=now,
            )
            db.add(fallback_order)
            await db.flush()
            db.add(
                OrderItem(
                    order_id=fallback_order.id,
                    product_id=product.id,
                    quantity=1,
                    unit_price=Decimal("100.00"),
                    unit_cost=Decimal("40.0000"),
                    is_pending=False,
                )
            )
            await db.commit()

            fallback_response = await convert_order_to_consignment(
                fallback_order.id,
                ConvertToFiadoRequest(customer_id=customer.id),
                db,
                manager,
            )
            self.assertNotIn("error", fallback_response)
            fallback = await db.scalar(
                select(ConsignmentOrder)
                .where(
                    ConsignmentOrder.id == fallback_response["consignment_id"]
                )
                .options(selectinload(ConsignmentOrder.waiter))
            )
            self.assertIsNone(fallback.credited_waiter_id)
            self.assertEqual(fallback.waiter_id, original_waiter.id)
            self.assertEqual(fallback.credited_waiter_name, original_waiter.name)

            cash_session.status = "closed"
            cash_session.closed_at = datetime.now(timezone.utc)
            cash_session.closed_by_id = manager.id
            cash_session.final_cash = ZERO
            await db.commit()

            consignment_ids = [converted.id, fallback.id]
            order_ids = [selected_order.id, fallback_order.id]
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
            await db.execute(
                delete(OrderItem).where(OrderItem.order_id.in_(order_ids))
            )
            await db.execute(delete(Order).where(Order.id.in_(order_ids)))
            await db.execute(
                delete(CashRegisterSession).where(
                    CashRegisterSession.id == cash_session.id
                )
            )
            await db.execute(delete(Product).where(Product.id == product.id))
            await db.execute(delete(Table).where(Table.id == table.id))
            await db.execute(delete(Customer).where(Customer.id == customer.id))
            await db.execute(
                delete(Employee).where(Employee.id == selected_waiter.id)
            )
            await db.commit()
