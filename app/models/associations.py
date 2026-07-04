from sqlalchemy import Integer, ForeignKey, Table, Column
from app.core.database import Base


supplier_product = Table(
    "supplier_product",
    Base.metadata,
    Column("supplier_id", Integer, ForeignKey("suppliers.id"), primary_key=True),
    Column("product_id", Integer, ForeignKey("products.id"), primary_key=True),
)
