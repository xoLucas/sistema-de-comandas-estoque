from decimal import Decimal
import os
import unittest
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from app.core.database import async_session, engine
from app.core.seed import run_seed
from app.models.cash_register_session import CashRegisterSession
from app.models.consignment import ConsignmentOrderItem
from app.models.customer import Customer
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.table import Table
from app.models.user import User
from app.routers.consignments import (
    ConsignmentCreateRequest,
    ConsignmentItemRequest,
    create_consignment,
)
from app.routers.orders import CreatePedidoRequest, PedidoItem, create_pedido
from app.routers.stock import ProductUpdate, update_product
from app.services.financial_migration_service import (
    PACK_COST_VERSION,
    run_financial_backfills,
)
from app.services.money_service import ZERO


RUN_INTEGRATION = os.getenv("RUN_DATABASE_INTEGRATION_TESTS") == "1"
DATABASE_NAME = make_url(os.getenv("DATABASE_URL", "sqlite:///unsafe")).database
SAFE_DATABASE = DATABASE_NAME == "ladsbeer_codex_test"


@unittest.skipUnless(
    RUN_INTEGRATION and SAFE_DATABASE,
    "requires RUN_DATABASE_INTEGRATION_TESTS=1 and database ladsbeer_codex_test",
)
class PackCostIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await run_seed()

        async with async_session() as db:
            self.manager_id = await db.scalar(
                select(User.id).where(User.role == "gerente").order_by(User.id)
            )

            suffix = uuid4().hex[:8]
            self.category = f"E2E Pack {suffix}"
            unit = Product(
                code=f"UNI{suffix}",
                name=f"E2E UNIT {suffix}",
                category=self.category,
                cost=Decimal("5.0000"),
                margin_pct=ZERO,
                price=Decimal("10.00"),
                stock=200,
                min_stock=1,
                pack_size=1,
            )
            db.add(unit)
            await db.flush()
            pack = Product(
                code=f"PACK{suffix}",
                name=f"E2E PACK {suffix}",
                category=self.category,
                cost=ZERO,
                margin_pct=ZERO,
                price=Decimal("60.00"),
                stock=15,
                min_stock=1,
                pack_unit_product_id=unit.id,
                pack_size=12,
            )
            db.add(pack)
            await db.flush()

            highest_number = await db.scalar(
                select(func.coalesce(func.max(Table.number), 0))
            )
            table = Table(
                number=int(highest_number) + 8001,
                status="vazia",
                is_balcao=False,
                active=True,
            )
            customer = Customer(
                name=f"E2E Cliente {suffix}",
                customer_type="pf",
                active=True,
            )
            db.add_all([table, customer])
            await db.commit()

            self.unit_id = unit.id
            self.pack_id = pack.id
            self.table_id = table.id
            self.customer_id = customer.id

    async def asyncTearDown(self) -> None:
        await engine.dispose()

    async def _ensure_open_cash(self, db) -> None:
        existing = await db.scalar(
            select(CashRegisterSession).where(CashRegisterSession.status == "open")
        )
        if existing:
            return
        db.add(
            CashRegisterSession(
                opened_by_id=self.manager_id,
                initial_cash=ZERO,
                status="open",
            )
        )
        await db.commit()

    async def test_pack_sale_and_consignment_snapshot_unit_cost(self) -> None:
        async with async_session() as db:
            await self._ensure_open_cash(db)
            manager = await db.get(User, self.manager_id)
            order = Order(
                table_id=self.table_id,
                waiter_id=self.manager_id,
                status="aberta",
                total=ZERO,
            )
            db.add(order)
            await db.commit()
            order_id = order.id

        async with async_session() as db:
            manager = await db.get(User, self.manager_id)
            response = await create_pedido(
                CreatePedidoRequest(
                    table_id=self.table_id,
                    order_id=order_id,
                    items=[PedidoItem(product_id=self.pack_id, quantity=2)],
                ),
                db,
                manager,
            )
            self.assertNotIn("error", response)
            item = await db.scalar(
                select(OrderItem).where(
                    OrderItem.order_id == order_id,
                    OrderItem.product_id == self.pack_id,
                )
            )
            self.assertEqual(item.unit_cost, Decimal("60.0000"))

            consignment_response = await create_consignment(
                ConsignmentCreateRequest(
                    customer_id=self.customer_id,
                    items=[ConsignmentItemRequest(product_id=self.pack_id, quantity=1)],
                ),
                db,
                manager,
            )
            self.assertNotIn("error", consignment_response)
            consignment_item = await db.scalar(
                select(ConsignmentOrderItem).where(
                    ConsignmentOrderItem.consignment_order_id
                    == consignment_response["id"],
                    ConsignmentOrderItem.product_id == self.pack_id,
                )
            )
            self.assertEqual(consignment_item.unit_cost, Decimal("60.0000"))

    async def test_backfill_repairs_pack_cost_and_item_snapshots(self) -> None:
        async with async_session() as db:
            unit = await db.get(Product, self.unit_id)
            unit.cost = Decimal("5.0000")
            pack = await db.get(Product, self.pack_id)
            pack.cost = ZERO
            pack.stock = 15
            order = Order(
                table_id=self.table_id,
                waiter_id=self.manager_id,
                status="aberta",
                total=ZERO,
            )
            db.add(order)
            await db.flush()
            item = OrderItem(
                order_id=order.id,
                product_id=self.pack_id,
                quantity=1,
                unit_price=Decimal("60.00"),
                unit_cost=ZERO,
            )
            db.add(item)
            await db.execute(
                text("DELETE FROM schema_migrations WHERE version = :version"),
                {"version": PACK_COST_VERSION},
            )
            await db.commit()
            item_id = item.id

        async with async_session() as db:
            await run_financial_backfills(db)

        async with async_session() as db:
            pack = await db.get(Product, self.pack_id)
            item = await db.get(OrderItem, item_id)

        self.assertEqual(pack.cost, Decimal("60.0000"))
        self.assertEqual(pack.stock, 0)
        self.assertEqual(item.unit_cost, Decimal("60.0000"))

    async def test_update_unit_cost_syncs_packs_and_pack_stock_is_ignored(self) -> None:
        async with async_session() as db:
            manager = await db.get(User, self.manager_id)
            response = await update_product(
                self.unit_id,
                ProductUpdate(cost=Decimal("6.0000")),
                db,
                manager,
            )
            self.assertNotIn("error", response)

        async with async_session() as db:
            pack = await db.get(Product, self.pack_id)
            self.assertEqual(pack.cost, Decimal("72.0000"))

        async with async_session() as db:
            manager = await db.get(User, self.manager_id)
            response = await update_product(
                self.pack_id,
                ProductUpdate(stock=0),
                db,
                manager,
            )
            self.assertNotIn("error", response)

        async with async_session() as db:
            pack = await db.get(Product, self.pack_id)
            self.assertEqual(pack.cost, Decimal("72.0000"))
