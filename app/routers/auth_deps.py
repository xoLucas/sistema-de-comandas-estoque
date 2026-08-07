from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request = None,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    token = None
    if credentials:
        token = credentials.credentials
    elif request and request.cookies.get("access_token"):
        token = request.cookies.get("access_token")

    if not token:
        raise HTTPException(status_code=401, detail="Token de acesso ausente")

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token inválido")

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")

    return user


def require_role(*roles: str):
    async def _require_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Acesso restrito")
        return user
    return _require_role


def can_view_product_cost(user: User) -> bool:
    return user.role in ("gerente", "caixa", "estoquista")


def can_manage_stock(user: User) -> bool:
    return user.role in ("gerente", "estoquista", "caixa")


def can_view_financial(user: User) -> bool:
    return user.role in ("gerente", "caixa")


def can_manage_cash_register(user: User) -> bool:
    return user.role in ("gerente", "caixa")


def can_view_suppliers(user: User) -> bool:
    return user.role in ("gerente", "estoquista", "caixa")


def can_view_promotions(user: User) -> bool:
    return user.role in ("gerente", "caixa", "estoquista", "garcom")


def can_manage_promotions(user: User) -> bool:
    return user.role in ("gerente", "caixa", "estoquista")


def can_view_settings(user: User) -> bool:
    return user.role == "gerente"


def can_view_employees(user: User) -> bool:
    return user.role == "gerente"


def can_view_customers(user: User) -> bool:
    return user.role in ("gerente", "caixa", "garcom")


async def get_current_user_optional(
    request: Request = None,
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    token = None
    if credentials:
        token = credentials.credentials
    elif request and request.cookies.get("access_token"):
        token = request.cookies.get("access_token")

    if not token:
        return None

    payload = decode_access_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    result = await db.execute(select(User).where(User.id == int(user_id)))
    return result.scalars().first()
