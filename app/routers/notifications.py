from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.routers.auth_deps import get_current_user, require_role
from app.routers.ws import broadcast_notification
from app.services.notification_service import (
    get_notifications,
    get_notification_by_id,
    get_unread_count,
    mark_as_read,
    mark_as_resolved,
    notification_to_dict,
)
from app.services.printer_service import (
    build_kitchen_ticket,
    build_bar_ticket,
    build_order_receipt,
    build_ficha_ticket,
    get_printer_for_function,
    send_to_printer,
)
from app.services.settings_service import get_setting

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class ReprintRequest(BaseModel):
    target_printer_id: str


class ResolveRequest(BaseModel):
    resolution: str = "manual_note"


@router.get("")
async def list_notifications(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    notifications = await get_notifications(db, status=status, limit=100)
    return {
        "notifications": [notification_to_dict(n) for n in notifications],
        "is_manager": user.role == "gerente",
    }


@router.get("/unread-count")
async def unread_count(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"count": await get_unread_count(db)}


@router.post("/{notification_id}/read")
async def read_notification(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    notification = await mark_as_read(db, notification_id)
    if not notification:
        return {"error": "Notificação não encontrada"}
    data = notification_to_dict(notification)
    await broadcast_notification(data)
    return {"success": True, "notification": data}


@router.post("/{notification_id}/resolve")
async def resolve_notification(
    notification_id: int,
    req: ResolveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    notification = await get_notification_by_id(db, notification_id)
    if not notification:
        return {"error": "Notificação não encontrada"}

    updated = await mark_as_resolved(db, notification_id, user.id, req.resolution)
    if not updated:
        return {"error": "Erro ao resolver notificação"}
    data = notification_to_dict(updated)
    await broadcast_notification(data)
    return {"success": True, "notification": data}


@router.post("/{notification_id}/reprint")
async def reprint_notification(
    notification_id: int,
    req: ReprintRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    notification = await get_notification_by_id(db, notification_id)
    if not notification:
        return {"error": "Notificação não encontrada"}

    if notification.type != "printer_failure":
        return {"error": "Notificação não é de falha de impressora"}

    details = notification.details or {}
    function = details.get("function")
    failed_printer_id = details.get("failed_printer_id") or ""

    if req.target_printer_id == failed_printer_id:
        return {"error": "Escolha uma impressora diferente da que falhou"}

    target_config = await get_printer_for_function(function)
    if target_config and target_config["id"] != req.target_printer_id:
        target_config = None

    if not target_config:
        from app.services.printer_service import _load_printer_config
        target_config = await _load_printer_config(req.target_printer_id)

    if not target_config:
        return {"error": "Impressora selecionada não está configurada"}

    data = await _rebuild_printer_data(notification, target_config["width"], db)
    if not data:
        return {"error": "Não foi possível reconstruir o ticket"}

    result = await send_to_printer(data, req.target_printer_id)
    if not result.get("success"):
        return {"error": result.get("error", "Erro ao reimprimir")}

    updated = await mark_as_resolved(db, notification_id, user.id, "reprint")
    if updated:
        data = notification_to_dict(updated)
        await broadcast_notification(data)

    return {"success": True, "message": f"Reimpresso em {target_config.get('name', 'impressora')}"}


async def _rebuild_printer_data(notification, printer_width: int, db) -> bytes | None:
    details = notification.details or {}
    function = details.get("function")
    table_number = details.get("table_number") or 0
    round_number = details.get("round_number") or 0
    items = details.get("items") or []
    customer_name = details.get("customer_name")
    waiter_name = details.get("waiter_name") or ""
    order_id = details.get("order_id")
    observation = details.get("observation")
    ficha_mode = bool(details.get("ficha_mode"))

    if function == "cozinha":
        return build_kitchen_ticket(
            table_number,
            round_number,
            items,
            waiter_name,
            customer_name,
            order_id,
            printer_width,
            observation,
        )

    if function == "bar":
        return build_bar_ticket(
            table_number,
            round_number,
            items,
            waiter_name,
            customer_name,
            order_id,
            printer_width,
            observation,
        )

    if function == "nota":
        if ficha_mode:
            store_name = await get_setting(db, "store_name", "Lads Beer")
            tickets = bytearray()
            for item in items:
                qty = int(item.get("quantity", 1))
                name = item.get("product_name") or item.get("name") or "Item"
                for _ in range(qty):
                    tickets.extend(build_ficha_ticket(store_name, name, printer_width))
            return bytes(tickets) if tickets else None

        order_data = {
            "order_id": order_id,
            "table_label": details.get("table_label", "Balcão"),
            "customer_name": customer_name,
            "items": items,
            "total": float(details.get("total", 0)),
            "service_charge_pct": float(details.get("service_charge_pct", 0)),
            "service_charge_amount": float(details.get("service_charge_amount", 0)),
            "partial_payment": float(details.get("partial_payment", 0)),
            "final_total": float(details.get("final_total", 0)),
            "payment_method": details.get("payment_method", ""),
        }
        store_info = {
            "name": await get_setting(db, "store_name", "Lads Beer"),
            "address": await get_setting(db, "store_address", ""),
            "phone": await get_setting(db, "store_phone", ""),
            "cnpj": await get_setting(db, "store_cnpj", ""),
            "ticket_footer": await get_setting(db, "ticket_footer", "Obrigado pela preferência!"),
        }
        return build_order_receipt(order_data, store_info, printer_width)

    return None
