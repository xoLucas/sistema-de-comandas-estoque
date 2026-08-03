from datetime import datetime
from sqlalchemy import Integer, String, Float, ForeignKey, DateTime, func, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CashRegisterMovement(Base):
    __tablename__ = "cash_register_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("cash_register_sessions.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session = relationship("CashRegisterSession", back_populates="movements")
    created_by = relationship("User")
