from datetime import datetime

from sqlalchemy import Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class OrderTransfer(Base):
    __tablename__ = "order_transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"), nullable=False, index=True
    )
    from_table_id: Mapped[int | None] = mapped_column(
        ForeignKey("tables.id"), nullable=True
    )
    to_table_id: Mapped[int | None] = mapped_column(
        ForeignKey("tables.id"), nullable=True
    )
    moved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    moved_by_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    from_table_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    to_table_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    order = relationship("Order", back_populates="transfers")
    from_table = relationship("Table", foreign_keys=[from_table_id])
    to_table = relationship("Table", foreign_keys=[to_table_id])
    moved_by = relationship("User", foreign_keys=[moved_by_id])
