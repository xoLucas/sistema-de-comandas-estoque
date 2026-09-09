from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

from sqlalchemy.sql.elements import TextClause

# Register the complete SQLAlchemy model graph for isolated ORM tests.
import app.core.seed  # noqa: F401
from app.core import scheduler
from app.core.timezone import local_day_to_utc_range
from app.routers import dashboards
from app.services import notification_service


LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value


class _ScalarsResult:
    def scalars(self):
        return self

    def first(self):
        return None


class _AsyncSessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _SchedulerDatabase:
    def __init__(self, session, open_orders_count=1):
        self.session = session
        self.open_orders_count = open_orders_count
        self.refreshed = None

    async def execute(self, statement):
        if isinstance(statement, TextClause):
            return _ScalarResult(None)
        sql = str(statement)
        if "count" in sql and "orders" in sql:
            return _ScalarResult(self.open_orders_count)
        return _ScalarResult(self.session)

    async def commit(self):
        return None

    async def refresh(self, value):
        self.refreshed = value
        return None


class _NotificationDatabase:
    def __init__(self):
        self.statement = None
        self.added = None

    async def execute(self, statement):
        self.statement = statement
        return _ScalarsResult()

    def add(self, value):
        self.added = value

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def refresh(self, _value):
        return None


class OvernightSessionConsistencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_automatic_report_uses_complete_open_session_window(self) -> None:
        opened_at = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
        fixed_local_now = datetime(2026, 9, 8, 3, 0, tzinfo=LOCAL_TIMEZONE)
        expected_end = fixed_local_now.astimezone(timezone.utc)
        cash_session = SimpleNamespace(id=42, opened_at=opened_at)
        db = _SchedulerDatabase(cash_session, open_orders_count=2)

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_local_now.replace(tzinfo=None)
                return fixed_local_now.astimezone(tz)

        build_report = AsyncMock(return_value={"report_type": "parcial"})
        send_email = AsyncMock(return_value={"success": True})

        with (
            patch.object(scheduler, "async_session", lambda: _AsyncSessionContext(db)),
            patch.object(scheduler, "datetime", _FixedDatetime),
            patch.object(
                scheduler,
                "get_setting_as_bool",
                AsyncMock(return_value=True),
            ),
            patch.object(
                scheduler,
                "get_setting",
                AsyncMock(side_effect=["03:00", "caixa@example.com"]),
            ),
            patch.object(
                scheduler,
                "create_cash_register_close_notification",
                AsyncMock(return_value=None),
            ),
            patch.object(scheduler, "_build_session_report", build_report),
            patch.object(
                scheduler,
                "_build_pdf_bytes",
                Mock(return_value=BytesIO(b"%PDF-session")),
            ),
            patch.object(scheduler, "send_email_with_attachment", send_email),
        ):
            await scheduler.auto_close_cash_register()

        build_report.assert_awaited_once_with(
            session=cash_session,
            start=opened_at,
            end=expected_end,
            report_type="parcial",
            db=db,
            generated_by="Sistema",
        )
        email_payload = send_email.await_args.kwargs
        self.assertEqual(email_payload["attachment_bytes"], b"%PDF-session")
        self.assertEqual(
            email_payload["attachment_filename"],
            "fechamento_sessao_42_parcial.pdf",
        )
        self.assertIn("07/09/2026 07:00", email_payload["body"])
        self.assertIn("08/09/2026 03:00", email_payload["body"])
        self.assertIn("NÃO foi fechado", email_payload["body"])

    async def test_auto_close_closes_cash_register_without_open_orders(self) -> None:
        opened_at = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)
        fixed_local_now = datetime(2026, 9, 7, 23, 0, tzinfo=LOCAL_TIMEZONE)
        cash_session = SimpleNamespace(id=42, opened_at=opened_at, movements=[])
        db = _SchedulerDatabase(cash_session, open_orders_count=0)
        system_user = SimpleNamespace(id=7, name="Sistema")
        notification = SimpleNamespace(
            id=1,
            type="cash_register_auto_closed",
            title="Caixa fechado automaticamente",
            message="O caixa foi fechado automaticamente às 23:00.",
            details={"close_time": "23:00"},
            status="unread",
            resolution=None,
            resolved_by_id=None,
            resolved_at=None,
            created_at=fixed_local_now.replace(tzinfo=None),
        )

        class _FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_local_now.replace(tzinfo=None)
                return fixed_local_now.astimezone(tz)

        finalize = AsyncMock()
        send_close_email = AsyncMock()
        broadcast = AsyncMock()

        with (
            patch.object(scheduler, "async_session", lambda: _AsyncSessionContext(db)),
            patch.object(scheduler, "datetime", _FixedDatetime),
            patch.object(
                scheduler,
                "get_setting_as_bool",
                AsyncMock(return_value=True),
            ),
            patch.object(
                scheduler,
                "get_setting",
                AsyncMock(return_value="23:00"),
            ),
            patch.object(
                scheduler,
                "_ensure_system_user",
                AsyncMock(return_value=system_user),
            ),
            patch.object(
                scheduler,
                "compute_session_cash_summary",
                AsyncMock(return_value={"expected_cash": 250.0}),
            ),
            patch.object(scheduler, "finalize_cash_session", finalize),
            patch.object(scheduler, "send_session_close_report_email", send_close_email),
            patch.object(
                scheduler,
                "create_cash_register_auto_closed_notification",
                AsyncMock(return_value=notification),
            ),
            patch.object(scheduler, "broadcast_notification", broadcast),
        ):
            await scheduler.auto_close_cash_register()

        finalize.assert_awaited_once_with(
            cash_session,
            db=db,
            closed_by_id=system_user.id,
            final_cash=Decimal("250.00"),
            observations=(
                "Fechamento automático no horário configurado (23:00). "
                "Nenhuma comanda aberta no momento."
            ),
        )
        send_close_email.assert_awaited_once_with(db, cash_session)
        self.assertEqual(db.refreshed, cash_session)
        broadcast.assert_awaited_once()

    async def test_close_notification_uses_brasilia_calendar_day(self) -> None:
        local_today = date(2026, 9, 8)
        expected_start, expected_end = local_day_to_utc_range(local_today)
        db = _NotificationDatabase()

        with patch.object(
            notification_service,
            "today_local",
            return_value=local_today,
        ):
            notification = await notification_service.create_cash_register_close_notification(
                db,
                "03:00",
                open_orders_count=3,
            )

        query_values = list(db.statement.compile().params.values())
        self.assertIn(expected_start, query_values)
        self.assertIn(expected_end, query_values)
        self.assertIs(notification, db.added)
        self.assertIn("3 comanda(s) aberta(s)", notification.message)

    def test_dashboard_month_uses_brasilia_date(self) -> None:
        with patch.object(
            dashboards,
            "today_local",
            return_value=date(2026, 1, 31),
        ):
            self.assertEqual(dashboards._current_local_month(), 1)


if __name__ == "__main__":
    unittest.main()