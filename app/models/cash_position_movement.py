from datetime import datetime
from decimal import Decimal

from sqlalchemy import Integer, String, Numeric, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CashPositionMovement(Base):
    __tablename__ = "cash_position_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # entrada | saida
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # automatico | manual
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    observation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("cash_register_sessions.id"), nullable=True
    )
    refund_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_refunds.id"), nullable=True, unique=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    created_by = relationship("User", foreign_keys=[created_by_id])
    session = relationship("CashRegisterSession")
