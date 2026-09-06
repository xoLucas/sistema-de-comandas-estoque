from datetime import datetime, timedelta, timezone
from decimal import Decimal
import asyncio
import os
import unittest
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import selectinload

from app.core.database import async_session, engine
from app.core.seed import run_seed
from app.core.migrations import run_migrations
from app.models.cash_position_movement import CashPositionMovement
from app.models.cash_register_session import CashRegisterSession
from app.models.consignment import (
    ConsignmentOrder,
    ConsignmentOrderItem,
    ConsignmentPayment,
)
from app.models.customer import Customer
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
from app.routers.consignments import (
    ConvertToFiadoRequest,
    convert_order_to_consignment,
)
from app.routers.cash_register import OpenCashRegisterRequest, open_cash_register
from app.routers.customers import customer_summary
from app.routers.dashboards import dashboard_geral
from app.routers.financial import (
    _build_daily_report,
    compute_period_profit,
    list_consignment_payments,
    list_sales,
)
from app.routers.orders import PartialPaymentRequest, partial_payment
from app.routers.tables import get_table_detail
from app.core.timezone import as_local
from app.routers.stock import _apply_pack_stock_change
from app.services.cash_service import (
    compute_payment_breakdown,
    compute_session_cash_summary,
)
from app.services.money_service import ZERO, money
from app.services.payment_service import create_order_payment
from app.services.refund_service import (
    refund_full_consignment,
    refund_full_order,
    refund_paid_items,
)
from app.services.financial_migration_service import (
    BACKFILL_VERSION,
    run_financial_backfills,
)


RUN_INTEGRATION = os.getenv("RUN_DATABASE_INTEGRATION_TESTS") == "1"
DATABASE_NAME = make_url(os.getenv("DATABASE_URL", "sqlite:///unsafe")).database
SAFE_DATABASE = DATABASE_NAME == "ladsbeer_codex_test"


