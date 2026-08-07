from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, cast, Date, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import hash_password
from app.core.timezone import (
    ensure_utc,
    local_day_to_utc_range,
    parse_local_date,
    parse_local_datetime,
)
from app.models.employee import Employee
from app.models.daily_payment import DailyPayment
from app.models.expense import Expense
from app.models.user import User
from app.routers.auth_deps import get_current_user, require_role, can_view_employees
from app.validators.pydantic_mixins import EmployeeValidationMixin

router = APIRouter(prefix="/api", tags=["employees"])


class EmployeeCreate(EmployeeValidationMixin, BaseModel):
    name: str
    age: int | None = None
    nickname: str | None = None
    contact: str | None = None
    role: str
    active: bool = True
    create_login: bool = False
    username: str | None = None
    password: str | None = None
    login_role: str | None = None


class EmployeeUpdate(EmployeeValidationMixin, BaseModel):
    name: str
    age: int | None = None
    nickname: str | None = None
    contact: str | None = None
    role: str
    active: bool = True


class DailyPaymentCreate(BaseModel):
    employee_id: int
    amount: float
    payment_date: str  # ISO format
    notes: str | None = None


@router.get("/funcionarios")
async def list_employees(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_employees(user):
        return {"error": "Acesso restrito ao gerente"}

    query = select(Employee)
    if active_only:
        query = query.where(Employee.active == True)
    result = await db.execute(query.order_by(Employee.name))
    employees = result.scalars().all()
    return [
        {
            "id": e.id,
            "name": e.name,
            "age": e.age,
            "nickname": e.nickname,
            "contact": e.contact,
            "role": e.role,
            "active": e.active,
            "user_id": e.user_id,
            "has_login": e.user_id is not None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in employees
    ]


@router.get("/funcionarios/{employee_id}")
async def get_employee(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_employees(user):
        return {"error": "Acesso restrito ao gerente"}

    result = await db.execute(
        select(Employee)
        .where(Employee.id == employee_id)
        .options(selectinload(Employee.daily_payments).selectinload(DailyPayment.registered_by))
    )
    employee = result.scalars().first()
    if not employee:
        return {"error": "Funcionário não encontrado"}

    return {
        "id": employee.id,
        "name": employee.name,
        "age": employee.age,
        "nickname": employee.nickname,
        "contact": employee.contact,
        "role": employee.role,
        "active": employee.active,
        "user_id": employee.user_id,
        "has_login": employee.user_id is not None,
        "daily_payments": [
            {
                "id": dp.id,
                "amount": float(dp.amount),
                "payment_date": dp.payment_date.isoformat(),
                "notes": dp.notes,
                "registered_by": dp.registered_by.name if dp.registered_by else None,
            }
            for dp in employee.daily_payments
        ],
    }


@router.post("/funcionarios")
async def create_employee(
    req: EmployeeCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    if not req.name or not req.role:
        return {"error": "Nome e função são obrigatórios"}

    user_id = None
    if req.create_login:
        if not req.username or not req.password or not req.login_role:
            return {"error": "Username, senha e função de login são obrigatórios para criar acesso"}

        existing = await db.execute(select(User).where(User.username == req.username))
        if existing.scalars().first():
            return {"error": "Nome de usuário já existe"}

        new_user = User(
            username=req.username,
            password_hash=hash_password(req.password),
            name=req.name,
            role=req.login_role,
            is_registered=True,
        )
        db.add(new_user)
        await db.flush()
        user_id = new_user.id

    employee = Employee(
        name=req.name,
        age=req.age,
        nickname=req.nickname,
        contact=req.contact,
        role=req.role,
        active=req.active,
        user_id=user_id,
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)

    return {
        "id": employee.id,
        "name": employee.name,
        "role": employee.role,
        "has_login": employee.user_id is not None,
    }


@router.put("/funcionarios/{employee_id}")
async def update_employee(
    employee_id: int,
    req: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    employee = result.scalars().first()
    if not employee:
        return {"error": "Funcionário não encontrado"}

    if not req.name or not req.role:
        return {"error": "Nome e função são obrigatórios"}

    employee.name = req.name
    employee.age = req.age
    employee.nickname = req.nickname
    employee.contact = req.contact
    employee.role = req.role
    employee.active = req.active

    await db.commit()
    await db.refresh(employee)

    return {
        "id": employee.id,
        "name": employee.name,
        "role": employee.role,
        "active": employee.active,
    }


@router.delete("/funcionarios/{employee_id}")
async def delete_employee(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    result = await db.execute(select(Employee).where(Employee.id == employee_id))
    employee = result.scalars().first()
    if not employee:
        return {"error": "Funcionário não encontrado"}

    await db.delete(employee)
    await db.commit()
    return {"message": "Funcionário removido"}


@router.post("/funcionarios/diaria")
async def pay_daily(
    req: DailyPaymentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente")),
):
    if req.amount <= 0:
        return {"error": "Valor deve ser maior que zero"}

    result = await db.execute(select(Employee).where(Employee.id == req.employee_id))
    employee = result.scalars().first()
    if not employee:
        return {"error": "Funcionário não encontrado"}

    payment_date = parse_local_datetime(req.payment_date)
    if payment_date is None:
        return {"error": "Data inválida"}

    daily = DailyPayment(
        employee_id=employee.id,
        amount=req.amount,
        payment_date=payment_date,
        notes=req.notes,
        registered_by_id=user.id,
    )
    db.add(daily)
    await db.flush()

    expense = Expense(
        description=f"Diária - {employee.name}",
        amount=req.amount,
        category="diaria",
        expense_date=ensure_utc(payment_date),
        reference_id=daily.id,
        reference_type="daily_payment",
        created_by_id=user.id,
    )
    db.add(expense)

    await db.commit()
    await db.refresh(daily)

    return {
        "id": daily.id,
        "employee_id": daily.employee_id,
        "employee_name": employee.name,
        "amount": float(daily.amount),
        "payment_date": daily.payment_date.isoformat(),
        "notes": daily.notes,
    }


@router.get("/despesas")
async def list_expenses(
    date: str | None = None,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("gerente", "caixa")),
):
    query = select(Expense)
    if date:
        target = parse_local_date(date)
        if target is None:
            return {"error": "Data inválida"}
        day_start, day_end = local_day_to_utc_range(target)
        query = query.where(Expense.expense_date >= day_start, Expense.expense_date <= day_end)
    if category:
        query = query.where(Expense.category == category)

    result = await db.execute(query.order_by(Expense.expense_date.desc()))
    expenses = result.scalars().all()
    return [
        {
            "id": e.id,
            "description": e.description,
            "amount": float(e.amount),
            "category": e.category,
            "expense_date": e.expense_date.isoformat(),
            "reference_id": e.reference_id,
            "reference_type": e.reference_type,
        }
        for e in expenses
    ]


@router.get("/funcionarios/{employee_id}/total-diarias")
async def employee_daily_total(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not can_view_employees(user):
        return {"error": "Acesso restrito ao gerente"}

    result = await db.execute(
        select(func.coalesce(func.sum(DailyPayment.amount), 0.0))
        .where(DailyPayment.employee_id == employee_id)
    )
    total = float(result.scalar_one())
    return {"employee_id": employee_id, "total_paid": total}
