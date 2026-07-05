from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.promotion import Promotion
from app.models.product import Product
from app.models.user import User
from app.routers.auth_deps import get_current_user

router = APIRouter(prefix="/api/promocoes", tags=["promocoes"])


class PromotionCreate(BaseModel):
    name: str
    description: str | None = None
    discount_pct: float
    start_at: str | None = None  # ISO datetime
    end_at: str | None = None
    is_active: bool = True
    product_ids: list[int] = []


class PromotionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    discount_pct: float | None = None
    start_at: str | None = None
    end_at: str | None = None
    is_active: bool | None = None
    product_ids: list[int] | None = None


def _is_promotion_active(promotion: Promotion) -> bool:
    if not promotion.is_active:
        return False
    now = datetime.now(promotion.created_at.tzinfo if promotion.created_at else None)
    if promotion.start_at and now < promotion.start_at:
        return False
    if promotion.end_at and now > promotion.end_at:
        return False
    return True


def _promotion_status(promotion: Promotion) -> str:
    if not promotion.is_active:
        return "desativada"
    now = datetime.now(promotion.created_at.tzinfo if promotion.created_at else None)
    if promotion.start_at and now < promotion.start_at:
        return "agendada"
    if promotion.end_at and now > promotion.end_at:
        return "expirada"
    return "ativa"


@router.get("")
async def list_promotions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Promotion).options(selectinload(Promotion.products)).order_by(Promotion.created_at.desc())
    )
    promotions = result.scalars().all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "discount_pct": float(p.discount_pct),
            "start_at": p.start_at.isoformat() if p.start_at else None,
            "end_at": p.end_at.isoformat() if p.end_at else None,
            "is_active": p.is_active,
            "status": _promotion_status(p),
            "is_running": _is_promotion_active(p),
            "products": [
                {"id": prod.id, "name": prod.name, "category": prod.category, "price": float(prod.price)}
                for prod in p.products
            ],
        }
        for p in promotions
    ]


@router.post("")
async def create_promotion(
    req: PromotionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("gerente", "caixa"):
        return {"error": "Acesso restrito ao gerente ou caixa"}

    promotion = Promotion(
        name=req.name,
        description=req.description,
        discount_pct=req.discount_pct,
        is_active=req.is_active,
        start_at=datetime.fromisoformat(req.start_at) if req.start_at else None,
        end_at=datetime.fromisoformat(req.end_at) if req.end_at else None,
    )

    if req.product_ids:
        product_result = await db.execute(select(Product).where(Product.id.in_(req.product_ids)))
        promotion.products = product_result.scalars().all()

    db.add(promotion)
    await db.commit()
    await db.refresh(promotion)

    result = await db.execute(
        select(Promotion).where(Promotion.id == promotion.id).options(selectinload(Promotion.products))
    )
    promotion = result.scalars().first()

    return {
        "id": promotion.id,
        "name": promotion.name,
        "description": promotion.description,
        "discount_pct": float(promotion.discount_pct),
        "start_at": promotion.start_at.isoformat() if promotion.start_at else None,
        "end_at": promotion.end_at.isoformat() if promotion.end_at else None,
        "is_active": promotion.is_active,
        "status": _promotion_status(promotion),
        "is_running": _is_promotion_active(promotion),
        "products": [
            {"id": prod.id, "name": prod.name, "category": prod.category, "price": float(prod.price)}
            for prod in promotion.products
        ],
    }


@router.put("/{promotion_id}")
async def update_promotion(
    promotion_id: int,
    req: PromotionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("gerente", "caixa"):
        return {"error": "Acesso restrito ao gerente ou caixa"}

    result = await db.execute(
        select(Promotion).where(Promotion.id == promotion_id).options(selectinload(Promotion.products))
    )
    promotion = result.scalars().first()
    if not promotion:
        return {"error": "Promoção não encontrada"}

    if req.name is not None:
        promotion.name = req.name
    if req.description is not None:
        promotion.description = req.description
    if req.discount_pct is not None:
        promotion.discount_pct = req.discount_pct
    if req.is_active is not None:
        promotion.is_active = req.is_active
    if req.start_at is not None:
        promotion.start_at = datetime.fromisoformat(req.start_at) if req.start_at else None
    if req.end_at is not None:
        promotion.end_at = datetime.fromisoformat(req.end_at) if req.end_at else None
    if req.product_ids is not None:
        product_result = await db.execute(select(Product).where(Product.id.in_(req.product_ids)))
        promotion.products = product_result.scalars().all()

    await db.commit()

    result = await db.execute(
        select(Promotion).where(Promotion.id == promotion.id).options(selectinload(Promotion.products))
    )
    promotion = result.scalars().first()

    return {
        "id": promotion.id,
        "name": promotion.name,
        "description": promotion.description,
        "discount_pct": float(promotion.discount_pct),
        "start_at": promotion.start_at.isoformat() if promotion.start_at else None,
        "end_at": promotion.end_at.isoformat() if promotion.end_at else None,
        "is_active": promotion.is_active,
        "status": _promotion_status(promotion),
        "is_running": _is_promotion_active(promotion),
        "products": [
            {"id": prod.id, "name": prod.name, "category": prod.category, "price": float(prod.price)}
            for prod in promotion.products
        ],
    }


@router.delete("/{promotion_id}")
async def delete_promotion(
    promotion_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("gerente", "caixa"):
        return {"error": "Acesso restrito ao gerente ou caixa"}

    result = await db.execute(select(Promotion).where(Promotion.id == promotion_id))
    promotion = result.scalars().first()
    if not promotion:
        return {"error": "Promoção não encontrada"}

    await db.delete(promotion)
    await db.commit()
    return {"message": "Promoção removida"}
