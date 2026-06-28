from datetime import datetime
from sqlalchemy import Integer, String, Float, Boolean, ForeignKey, DateTime, func, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("tables.id"), nullable=False)
    waiter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="aberta", nullable=False)
    total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    partial_payment: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    partial_service_charge: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    partial_payments_detail: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)
    service_charge_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    service_charge_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    table = relationship("Table", back_populates="orders")
    waiter = relationship("User")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    rounds = relationship("OrderRound", back_populates="order", cascade="all, delete-orphan")
