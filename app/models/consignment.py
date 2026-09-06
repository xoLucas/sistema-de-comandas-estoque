from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ConsignmentOrder(Base):
    __tablename__ = "consignment_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    source_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True, unique=True
    )
    waiter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    credited_waiter_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    credited_waiter_name_snapshot: Mapped[str | None] = mapped_column(
        "credited_waiter_name", String(100), nullable=True
    )

    order_type: Mapped[str] = mapped_column(String(20), default="pf", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pendente", nullable=False)

    product_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    service_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)

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
    credited_waiter = relationship("Employee", foreign_keys=[credited_waiter_id])
    items = relationship(
        "ConsignmentOrderItem", back_populates="consignment_order", cascade="all, delete-orphan"
    )
    payments = relationship(
        "ConsignmentPayment", back_populates="consignment_order", cascade="all, delete-orphan"
    )
    refunds = relationship("PaymentRefund", back_populates="consignment_order")

    @property
    def credited_waiter_name(self) -> str | None:
        """Return the employee selected for credit, falling back to the source user."""
        if self.credited_waiter_name_snapshot:
            return self.credited_waiter_name_snapshot
        if self.credited_waiter:
            return self.credited_waiter.name
        return self.waiter.name if self.waiter else None


class ConsignmentOrderItem(Base):
    __tablename__ = "consignment_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    consignment_order_id: Mapped[int] = mapped_column(
        ForeignKey("consignment_orders.id"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True, default=None)

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
    __table_args__ = (
        CheckConstraint(
            "amount = product_portion + service_portion",
            name="ck_consignment_payment_amounts",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    consignment_order_id: Mapped[int] = mapped_column(
        ForeignKey("consignment_orders.id"), nullable=False
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    product_portion: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    service_portion: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    card_machine: Mapped[str | None] = mapped_column(String(30), nullable=True)
    card_fee_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=0, nullable=False)
    card_fee_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    cash_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("cash_register_sessions.id"), nullable=True
    )
    source_order_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_payments.id"), nullable=True, unique=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    is_legacy_inferred: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    consignment_order = relationship("ConsignmentOrder", back_populates="payments")
    user = relationship("User")
    cash_session = relationship("CashRegisterSession")
    source_order_payment = relationship("OrderPayment")
    refunds = relationship("PaymentRefund", back_populates="consignment_payment")
