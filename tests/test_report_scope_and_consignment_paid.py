from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.core.database import async_session, engine
from app.core.seed import run_seed
from app.core.timezone import as_local
from app.models.cash_register_session import CashRegisterSession
from app.models.consignment import ConsignmentOrder, ConsignmentOrderItem, ConsignmentPayment
from app.models.customer import Customer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.payment import OrderPaymentAllocation
from app.models.product import Product
from app.models.table import Table
from app.models.user import User
from app.routers.dashboards import dashboard_geral
from app.routers.financial import compute_period_profit, list_sales
from app.services.money_service import ZERO
from app.services.payment_service import create_order_payment
from app.services.refund_service import refund_full_consignment, refund_full_order, refund_paid_items


RUN_INTEGRATION = os.getenv("RUN_DATABASE_INTEGRATION_TESTS") == "1"
DATABASE_NAME = make_url(os.getenv("DATABASE_URL", "sqlite:///unsafe")).database
SAFE_DATABASE = DATABASE_NAME == "ladsbeer_codex_test"


@unittest.skipUnless(
    RUN_INTEGRATION and SAFE_DATABASE,
    "requires RUN_DATABASE_INTEGRATION_TESTS=1 and database ladsbeer_codex_test",
)
class ReportScopeAndConsignmentPaidTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await run_seed()

        async with async_session() as db:
            self.manager_id = await db.scalar(
                select(User.id).where(User.role == "gerente").order_by(User.id)
            )
            suffix = uuid4().hex[:8]
            self.category = f"E2E Scope {suffix}"
            product = Product(
                code=f"SCOPE{suffix}",
                name=f"E2E SCOPE {suffix}",
                category=self.category,
                cost=Decimal("40.0000"),
                margin_pct=ZERO,
                price=Decimal("50.00"),
                stock=1000,
                min_stock=1,
                pack_size=1,
            )
            customer = Customer(name=f"E2E Scope Customer {suffix}", active=True)
            highest_number = await db.scalar(select(func.coalesce(func.max(Table.number), 0)))
            table = Table(
                number=int(highest_number) + 7001,
                status="ocupada",
                is_balcao=False,
                active=True,
            )
            db.add_all([product, customer, table])
            await db.commit()

            self.product_id = product.id
            self.customer_id = customer.id
            self.table_id = table.id

            existing = await db.scalar(
                select(CashRegisterSession).where(CashRegisterSession.status == "open")
            )
            if not existing:
                session = CashRegisterSession(
                    opened_by_id=self.manager_id,
                    initial_cash=Decimal("0.00"),
                    status="open",
                )
                db.add(session)
                await db.commit()
                self.session_id = session.id
            else:
                self.session_id = existing.id

    async def asyncTearDown(self) -> None:
        await engine.dispose()

    async def _cash_session(self, db) -> CashRegisterSession:
        return await db.get(CashRegisterSession, self.session_id)

    async def test_estornada_excluded_and_partial_refund_still_subtracts(self) -> None:
        today = as_local(datetime.now(timezone.utc)).date()

        async with async_session() as db:
            manager = await db.get(User, self.manager_id)
            session = await self._cash_session(db)

            baseline_sales = await list_sales(today.isoformat(), db, manager)
            baseline_total = money_float(baseline_sales["summary"]["total_sales"])
            now = datetime.now(timezone.utc)
            baseline_profit = await compute_period_profit(
                now.replace(hour=0, minute=0, second=0, microsecond=0),
                now + timedelta(minutes=5),
                db,
            )
            baseline_profit_sales = money_float(baseline_profit["total_sales"])
            baseline_dashboard = await dashboard_geral(
                today.isoformat(), today.isoformat(), "json", db, manager
            )
            baseline_dashboard_total = money_float(
                baseline_dashboard["sales"]["total"]
            )

            refunded_order = Order(
                table_id=self.table_id,
                waiter_id=self.manager_id,
                closed_by_id=self.manager_id,
                status="finalizada",
                total=Decimal("100.00"),
                payment_method="pix",
                closed_at=datetime.now(timezone.utc),
            )
            db.add(refunded_order)
            await db.flush()
            db.add(
                OrderItem(
                    order_id=refunded_order.id,
                    product_id=self.product_id,
                    quantity=2,
                    unit_price=Decimal("50.00"),
                    unit_cost=Decimal("40.0000"),
                )
            )
            await create_order_payment(
                db,
                order=refunded_order,
                user=manager,
                cash_session=session,
                payment_type="final",
                product_amount=Decimal("100.00"),
                service_amount=ZERO,
                payment_method="pix",
                card_machine=None,
                idempotency_key=f"scope-full-{uuid4().hex}",
            )
            await refund_full_order(
                db,
                order_id=refunded_order.id,
                user=manager,
                cash_session=session,
                reason="Scope full refund",
                idempotency_key=f"scope-full-refund-{uuid4().hex}",
            )

            partial_order = Order(
                table_id=self.table_id,
                waiter_id=self.manager_id,
                closed_by_id=self.manager_id,
                status="finalizada",
                total=Decimal("100.00"),
                payment_method="pix",
                closed_at=datetime.now(timezone.utc),
            )
            db.add(partial_order)
            await db.flush()
            item = OrderItem(
                order_id=partial_order.id,
                product_id=self.product_id,
                quantity=2,
                unit_price=Decimal("50.00"),
                unit_cost=Decimal("40.0000"),
            )
            db.add(item)
            await db.flush()
            payment, _ = await create_order_payment(
                db,
                order=partial_order,
                user=manager,
                cash_session=session,
                payment_type="partial",
                product_amount=Decimal("50.00"),
                service_amount=ZERO,
                payment_method="pix",
                card_machine=None,
                idempotency_key=f"scope-partial-{uuid4().hex}",
            )
            db.add(
                OrderPaymentAllocation(
                    payment_id=payment.id,
                    order_item_id=item.id,
                    product_id=self.product_id,
                    quantity=1,
                    unit_price=Decimal("50.00"),
                    product_amount=Decimal("50.00"),
                    service_amount=ZERO,
                )
            )
            await db.commit()
            partial_order_id = partial_order.id
            item_id = item.id

        async with async_session() as db:
            manager = await db.get(User, self.manager_id)
            session = await self._cash_session(db)
            await refund_paid_items(
                db,
                order_id=partial_order_id,
                quantities={item_id: 1},
                user=manager,
                cash_session=session,
                reason="Scope partial refund",
                idempotency_key=f"scope-item-refund-{uuid4().hex}",
            )
            await db.commit()

        async with async_session() as db:
            manager = await db.get(User, self.manager_id)
            sales = await list_sales(today.isoformat(), db, manager)
            self.assertEqual(
                money_float(sales["summary"]["total_sales"]), baseline_total + 50.0
            )

            now = datetime.now(timezone.utc)
            profit = await compute_period_profit(
                now.replace(hour=0, minute=0, second=0, microsecond=0),
                now + timedelta(minutes=5),
                db,
            )
            self.assertEqual(
                money_float(profit["total_sales"]), baseline_profit_sales + 50.0
            )

            general = await dashboard_geral(
                today.isoformat(), today.isoformat(), "json", db, manager
            )
            self.assertEqual(
                money_float(general["sales"]["total"]), baseline_dashboard_total + 50.0
            )

            no_filter = await list_sales(None, db, manager)
            self.assertIn("summary", no_filter)

    async def test_consignment_paid_is_gross_net_of_refunds(self) -> None:
        today = as_local(datetime.now(timezone.utc)).date()

        async with async_session() as db:
            manager = await db.get(User, self.manager_id)
            baseline_sales = await list_sales(today.isoformat(), db, manager)
            baseline_paid = money_float(baseline_sales["summary"]["consignment_paid"])
            baseline_dashboard = await dashboard_geral(
                today.isoformat(), today.isoformat(), "json", db, manager
            )
            baseline_dashboard_paid = money_float(
                baseline_dashboard["sales"]["consignment_paid"]
            )

            consignment = ConsignmentOrder(
                customer_id=self.customer_id,
                waiter_id=self.manager_id,
                status="pendente",
                product_total=Decimal("100.00"),
                service_total=Decimal("10.00"),
                total=Decimal("110.00"),
                amount_paid=ZERO,
                balance=Decimal("110.00"),
                created_at=datetime.now(timezone.utc),
            )
            db.add(consignment)
            await db.flush()
            db.add(
                ConsignmentOrderItem(
                    consignment_order_id=consignment.id,
                    product_id=self.product_id,
                    quantity=2,
                    unit_price=Decimal("50.00"),
                    unit_cost=Decimal("40.0000"),
                )
            )
            db.add(
                ConsignmentPayment(
                    consignment_order_id=consignment.id,
                    user_id=self.manager_id,
                    amount=Decimal("110.00"),
                    product_portion=Decimal("100.00"),
                    service_portion=Decimal("10.00"),
                    payment_method="pix",
                    card_fee_rate=ZERO,
                    card_fee_amount=ZERO,
                    cash_session_id=self.session_id,
                    idempotency_key=f"scope-consig-pay-{uuid4().hex}",
                )
            )
            consignment.amount_paid = Decimal("110.00")
            consignment.balance = ZERO
            consignment.status = "pago"
            await db.commit()
            consignment_id = consignment.id

        async with async_session() as db:
            manager = await db.get(User, self.manager_id)
            sales = await list_sales(today.isoformat(), db, manager)
            self.assertEqual(
                money_float(sales["summary"]["consignment_paid"]), baseline_paid + 110.0
            )

            general = await dashboard_geral(
                today.isoformat(), today.isoformat(), "json", db, manager
            )
            self.assertEqual(
                money_float(general["sales"]["consignment_paid"]),
                baseline_dashboard_paid + 110.0,
            )

        async with async_session() as db:
            manager = await db.get(User, self.manager_id)
            session = await self._cash_session(db)
            await refund_full_consignment(
                db,
                consignment_id=consignment_id,
                user=manager,
                cash_session=session,
                reason="Scope consignment refund",
                idempotency_key=f"scope-consig-refund-{uuid4().hex}",
            )
            await db.commit()

        async with async_session() as db:
            manager = await db.get(User, self.manager_id)
            sales = await list_sales(today.isoformat(), db, manager)
            self.assertEqual(
                money_float(sales["summary"]["consignment_paid"]), baseline_paid
            )

            general = await dashboard_geral(
                today.isoformat(), today.isoformat(), "json", db, manager
            )
            self.assertEqual(
                money_float(general["sales"]["consignment_paid"]),
                baseline_dashboard_paid,
            )


def money_float(value) -> float:
    return round(float(value or 0), 2)
