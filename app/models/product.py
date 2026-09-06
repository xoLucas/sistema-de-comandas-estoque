from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.associations import supplier_product


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "(pack_unit_product_id IS NULL AND pack_size = 1) OR "
            "(pack_unit_product_id IS NOT NULL AND pack_size >= 2)",
            name="ck_product_pack_configuration",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    margin_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=0, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_stock: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    printer: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pack_unit_product_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("products.id"), nullable=True
    )
    pack_size: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    suppliers = relationship("Supplier", secondary=supplier_product, back_populates="products")
    stock_history = relationship(
        "StockHistory",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="StockHistory.created_at.desc()",
        foreign_keys="StockHistory.product_id",
    )
    promotions = relationship("Promotion", secondary="promotion_product", back_populates="products")
    pack_unit_product = relationship("Product", remote_side=[id])
