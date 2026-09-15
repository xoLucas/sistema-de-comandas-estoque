from decimal import Decimal
import os
import unittest

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.core.database import async_session, engine
from app.core.seed import run_seed
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_transfer import OrderTransfer
from app.models.product import Product
from app.models.table import Table
from app.models.user import User
from app.routers.orders import MoveOrderRequest, move_order
from app.routers.tables import get_table_detail


RUN_INTEGRATION = os.getenv("RUN_DATABASE_INTEGRATION_TESTS") == "1"
DATABASE_NAME = make_url(os.getenv("DATABASE_URL", "sqlite:///unsafe")).database
SAFE_DATABASE = DATABASE_NAME == "ladsbeer_codex_test"


@unittest.skipUnless(
    RUN_INTEGRATION and SAFE_DATABASE,
    "requires RUN_DATABASE_INTEGRATION_TESTS=1 and database ladsbeer_codex_test",
)
class OrderTransferIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await run_seed()

        async with async_session() as db:
            self.manager = await db.scalar(
                select(User).where(User.role == "gerente").order_by(User.id)
            )
            self.product = await db.scalar(select(Product).order_by(Product.id))
            self.balcao = await db.scalar(
                select(Table).where(Table.is_balcao == True).order_by(Table.id)  # noqa: E712
            )
            highest_number = await db.scalar(select(func.coalesce(func.max(Table.number), 0)))
            self.origin = Table(
                number=int(highest_number) + 9001,
                status="ocupada",
                is_balcao=False,
                active=True,
            )
            self.destination = Table(
                number=int(highest_number) + 9002,
                status="vazia",
                is_balcao=False,
                active=True,
            )
            self.archived = Table(
                number=int(highest_number) + 9003,
                status="vazia",
                is_balcao=False,
                active=False,
            )
            db.add_all([self.origin, self.destination, self.archived])
            await db.flush()

            order = Order(
                table_id=self.origin.id,
                waiter_id=self.manager.id,
                status="aberta",
                total=Decimal("20.00"),
                partial_payment=Decimal("5.00"),
                partial_service_charge=Decimal("1.00"),
                service_charge_amount=Decimal("1.00"),
            )
            db.add(order)
            await db.flush()
            db.add(
                OrderItem(
                    order_id=order.id,
                    product_id=self.product.id,
                    quantity=2,
                    unit_price=Decimal("10.00"),
                    unit_cost=Decimal("4.00"),
                )
            )
            await db.commit()

            self.order_id = order.id
            self.origin_id = self.origin.id
            self.destination_id = self.destination.id
            self.archived_id = self.archived.id
            self.balcao_id = self.balcao.id
            self.origin_label = f"Mesa {self.origin.number}"
            self.destination_label = f"Mesa {self.destination.number}"

    async def asyncTearDown(self) -> None:
        await engine.dispose()

    async def test_move_order_updates_tables_and_audits(self) -> None:
        async with async_session() as db:
            response = await move_order(
                self.order_id,
                MoveOrderRequest(destination_table_id=self.destination_id),
                db,
                self.manager,
            )

        self.assertNotIn("error", response)
        self.assertEqual(response["to_table_id"], self.destination_id)

        async with async_session() as db:
            order = await db.get(Order, self.order_id)
            origin = await db.get(Table, self.origin_id)
            destination = await db.get(Table, self.destination_id)
            transfer = await db.scalar(
                select(OrderTransfer).where(OrderTransfer.order_id == self.order_id)
            )

            self.assertEqual(order.table_id, self.destination_id)
            self.assertEqual(order.total, Decimal("20.00"))
            self.assertEqual(order.partial_payment, Decimal("5.00"))
            self.assertEqual(order.partial_service_charge, Decimal("1.00"))
            self.assertEqual(order.service_charge_amount, Decimal("1.00"))
            self.assertEqual(origin.status, "vazia")
            self.assertEqual(destination.status, "ocupada")
            self.assertIsNotNone(transfer)
            self.assertEqual(transfer.from_table_id, self.origin_id)
            self.assertEqual(transfer.to_table_id, self.destination_id)
            self.assertEqual(transfer.moved_by_id, self.manager.id)
            self.assertEqual(
                transfer.from_table_label, f"Mesa {origin.number}"
            )
            self.assertEqual(
                transfer.to_table_label, f"Mesa {destination.number}"
            )

    async def test_move_order_allows_parallel_order_on_occupied_destination(self) -> None:
        async with async_session() as db:
            db.add(
                Order(
                    table_id=self.destination_id,
                    waiter_id=self.manager.id,
                    status="aberta",
                    total=Decimal("7.00"),
                )
            )
            await db.commit()

        async with async_session() as db:
            response = await move_order(
                self.order_id,
                MoveOrderRequest(destination_table_id=self.destination_id),
                db,
                self.manager,
            )
        self.assertNotIn("error", response)

        async with async_session() as db:
            destination = await db.get(Table, self.destination_id)
            open_orders = (
                await db.execute(
                    select(func.count(Order.id)).where(
                        Order.table_id == self.destination_id,
                        Order.status == "aberta",
                    )
                )
            ).scalar_one()
            self.assertEqual(destination.status, "ocupada")
            self.assertEqual(open_orders, 2)

    async def test_move_order_rejects_balcao_same_table_and_archived_destination(self) -> None:
        async with async_session() as db:
            same_table = await move_order(
                self.order_id,
                MoveOrderRequest(destination_table_id=self.origin_id),
                db,
                self.manager,
            )
            self.assertIn("error", same_table)

            to_balcao = await move_order(
                self.order_id,
                MoveOrderRequest(destination_table_id=self.balcao_id),
                db,
                self.manager,
            )
            self.assertIn("error", to_balcao)

            to_archived = await move_order(
                self.order_id,
                MoveOrderRequest(destination_table_id=self.archived_id),
                db,
                self.manager,
            )
            self.assertIn("error", to_archived)

    async def test_move_order_from_balcao_is_blocked(self) -> None:
        async with async_session() as db:
            order = Order(
                table_id=self.balcao_id,
                waiter_id=self.manager.id,
                status="aberta",
                total=Decimal("3.00"),
            )
            db.add(order)
            await db.commit()
            order_id = order.id

        async with async_session() as db:
            response = await move_order(
                order_id,
                MoveOrderRequest(destination_table_id=self.destination_id),
                db,
                self.manager,
            )
        self.assertIn("error", response)

    async def test_move_order_exposes_transfer_history_on_table_detail(self) -> None:
        async with async_session() as db:
            response = await move_order(
                self.order_id,
                MoveOrderRequest(destination_table_id=self.destination_id),
                db,
                self.manager,
            )
            self.assertNotIn("error", response)

        async with async_session() as db:
            detail = await get_table_detail(self.destination_id, db, self.manager)

        comanda = next(
            order for order in detail["orders"] if order["id"] == self.order_id
        )
        self.assertEqual(len(comanda["transfers"]), 1)
        self.assertEqual(comanda["transfers"][0]["from_label"], self.origin_label)
        self.assertEqual(comanda["transfers"][0]["to_label"], self.destination_label)
        self.assertTrue(comanda["transfers"][0]["moved_by_name"])
