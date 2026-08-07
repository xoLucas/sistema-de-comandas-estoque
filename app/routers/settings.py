from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.setting import Setting
from app.models.user import User
from app.routers.auth_deps import get_current_user, require_role, can_view_settings
from app.validators.pydantic_mixins import validate_setting_value
from app.services.printer_service import (
    EscPosBuilder,
    _load_printer_config,
    _send_to_printer_backend,
)

router = APIRouter(prefix="/api", tags=["settings"])


class SettingUpdate(BaseModel):
    value: str


@router.get("/configuracoes")
async def list_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    result = await db.execute(select(Setting).order_by(Setting.label))
    settings = result.scalars().all()
    return [
        {
            "id": s.id,
            "key": s.key,
            "value": s.value,
            "label": s.label,
            "description": s.description,
            "type": s.type,
        }
        for s in settings
    ]


@router.get("/configuracoes/{key}")
async def get_setting_by_key(
    key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalars().first()
    if not setting:
        return {"error": "Configuração não encontrada"}
    return {
        "id": setting.id,
        "key": setting.key,
        "value": setting.value,
        "label": setting.label,
        "description": setting.description,
        "type": setting.type,
    }


@router.put("/configuracoes/{key}")
async def update_setting(
    key: str,
    payload: SettingUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalars().first()
    if not setting:
        return {"error": "Configuração não encontrada"}

    try:
        setting.value = validate_setting_value(key, payload.value)
    except ValueError as exc:
        return {"error": str(exc)}

    await db.commit()
    await db.refresh(setting)
    return {
        "id": setting.id,
        "key": setting.key,
        "value": setting.value,
        "label": setting.label,
        "description": setting.description,
        "type": setting.type,
    }


def _build_test_ticket(width: int = 48) -> bytes:
    """Build a simple ESC/POS test ticket for a configured printer."""
    b = EscPosBuilder(width=width)
    b.align_center()
    b.bold_on()
    b.line("LADS BEER")
    b.bold_off()
    b.line("Teste de Impressora")
    b.separator()

    b.align_left()
    b.line("Esta e uma impressao de teste.")
    b.line("Se voce esta lendo isso, a")
    b.line("impressora esta configurada")
    b.line("corretamente na rede.")
    b.separator()

    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))
    b.line(f"Data: {now.strftime('%d/%m/%Y %H:%M')}")
    b.line("Porta: 9100 (raw ESC/POS)")
    b.separator()

    b.align_center()
    b.line("Sistema Lads Beer")
    b.line("OK")
    b.cut()
    return b.build()


@router.post("/impressoras/{printer_id}/teste")
async def test_printer(
    printer_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    """Send a test ticket to a configured printer (1 or 2)."""
    config = await _load_printer_config(printer_id)
    if not config:
        return {"success": False, "error": f"Impressora {printer_id} nao configurada"}

    data = _build_test_ticket(width=config.get("width", 48))
    try:
        await _send_to_printer_backend(data, config)
        return {"success": True, "printer": printer_id}
    except Exception as e:
        return {"success": False, "error": str(e), "printer": printer_id}
