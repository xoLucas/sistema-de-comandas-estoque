from datetime import datetime
from decimal import Decimal

from sqlalchemy import Integer, String, Numeric, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StockHistory(Base):
    __tablename__ = "stock_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    consignment_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("consignment_orders.id"), nullable=True
    )
    table_id: Mapped[int | None] = mapped_column(ForeignKey("tables.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # entrada or saida
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    source_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    source_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversion_factor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    product = relationship("Product", back_populates="stock_history", foreign_keys=[product_id])
    source_product = relationship("Product", foreign_keys=[source_product_id])
