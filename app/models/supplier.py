from sqlalchemy import Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.associations import supplier_product


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    products = relationship("Product", secondary=supplier_product, back_populates="suppliers")
