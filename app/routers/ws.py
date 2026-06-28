from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import async_session
from app.core.security import decode_access_token
from app.core.websocket import manager
from app.models.table import Table
from app.models.order import Order
from app.models.order_round import OrderRound
from app.models.order_item import OrderItem
from app.models.user import User

router = APIRouter(prefix="/ws", tags=["websocket"])


async def _get_user_from_token(token: str) -> User | None:
    payload = decode_access_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == int(user_id)))
        return result.scalars().first()


async def _build_table_payload(table_id: int) -> dict | None:
    async with async_session() as db:
        result = await db.execute(select(Table).where(Table.id == table_id))
        table = result.scalars().first()
        if not table:
            return None

        order_result = await db.execute(
            select(Order)
            .where(Order.table_id == table_id, Order.status == "aberta")
            .options(
                selectinload(Order.items),
                selectinload(Order.rounds).selectinload(OrderRound.items),
            )
        )
        open_order = order_result.scalars().first()

        return {
            "id": table.id,
            "number": table.number,
            "status": table.status,
            "is_balcao": table.is_balcao,
            "total": float(open_order.total) if open_order else 0.0,
            "partial_payment": float(open_order.partial_payment) if open_order else 0.0,
            "partial_service_charge": float(open_order.partial_service_charge) if open_order else 0.0,
            "has_open_order": open_order is not None,
            "label": "Balcão" if table.is_balcao else f"Mesa {table.number}",
        }


async def broadcast_table_update(table_id: int) -> None:
    payload = await _build_table_payload(table_id)
    if payload:
        await manager.broadcast({"type": "table_update", "data": payload})


@router.websocket("/mesas")
async def tables_websocket(
    websocket: WebSocket,
    token: str = Query(...),
):
    user = await _get_user_from_token(token)
    if not user:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; clients may send ping messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
