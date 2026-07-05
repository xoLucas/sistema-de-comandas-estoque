from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting


async def get_setting(db: AsyncSession, key: str, default: str | None = None) -> str | None:
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalars().first()
    if setting is None:
        return default
    return setting.value


async def get_setting_as_float(db: AsyncSession, key: str, default: float = 0.0) -> float:
    raw = await get_setting(db, key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


async def get_setting_as_int(db: AsyncSession, key: str, default: int = 0) -> int:
    raw = await get_setting(db, key)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except (ValueError, TypeError):
        return default


async def get_setting_as_bool(db: AsyncSession, key: str, default: bool = False) -> bool:
    raw = await get_setting(db, key)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "sim", "on")
