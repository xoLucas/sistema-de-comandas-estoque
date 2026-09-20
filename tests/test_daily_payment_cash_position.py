"""Tests for the automatic daily payment outflow in the cash position.

Business rules covered:
- Paying an employee daily creates an automatic "saida" CashPositionMovement.
- The movement is linked to the open cash session when one exists.
- The cash position (entradas - saidas) decreases by the daily amount.
- The expected cash (physical drawer) is NOT affected by the daily.
- Deleting the employee keeps the movement in the position history
  (daily_payment_id is set to NULL by the database).
"""

from datetime import datetime, timezone
from decimal import Decimal
import os
import unittest

from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url

from app.core.database import async_session, engine
from app.core.seed import run_seed
from app.models.cash_position_movement import CashPositionMovement
from app.models.cash_register_session import CashRegisterSession
from app.models.daily_payment import DailyPayment
from app.models.employee import Employee
from app.models.expense import Expense
from app.models.user import User
from app.routers.cash_register import OpenCashRegisterRequest, open_cash_register
from app.routers.employees import DailyPaymentCreate, delete_employee, pay_daily
from app.services.cash_service import compute_session_cash_summary


RUN_INTEGRATION = os.getenv("RUN_DATABASE_INTEGRATION_TESTS") == "1"
DATABASE_NAME = make_url(os.getenv("DATABASE_URL", "sqlite:///unsafe")).database
SAFE_DATABASE = DATABASE_NAME == "ladsbeer_codex_test"


@unittest.skipUnless(
    RUN_INTEGRATION and SAFE_DATABASE,
    "requires RUN_DATABASE_INTEGRATION_TESTS=1 and database ladsbeer_codex_test",
)
class DailyPaymentCashPositionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await run_seed()

        self.employee_ids: list[int] = []
        self.daily_ids: list[int] = []
        self.movement_ids: list[int] = []

        async with async_session() as db:
            self.manager = await db.scalar(
                select(User).where(User.role == "gerente").order_by(User.id)
            )
            for session in (
                await db.execute(
                    select(CashRegisterSession).where(CashRegisterSession.status == "open")
                )
            ).scalars().all():
                session.status = "closed"
                session.closed_at = datetime.now(timezone.utc)
                session.closed_by_id = self.manager.id
                session.final_cash = session.initial_cash
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with async_session() as db:
            if self.movement_ids:
                await db.execute(
                    delete(CashPositionMovement).where(
                        CashPositionMovement.id.in_(self.movement_ids)
                    )
                )
            if self.daily_ids:
                await db.execute(
                    delete(Expense).where(
                        Expense.reference_type == "daily_payment",
                        Expense.reference_id.in_(self.daily_ids),
                    )
                )
                await db.execute(
                    delete(DailyPayment).where(DailyPayment.id.in_(self.daily_ids))
                )
            if self.employee_ids:
                await db.execute(delete(Employee).where(Employee.id.in_(self.employee_ids)))
            await db.commit()

        await engine.dispose()

    async def _create_employee(self, suffix: str) -> int:
        async with async_session() as db:
            employee = Employee(
                name=f"Diaria Test {suffix}",
                role="garcom",
                active=True,
            )
            db.add(employee)
            await db.commit()
            await db.refresh(employee)
            self.employee_ids.append(employee.id)
            return employee.id

    async def _pay_daily(self, employee_id: int, amount: float, **kwargs) -> int:
        async with async_session() as db:
            response = await pay_daily(
                DailyPaymentCreate(
                    employee_id=employee_id,
                    amount=amount,
                    **kwargs,
                ),
                db,
                self.manager,
            )
            self.assertNotIn("error", response)

        self.daily_ids.append(response["id"])

        async with async_session() as db:
            movement = await db.scalar(
                select(CashPositionMovement).where(
                    CashPositionMovement.daily_payment_id == response["id"]
                )
            )
            self.assertIsNotNone(movement)
            self.movement_ids.append(movement.id)
        return response["id"]

    async def _cash_position(self, db) -> float:
        result = await db.execute(
            select(CashPositionMovement.type, func.sum(CashPositionMovement.amount)).group_by(
                CashPositionMovement.type
            )
        )
        totals = {movement_type: float(amount or 0) for movement_type, amount in result.all()}
        return round(totals.get("entrada", 0.0) - totals.get("saida", 0.0), 2)

    async def test_daily_payment_creates_automatic_outflow_linked_to_open_session(self) -> None:
        employee_id = await self._create_employee("open")

        async with async_session() as db:
            opened = await open_cash_register(
                OpenCashRegisterRequest(initial_cash=Decimal("100.00")),
                db,
                self.manager,
            )
            self.assertNotIn("error", opened)
            session_id = opened["session"]["id"]
            position_before = await self._cash_position(db)

        daily_id = await self._pay_daily(
            employee_id,
            50.0,
            payment_date="2026-09-20T12:00:00",
            notes="Diaria de teste",
        )

        async with async_session() as db:
            movement = await db.get(CashPositionMovement, self.movement_ids[-1])
            self.assertEqual(movement.type, "saida")
            self.assertEqual(movement.source, "automatico")
            self.assertEqual(movement.title, "Diária - Diaria Test open")
            self.assertEqual(movement.amount, Decimal("50.00"))
            self.assertEqual(movement.observation, "Diaria de teste")
            self.assertEqual(movement.session_id, session_id)
            self.assertEqual(movement.created_by_id, self.manager.id)
            self.assertEqual(movement.daily_payment_id, daily_id)

            position_after = await self._cash_position(db)
            self.assertAlmostEqual(position_before - position_after, 50.0, places=2)

            session = await db.get(CashRegisterSession, session_id)
            summary = await compute_session_cash_summary(
                session,
                session.opened_at,
                datetime.now(timezone.utc),
                db,
                movements=[],
            )
            self.assertEqual(summary["expected_cash"], 100.0)

    async def test_daily_payment_without_open_session_still_debits_position(self) -> None:
        employee_id = await self._create_employee("no-session")

        async with async_session() as db:
            position_before = await self._cash_position(db)

        await self._pay_daily(
            employee_id,
            30.0,
            payment_date="2026-09-20T13:00:00",
        )

        async with async_session() as db:
            movement = await db.get(CashPositionMovement, self.movement_ids[-1])
            self.assertIsNone(movement.session_id)
            self.assertEqual(movement.amount, Decimal("30.00"))

            position_after = await self._cash_position(db)
            self.assertAlmostEqual(position_before - position_after, 30.0, places=2)

    async def test_deleting_employee_keeps_position_movement(self) -> None:
        employee_id = await self._create_employee("delete")

        daily_id = await self._pay_daily(
            employee_id,
            25.0,
            payment_date="2026-09-20T14:00:00",
        )

        async with async_session() as db:
            movement_id = self.movement_ids[-1]
            position_before = await self._cash_position(db)

        async with async_session() as db:
            deleted = await delete_employee(employee_id, db, self.manager)
            self.assertNotIn("error", deleted)

        async with async_session() as db:
            self.assertIsNone(await db.get(DailyPayment, daily_id))
            movement = await db.get(CashPositionMovement, movement_id)
            self.assertIsNotNone(movement)
            self.assertIsNone(movement.daily_payment_id)
            self.assertEqual(movement.amount, Decimal("25.00"))

            position_after = await self._cash_position(db)
            self.assertAlmostEqual(position_before, position_after, places=2)
