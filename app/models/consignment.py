from datetime import date, datetime
from sqlalchemy import Integer, String, Float, Boolean, ForeignKey, DateTime, Date, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ConsignmentOrder(Base):
    __tablename__ = "consignment_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    source_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    waiter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    order_type: Mapped[str] = mapped_column(String(20), default="pf", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pendente", nullable=False)

    total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    amount_paid: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    balance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    customer = relationship("Customer", back_populates="consignment_orders")
    source_order = relationship("Order", back_populates="consignment_order")
    waiter = relationship("User")
    items = relationship(
        "ConsignmentOrderItem", back_populates="consignment_order", cascade="all, delete-orphan"
    )
    payments = relationship(
        "ConsignmentPayment", back_populates="consignment_order", cascade="all, delete-orphan"
    )


class ConsignmentOrderItem(Base):
    __tablename__ = "consignment_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    consignment_order_id: Mapped[int] = mapped_column(
        ForeignKey("consignment_orders.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    unit_cost: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    consignment_order = relationship("ConsignmentOrder", back_populates="items")
    product = relationship("Product")


class ConsignmentPayment(Base):
    __tablename__ = "consignment_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    consignment_order_id: Mapped[int] = mapped_column(
        ForeignKey("consignment_orders.id"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    amount: Mapped[float] = mapped_column(Float, nullable=False)
    service_portion: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    card_machine: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    consignment_order = relationship("ConsignmentOrder", back_populates="payments")
    user = relationship("User")
