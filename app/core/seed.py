from sqlalchemy import select
from app.core.database import async_session, engine, Base
from app.core.security import hash_password

from app.models.table import Table
from app.models.product import Product
from app.models.user import User
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_round import OrderRound


SEED_TABLES = [
    {"number": 1, "status": "vazia", "is_balcao": False},
    {"number": 2, "status": "vazia", "is_balcao": False},
    {"number": 3, "status": "vazia", "is_balcao": False},
    {"number": 4, "status": "vazia", "is_balcao": False},
    {"number": 5, "status": "vazia", "is_balcao": False},
    {"number": 6, "status": "vazia", "is_balcao": False},
    {"number": 7, "status": "vazia", "is_balcao": False},
    {"number": 8, "status": "vazia", "is_balcao": False},
    {"number": 9, "status": "vazia", "is_balcao": False},
    {"number": 10, "status": "vazia", "is_balcao": False},
    {"number": 0, "status": "vazia", "is_balcao": True},
]

SEED_PRODUCTS = [
    {"name": "Espetinho de Carne", "category": "Carnes", "price": 12.00, "stock": 100, "min_stock": 15},
    {"name": "Espetinho de Frango", "category": "Carnes", "price": 12.00, "stock": 80, "min_stock": 15},
    {"name": "Espetinho Misto", "category": "Carnes", "price": 14.00, "stock": 70, "min_stock": 10},
    {"name": "Porção de Fritas", "category": "Acompanhamentos", "price": 18.00, "stock": 100, "min_stock": 10},
    {"name": "Porção de Mandioca", "category": "Acompanhamentos", "price": 16.00, "stock": 90, "min_stock": 10},
    {"name": "Cerveja Lata", "category": "Bebidas", "price": 8.00, "stock": 150, "min_stock": 20},
    {"name": "Refrigerante Lata", "category": "Bebidas", "price": 6.00, "stock": 120, "min_stock": 15},
    {"name": "Água Mineral", "category": "Bebidas", "price": 4.00, "stock": 80, "min_stock": 10},
    {"name": "Suco de Laranja", "category": "Bebidas", "price": 7.00, "stock": 50, "min_stock": 5},
    {"name": "Molho de Alho", "category": "Condimentos", "price": 3.00, "stock": 30, "min_stock": 5},
    {"name": "Vinagrete", "category": "Condimentos", "price": 5.00, "stock": 25, "min_stock": 5},
    {"name": "Farofa", "category": "Condimentos", "price": 4.00, "stock": 40, "min_stock": 5},
]

SEED_USERS = [
    {
        "username": "sem_nome",
        "password": "123456",
        "name": "Sem nome",
        "role": "garcom",
        "is_registered": False,
    },
    {
        "username": "gerente",
        "password": "admin123",
        "name": "Gerente",
        "role": "gerente",
        "is_registered": True,
    },
    {
        "username": "caixa",
        "password": "caixa123",
        "name": "Caixa",
        "role": "caixa",
        "is_registered": True,
    },
    {
        "username": "estoquista",
        "password": "estoque123",
        "name": "Estoquista",
        "role": "estoquista",
        "is_registered": True,
    },
]


async def run_seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        for t in SEED_TABLES:
            session.add(Table(**t))

        for p in SEED_PRODUCTS:
            session.add(Product(**p))

        for u in SEED_USERS:
            session.add(
                User(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    name=u["name"],
                    role=u["role"],
                    is_registered=u["is_registered"],
                )
            )

        await session.commit()
