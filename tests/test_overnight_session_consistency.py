from datetime import date, datetime, timezone
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

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
    def __init__(self, session):
        self.session = session

    async def execute(self, _statement):
        return _ScalarResult(self.session)


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
        db = _SchedulerDatabase(cash_session)

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
            await scheduler.auto_close_notification()

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
            )

        query_values = list(db.statement.compile().params.values())
        self.assertIn(expected_start, query_values)
        self.assertIn(expected_end, query_values)
        self.assertIs(notification, db.added)

    def test_dashboard_month_uses_brasilia_date(self) -> None:
        with patch.object(
            dashboards,
            "today_local",
            return_value=date(2026, 1, 31),
        ):
            self.assertEqual(dashboards._current_local_month(), 1)


if __name__ == "__main__":
    unittest.main()
