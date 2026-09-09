from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, desc, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.database import async_session
from app.models.cash_register_session import CashRegisterSession
from app.models.order import Order
from app.models.user import User
from app.services.notification_service import (
    cleanup_old_notifications,
    create_cash_register_close_notification,
    create_cash_register_auto_closed_notification,
    notification_to_dict,
)
from app.routers.ws import broadcast_notification
from app.services.settings_service import (
    get_setting,
    get_setting_as_bool,
)
from app.services.email_service import send_email_with_attachment
from app.services.cash_service import compute_session_cash_summary
from app.routers.financial import (
    _build_session_report,
    _build_pdf_bytes,
    finalize_cash_session,
    send_session_close_report_email,
)
from app.services.money_service import money


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

        system_user = await _ensure_system_user(db)
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('cash_register_open'))")
        )
        existing = await db.execute(
            select(CashRegisterSession)
            .where(CashRegisterSession.status == "open")
            .with_for_update()
        )
        if existing.scalar_one_or_none():
            return

        last_closed = await _get_last_closed_session(db)
        initial_cash = money(last_closed.final_cash) if last_closed else money(0)

        session = CashRegisterSession(
            opened_by_id=system_user.id,
            initial_cash=initial_cash,
            status="open",
        )
        db.add(session)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()


async def _send_auto_partial_report(
    db,
    session: CashRegisterSession,
    configured_time: str,
) -> None:
    """Send the partial cash register report when open orders block auto-close."""
    report_email = await get_setting(db, "auto_report_email", "")
    if not report_email:
        return

    report_end = datetime.now(timezone.utc)
    try:
        report = await _build_session_report(
            session=session,
            start=session.opened_at,
            end=report_end,
            report_type="parcial",
            db=db,
            generated_by="Sistema",
        )
    except Exception:
        return

    if "error" in report:
        return

    try:
        pdf_buffer = _build_pdf_bytes(report, f"sessao_{session.id}_parcial")
        pdf_bytes = pdf_buffer.getvalue()
    except Exception:
        return
    if not pdf_bytes:
        return

    opened_at = session.opened_at.astimezone(TIMEZONE)
    report_end_local = report_end.astimezone(TIMEZONE)
    subject = f"Relatório Parcial de Caixa - Sessão #{session.id}"
    body = (
        "Horário de fechamento automático atingido "
        f"({report_end_local.strftime('%d/%m/%Y %H:%M')}).\n\n"
        "Existem comandas abertas, então o caixa NÃO foi fechado "
        "automaticamente.\nSegue em anexo o relatório parcial da sessão "
        f"iniciada em {opened_at.strftime('%d/%m/%Y %H:%M')}.\n\n"
        "Encerre as comandas abertas e feche o caixa manualmente."
    )

    await send_email_with_attachment(
        to_addr=report_email,
        subject=subject,
        body=body,
        attachment_bytes=pdf_bytes,
        attachment_filename=f"fechamento_sessao_{session.id}_parcial.pdf",
    )


async def auto_close_cash_register() -> None:
    async with async_session() as db:
        if not await get_setting_as_bool(db, "auto_close_enabled"):
            return

        configured_time = await get_setting(db, "auto_close_time", "00:00")
        now = datetime.now(TIMEZONE)
        if now.strftime("%H:%M") != configured_time:
            return

        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('cash_register_close'))")
        )
        result = await db.execute(
            select(CashRegisterSession)
            .where(CashRegisterSession.status == "open")
            .options(
                selectinload(CashRegisterSession.opened_by),
                selectinload(CashRegisterSession.closed_by),
                selectinload(CashRegisterSession.movements),
            )
            .with_for_update()
        )
        session = result.scalar_one_or_none()
        if not session:
            return

        open_orders_result = await db.execute(
            select(func.count(Order.id)).where(Order.status == "aberta")
        )
        open_orders = open_orders_result.scalar_one() or 0

        # Open orders (including the counter) block the automatic close.
        if open_orders > 0:
            notification = await create_cash_register_close_notification(
                db, configured_time, open_orders_count=open_orders
            )
            if notification:
                await broadcast_notification(notification_to_dict(notification))
            await _send_auto_partial_report(db, session, configured_time)
            return

        # No open orders: close the cash register for real.
        system_user = await _ensure_system_user(db)
        report_end = datetime.now(timezone.utc)
        cash_summary = await compute_session_cash_summary(
            session,
            session.opened_at,
            report_end,
            db,
            movements=session.movements,
        )
        final_cash = money(cash_summary["expected_cash"])

        await finalize_cash_session(
            session,
            db=db,
            closed_by_id=system_user.id,
            final_cash=final_cash,
            observations=(
                "Fechamento automático no horário configurado "
                f"({configured_time}). Nenhuma comanda aberta no momento."
            ),
        )
        await db.commit()
        await db.refresh(session)

        await send_session_close_report_email(db, session)

        notification = await create_cash_register_auto_closed_notification(
            db, configured_time
        )
        if notification:
            await broadcast_notification(notification_to_dict(notification))


async def cleanup_notifications() -> None:
    async with async_session() as db:
        deleted = await cleanup_old_notifications(db, days=7)
        if deleted > 0:
            print(f"[scheduler] {deleted} notificações antigas removidas")


async def _scheduler_tick() -> None:
    await auto_open_cash_register()
    await auto_close_cash_register()


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
