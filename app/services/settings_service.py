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


async def get_card_machine_settings(db: AsyncSession) -> dict:
    return {
        "1": {
            "name": await get_setting(db, "card_machine_1_name", "Maquininha 1"),
            "debit_fee": await get_setting_as_float(db, "card_machine_1_debit_fee", 1.5),
            "credit_fee": await get_setting_as_float(db, "card_machine_1_credit_fee", 3.5),
        },
        "2": {
            "name": await get_setting(db, "card_machine_2_name", "Maquininha 2"),
            "debit_fee": await get_setting_as_float(db, "card_machine_2_debit_fee", 2.0),
            "credit_fee": await get_setting_as_float(db, "card_machine_2_credit_fee", 4.0),
        },
    }


async def get_card_fee_for_machine(
    db: AsyncSession,
    machine: str | None,
    method: str,
    default_rates: dict[str, float] | None = None,
) -> float:
    machines = await get_card_machine_settings(db)
    if machine and machine in machines:
        if method == "cartao_debito":
            return machines[machine]["debit_fee"]
        if method == "cartao_credito":
            return machines[machine]["credit_fee"]
    if default_rates:
        return default_rates.get(method, 0.0)
    return 0.0