@unittest.skipUnless(
    RUN_INTEGRATION and SAFE_DATABASE,
    "requires RUN_DATABASE_INTEGRATION_TESTS=1 and database ladsbeer_codex_test",
)
class FinancialWorkflowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await run_seed()

    async def asyncTearDown(self) -> None:
        await engine.dispose()

    async def test_00_concurrent_cash_open_creates_one_session(self) -> None:
        async with async_session() as first_db, async_session() as second_db:
            first_manager = await first_db.scalar(
                select(User).where(User.role == "gerente").order_by(User.id)
            )
            second_manager = await second_db.get(User, first_manager.id)
            results = await asyncio.gather(
                open_cash_register(
                    OpenCashRegisterRequest(initial_cash=Decimal("10.00")),
                    first_db,
                    first_manager,
                ),
                open_cash_register(
                    OpenCashRegisterRequest(initial_cash=Decimal("20.00")),
                    second_db,
                    second_manager,
                ),
            )

        self.assertEqual(sum("error" not in result for result in results), 1)
        self.assertEqual(sum("error" in result for result in results), 1)
        async with async_session() as db:
            open_sessions = (
                await db.execute(
                    select(CashRegisterSession).where(
                        CashRegisterSession.status == "open"
                    )
                )
            ).scalars().all()
            self.assertEqual(len(open_sessions), 1)
            open_sessions[0].status = "closed"
            open_sessions[0].closed_at = datetime.now(timezone.utc)
            open_sessions[0].closed_by_id = open_sessions[0].opened_by_id
            open_sessions[0].final_cash = open_sessions[0].initial_cash
            await db.commit()

    async def test_01_refund_compatibility_migration_repairs_intermediate_schema(self) -> None:
        migration_version = "20260906_06_payment_refund_compatibility"
        historical_time = datetime(2020, 1, 2, tzinfo=timezone.utc)
        async with async_session() as db:
            manager = await db.scalar(
                select(User).where(User.role == "gerente").order_by(User.id)
            )
            table = await db.scalar(select(Table).order_by(Table.id))
            source_session = CashRegisterSession(
                opened_by_id=manager.id,
                closed_by_id=manager.id,
                initial_cash=ZERO,
                final_cash=ZERO,
                status="closed",
                opened_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                closed_at=historical_time - timedelta(hours=1),
            )
            db.add(source_session)
            await db.flush()
            order = Order(
                table_id=table.id,
                waiter_id=manager.id,
                closed_by_id=manager.id,
                status="finalizada",
                total=Decimal("10.00"),
                payment_method="pix",
                closed_at=historical_time,
            )
            db.add(order)
            await db.flush()
            payment = OrderPayment(
                order_id=order.id,
                user_id=manager.id,
                cash_session_id=source_session.id,
                payment_type="final",
                gross_amount=Decimal("10.00"),
                product_amount=Decimal("9.00"),
                service_amount=Decimal("1.00"),
                payment_method="pix",
                card_fee_rate=ZERO,
                card_fee_amount=ZERO,
                idempotency_key=f"migration-source-{uuid4().hex}",
                created_at=historical_time,
            )
            db.add(payment)
            await db.flush()
            refund = PaymentRefund(
                refund_group_key=f"migration-refund-{uuid4().hex}",
                payment_id=payment.id,
                order_id=order.id,
                user_id=manager.id,
                cash_session_id=source_session.id,
                gross_amount=Decimal("10.00"),
                product_amount=Decimal("9.00"),
                service_amount=Decimal("1.00"),
                payment_method="pix",
                service_was_recognized=True,
                sale_was_recognized=True,
                service_already_repassed=False,
                reason="Migration compatibility test",
                idempotency_key=f"migration-refund-key-{uuid4().hex}",
                created_at=historical_time,
            )
            db.add(refund)
            await db.flush()
            refund_id = refund.id
            payment_id = payment.id
            order_id = order.id
            session_id = source_session.id
            await db.commit()

        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM schema_migrations WHERE version = :version"),
                {"version": migration_version},
            )
            await connection.execute(
                text(
                    "ALTER TABLE payment_refunds "
                    "DROP COLUMN IF EXISTS refund_group_key CASCADE"
                )
            )
            await connection.execute(
                text(
                    "ALTER TABLE payment_refunds "
                    "DROP COLUMN IF EXISTS service_already_repassed"
                )
            )

        await run_migrations()

        async with async_session() as db:
            columns = set(
                (
                    await db.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'payment_refunds'"
                        )
                    )
                ).scalars().all()
            )
            self.assertIn("refund_group_key", columns)
            self.assertIn("service_already_repassed", columns)
            migrated_refund = (
                await db.execute(
                    text(
                        "SELECT refund_group_key, service_already_repassed "
                        "FROM payment_refunds WHERE id = :refund_id"
                    ),
                    {"refund_id": refund_id},
                )
            ).one()
            self.assertEqual(migrated_refund.refund_group_key, f"legacy-refund:{refund_id}")
            self.assertTrue(migrated_refund.service_already_repassed)
            marker = await db.scalar(
                text("SELECT 1 FROM schema_migrations WHERE version = :version"),
                {"version": migration_version},
            )
            self.assertEqual(marker, 1)
            await db.execute(
                text("DELETE FROM payment_refunds WHERE id = :refund_id"),
                {"refund_id": refund_id},
            )
            await db.execute(
                text("DELETE FROM order_payments WHERE id = :payment_id"),
                {"payment_id": payment_id},
            )
            await db.execute(
                text("DELETE FROM orders WHERE id = :order_id"),
                {"order_id": order_id},
            )
            await db.execute(
                text("DELETE FROM cash_register_sessions WHERE id = :session_id"),
                {"session_id": session_id},
            )
            await db.commit()

    async def test_partial_item_payment_is_persistent_and_reversible(self) -> None:
        now = datetime.now(timezone.utc)
        suffix = uuid4().hex[:10]

        async with async_session() as db:
            manager = await db.scalar(
                select(User).where(User.role == "gerente").order_by(User.id)
            )
            session = CashRegisterSession(
                opened_by_id=manager.id,
                initial_cash=Decimal("25.00"),
                status="open",
                opened_at=now,
            )
            table = Table(
                number=800000 + int(suffix[:5], 16),
                name=f"Partial Integration {suffix}",
                status="ocupada",
                is_balcao=False,
            )
            product = Product(
                name=f"Partial Product {suffix}",
                category="Integration",
                price=Decimal("10.00"),
                cost=Decimal("4.0000"),
                stock=8,
                min_stock=1,
            )
            db.add_all([session, table, product])
            await db.flush()
            order = Order(
                table_id=table.id,
                waiter_id=manager.id,
                status="aberta",
                total=Decimal("20.00"),
                created_at=now,
            )
            db.add(order)
            await db.flush()
            item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=2,
                unit_price=Decimal("10.00"),
                unit_cost=Decimal("4.0000"),
                is_pending=False,
            )
            db.add(item)
            await db.commit()

            request_key = f"partial-item-{suffix}"
            request = PartialPaymentRequest(
                table_id=table.id,
                order_id=order.id,
                amount=Decimal("11.00"),
                payment_method="pix",
                apply_service_charge=True,
                items=[{"order_item_id": item.id, "quantity": 1}],
                idempotency_key=request_key,
            )
            response = await partial_payment(request, db, manager)
            self.assertNotIn("error", response)
            self.assertEqual(money(response["partial_payment"]), Decimal("10.00"))
            self.assertEqual(
                money(response["partial_service_charge"]), Decimal("1.00")
            )

            replay = await partial_payment(request, db, manager)
            self.assertTrue(replay["idempotent_replay"])
            payment_count = await db.scalar(
                select(func.count(OrderPayment.id)).where(
                    OrderPayment.order_id == order.id
                )
            )
            self.assertEqual(payment_count, 1)
            allocation = await db.scalar(
                select(OrderPaymentAllocation).where(
                    OrderPaymentAllocation.payment_id == response["payment_id"]
                )
            )
            self.assertEqual(allocation.quantity, 1)
            self.assertEqual(allocation.product_amount, Decimal("10.00"))
            self.assertEqual(allocation.service_amount, Decimal("1.00"))

            detail = await get_table_detail(table.id, db, manager)
            detail_item = detail["orders"][0]["pedidos"][0]["items"][0]
            self.assertEqual(detail_item["paid_quantity"], 1)

            refund = await refund_paid_items(
                db,
                order_id=order.id,
                quantities={item.id: 1},
                user=manager,
                cash_session=session,
                reason="Integration item refund",
                idempotency_key=f"partial-item-refund-{suffix}",
            )
            self.assertEqual(refund.product_amount, Decimal("10.00"))
            self.assertEqual(refund.service_amount, Decimal("1.00"))
            await db.commit()

            refund_row = await db.get(PaymentRefund, refund.refund_ids[0])
            self.assertFalse(refund_row.sale_was_recognized)

            refreshed_order = await db.get(Order, order.id)
            self.assertEqual(refreshed_order.total, Decimal("10.00"))
            self.assertEqual(refreshed_order.partial_payment, ZERO)
            self.assertEqual(refreshed_order.partial_service_charge, ZERO)
            detail = await get_table_detail(table.id, db, manager)
            detail_item = detail["orders"][0]["pedidos"][0]["items"][0]
            self.assertEqual(detail_item["quantity"], 1)
            self.assertEqual(detail_item["paid_quantity"], 0)

            profit = await compute_period_profit(
                now - timedelta(minutes=1),
                datetime.now(timezone.utc) + timedelta(minutes=1),
                db,
            )
            self.assertEqual(money(profit["total_sales"]), ZERO)
            self.assertEqual(money(profit["total_cogs"]), ZERO)

            report = await _build_daily_report(as_local(now).date(), db, manager.name)
            self.assertEqual(money(report["summary"]["total_sales"]), ZERO)
            self.assertEqual(money(report["summary"]["total_cogs"]), ZERO)
            self.assertEqual(
                money(report["summary"]["total_service_charge"]), ZERO
            )

            session.status = "closed"
            session.closed_at = datetime.now(timezone.utc)
            session.closed_by_id = manager.id
            session.final_cash = session.initial_cash
            await db.commit()

    async def test_refunds_fiado_pack_cash_and_reports_stay_consistent(self) -> None:
        now = datetime.now(timezone.utc)
        suffix = uuid4().hex[:10]

        async with async_session() as db:
            manager = await db.scalar(
                select(User).where(User.role == "gerente").order_by(User.id)
            )
            self.assertIsNotNone(manager)

            open_session = CashRegisterSession(
                opened_by_id=manager.id,
                initial_cash=Decimal("100.00"),
                status="open",
                opened_at=now,
            )
            closed_session = CashRegisterSession(
                opened_by_id=manager.id,
                closed_by_id=manager.id,
                initial_cash=ZERO,
                final_cash=ZERO,
                status="closed",
                opened_at=now - timedelta(hours=2),
                closed_at=now - timedelta(hours=1),
            )
            table = Table(
                number=900000 + int(suffix[:5], 16),
                name=f"Integration {suffix}",
                status="ocupada",
                is_balcao=False,
            )
            customers = [
                Customer(name=f"Integration Customer {suffix}-{index}")
                for index in range(5)
            ]
            products = [
                Product(
                    name=f"Integration Product {suffix}-{index}",
                    category="Integration",
                    price=Decimal("100.00"),
                    cost=Decimal("40.0000"),
                    stock=9,
                    min_stock=1,
                )
                for index in range(4)
            ]
            db.add_all(
                [open_session, closed_session, table, *customers, *products]
            )
            await db.flush()

            # A regular card sale fully refunded in the same cash session.
            regular_order = Order(
                table_id=table.id,
                waiter_id=manager.id,
                closed_by_id=manager.id,
                customer_id=customers[0].id,
                status="finalizada",
                total=Decimal("100.00"),
                service_charge_pct=Decimal("10.0000"),
                service_charge_applied=True,
                service_charge_amount=Decimal("10.00"),
                payment_method="cartao_credito",
                card_machine="1",
                closed_at=now,
            )
            db.add(regular_order)
            await db.flush()
            db.add(
                OrderItem(
                    order_id=regular_order.id,
                    product_id=products[0].id,
                    quantity=1,
                    unit_price=Decimal("100.00"),
                    unit_cost=Decimal("40.0000"),
                    is_pending=False,
                )
            )
            regular_payment, _ = await create_order_payment(
                db,
                order=regular_order,
                user=manager,
                cash_session=open_session,
                payment_type="final",
                product_amount=Decimal("100.00"),
                service_amount=Decimal("10.00"),
                payment_method="cartao_credito",
                card_machine="1",
                idempotency_key=f"regular-payment-{suffix}",
            )
            self.assertEqual(regular_payment.card_fee_amount, Decimal("3.85"))
            regular_refund = await refund_full_order(
                db,
                order_id=regular_order.id,
                user=manager,
                cash_session=open_session,
                reason="Integration refund",
                idempotency_key=f"regular-refund-{suffix}",
            )
            self.assertEqual(regular_refund.gross_amount, Decimal("110.00"))
            self.assertEqual(products[0].stock, 10)
            replay = await refund_full_order(
                db,
                order_id=regular_order.id,
                user=manager,
                cash_session=open_session,
                reason="Integration refund",
                idempotency_key=f"regular-refund-{suffix}",
            )
            self.assertTrue(replay.replayed)

            # A direct consignment returns only money actually paid, but reverses
            # the whole product and frozen COGS when canceled.
            direct_consignment = ConsignmentOrder(
                customer_id=customers[1].id,
                waiter_id=manager.id,
                status="pendente",
                product_total=Decimal("100.00"),
                service_total=ZERO,
                total=Decimal("100.00"),
                amount_paid=Decimal("50.00"),
                balance=Decimal("50.00"),
                created_at=now,
            )
            db.add(direct_consignment)
            await db.flush()
            db.add(
                ConsignmentOrderItem(
                    consignment_order_id=direct_consignment.id,
                    product_id=products[1].id,
                    quantity=1,
                    unit_price=Decimal("100.00"),
                    unit_cost=Decimal("40.0000"),
                )
            )
            db.add(
                ConsignmentPayment(
                    consignment_order_id=direct_consignment.id,
                    user_id=manager.id,
                    amount=Decimal("50.00"),
                    product_portion=Decimal("50.00"),
                    service_portion=ZERO,
                    payment_method="dinheiro",
                    card_fee_rate=ZERO,
                    card_fee_amount=ZERO,
                    cash_session_id=open_session.id,
                    idempotency_key=f"direct-consignment-payment-{suffix}",
                    created_at=now,
                )
            )
            await db.flush()
            direct_refund = await refund_full_consignment(
                db,
                consignment_id=direct_consignment.id,
                user=manager,
                cash_session=open_session,
                reason="Integration direct consignment refund",
                idempotency_key=f"direct-consignment-refund-{suffix}",
            )
            self.assertEqual(direct_refund.gross_amount, Decimal("50.00"))
            self.assertEqual(direct_refund.product_amount, Decimal("50.00"))
            self.assertEqual(products[1].stock, 10)

            # A pack entry changes the linked physical unit stock and records the
            # conversion source, quantity and factor.
            unit_product = Product(
                name=f"Integration Unit {suffix}",
                category="Integration",
                price=Decimal("5.00"),
                cost=Decimal("2.0000"),
                stock=100,
                min_stock=10,
            )
            db.add(unit_product)
            await db.flush()
            pack_product = Product(
                name=f"Integration Pack {suffix}",
                category="Integration Packs",
                price=Decimal("100.00"),
                cost=Decimal("48.0000"),
                stock=0,
                min_stock=1,
                pack_unit_product_id=unit_product.id,
                pack_size=24,
            )
            db.add(pack_product)
            await db.flush()
            changed_product, moved_quantity, _ = await _apply_pack_stock_change(
                pack_product,
                2,
                "entrada",
                "Integration pack entry",
                db,
            )
            self.assertEqual(changed_product.id, unit_product.id)
            self.assertEqual(moved_quantity, 48)
            self.assertEqual(unit_product.stock, 148)
            pack_history = await db.scalar(
                select(StockHistory)
                .where(StockHistory.source_product_id == pack_product.id)
                .order_by(StockHistory.id.desc())
            )
            self.assertEqual(pack_history.source_quantity, 2)
            self.assertEqual(pack_history.conversion_factor, 24)
            self.assertEqual(pack_history.quantity, 48)

            # The approved fiado example: product 100, product paid 50,
            # service paid 5 and remaining service 5 => total 110, paid 55,
            # balance 55. The refund returns 55 and reverses the full item.
            fiado_order = Order(
                table_id=table.id,
                waiter_id=manager.id,
                customer_id=customers[2].id,
                status="aberta",
                total=Decimal("100.00"),
                partial_payment=Decimal("50.00"),
                partial_service_charge=Decimal("5.00"),
                created_at=now,
            )
            db.add(fiado_order)
            await db.flush()
            db.add(
                OrderItem(
                    order_id=fiado_order.id,
                    product_id=products[2].id,
                    quantity=1,
                    unit_price=Decimal("100.00"),
                    unit_cost=Decimal("40.0000"),
                    is_pending=False,
                )
            )
            await create_order_payment(
                db,
                order=fiado_order,
                user=manager,
                cash_session=closed_session,
                payment_type="partial",
                product_amount=Decimal("50.00"),
                service_amount=Decimal("5.00"),
                payment_method="pix",
                card_machine=None,
                idempotency_key=f"fiado-source-payment-{suffix}",
            )
            await db.flush()
            conversion = await convert_order_to_consignment(
                fiado_order.id,
                ConvertToFiadoRequest(
                    customer_id=customers[2].id,
                    apply_service_charge=True,
                ),
                db,
                manager,
            )
            self.assertNotIn("error", conversion)
            converted = await db.get(ConsignmentOrder, conversion["consignment_id"])
            self.assertEqual(converted.product_total, Decimal("100.00"))
            self.assertEqual(converted.service_total, Decimal("10.00"))
            self.assertEqual(converted.total, Decimal("110.00"))
            self.assertEqual(converted.amount_paid, Decimal("55.00"))
            self.assertEqual(converted.balance, Decimal("55.00"))
            linked_refund = await refund_full_order(
                db,
                order_id=fiado_order.id,
                user=manager,
                cash_session=open_session,
                reason="Integration fiado refund",
                idempotency_key=f"fiado-refund-{suffix}",
            )
            self.assertEqual(linked_refund.gross_amount, Decimal("55.00"))
            self.assertEqual(linked_refund.product_amount, Decimal("50.00"))
            self.assertEqual(linked_refund.service_amount, Decimal("5.00"))
            self.assertEqual(products[2].stock, 10)
            await db.flush()

            linked_refund_rows = (
                await db.execute(
                    select(PaymentRefund).where(
                        PaymentRefund.id.in_(linked_refund.refund_ids)
                    )
                )
            ).scalars().all()
            self.assertFalse(
                any(refund.service_already_repassed for refund in linked_refund_rows)
            )
            self.assertFalse(
                any(refund.service_was_recognized for refund in linked_refund_rows)
            )

            linked_item_refund = await db.scalar(
                select(func.sum(PaymentRefundItem.product_amount)).where(
                    PaymentRefundItem.refund_id.in_(linked_refund.refund_ids)
                )
            )
            self.assertEqual(money(linked_item_refund), Decimal("100.00"))

            # Service refunded after its source cash session was closed remains
            # an operating loss and does not reverse the frozen card fee.
            repassed_order = Order(
                table_id=table.id,
                waiter_id=manager.id,
                closed_by_id=manager.id,
                customer_id=customers[3].id,
                status="finalizada",
                total=Decimal("100.00"),
                service_charge_pct=Decimal("10.0000"),
                service_charge_applied=True,
                service_charge_amount=Decimal("10.00"),
                payment_method="pix",
                closed_at=now,
            )
            db.add(repassed_order)
            await db.flush()
            db.add(
                OrderItem(
                    order_id=repassed_order.id,
                    product_id=products[3].id,
                    quantity=1,
                    unit_price=Decimal("100.00"),
                    unit_cost=Decimal("40.0000"),
                    is_pending=False,
                )
            )
            await create_order_payment(
                db,
                order=repassed_order,
                user=manager,
                cash_session=closed_session,
                payment_type="final",
                product_amount=Decimal("100.00"),
                service_amount=Decimal("10.00"),
                payment_method="pix",
                card_machine=None,
                idempotency_key=f"repassed-payment-{suffix}",
            )
            await db.flush()
            repassed_refund = await refund_full_order(
                db,
                order_id=repassed_order.id,
                user=manager,
                cash_session=open_session,
                reason="Integration repassed service refund",
                idempotency_key=f"repassed-refund-{suffix}",
            )
            repassed_refund_row = await db.get(
                PaymentRefund, repassed_refund.refund_ids[0]
            )
            self.assertTrue(repassed_refund_row.service_already_repassed)
            self.assertEqual(products[3].stock, 10)

            await db.commit()

            # All product sales and frozen COGS are reversed in this same test
            # period. Only the original card fee and retained service remain.
            profit = await compute_period_profit(
                now - timedelta(minutes=1),
                datetime.now(timezone.utc) + timedelta(minutes=1),
                db,
            )
            self.assertEqual(money(profit["total_sales"]), ZERO)
            self.assertEqual(money(profit["total_cogs"]), ZERO)
            self.assertEqual(money(profit["total_card_fees"]), Decimal("3.85"))
            self.assertEqual(money(profit["retained_service_loss"]), Decimal("10.00"))
            self.assertEqual(money(profit["net_profit"]), Decimal("-13.85"))

            method_totals, _ = await compute_payment_breakdown(
                now - timedelta(minutes=1),
                datetime.now(timezone.utc) + timedelta(minutes=1),
                db,
            )
            self.assertEqual(money(method_totals["cartao_credito"]["gross"]), ZERO)
            self.assertEqual(money(method_totals["dinheiro"]["gross"]), ZERO)
            self.assertEqual(money(method_totals["pix"]["gross"]), ZERO)

            report = await _build_daily_report(
                as_local(now).date(), db, manager.name
            )
            self.assertEqual(money(report["summary"]["total_sales"]), ZERO)
            self.assertEqual(money(report["summary"]["total_cogs"]), ZERO)
            self.assertEqual(
                money(report["summary"]["total_service_charge"]),
                Decimal("10.00"),
            )
            self.assertEqual(
                money(report["summary"]["retained_service_loss"]),
                Decimal("10.00"),
            )
            self.assertEqual(
                money(report["summary"]["net_profit"]), Decimal("-13.85")
            )

            report_date = as_local(now).date().isoformat()
            general_dashboard = await dashboard_geral(
                report_date,
                report_date,
                "json",
                db,
                manager,
            )
            self.assertEqual(
                money(general_dashboard["sales"]["total"]), ZERO
            )
            self.assertEqual(
                money(general_dashboard["sales"]["service_charge"]),
                Decimal("10.00"),
            )

            sales_page = await list_sales(report_date, db, manager)
            self.assertEqual(money(sales_page["summary"]["total_sales"]), ZERO)
            self.assertEqual(
                money(sales_page["summary"]["total_service_charge"]),
                Decimal("10.00"),
            )
            consignment_payment_page = await list_consignment_payments(
                report_date, db, manager
            )
            self.assertTrue(
                any(
                    payment["consignment_id"] == converted.id
                    for payment in consignment_payment_page["pagamentos"]
                )
            )

            cash_summary = await compute_session_cash_summary(
                open_session,
                open_session.opened_at,
                datetime.now(timezone.utc) + timedelta(minutes=1),
                db,
                movements=[],
            )
            self.assertEqual(money(cash_summary["cash_inflows"]), ZERO)
            self.assertEqual(money(cash_summary["expected_cash"]), Decimal("100.00"))

            workflow_refund_ids = [
                *regular_refund.refund_ids,
                *direct_refund.refund_ids,
                *linked_refund.refund_ids,
                *repassed_refund.refund_ids,
            ]
            position_refunds = await db.scalar(
                select(func.sum(CashPositionMovement.amount)).where(
                    CashPositionMovement.refund_id.in_(workflow_refund_ids)
                )
            )
            self.assertEqual(money(position_refunds), Decimal("325.00"))

            for customer in customers[:4]:
                summary = await customer_summary(customer.id, db, manager)
                self.assertEqual(money(summary["total_spent"]), ZERO)

            direct_with_refunds = await db.scalar(
                select(ConsignmentOrder)
                .where(ConsignmentOrder.id == direct_consignment.id)
                .options(selectinload(ConsignmentOrder.refunds))
            )
            refunded_amount = money(
                sum(
                    (refund.gross_amount for refund in direct_with_refunds.refunds),
                    ZERO,
                )
            )
            self.assertEqual(
                money(direct_with_refunds.amount_paid - refunded_amount), ZERO
            )

            # Simulate records from the previous production format, remove only
            # the disposable database's backfill marker, and verify the one-time
            # migration reconstructs normalized payments and frozen costs.
            await db.execute(
                text(
                    "ALTER TABLE consignment_payments "
                    "DROP CONSTRAINT ck_consignment_payment_amounts"
                )
            )
            legacy_order = Order(
                table_id=table.id,
                waiter_id=manager.id,
                closed_by_id=manager.id,
                customer_id=customers[4].id,
                status="finalizada",
                total=Decimal("100.00"),
                partial_payment=Decimal("30.00"),
                partial_service_charge=Decimal("3.00"),
                partial_payments_detail=[
                    {
                        "amount": 33.0,
                        "product_portion": 30.0,
                        "service_portion": 3.0,
                        "method": "dinheiro",
                        "created_at": now.isoformat(),
                    }
                ],
                service_charge_pct=Decimal("10.0000"),
                service_charge_applied=True,
                service_charge_amount=Decimal("10.00"),
                payment_method="dinheiro",
                closed_at=now,
            )
            db.add(legacy_order)
            await db.flush()
            db.add(
                OrderItem(
                    order_id=legacy_order.id,
                    product_id=products[0].id,
                    quantity=1,
                    unit_price=Decimal("100.00"),
                    unit_cost=Decimal("40.0000"),
                    is_pending=False,
                )
            )
            legacy_consignment = ConsignmentOrder(
                customer_id=customers[4].id,
                waiter_id=manager.id,
                status="pendente",
                product_total=ZERO,
                service_total=ZERO,
                total=Decimal("100.00"),
                amount_paid=Decimal("50.00"),
                balance=Decimal("50.00"),
                created_at=now,
            )
            db.add(legacy_consignment)
            await db.flush()
            modern_consignment = ConsignmentOrder(
                customer_id=customers[4].id,
                waiter_id=manager.id,
                status="pendente",
                product_total=Decimal("80.00"),
                service_total=Decimal("20.00"),
                total=Decimal("100.00"),
                amount_paid=Decimal("40.00"),
                balance=Decimal("60.00"),
                created_at=now,
            )
            db.add(modern_consignment)
            await db.flush()
            modern_payment = ConsignmentPayment(
                consignment_order_id=modern_consignment.id,
                user_id=manager.id,
                amount=Decimal("40.00"),
                product_portion=Decimal("30.00"),
                service_portion=Decimal("10.00"),
                payment_method="cartao_credito",
                card_fee_rate=Decimal("1.2345"),
                card_fee_amount=Decimal("7.89"),
                cash_session_id=open_session.id,
                idempotency_key=f"modern-consignment-{suffix}",
                is_legacy_inferred=False,
                created_at=now,
            )
            db.add(modern_payment)
            db.add_all(
                [
                    ConsignmentOrderItem(
                        consignment_order_id=legacy_consignment.id,
                        product_id=products[1].id,
                        quantity=1,
                        unit_price=Decimal("100.00"),
                        unit_cost=None,
                    ),
                    ConsignmentPayment(
                        consignment_order_id=legacy_consignment.id,
                        user_id=manager.id,
                        amount=Decimal("50.00"),
                        product_portion=ZERO,
                        service_portion=ZERO,
                        payment_method="dinheiro",
                        card_fee_rate=ZERO,
                        card_fee_amount=ZERO,
                        created_at=now,
                    ),
                    StockHistory(
                        product_id=products[1].id,
                        type="saida",
                        quantity=2,
                        unit_cost_snapshot=None,
                        note="Integration legacy loss",
                        created_at=now,
                    ),
                ]
            )
            await db.commit()
            await db.execute(
                text("DELETE FROM schema_migrations WHERE version = :version"),
                {"version": BACKFILL_VERSION},
            )
            await db.commit()

            await run_financial_backfills(db)

            legacy_payments = (
                await db.execute(
                    select(OrderPayment)
                    .where(OrderPayment.order_id == legacy_order.id)
                    .order_by(OrderPayment.payment_type.desc())
                )
            ).scalars().all()
            self.assertEqual(len(legacy_payments), 2)
            self.assertEqual(
                money(sum((payment.gross_amount for payment in legacy_payments), ZERO)),
                Decimal("110.00"),
            )
            self.assertEqual(
                money(sum((payment.product_amount for payment in legacy_payments), ZERO)),
                Decimal("100.00"),
            )
            self.assertEqual(
                money(sum((payment.service_amount for payment in legacy_payments), ZERO)),
                Decimal("10.00"),
            )
            migrated_consignment_payment = await db.scalar(
                select(ConsignmentPayment).where(
                    ConsignmentPayment.consignment_order_id
                    == legacy_consignment.id
                )
            )
            self.assertEqual(
                migrated_consignment_payment.product_portion,
                Decimal("50.00"),
            )
            self.assertEqual(
                migrated_consignment_payment.service_portion,
                ZERO,
            )
            modern_payment = await db.scalar(
                select(ConsignmentPayment)
                .where(ConsignmentPayment.id == modern_payment.id)
                .execution_options(populate_existing=True)
            )
            modern_consignment = await db.scalar(
                select(ConsignmentOrder)
                .where(ConsignmentOrder.id == modern_consignment.id)
                .execution_options(populate_existing=True)
            )
            self.assertEqual(modern_payment.product_portion, Decimal("30.00"))
            self.assertEqual(modern_payment.service_portion, Decimal("10.00"))
            self.assertEqual(modern_payment.card_fee_rate, Decimal("1.2345"))
            self.assertEqual(modern_payment.card_fee_amount, Decimal("7.89"))
            self.assertFalse(modern_payment.is_legacy_inferred)
            self.assertEqual(modern_consignment.product_total, Decimal("80.00"))
            self.assertEqual(modern_consignment.service_total, Decimal("20.00"))
            self.assertEqual(modern_consignment.amount_paid, Decimal("40.00"))
            self.assertEqual(modern_consignment.balance, Decimal("60.00"))
            migrated_loss = await db.scalar(
                select(StockHistory).where(
                    StockHistory.note == "Integration legacy loss"
                )
            )
            self.assertEqual(migrated_loss.unit_cost_snapshot, Decimal("40.0000"))
            marker_count = await db.scalar(
                select(func.count()).select_from(text("schema_migrations")).where(
                    text("version = :version")
                ),
                {"version": BACKFILL_VERSION},
            )
            self.assertEqual(marker_count, 1)


if __name__ == "__main__":
    unittest.main()
