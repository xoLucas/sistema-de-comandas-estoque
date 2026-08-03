from datetime import date, datetime
from sqlalchemy import Integer, String, Boolean, Date, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document: Mapped[str | None] = mapped_column(String(30), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    customer_type: Mapped[str] = mapped_column(String(20), default="pf", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    orders = relationship("Order", back_populates="customer")
    consignment_orders = relationship("ConsignmentOrder", back_populates="customer")
