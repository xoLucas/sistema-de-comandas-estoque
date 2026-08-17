from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.product import Product

TIMEZONE = ZoneInfo("America/Sao_Paulo")


async def create_printer_failure_notification(
    db: AsyncSession,
    function: str,
    failed_printer_id: str,
    failed_printer_name: str,
    error: str,
    order_id: int | None = None,
    table_id: int | None = None,
    table_number: int | None = None,
    table_label: str | None = None,
    round_number: int | None = None,
    items: list[dict] | None = None,
    customer_name: str | None = None,
    waiter_name: str | None = None,
    observation: str | None = None,
    ficha_mode: bool = False,
) -> Notification:
    function_label = _function_label(function)
    title = f"Falha na impressora {function_label}"

    message_parts = []
    if table_label:
        message_parts.append(table_label)
    if round_number:
        message_parts.append(f"pedido #{round_number}")
    message_parts.append(f"impressora {failed_printer_name}")
    message = " — ".join(message_parts) if message_parts else f"Falha ao imprimir em {failed_printer_name}"

    details = {
        "function": function,
        "failed_printer_id": failed_printer_id,
        "failed_printer_name": failed_printer_name,
        "error": error,
        "order_id": order_id,
        "table_id": table_id,
        "table_number": table_number,
        "table_label": table_label,
        "round_number": round_number,
        "items": items or [],
        "customer_name": customer_name,
        "waiter_name": waiter_name,
        "observation": observation,
        "ficha_mode": ficha_mode,
    }

    notification = Notification(
        type="printer_failure",
        title=title,
        message=message,
        details=details,
        status="unread",
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    return notification


async def create_stock_notification(
    db: AsyncSession,
    product_id: int,
    product_name: str,
    status: str,
    stock: int,
    min_stock: int,
) -> Notification | None:
    if status not in ("em_risco", "em_falta"):
        return None

    notification_type = "stock_risk" if status == "em_risco" else "stock_out"
    title = "Produto em risco" if status == "em_risco" else "Produto em falta"
    message = f"{product_name} está {status.replace('_', ' ')} (estoque: {stock}, mínimo: {min_stock})."

    existing = await db.execute(
        select(Notification)
        .where(
            Notification.type == notification_type,
            Notification.status.in_(["unread", "read"]),
            Notification.details["product_id"].as_string() == str(product_id),
        )
        .order_by(desc(Notification.created_at))
        .limit(1)
    )
    if existing.scalars().first():
        return None

    notification = Notification(
        type=notification_type,
        title=title,
        message=message,
        details={
            "product_id": product_id,
            "product_name": product_name,
            "status": status,
            "stock": stock,
            "min_stock": min_stock,
        },
        status="unread",
    )
    db.add(notification)
    await db.flush()
    await db.refresh(notification)
    return notification


async def create_cash_register_close_notification(
    db: AsyncSession,
    close_time: str,
) -> Notification | None:
    today = datetime.now(TIMEZONE).date()
    existing = await db.execute(
        select(Notification)
        .where(
            Notification.type == "cash_register_close_time",
            Notification.created_at >= today,
        )
        .order_by(Notification.created_at.desc())
        .limit(1)
    )
    if existing.scalars().first():
        return None

    notification = Notification(
        type="cash_register_close_time",
        title="Hora de fechar o caixa",
        message=f"O horário programado de fechamento ({close_time}) foi atingido. O caixa ainda está aberto.",
        details={"close_time": close_time},
        status="unread",
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    return notification


async def get_notifications(
    db: AsyncSession,
    status: str | None = None,
    limit: int = 100,
) -> list[Notification]:
    query = select(Notification).order_by(desc(Notification.created_at))
    if status:
        query = query.where(Notification.status == status)
    query = query.limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_unread_count(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(Notification.id)).where(Notification.status == "unread")
    )
    return result.scalar_one()


async def get_notification_by_id(db: AsyncSession, notification_id: int) -> Notification | None:
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id)
    )
    return result.scalars().first()


async def mark_as_read(db: AsyncSession, notification_id: int) -> Notification | None:
    notification = await get_notification_by_id(db, notification_id)
    if not notification:
        return None
    if notification.status == "unread":
        notification.status = "read"
        await db.commit()
        await db.refresh(notification)
    return notification


async def mark_as_resolved(
    db: AsyncSession,
    notification_id: int,
    user_id: int,
    resolution: str,
) -> Notification | None:
    notification = await get_notification_by_id(db, notification_id)
    if not notification:
        return None
    notification.status = "resolved"
    notification.resolution = resolution
    notification.resolved_by_id = user_id
    notification.resolved_at = datetime.now(TIMEZONE)
    await db.commit()
    await db.refresh(notification)
    return notification


async def cleanup_old_notifications(db: AsyncSession, days: int = 7) -> int:
    cutoff = datetime.now(TIMEZONE) - timedelta(days=days)
    result = await db.execute(
        select(Notification).where(Notification.created_at < cutoff)
    )
    old_notifications = result.scalars().all()
    count = len(old_notifications)
    for n in old_notifications:
        await db.delete(n)
    await db.commit()
    return count


def notification_to_dict(notification: Notification) -> dict:
    return {
        "id": notification.id,
        "type": notification.type,
        "title": notification.title,
        "message": notification.message,
        "details": notification.details or {},
        "status": notification.status,
        "resolution": notification.resolution,
        "resolved_by_id": notification.resolved_by_id,
        "resolved_at": notification.resolved_at.isoformat() if notification.resolved_at else None,
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
    }


def _function_label(function: str) -> str:
    labels = {
        "cozinha": "da cozinha",
        "bar": "do bar",
        "nota": "da nota",
    }
    return labels.get(function, function)


async def notify_stock_alert(
    db: AsyncSession,
    product: Product,
) -> Notification | None:
    """Create a stock notification within the current session.

    The caller must commit the transaction and then broadcast the notification.
    """
    from app.services.stock_service import stock_status, is_pack, pack_stock_for_product

    status = stock_status(product)
    if status not in ("em_risco", "em_falta"):
        return None

    current_stock = pack_stock_for_product(product) if is_pack(product) else product.stock
    return await create_stock_notification(
        db,
        product.id,
        product.name,
        status,
        current_stock,
        product.min_stock,
    )


async def broadcast_stock_notification(notification_id: int) -> None:
    """Broadcast an existing stock notification via WebSocket."""
    from app.routers.ws import broadcast_notification
    from app.core.database import async_session

    async with async_session() as db:
        notification = await get_notification_by_id(db, notification_id)
        if notification:
            await broadcast_notification(notification_to_dict(notification))
