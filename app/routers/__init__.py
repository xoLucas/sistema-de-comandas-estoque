from app.routers.tables import router as tables_router
from app.routers.orders import router as orders_router
from app.routers.products import router as products_router

__all__ = ["tables_router", "orders_router", "products_router"]
