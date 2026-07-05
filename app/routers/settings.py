from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.setting import Setting
from app.models.user import User
from app.routers.auth_deps import get_current_user, require_role, can_view_settings

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

    setting.value = payload.value
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
