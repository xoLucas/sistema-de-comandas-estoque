from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
import logging
from app.core.timezone import as_local
from app.models.cash_register_session import CashRegisterSession
from app.models.cash_register_movement import CashRegisterMovement
from app.models.order import Order
from app.models.table import Table
from app.models.user import User
from app.routers.auth_deps import get_current_user, can_manage_cash_register
from app.services.settings_service import get_setting, get_setting_as_bool
from app.services.email_service import send_email_with_attachment
from app.services.cash_service import compute_cash_inflows
from app.routers.financial import _build_session_report, _build_pdf_bytes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/caixa", tags=["caixa"])



class OpenCashRegisterRequest(BaseModel):
    initial_cash: float


class CloseCashRegisterRequest(BaseModel):
    final_cash: float
    observations: str | None = None


class CashMovementRequest(BaseModel):
    type: str  # sangria or suprimento
    amount: float
    note: str | None = None


@router.get("/ativo")
async def get_active_session(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_cash_register(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    result = await db.execute(
        select(CashRegisterSession)
        .where(CashRegisterSession.status == "open")
        .options(
            selectinload(CashRegisterSession.opened_by),
            selectinload(CashRegisterSession.movements).selectinload(CashRegisterMovement.created_by),
        )
        .order_by(desc(CashRegisterSession.opened_at))
    )
    session = result.scalar_one_or_none()

    if not session:
        return {"active": False, "session": None}

    total_sangria = sum(float(m.amount) for m in session.movements if m.type == "sangria")
    total_suprimento = sum(float(m.amount) for m in session.movements if m.type == "suprimento")

    end_time = datetime.now(timezone.utc)
    cash_inflows = await compute_cash_inflows(
        session, session.opened_at, end_time, db
    )
    expected_cash = round(
        float(session.initial_cash)
        + cash_inflows
        - total_sangria
        + total_suprimento,
        2,
    )

    return {
        "active": True,
        "session": {
            "id": session.id,
            "opened_at": session.opened_at.isoformat() if session.opened_at else None,
            "opened_by": session.opened_by.name if session.opened_by else "N/A",
            "initial_cash": float(session.initial_cash),
            "status": session.status,
            "total_sangria": round(total_sangria, 2),
            "total_suprimento": round(total_suprimento, 2),
            "cash_inflows": cash_inflows,
            "expected_cash": expected_cash,
            "movements": [
                {
                    "id": m.id,
                    "type": m.type,
                    "amount": float(m.amount),
                    "note": m.note,
                    "created_by": m.created_by.name if m.created_by else None,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in session.movements
            ],
        },
    }


@router.get("/sessoes")
async def list_sessions(
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_cash_register(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    result = await db.execute(
        select(CashRegisterSession)
        .options(
            selectinload(CashRegisterSession.opened_by),
            selectinload(CashRegisterSession.closed_by),
        )
        .order_by(desc(CashRegisterSession.opened_at))
        .limit(limit)
    )
    sessions = result.scalars().all()

    return {
        "sessions": [
            {
                "id": s.id,
                "opened_at": s.opened_at.isoformat() if s.opened_at else None,
                "closed_at": s.closed_at.isoformat() if s.closed_at else None,
                "opened_by": s.opened_by.name if s.opened_by else "N/A",
                "closed_by": s.closed_by.name if s.closed_by else None,
                "initial_cash": float(s.initial_cash),
                "final_cash": float(s.final_cash) if s.final_cash is not None else None,
                "status": s.status,
                "observations": s.observations,
            }
            for s in sessions
        ]
    }


@router.post("/abrir")
async def open_cash_register(
    req: OpenCashRegisterRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_cash_register(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    if req.initial_cash < 0:
        return {"error": "O dinheiro inicial não pode ser negativo"}

    result = await db.execute(
        select(CashRegisterSession)
        .where(CashRegisterSession.status == "open")
        .with_for_update()
    )
    if result.scalar_one_or_none():
        return {"error": "Já existe um caixa aberto. Feche-o antes de abrir um novo."}

    session = CashRegisterSession(
        opened_by_id=user.id,
        initial_cash=req.initial_cash,
        status="open",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return {
        "success": True,
        "session": {
            "id": session.id,
            "opened_at": session.opened_at.isoformat() if session.opened_at else None,
            "opened_by": user.name,
            "initial_cash": float(session.initial_cash),
            "status": session.status,
        },
    }


@router.post("/fechar")
async def close_cash_register(
    req: CloseCashRegisterRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_cash_register(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    result = await db.execute(
        select(CashRegisterSession)
        .where(CashRegisterSession.status == "open")
        .options(selectinload(CashRegisterSession.opened_by))
        .with_for_update()
    )
    session = result.scalar_one_or_none()

    if not session:
        return {"error": "Não há caixa aberto no momento."}

    if req.final_cash < 0:
        return {"error": "O dinheiro final não pode ser negativo"}

    pending_count_result = await db.execute(
        select(func.count(Order.id))
        .join(Table)
        .where(Order.status == "aberta", Table.is_balcao == False)
    )
    pending_count = pending_count_result.scalar_one() or 0
    if pending_count > 0:
        return {
            "error": f"Tem {pending_count} comanda(s) pendente(s). Encerre elas para concluir a operação.",
            "pending_orders": pending_count,
        }

    session.status = "closed"
    session.closed_at = datetime.now(timezone.utc)
    session.closed_by_id = user.id
    session.final_cash = req.final_cash
    session.observations = req.observations or session.observations

    await db.commit()
    await db.refresh(session)

    await _send_close_report_email(db, session)

    return {
        "success": True,
        "session": {
            "id": session.id,
            "opened_at": session.opened_at.isoformat() if session.opened_at else None,
            "closed_at": session.closed_at.isoformat() if session.closed_at else None,
            "opened_by": session.opened_by.name if session.opened_by else "N/A",
            "closed_by": user.name,
            "initial_cash": float(session.initial_cash),
            "final_cash": float(session.final_cash) if session.final_cash is not None else None,
            "status": session.status,
            "observations": session.observations,
        },
    }


@router.get("/movimentacoes")
async def list_cash_movements(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_cash_register(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    result = await db.execute(
        select(CashRegisterSession)
        .where(CashRegisterSession.status == "open")
        .options(
            selectinload(CashRegisterSession.movements).selectinload(CashRegisterMovement.created_by),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return {"movements": []}

    return {
        "movements": [
            {
                "id": m.id,
                "type": m.type,
                "amount": float(m.amount),
                "note": m.note,
                "created_by": m.created_by.name if m.created_by else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in session.movements
        ]
    }


@router.post("/movimentacoes")
async def create_cash_movement(
    req: CashMovementRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_manage_cash_register(user):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    if req.type not in ("sangria", "suprimento"):
        return {"error": "Tipo deve ser sangria ou suprimento"}
    if req.amount <= 0:
        return {"error": "Valor deve ser maior que zero"}

    result = await db.execute(
        select(CashRegisterSession).where(CashRegisterSession.status == "open")
    )
    session = result.scalar_one_or_none()
    if not session:
        return {"error": "Não há caixa aberto no momento"}

    movement = CashRegisterMovement(
        session_id=session.id,
        type=req.type,
        amount=req.amount,
        note=req.note,
        created_by_id=user.id,
    )
    db.add(movement)
    await db.commit()
    await db.refresh(movement)

    return {
        "success": True,
        "movement": {
            "id": movement.id,
            "type": movement.type,
            "amount": float(movement.amount),
            "note": movement.note,
            "created_by": user.name,
            "created_at": movement.created_at.isoformat() if movement.created_at else None,
        },
    }


async def _send_close_report_email(db, session: CashRegisterSession) -> None:
    report_email = await get_setting(db, "auto_report_email", "")
    if not report_email:
        return

    try:
        report = await _build_session_report(
            session=session,
            start=session.opened_at,
            end=session.closed_at or datetime.now(timezone.utc),
            report_type="final",
            db=db,
            generated_by=session.closed_by.name if session.closed_by else "Sistema",
        )
        if "error" in report:
            return

        buffer = _build_pdf_bytes(report, f"sessao_{session.id}")
        pdf_bytes = buffer.getvalue()
        if not pdf_bytes:
            return

        close_date = as_local(session.closed_at or datetime.now(timezone.utc)).date()
        close_dt = as_local(session.closed_at or datetime.now(timezone.utc))
        subject = f"Fechamento de Caixa - {close_date.strftime('%d/%m/%Y')}"
        body = (
            f"Caixa fechado em {close_dt.strftime('%d/%m/%Y %H:%M')}.\n\n"
            f"Aberto por: {session.opened_by.name if session.opened_by else 'N/A'}\n"
            f"Fechado por: {session.closed_by.name if session.closed_by else 'N/A'}\n"
            f"Dinheiro inicial: R$ {float(session.initial_cash):.2f}\n"
            f"Dinheiro final: R$ {float(session.final_cash or 0):.2f}\n\n"
            "Segue o relatório completo em anexo."
        )

        await send_email_with_attachment(
            to_addr=report_email,
            subject=subject,
            body=body,
            attachment_bytes=pdf_bytes,
            attachment_filename=f"fechamento_caixa_{close_date.strftime('%Y%m%d')}.pdf",
        )
    except Exception:
        logger.exception("Failed to send cash register close report email")
