from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class OrderPayment(Base):
    __tablename__ = "order_payments"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_order_payments_idempotency_key"),
        CheckConstraint(
            "gross_amount = product_amount + service_amount",
            name="ck_order_payment_amounts",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cash_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("cash_register_sessions.id"), nullable=True, index=True
    )
    payment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    product_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    service_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    card_machine: Mapped[str | None] = mapped_column(String(30), nullable=True)
    card_fee_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=0)
    card_fee_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_legacy_inferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order = relationship("Order", back_populates="payments")
    user = relationship("User")
    cash_session = relationship("CashRegisterSession")
    allocations = relationship(
        "OrderPaymentAllocation",
        back_populates="payment",
        cascade="all, delete-orphan",
    )
    refunds = relationship("PaymentRefund", back_populates="payment")


class OrderPaymentAllocation(Base):
    __tablename__ = "order_payment_allocations"
    __table_args__ = (
        UniqueConstraint(
            "payment_id", "order_item_id", name="uq_order_payment_allocation_item"
        ),
        CheckConstraint("quantity > 0", name="ck_order_payment_allocation_quantity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("order_payments.id"), nullable=False, index=True
    )
    # Intentionally not a FK: an item may be removed after its payment is fully refunded.
    order_item_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    product_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    service_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    payment = relationship("OrderPayment", back_populates="allocations")
    product = relationship("Product")


class PaymentRefund(Base):
    __tablename__ = "payment_refunds"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_payment_refunds_idempotency_key"),
        CheckConstraint(
            "gross_amount = product_amount + service_amount",
            name="ck_payment_refund_amounts",
        ),
        CheckConstraint(
            "(payment_id IS NOT NULL AND consignment_payment_id IS NULL) "
            "OR (payment_id IS NULL AND consignment_payment_id IS NOT NULL) "
            "OR (payment_id IS NULL AND consignment_payment_id IS NULL "
            "AND gross_amount = 0 AND payment_method = 'fiado')",
            name="ck_payment_refund_source",
        ),
        CheckConstraint(
            "order_id IS NOT NULL OR consignment_order_id IS NOT NULL",
            name="ck_payment_refund_target",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refund_group_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_payments.id"), nullable=True, index=True
    )
    consignment_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("consignment_payments.id"), nullable=True, index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True, index=True
    )
    consignment_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("consignment_orders.id"), nullable=True, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    cash_session_id: Mapped[int] = mapped_column(
        ForeignKey("cash_register_sessions.id"), nullable=False, index=True
    )
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    product_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    service_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    service_was_recognized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    sale_was_recognized: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    service_already_repassed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    payment = relationship("OrderPayment", back_populates="refunds")
    consignment_payment = relationship("ConsignmentPayment", back_populates="refunds")
    order = relationship("Order", back_populates="refunds")
    consignment_order = relationship("ConsignmentOrder", back_populates="refunds")
    user = relationship("User")
    cash_session = relationship("CashRegisterSession")
    items = relationship(
        "PaymentRefundItem",
        back_populates="refund",
        cascade="all, delete-orphan",
    )


class PaymentRefundItem(Base):
    __tablename__ = "payment_refund_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_payment_refund_item_quantity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refund_id: Mapped[int] = mapped_column(
        ForeignKey("payment_refunds.id"), nullable=False, index=True
    )
    order_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    product_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    service_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    refund = relationship("PaymentRefund", back_populates="items")
    product = relationship("Product")
