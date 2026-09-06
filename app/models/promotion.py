from datetime import datetime
from decimal import Decimal

from sqlalchemy import Integer, String, Numeric, DateTime, Boolean, ForeignKey, Table, Column, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


promotion_product = Table(
    "promotion_product",
    Base.metadata,
    Column("promotion_id", Integer, ForeignKey("promotions.id"), primary_key=True),
    Column("product_id", Integer, ForeignKey("products.id"), primary_key=True),
)


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=0)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    products = relationship("Product", secondary=promotion_product, back_populates="promotions")
