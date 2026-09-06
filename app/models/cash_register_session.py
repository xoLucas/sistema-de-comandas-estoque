from datetime import datetime
from decimal import Decimal

from sqlalchemy import Integer, String, Numeric, ForeignKey, DateTime, func, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CashRegisterSession(Base):
    __tablename__ = "cash_register_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    closed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    final_cash: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    opened_by = relationship("User", foreign_keys=[opened_by_id])
    closed_by = relationship("User", foreign_keys=[closed_by_id])
    movements = relationship(
        "CashRegisterMovement",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="CashRegisterMovement.created_at.desc()",
    )
