from datetime import datetime, date
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func, extract, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.order import Order
from app.models.table import Table
from app.models.user import User
from app.routers.auth_deps import get_current_user

router = APIRouter(prefix="/api/financeiro", tags=["financeiro"])


@router.get("/vendas")
async def list_sales(
    date_filter: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("caixa", "gerente"):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    query = (
        select(Order)
        .where(Order.status == "finalizada")
        .options(
            selectinload(Order.table),
            selectinload(Order.waiter),
            selectinload(Order.items),
        )
        .order_by(Order.closed_at.desc())
    )

    if date_filter:
        try:
            filter_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
            query = query.where(cast(Order.closed_at, Date) == filter_date)
        except ValueError:
            pass

    result = await db.execute(query)
    orders = result.scalars().all()

    data = []
    total_day = 0.0
    total_service = 0.0

    for o in orders:
        service_amount = o.total * (o.service_charge_pct / 100)
        final = o.total + service_amount - o.partial_payment
        total_day += final
        total_service += service_amount

        data.append(
            {
                "order_id": o.id,
                "table_number": o.table.number if o.table else 0,
                "is_balcao": o.table.is_balcao if o.table else False,
                "waiter_name": o.waiter.name if o.waiter else "N/A",
                "items_count": sum(item.quantity for item in o.items),
                "total": float(o.total),
                "service_charge_pct": float(o.service_charge_pct),
                "service_charge_amount": float(service_amount),
                "partial_payment": float(o.partial_payment),
                "final_total": float(final),
                "closed_at": o.closed_at.isoformat() if o.closed_at else None,
            }
        )

    return {
        "sales": data,
        "summary": {
            "total_sales": round(total_day, 2),
            "total_service_charge": round(total_service, 2),
            "orders_count": len(data),
        },
    }


@router.get("/dashboard")
async def dashboard(
    period: str = Query("daily"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("caixa", "gerente"):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    today = date.today()

    result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total), 0),
            func.coalesce(
                func.sum(Order.total * Order.service_charge_pct / 100), 0
            ),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            cast(Order.closed_at, Date) == today,
        )
    )
    today_total, today_service, today_count = result.one()

    result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total), 0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            extract("year", Order.closed_at) == today.year,
            extract("month", Order.closed_at) == today.month,
        )
    )
    month_total, month_count = result.one()

    result = await db.execute(
        select(
            func.coalesce(func.sum(Order.total), 0),
            func.count(Order.id),
        ).where(
            Order.status == "finalizada",
            extract("year", Order.closed_at) == today.year,
            extract("week", Order.closed_at) == today.isocalendar()[1],
        )
    )
    week_total, week_count = result.one()

    return {
        "today": {
            "total": round(float(today_total), 2),
            "service_charge": round(float(today_service), 2),
            "orders": today_count,
        },
        "week": {
            "total": round(float(week_total), 2),
            "orders": week_count,
        },
        "month": {
            "total": round(float(month_total), 2),
            "orders": month_count,
        },
    }


class DailyCloseRequest(BaseModel):
    date: str


@router.post("/fechamento-diario")
async def daily_close(
    req: DailyCloseRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in ("caixa", "gerente"):
        return {"error": "Acesso restrito ao caixa ou gerente"}

    try:
        close_date = datetime.strptime(req.date, "%Y-%m-%d").date()
    except ValueError:
        return {"error": "Data inválida. Use formato YYYY-MM-DD"}

    result = await db.execute(
        select(Order)
        .where(
            Order.status == "finalizada",
            cast(Order.closed_at, Date) == close_date,
        )
        .options(
            selectinload(Order.table),
            selectinload(Order.waiter),
            selectinload(Order.items),
        )
        .order_by(Order.closed_at)
    )
    orders = result.scalars().all()

    if not orders:
        return {"error": "Nenhuma venda encontrada nesta data"}

    report = {
        "date": req.date,
        "closed_by": user.name,
        "generated_at": datetime.now().isoformat(),
        "orders": [],
        "summary": {
            "total_sales": 0.0,
            "total_service_charge": 0.0,
            "total_partial_payments": 0.0,
            "net_total": 0.0,
            "orders_count": len(orders),
        },
    }

    for o in orders:
        service_amount = o.total * (o.service_charge_pct / 100)
        final = o.total + service_amount - o.partial_payment

        report["summary"]["total_sales"] += o.total
        report["summary"]["total_service_charge"] += service_amount
        report["summary"]["total_partial_payments"] += o.partial_payment
        report["summary"]["net_total"] += final

        report["orders"].append(
            {
                "order_id": o.id,
                "table": f"Mesa {o.table.number}" if (o.table and not o.table.is_balcao) else "Balcão",
                "waiter": o.waiter.name if o.waiter else "N/A",
                "total": float(o.total),
                "service_charge": round(service_amount, 2),
                "partial_payment": float(o.partial_payment),
                "final_total": round(final, 2),
                "closed_at": o.closed_at.strftime("%H:%M") if o.closed_at else "",
            }
        )

    report["summary"]["total_sales"] = round(report["summary"]["total_sales"], 2)
    report["summary"]["total_service_charge"] = round(report["summary"]["total_service_charge"], 2)
    report["summary"]["total_partial_payments"] = round(report["summary"]["total_partial_payments"], 2)
    report["summary"]["net_total"] = round(report["summary"]["net_total"], 2)

    return report
