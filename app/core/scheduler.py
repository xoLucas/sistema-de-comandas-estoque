from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, desc

from app.core.database import async_session
from app.models.cash_register_session import CashRegisterSession
from app.models.user import User
from app.services.notification_service import (
    cleanup_old_notifications,
    create_cash_register_close_notification,
    notification_to_dict,
)
from app.routers.ws import broadcast_notification
from app.services.settings_service import (
    get_setting,
    get_setting_as_bool,
)
from app.services.email_service import send_email_with_attachment
from app.routers.financial import _build_daily_report, _build_pdf_bytes


SCHEDULER = AsyncIOScheduler(timezone=ZoneInfo("America/Sao_Paulo"))
TIMEZONE = ZoneInfo("America/Sao_Paulo")


async def _ensure_system_user(db) -> User:
    result = await db.execute(select(User).where(User.username == "sistema"))
    user = result.scalars().first()
    if not user:
        from app.core.security import hash_password

        user = User(
            username="sistema",
            password_hash=hash_password("system_not_for_login"),
            name="Sistema",
            role="gerente",
            is_registered=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def _get_last_closed_session(db):
    result = await db.execute(
        select(CashRegisterSession)
        .where(CashRegisterSession.status == "closed")
        .order_by(desc(CashRegisterSession.closed_at))
        .limit(1)
    )
    return result.scalars().first()


async def auto_open_cash_register() -> None:
    async with async_session() as db:
        if not await get_setting_as_bool(db, "auto_open_enabled"):
            return

        configured_time = await get_setting(db, "auto_open_time", "18:00")
        now = datetime.now(TIMEZONE)
        if now.strftime("%H:%M") != configured_time:
            return

        existing = await db.execute(
            select(CashRegisterSession).where(CashRegisterSession.status == "open")
        )
        if existing.scalar_one_or_none():
            return

        last_closed = await _get_last_closed_session(db)
        initial_cash = float(last_closed.final_cash) if last_closed else 0.0

        system_user = await _ensure_system_user(db)

        session = CashRegisterSession(
            opened_by_id=system_user.id,
            initial_cash=initial_cash,
            status="open",
        )
        db.add(session)
        await db.commit()


async def auto_close_notification() -> None:
    async with async_session() as db:
        if not await get_setting_as_bool(db, "auto_close_enabled"):
            return

        configured_time = await get_setting(db, "auto_close_time", "00:00")
        now = datetime.now(TIMEZONE)
        if now.strftime("%H:%M") != configured_time:
            return

        result = await db.execute(
            select(CashRegisterSession).where(CashRegisterSession.status == "open")
        )
        session = result.scalar_one_or_none()
        if not session:
            return

        # Always create an in-app notification; do not close the cash register automatically.
        notification = await create_cash_register_close_notification(db, configured_time)
        if notification:
            await broadcast_notification(notification_to_dict(notification))

        report_email = await get_setting(db, "auto_report_email", "")
        if not report_email:
            return

        today = now.date()
        try:
            report = await _build_daily_report(today, db, "Sistema")
        except Exception:
            return

        if "error" in report:
            return

        try:
            pdf_bytes = _build_pdf_bytes(report, str(today))
        except Exception:
            return

        subject = f"Relatório de Fechamento - {today.strftime('%d/%m/%Y')}"
        body = (
            f"Horário de fechamento automático atingido ({today.strftime('%d/%m/%Y')}).\n\n"
            "O caixa ainda está aberto. Segue em anexo o relatório parcial do dia.\n\n"
            "Acesse o sistema para fechar o caixa manualmente quando possível."
        )

        await send_email_with_attachment(
            to_addr=report_email,
            subject=subject,
            body=body,
            attachment_bytes=pdf_bytes,
            attachment_filename=f"fechamento_{today.strftime('%Y%m%d')}.pdf",
        )


async def cleanup_notifications() -> None:
    async with async_session() as db:
        deleted = await cleanup_old_notifications(db, days=7)
        if deleted > 0:
            print(f"[scheduler] {deleted} notificações antigas removidas")


async def _scheduler_tick() -> None:
    await auto_open_cash_register()
    await auto_close_notification()


def start_scheduler() -> None:
    if SCHEDULER.running:
        return

    SCHEDULER.add_job(
        _scheduler_tick,
        "cron",
        hour="*",
        minute="*",
        id="cash_register_scheduler_tick",
        replace_existing=True,
    )
    SCHEDULER.add_job(
        cleanup_notifications,
        "cron",
        hour=3,
        minute=0,
        id="notifications_cleanup",
        replace_existing=True,
    )
    SCHEDULER.start()


def shutdown_scheduler() -> None:
    if SCHEDULER.running:
        SCHEDULER.shutdown()
