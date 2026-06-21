from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.models.user import User
from app.routers.auth_deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterNameRequest(BaseModel):
    name: str


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalars().first()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")

    token = create_access_token(data={"sub": str(user.id), "role": user.role})

    return {
        "access_token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "name": user.name,
            "role": user.role,
            "is_registered": user.is_registered,
        },
    }


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "role": user.role,
        "is_registered": user.is_registered,
    }


@router.post("/register-name")
async def register_name(
    req: RegisterNameRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.is_registered:
        raise HTTPException(status_code=400, detail="Usuário já está registrado")

    user.name = req.name
    user.is_registered = True
    await db.commit()
    await db.refresh(user)

    return {
        "id": user.id,
        "name": user.name,
        "is_registered": user.is_registered,
    }


@router.get("/users")
async def list_users(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "gerente":
        raise HTTPException(status_code=403, detail="Acesso restrito ao gerente")

    result = await db.execute(select(User).order_by(User.name))
    users = result.scalars().all()

    return [
        {
            "id": u.id,
            "username": u.username,
            "name": u.name,
            "role": u.role,
            "is_registered": u.is_registered,
        }
        for u in users
    ]


class CreateUserRequest(BaseModel):
    username: str
    password: str
    name: str
    role: str


@router.post("/users")
async def create_user(
    req: CreateUserRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != "gerente":
        raise HTTPException(status_code=403, detail="Acesso restrito ao gerente")

    if req.role not in ("garcom", "caixa", "estoquista", "gerente"):
        raise HTTPException(status_code=400, detail="Cargo inválido")

    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Usuário já existe")

    new_user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        name=req.name,
        role=req.role,
        is_registered=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return {
        "id": new_user.id,
        "username": new_user.username,
        "name": new_user.name,
        "role": new_user.role,
    }
